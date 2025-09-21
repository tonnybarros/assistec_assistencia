from odoo import api, fields, models, _

class MailMessageSubtype(models.Model):
    _inherit = "mail.message.subtype"

    @api.model
    def ensure_webhook_subtype(self):
        subtype = self.env.ref(
            "assistec_assistencia.subtype_webhook",
            raise_if_not_found=False,
        )
        if not subtype:
            subtype = self.create({
                "name": _("Webhook"),
                "internal": True,
                "default": False,
                "res_model": "assistec.order",
                "description": _("Envios de webhook"),
                "sequence": 20,
            })
            # registra o xml_id p/ leituras futuras
            self.env["ir.model.data"].create({
                "name": "subtype_webhook",
                "model": "mail.message.subtype",
                "module": "assistec_assistencia",
                "res_id": subtype.id,
                "noupdate": True,
            })
        return subtype            # <<< devolve o record
