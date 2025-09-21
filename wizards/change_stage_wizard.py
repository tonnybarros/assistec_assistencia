# assistec_assistencia/wizards/change_stage_wizard.py
# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from datetime import timedelta
from markupsafe import Markup, escape


class AssistecOrderChangeStageWizard(models.TransientModel):
    _name = "assistec.order.change.stage.wizard"
    _description = "Wizard para Ações de Etapa da OS"

    # --- CAMPOS ---
    stage_id = fields.Many2one("assistec.stage", string="Nova Situação")
    # campo técnico (não mostrar na view)
    is_closed_order = fields.Boolean(string="OS está Fechada?")

    # --- DEFAULTS ---
    @api.model
    def default_get(self, fields_list):
        """Flag fechada baseada em date_out e sugere a próxima etapa aberta."""
        res = super().default_get(fields_list)
        active_id = self.env.context.get("active_id")
        if active_id:
            order = self.env["assistec.order"].browse(active_id)
            res["is_closed_order"] = bool(order.date_out) or bool(
                order.stage_id and order.stage_id.mark_closed
            )
            Stage = self.env["assistec.stage"].sudo()
            current_seq = order.stage_id.sequence if order.stage_id else 0
            candidate = Stage.search(
                [
                    ("active", "=", True),
                    ("mark_closed", "=", False),
                    ("sequence", ">", current_seq),
                    ("company_id", "in", [False, order.company_id.id]),
                ],
                order="sequence asc",
                limit=1,
            )
            if candidate:
                res["stage_id"] = candidate.id
        return res

    # --- HELPERS ---
    def _get_order(self):
        order = self.env["assistec.order"].browse(self.env.context.get("active_id"))
        if not order:
            raise UserError(_("OS não encontrada."))
        return order

    def _get_warranty_days(self):
        ICP = self.env["ir.config_parameter"].sudo()
        try:
            return int(ICP.get_param("assistec.warranty_days", 90))
        except Exception:
            return 90

    def _get_warranty_base_date(self, order):
        """Base para contagem de garantia.
        Regra: só há garantia se a OS antiga teve REPARO (date_repaired).
        - Se teve reparo: conta a partir de date_out (se existir) SENÃO date_repaired.
        - Se NÃO teve reparo: não há garantia."""
        if not order.date_repaired:
            return None
        return order.date_out or order.date_repaired

    def _get_warranty_end_date(self, order):
        """Data final da garantia. None se não houver base (ou seja, sem reparo)."""
        base = self._get_warranty_base_date(order)
        if not base:
            return None
        return base + timedelta(days=self._get_warranty_days())

    def _is_within_warranty(self, order):
        """True se a OS antiga teve reparo e o prazo (base + X dias) ainda está vigente."""
        end = self._get_warranty_end_date(order)
        if not end:
            return False
        return fields.Datetime.now() <= end

    def _pick_default_close_stage(self, order):
        Stage = self.env["assistec.stage"].sudo()
        candidates = Stage.search(
            [
                ("mark_closed", "=", True),
                ("active", "=", True),
                ("company_id", "in", [False, order.company_id.id]),
            ],
            order="sequence asc",
        )
        if not candidates:
            raise UserError(_("Configure ao menos um estágio com 'Marcar Fechada' para encerrar a OS."))
        preferred_codes = {"done", "finished", "closed", "cancelled", "canceled"}
        preferred = candidates.filtered(lambda s: (s.code or "").lower() in preferred_codes)
        return (preferred or candidates)[0]

    def _get_default_open_stage(self, order):
        Stage = self.env["assistec.stage"].sudo()
        stg_draft = Stage.search(
            [
                ("active", "=", True),
                ("mark_closed", "=", False),
                ("code", "ilike", "draft"),
                ("company_id", "in", [False, order.company_id.id]),
            ],
            limit=1,
        )
        if stg_draft:
            return stg_draft
        return Stage.search(
            [
                ("active", "=", True),
                ("mark_closed", "=", False),
                ("company_id", "in", [False, order.company_id.id]),
            ],
            order="sequence asc",
            limit=1,
        )

    # --- AÇÕES (botões) ---
    def action_confirm_stage(self):
        """Muda a OS para a nova etapa selecionada."""
        self.ensure_one()
        if not self.stage_id:
            raise UserError(_("Por favor, selecione uma Situação para continuar."))
        order = self._get_order()
        vals = {"stage_id": self.stage_id.id}
        if getattr(self.stage_id, "mark_closed", False) and not order.date_out:
            vals["date_out"] = fields.Datetime.now()
        order.write(vals)

        body = Markup(_("Situação alterada para: <b>%s</b>") % escape(self.stage_id.name))
        order.message_post(body=body, subtype_xmlid="mail.mt_comment", message_type="comment")
        return {"type": "ir.actions.act_window_close"}


    def action_close_now(self):
        """Fecha a OS imediatamente usando a etapa padrão de fechamento."""
        self.ensure_one()
        order = self._get_order()
        close_stage = self._pick_default_close_stage(order)
        vals = {"stage_id": close_stage.id}
        if not order.date_out:
            vals["date_out"] = fields.Datetime.now()
        order.write(vals)

        body = Markup(_("OS encerrada na etapa: <b>%s</b>.") % escape(close_stage.name))
        order.message_post(body=body, subtype_xmlid="mail.mt_comment", message_type="comment")
        return {"type": "ir.actions.act_window_close"}


    def action_open_close_selector(self):
        """Abre o wizard para o usuário escolher QUAL etapa de fechamento usar."""
        self.ensure_one()
        order = self._get_order()
        action = self.env.ref("assistec_assistencia.action_open_close_stage_wizard").read()[0]
        ctx = dict(self.env.context or {})
        ctx.update({
            "active_id": order.id,
            "active_model": "assistec.order",
            "allowed_company_ids": [order.company_id.id] if order.company_id else False,
        })
        action["context"] = ctx
        return action


    def action_reopen_order(self):
        """Reabre SEMPRE criando nova OS, copiando dados e respeitando garantia."""
        self.ensure_one()
        old = self._get_order()
        open_stage = self._get_default_open_stage(old)
        if not open_stage:
            raise UserError(_("Não há etapa aberta configurada para iniciar a reabertura."))

        in_warranty = self._is_within_warranty(old)
        prefix_note = _("Esta OS é uma reabertura da OS %s.") % (old.name or "")
        new_notes = (prefix_note + ("\n\n" + (old.notes or "") if old.notes else "")).strip()

        new_order = old.with_context(
            mail_create_nosubscribe=True,
            skip_init_message=True,
            tracking_disable=True
        ).copy({
            "name": "/",
            "stage_id": open_stage.id,
            "warranty": bool(in_warranty),
            "date_in": fields.Datetime.now(),
            "date_repaired": False,
            "date_out": False,
            "notes": new_notes,
        })


        end_date = self._get_warranty_end_date(old)
        if in_warranty and end_date:
            data_fmt = end_date.date().strftime('%d/%m/%Y')
            msg = _("Reaberta em garantia (até %s).") % data_fmt
        elif in_warranty:
            msg = _("Reaberta em garantia.")
        else:
            msg = _("Reaberta fora da garantia.")


        body_new = Markup(_("Reabertura criada a partir da OS <b>%s</b>. %s")
                        % (escape(old.name or ""), escape(msg)))
        new_order.message_post(body=body_new, subtype_xmlid="mail.mt_comment", message_type="comment")

        body_old = Markup(_("OS reaberta em nova OS: <b>%s</b>. %s")
                        % (escape(new_order.name or ""), escape(msg)))
        old.message_post(body=body_old, subtype_xmlid="mail.mt_comment", message_type="comment")

        return {
            "type": "ir.actions.act_window",
            "res_model": "assistec.order",
            "view_mode": "form",
            "res_id": new_order.id,
            "target": "current",
        }
