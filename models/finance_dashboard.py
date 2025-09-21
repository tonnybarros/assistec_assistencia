# -*- coding: utf-8 -*-
from odoo import models, api, fields
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

class AssistecFinanceDashboard(models.TransientModel):
    _name = "assistec.finance.dashboard"
    _description = "Dashboard Financeiro (Assistec)"

    @api.model
    def get_data(self, period="month"):
        Order = self.env["assistec.order"]
        PartLine = self.env["assistec.order.part.line"]
        Stage = self.env["assistec.stage"]
        today = fields.Date.today()

        # Define o período
        if period == "day":
            date_from = today
        elif period == "week":
            date_from = today - timedelta(days=7)
        else:  # "month"
            date_from = today.replace(day=1)
        
        # Busca todos os estágios que marcam a OS como "Entregue"
        closed_stages = Stage.search([('mark_closed', '=', True)])
        if not closed_stages:
            return {
                "kpis": {"revenue_period": "R$ 0,00", "expenses_total": "R$ 0,00", "parts_total": "R$ 0,00", "commission_total": "R$ 0,00", "margin": "0.00%"},
                "series": [],
            }

        # Filtra OS válidas
        dom = [
            ("date_repaired", "!=", False),
            ("date_out", "!=", False),
            ("date_out", ">=", date_from),
            ("date_out", "<=", today),
            ("amount_total", ">", 0),
            ("stage_id", "in", closed_stages.ids),
        ]
        orders = Order.search(dom)

        # O resto do cálculo
        percent = float(
            self.env["ir.config_parameter"].sudo()
            .get_param("assistec.commission_percent", "15.0")
        ) / 100.0
        revenue_period = sum(orders.mapped("amount_total"))
        part_lines = PartLine.search([("order_id", "in", orders.ids)])
        part_total = sum(part_lines.mapped("subtotal"))
        commission_total = sum(orders.mapped(lambda o: o.amount_total * percent))
        expenses_total = part_total + commission_total
        margin_val = revenue_period - expenses_total
        margin_pct = f"{(margin_val / revenue_period * 100):.2f}%" if revenue_period else "0.00%"

        # Série do gráfico (6 meses)
        series = []
        for i in range(5, -1, -1):
            ref_month = (today.replace(day=1) - relativedelta(months=i))
            next_month = (ref_month + relativedelta(months=1))
            dom_m = [
                ("date_repaired", "!=", False),
                ("date_out", "!=", False),
                ("date_out", ">=", ref_month),
                ("date_out", "<", next_month),
                ("amount_total", ">", 0),
                ("stage_id", "in", closed_stages.ids),
            ]
            month_orders = Order.search(dom_m)
            month_total = sum(month_orders.mapped("amount_total"))
            label = ref_month.strftime("%b/%Y").capitalize()
            series.append((label, month_total))

        return {
            "kpis": {
                "revenue_period": f"R$ {revenue_period:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                "expenses_total": f"R$ {expenses_total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                "parts_total": f"R$ {part_total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                "commission_total": f"R$ {commission_total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                "margin": margin_pct,
            },
            "series": series,
        }