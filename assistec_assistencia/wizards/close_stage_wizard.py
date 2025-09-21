from odoo import api, fields, models, _
from odoo.exceptions import UserError
from markupsafe import Markup, escape


class AssistecOrderCloseWizard(models.TransientModel):
    _name = "assistec.order.close.wizard"
    _description = "Encerrar OS - Selecionar Etapa"

    close_stage_id = fields.Many2one(
        "assistec.stage",
        string="Etapa de Fechamento",
        required=True,
        domain="[('mark_closed','=',True),('active','=',True)]",
    )

    # CAMPO ADICIONADO AO WIZARD
    payment_method_id = fields.Many2one(
        "assistec.payment.method",
        string="Forma de Pagamento",
        required=True
    )

    note = fields.Text(string="Observações (opcional)")

    # --- HELPERS ---
    def _get_order(self):
        order = self.env["assistec.order"].browse(self.env.context.get("active_id"))
        if not order:
            raise UserError(_("OS não encontrada."))
        return order

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        order = self.env.context.get("active_id") and self.env["assistec.order"].browse(self.env.context["active_id"]) or False
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
                preferred = candidates.filtered(lambda s: (s.code or "").lower() in preferred_codes)
                res["close_stage_id"] = (preferred or candidates)[0].id
        return res

    # --- AÇÃO ---
    def action_apply_close(self):
        self.ensure_one()
        order = self._get_order()
        stage = self.close_stage_id

        # LÓGICA ATUALIZADA PARA SALVAR A FORMA DE PAGAMENTO
        vals = {
            "stage_id": stage.id,
            "payment_method_id": self.payment_method_id.id
        }
        if not order.date_out:
            vals["date_out"] = fields.Datetime.now()
        order.write(vals)

        # Chatter com Markup e informações adicionais
        parts = [Markup(_("OS encerrada na etapa: <b>%s</b>.") % escape(stage.name))]
        parts.append(Markup("<br/>") + Markup(_("Forma de Pagamento: <b>%s</b>.") % escape(self.payment_method_id.name)))
        if self.note:
            parts.append(Markup("<br/>") + Markup(_("Observações: %s") % escape(self.note)))

        order.message_post(
            body=Markup("").join(parts),
            subtype_xmlid="mail.mt_comment",
            message_type="comment",
        )
        return {"type": "ir.actions.act_window_close"}
