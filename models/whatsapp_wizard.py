# -*- coding: utf-8 -*-
import logging
import json

from odoo import api, fields, models, _
from odoo.exceptions import UserError

try:
    import requests
except Exception:
    requests = None

_logger = logging.getLogger(__name__)

class AssistecWhatsappWizard(models.TransientModel):
    _name = "assistec.whatsapp.wizard"
    _description = "Enviar WhatsApp"

    order_id = fields.Many2one("assistec.order", string="OS", required=True)
    partner_id = fields.Many2one("res.partner", string="Cliente", required=True, readonly=True)
    partner_mobile = fields.Char(string="Telefone do Cliente", required=True)
    message = fields.Text(string="Mensagem", required=True)

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        ctx = self.env.context
        order = self.env["assistec.order"].browse(ctx.get("default_order_id"))
        if order:
            vals.setdefault("order_id", order.id)
            vals.setdefault("partner_id", order.partner_id.id)
            vals.setdefault("partner_mobile", order.partner_mobile or order.partner_id.mobile or order.partner_id.phone)
        return vals

    @staticmethod
    def _only_digits(s): return "".join(ch for ch in (s or "") if ch.isdigit())

    def action_send_whatsapp(self):
        self.ensure_one()

        user = self.env.user
        company = self.env.company

        # 0) Sanitiza telefone
        def _digits(s): return "".join(ch for ch in (s or "") if ch.isdigit())
        msisdn = _digits(self.partner_mobile)
        if not msisdn:
            raise UserError(_("Informe um telefone válido."))

        # 1) Lê config direto do ICP (robusto) + fallback no mixin
        ICP = self.env["ir.config_parameter"].sudo()
        def _as_bool(v): return str(v).lower() in ("1", "true", "t", "y", "yes", "on")

        url = (ICP.get_param("assistec.webhook_url") or "").strip()
        enabled = _as_bool(ICP.get_param("assistec.webhook_enabled", "True"))
        verify_ssl = _as_bool(ICP.get_param("assistec.webhook_verify_ssl", "True"))
        timeout = int(ICP.get_param("assistec.webhook_timeout", "10") or 10)

        headers_json = ICP.get_param("assistec.webhook_headers_json") or ""
        try:
            extra_headers = json.loads(headers_json) if headers_json else {}
            if not isinstance(extra_headers, dict):
                extra_headers = {}
        except Exception:
            extra_headers = {}

        # Fallback: tenta pelo mixin também, caso alguém personalize lá
        if not (enabled and url):
            try:
                conf = self.env["assistec.webhook.mixin"]._get_webhook_conf()
                url = url or (conf.get("url") or "")
                enabled = enabled or bool(conf.get("enabled"))
                verify_ssl = verify_ssl if verify_ssl is not None else bool(conf.get("verify_ssl"))
                timeout = timeout or int(conf.get("timeout") or 10)
                extra_headers = extra_headers or conf.get("headers") or {}
            except Exception:
                pass

        if not (enabled and url):
            raise UserError(_("Webhook desativado ou sem URL configurada em Configurações."))

        # 2) Monta payload
        order = self.order_id
        export = order._export_order() if hasattr(order, "_export_order") else {"id": order.id, "name": order.name}
        payload = {
            "event": "whatsapp",
            "origin": "manual_os",
            "manual": True,
            "action": "send_whatsapp",
            "source": "odoo_assistec",
            "timestamp": fields.Datetime.now().isoformat(),
            "model": "assistec.order",
            "data": export,
            "message": self.message or "",
            "phone": msisdn,
            "actor": {
                "id": user.id,
                "login": user.login,
                "name": user.partner_id.display_name,
            },
        }
        headers = {
            "Content-Type": "application/json",
            "X-Assistec-Event": "whatsapp",
            "X-Assistec-Trigger": "manual",
            "X-Assistec-Source": "odoo_assistec",
            "X-Assistec-OS": str(order.id),
            "X-Assistec-OS-Name": order.name or "",
        }
        headers.update(extra_headers)

        # 3) Envia
        if not requests:
            raise UserError(_("Biblioteca 'requests' não instalada no servidor."))
        ok = False
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout, verify=verify_ssl)
            ok = 200 <= resp.status_code < 300
            if not ok:
                _logger.error("Webhook WhatsApp HTTP %s – %s", resp.status_code, (resp.text or "")[:300])
        except Exception as e:
            _logger.exception("Falha ao enviar WhatsApp: %s", e)
            ok = False

        # 4) Chatter + toast
        self.order_id.message_post(
            body=_("WhatsApp %s para %s.") % (_("enviado") if ok else _("falhou"), msisdn),
            message_type="notification",
            subtype_xmlid="mail.mt_comment",
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "WhatsApp",
                "message": _("Mensagem %s.") % (_("enviada") if ok else _("não enviada")),
                "type": "success" if ok else "danger",
                "sticky": False,
            },
        }

# Extensão do modelo da OS: método que monta a action e injeta o ID (sem active_id no XML)
class AssistecOrder(models.Model):
    _inherit = "assistec.order"

    def action_open_whatsapp_modal(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Enviar WhatsApp"),
            "res_model": "assistec.whatsapp.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_order_id": self.id,
                "default_partner_id": self.partner_id.id if self.partner_id else False,
                "default_partner_mobile": self.partner_mobile or self.partner_id.mobile or self.partner_id.phone,
            },
        }
