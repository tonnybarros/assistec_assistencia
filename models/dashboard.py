# -*- coding: utf-8 -*-
"""Dashboard Assistec – versão refatorada (patch 1)

• Corrige AttributeError em `rec["delivery_date"].date()` quando o campo é
  Date puro.
• Ajusta domínios que usam `delivery_date` para trabalhar com objetos `date` em
  vez de `datetime`.
• Mantém todas as funções públicas e helpers presentes na versão anterior.
"""

from odoo import api, fields, models
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta


class AssistecDashboard(models.TransientModel):
    _name = "assistec.dashboard"
    _description = "Dashboard Assistec"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _has(self, model, field):
        """Verifica se `field` existe em `model`."""
        return field in model._fields

    def _get_open_domain(self):
        Order = self.env["assistec.order"]
        if self._has(Order, "stage_id"):
            Stage = self.env[Order._fields["stage_id"].comodel_name]
            if self._has(Stage, "mark_closed"):
                return [("stage_id.mark_closed", "=", False)]
        if self._has(Order, "state"):
            return [("state", "not in", ("done", "cancel", "cancelled"))]
        return []

    def _get_done_domain(self):
        Order = self.env["assistec.order"]
        if self._has(Order, "stage_id"):
            Stage = self.env[Order._fields["stage_id"].comodel_name]
            if self._has(Stage, "mark_closed"):
                return [("stage_id.mark_closed", "=", True)]
        if self._has(Order, "state"):
            return [("state", "=", "done")]
        return [("id", "=", 0)]

    @staticmethod
    def _range(start: date, end: date):
        """Tupla (datetime_start, datetime_end) às 00:00."""
        return (
            datetime.combine(start, datetime.min.time()),
            datetime.combine(end,   datetime.min.time()),
        )

    # ------------------------------------------------------------------
    # API para o frontend
    # ------------------------------------------------------------------
    @api.model
    def get_dashboard_data(self, filters=None, **kw):
        Order = self.env["assistec.order"].with_context(active_test=False)
        dom_open = self._get_open_domain()
        dom_done = self._get_done_domain()

        today = date.today()
        tomorrow = today + timedelta(days=1)
        month_start = today.replace(day=1)
        next_month = month_start + relativedelta(months=1)

        def between(dom, start, end):
            d0, d1 = self._range(start, end)
            return dom + [("create_date", ">=", d0), ("create_date", "<", d1)]

        # ---------------- Cartões ----------------
        k_open = Order.search_count(dom_open)
        k_today = Order.search_count(between(dom_open, today, tomorrow))
        k_month = Order.search_count(between(dom_open, month_start, next_month))

        dom_due_today = dom_open + [("delivery_date", "=", today)]
        k_due_today = Order.search_count(dom_due_today)

        seven_days_ago = datetime.now() - timedelta(days=7)
        k_stalled_7d = Order.search_count(dom_open + [("create_date", "<", seven_days_ago)])

        k_without_budget = 0
        if self._has(Order, "amount_total"): # CORRIGIDO: usa amount_total em vez de has_budget
            k_without_budget = Order.search_count(dom_open + [("amount_total", "=", 0)])

        # ---------------- Meta do mês ----------------
        done_month = 0
        if self._has(Order, "date_out"):
            d0, d1 = self._range(month_start, next_month)
            done_month = Order.search_count(dom_done + [("date_out", ">=", d0), ("date_out", "<", d1)])

        meta = int(self.env["ir.config_parameter"].sudo().get_param("assistec.goal_month", "100") or 100)
        progress = 0 if meta <= 0 else min(100, int((done_month * 100) / meta))
        
        bar_class = 'bg-success' if progress >= 80 else \
                    'bg-warning' if progress >= 50 else 'bg-danger'

        # ---------------- KPIs ----------------
        top_resp_vals = {"id": 0, "name": "—", "qty": 0}
        resp_field = next((f for f in ("responsible_id", "user_id") if self._has(Order, f)), None)
        if resp_field:
            rows = Order.read_group(dom_open, [resp_field], [resp_field], orderby="__count DESC", limit=1)
            if rows and rows[0].get(resp_field):
                gf = rows[0][resp_field]
                top_resp_vals = {
                    "id": gf[0],
                    "name": gf[1] or "—",
                    "qty": rows[0][f"{resp_field}_count"],
                }

        avg_days_open = 0.0
        open_dates = Order.search(dom_open).mapped("create_date")
        if open_dates:
            now = datetime.now()
            avg_days_open = round(sum((now - d).days for d in open_dates) / len(open_dates), 1)

        budget_rate = 0
        if self._has(Order, "amount_total") and k_open: # CORRIGIDO: usa amount_total
            with_budget = Order.search_count(dom_open + [("amount_total", ">", 0)])
            budget_rate = int(round(with_budget * 100 / k_open, 0))

        last_partner = {"name": "N/A", "when": ""}
        lp = self.env["res.partner"].search([], order="create_date desc", limit=1)
        if lp:
            delta = datetime.now() - lp.create_date
            hours = int(delta.total_seconds() // 3600)
            last_partner = {"name": lp.display_name, "when": f"há {hours}h" if hours < 24 else f"há {hours // 24}d"}

        last_device = {"label": "N/A"}
        lo = Order.search([], order="create_date desc", limit=1)
        if lo:
            device = lo.repair_product_id.display_name or "Aparelho"
            last_device = {"label": f"{device} (OS {lo.name})"}

        # Tendência (14 dias)
        trend_points = []
        for i in range(13, -1, -1):
            ref = today - timedelta(days=i)
            d0, d1 = self._range(ref, ref + timedelta(days=1))
            qty = Order.search_count([("create_date", ">=", d0), ("create_date", "<", d1)])
            trend_points.append({"label": ref.strftime("%d/%m"), "qty": int(qty)})

        # =======================================================
        # ==== NOVA LÓGICA DE NOTIFICAÇÕES ADICIONADA AQUI ====
        # =======================================================
        notifications = {"due_soon": [], "urgent": []}

        if self._has(Order, "delivery_date"):
            dlimit = today + timedelta(days=4)
            due_soon_domain = dom_open + [("delivery_date", ">=", today), ("delivery_date", "<", dlimit)]
            due_soon_orders = Order.search_read(
                due_soon_domain,
                ["name", "partner_id", "delivery_date"],
                order="delivery_date asc",
            )
            for rec in due_soon_orders:
                rec["days_left"] = (rec["delivery_date"] - today).days
                notifications["due_soon"].append(rec)

        if self._has(Order, "priority"):
            notifications["urgent"] = Order.search_read(
                dom_open + [("priority", "=", "1")],
                ["name", "partner_id", "stage_id"],
            )

        # Payload final
        ACTION_OS = "assistec_assistencia.action_assistec_order"  # opcional

        cards = [
            {"key": "open", "label": "OS Abertas", "value": k_open,
            "action_xmlid": ACTION_OS, "domain": dom_open},
            {"key": "today", "label": "Hoje", "value": k_today,
            "action_xmlid": ACTION_OS, "domain": between(dom_open, today, tomorrow)},
            {"key": "month", "label": "Neste mês", "value": k_month,
            "action_xmlid": ACTION_OS, "domain": between(dom_open, month_start, next_month)},
            {"key": "due_today", "label": "Entregas hoje", "value": k_due_today,
            "action_xmlid": ACTION_OS, "domain": dom_open + [("delivery_date", "=", today)]},
            {"key": "stalled_7d", "label": "Paradas (7+ dias)", "value": k_stalled_7d,
            "action_xmlid": ACTION_OS, "domain": dom_open + [("create_date", "<", seven_days_ago)]},
            {"key": "without_budget", "label": "Sem orçamento", "value": k_without_budget,
            "action_xmlid": ACTION_OS, "domain": dom_open + [("amount_total", "=", 0)]},
        ]


        kpis = {
            "top_resp": top_resp_vals,
            "avg_days_open": avg_days_open,
            "budget_rate": budget_rate,
            "goal": meta,
            "done_month": done_month,
            "goal_progress": progress,
            "goal_bar_class": bar_class,
            "last_partner": last_partner,
            "last_device": last_device,
        }

        return {
            "cards": cards,
            "kpis": kpis,
            "trend": trend_points,
            "notifications": notifications,
        }