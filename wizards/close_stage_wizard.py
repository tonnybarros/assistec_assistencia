# -*- coding: utf-8 -*-
import logging    
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from markupsafe import Markup, escape

_logger = logging.getLogger(__name__)

class AssistecOrderCloseWizard(models.TransientModel):
    _name = "assistec.order.close.wizard"
    _description = "Encerrar OS – Selecionar Etapa"

    close_stage_id = fields.Many2one(
        "assistec.stage",
        string="Etapa de Fechamento",
        required=True,
        domain="[('mark_closed','=',True), ('active','=',True)]",
    )

    payment_method_id = fields.Many2one(
        "assistec.payment.method",
        string="Forma de Pagamento",
        help="Obrigatório quando a OS já estiver em um estágio marcado como 'Reparado'.",
    )

    note = fields.Text(string="Observações (opcional)")

    # -------------------------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------------------------
    def _get_order(self):
        order = self.env["assistec.order"].browse(self.env.context.get("active_id"))
        if not order:
            raise UserError(_("OS não encontrada."))
        return order

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        order = self._get_order() if self.env.context.get("active_id") else False
        if order:
            Stage = self.env["assistec.stage"].sudo()
            candidates = Stage.search(
                [
                    ("mark_closed", "=", True),
                    ("active", "=", True),
                    ("company_id", "in", [False, order.company_id.id]),
                ],
                order="sequence asc",
            )
            if candidates:
                preferred_codes = {"done", "finished", "closed", "cancelled", "canceled"}
                preferred = candidates.filtered(
                    lambda s: (s.code or "").lower() in preferred_codes
                )
                res["close_stage_id"] = (preferred or candidates)[0].id
        return res

    # -------------------------------------------------------------------------
    # AÇÃO – botão “Encerrar”
    # -------------------------------------------------------------------------
    def action_apply_close(self):
        self.ensure_one()
        order = self._get_order()
        stage = self.close_stage_id

        # Se a OS JÁ está em um estágio “reparado”, exija forma de pagamento
        if order.stage_id.mark_repaired and not self.payment_method_id:
            _logger.warning("Tentou encerrar OS %s sem pagamento", order.name)
            return {
                "type":   "ir.actions.client",
                "tag":    "display_notification",
                "params": {
                    "title":   _("Pagamento obrigatório"),
                    "message": _("Selecione a forma de pagamento para OS reparada."),
                    "type":    "danger",          # colors: success - info - warning - danger
                    "sticky":  False,             # some seconds e desaparece
                },
            }


        # Atualiza dados da OS
        vals = {
            "stage_id": stage.id,
            "payment_method_id": self.payment_method_id.id,
        }
        if not order.date_out:
            vals["date_out"] = fields.Datetime.now()
        order.write(vals)

        # Mensagem no Chatter
        parts = [
            Markup(_("OS encerrada na etapa: <b>%s</b>.") % escape(stage.name))
        ]
        if self.payment_method_id:
            parts.append(
                Markup("<br/>") + Markup(
                    _("Forma de Pagamento: <b>%s</b>.") % escape(self.payment_method_id.name)
                )
            )
        if self.note:
            parts.append(
                Markup("<br/>") + Markup(_("Observações: %s") % escape(self.note))
            )

        order.message_post(
            body=Markup("").join(parts),
            subtype_xmlid="mail.mt_comment",
            message_type="comment",
        )
        return {"type": "ir.actions.act_window_close"}
