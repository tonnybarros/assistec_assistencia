# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
import json, logging, re
from datetime import date, datetime
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT as DT_FMT

_logger = logging.getLogger(__name__)

try:
    import requests
except Exception:
    requests = None


# ═══════════════════════════════════════════════════════════════════
# helpers (nível de módulo)
# ═══════════════════════════════════════════════════════════════════
def _as_bool(v):
    return str(v).lower() in ("1", "true", "t", "y", "yes", "on")

def _dt_to_str(val):
    if isinstance(val, datetime):
        return val.strftime(DT_FMT)
    if isinstance(val, date):
        return val.isoformat()
    return val

# Telefone → MSISDN BR (E.164-like)
_PHONE_RE = re.compile(r"\D+")

def _format_msisdn(raw):
    """Converte '(11) 91234-5678' -> '5511912345678' ou False."""
    if not raw:
        return False
    digits = _PHONE_RE.sub("", str(raw))
    if len(digits) < 10:
        return False
    if digits.startswith("0"):
        digits = digits[1:]
    if not digits.startswith("55"):
        digits = "55" + digits
    return digits


# ═══════════════════════════════════════════════════════════════════
# MIXIN
# ═══════════════════════════════════════════════════════════════════
class AssistecWebhookMixin(models.AbstractModel):
    _name = "assistec.webhook.mixin"
    _description = "Mixin Webhook Assistec"

    # ------------------- Config -------------------
    def _get_webhook_conf(self):
        ICP = self.env["ir.config_parameter"].sudo()
        get = ICP.get_param
        return {
            "enabled":         _as_bool(get("assistec.webhook_enabled", "True")),
            "url":             (get("assistec.webhook_url") or "").strip(),
            "verify_ssl":      _as_bool(get("assistec.webhook_verify_ssl", "True")),
            "on_create":       _as_bool(get("assistec.webhook_on_create", "True")),
            "on_state_change": _as_bool(get("assistec.webhook_on_state_change", "True")),
            "state_whitelist": [
                s for s in (get("assistec.webhook_state_whitelist", "") or "")
                    .replace(" ", "").split(",") if s
            ],
            "timeout": int(get("assistec.webhook_timeout", "10") or 10),
            "headers": self._parse_headers(get("assistec.webhook_headers_json") or ""),
        }

    @staticmethod
    def _parse_headers(s):
        if not s:
            return {}
        try:
            d = json.loads(s)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    # ---------------- JSON safe -------------------
    @staticmethod
    def _json_safe(val):
        from odoo import models
        if isinstance(val, (datetime, date)):
            return val.isoformat()
        if isinstance(val, models.BaseModel):
            return {"id": val.id, "display_name": val.display_name} if val else False
        if isinstance(val, (list, tuple, set)):
            return [AssistecWebhookMixin._json_safe(v) for v in val]
        if isinstance(val, dict):
            return {k: AssistecWebhookMixin._json_safe(v) for k, v in val.items()}
        return val

    # ---------------- Export helpers --------------
    def _export_partner(self, p):
        if not p:
            return {}
        return {
            "id": p.id,
            "name": p.display_name,
            "mobile": p.mobile,
            "phone": p.phone,
            "email": p.email,
            "vat": p.vat,
            "street": getattr(p, "street_name", False) or p.street,
            "street2": p.street2,
            "zip": p.zip,
            "city": p.city,
            "state": p.state_id and p.state_id.code or False,
            "country": p.country_id and p.country_id.code or False,
        }

    def _export_line(self, l):
        return {
            "id": l.id,
            "service_id": l.service_id.id if l.service_id else False,
            "service": l.service_id.display_name if l.service_id else False,
            "qty": l.quantity,
            "uom": l.uom_id.display_name if l.uom_id else False,
            "price_unit": l.price_unit,
            "discount_type": l.discount_type,
            "discount_value": l.discount_value,
            "subtotal": l.subtotal,
            "notes": getattr(l, "notes", False) or getattr(l, "description", False) or False,
        }

    def _export_order(self):
        self.ensure_one()

        # ➕ responsável e celular normalizado
        r = self.responsible_id
        rp = r.partner_id if r else False
        resp_msisdn = _format_msisdn((rp.mobile or rp.phone) if rp else None)

        return self._json_safe({
            "id": self.id,
            "name": self.name,
            "company": self.company_id.display_name if self.company_id else False,
            "state": self.state,
            "stage": {
                "id": self.stage_id.id if self.stage_id else False,
                "code": self.stage_id.code if self.stage_id else False,
                "name": self.stage_id.display_name if self.stage_id else False,
            },
            "responsible": self.responsible_id.display_name if self.responsible_id else False,
            "responsible_id": r.id if r else False,
            "responsible_partner": ({
                "id": rp.id,
                "name": rp.display_name,
                "mobile": rp.mobile,
                "phone": rp.phone,
                "email": rp.email,
            } if rp else False),
            "responsible_msisdn": resp_msisdn,

            "dates": {
                "date_in": self.date_in,
                "date_repaired": self.date_repaired,
                "date_out": self.date_out,
                "date_warranty": self.date_warranty,
                "delivery_date": self.delivery_date,
            },
            "warranty": bool(self.warranty),
            "partner": self._export_partner(self.partner_id),
            "device": {
                "repair_product": self.repair_product_id.display_name if self.repair_product_id else False,
                "brand": self.brand_id.display_name if self.brand_id else False,
                "model": self.model,
                "serial_number": self.serial_number,
                "color": self.color,
                "accessories": self.accessories,
            },
            "descriptions": {
                "issue": self.issue_description,
                "notes": self.notes,
                "repair_notes": self.repair_notes,
            },
            "amounts": {
                "currency": self.currency_id.name if self.currency_id else False,
                "amount_untaxed": self.amount_untaxed,
                "amount_total": self.amount_total,
            },
            "tags": [t.display_name for t in self.tag_ids],
            "lines": [self._export_line(l) for l in self.line_ids],
        })

    # ---------------- Chatter + e-mail ------------
    def _log_webhook(self, body):
        """Cartão notification; e-mail só ao responsável (se tiver e-mail)."""
        subtype = self.env["mail.message.subtype"].ensure_webhook_subtype()
        if subtype.internal:
            subtype.internal = False  # permite e-mail

        partner = self.responsible_id.partner_id
        recipients = [partner.id] if partner and partner.email else []

        kw = {
            "body": body,
            "subtype_id": subtype.id,
            "message_type": "notification",
        }
        if recipients:
            kw["partner_ids"] = recipients

        self.message_post(**kw)  # sem channel_ids

    # ---------------- Envio -----------------------
    def _send_webhook(self, event="event"):
        if not requests:
            _logger.error("biblioteca 'requests' ausente – webhook não enviado.")
            self._log_webhook(_('Webhook “%s” falhou.') % event)
            return False

        conf = self._get_webhook_conf()
        if not (conf["enabled"] and conf["url"]):
            return False

        # URL pública (via token) se existir
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        if hasattr(self, "access_token") and self.access_token:
            public_url = f"{base_url}/os/{self.access_token}"
        else:
            public_url = False

        notify_enabled = bool(getattr(self, "notify_customer", False))

        payload = {
            "event": event,
            "timestamp": _dt_to_str(fields.Datetime.now()),
            "model": self._name,
            "data": self._export_order(),
            "public_url": public_url,

            # carimbos/flags
            "source": "notify",
            "notify": True,
            "notify_customer": notify_enabled,
        }
        headers = {
            "Content-Type": "application/json",
            "X-Assistec-Event": event,
            "X-Assistec-Source": "notify",
            "X-Assistec-Notify": "1" if notify_enabled else "0",
        }
        headers.update(conf.get("headers", {}))

        ok = False
        try:
            resp = requests.post(
                conf["url"], json=payload,
                headers=headers, timeout=conf["timeout"],
                verify=conf["verify_ssl"],
            )
            ok = resp.ok
            if not ok:
                _logger.error("Webhook HTTP %s – %s", resp.status_code, resp.text[:300])
        except Exception as exc:
            _logger.exception("Falha no webhook (OS %s): %s", self.id, exc)

        self._log_webhook(_('Webhook “%s” %s.') %
                          (event, _("enviado") if ok else _("falhou")))
        return ok

    # ---------------- Fila ------------------------
    def _queue_webhook(self, event="event"):
        self.ensure_one()
        if not getattr(self, "notify_customer", True):
            return
        conf = self._get_webhook_conf()
        if not (conf["enabled"] and conf["url"]):
            return
        self.env.cr.postcommit.add(lambda: self._send_webhook(event))


# ═══════════════════════════════════════════════════════════════════
# Extensão leve de assistec.order
# ═══════════════════════════════════════════════════════════════════
class AssistecOrderWebhookExt(AssistecWebhookMixin, models.Model):
    _inherit = "assistec.order"

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        if self.env["assistec.webhook.mixin"]._get_webhook_conf().get("on_create"):
            for r in recs:
                r._queue_webhook("create")
        return recs

    def write(self, vals):
        prev = {r.id: r.stage_id.id for r in self}
        res = super().write(vals)

        conf = self.env["assistec.webhook.mixin"]._get_webhook_conf()
        if not conf.get("on_state_change"):
            return res
        whitelist = conf.get("state_whitelist") or []

        for r in self:
            if prev[r.id] == r.stage_id.id:
                continue
            code = (r.stage_id.code or "").strip().lower()
            if whitelist and code not in whitelist:
                continue
            r._queue_webhook(f"stage:{code}")
            r._log_webhook(_('Webhook “%s” agendado.') % f"stage:{code}")
        return res

    def action_send_webhook(self):
        conf = self.env["assistec.webhook.mixin"]._get_webhook_conf()
        if not (conf["enabled"] and conf["url"]):
            raise UserError(_("Webhook desativado ou sem URL configurada."))

        for r in self:
            r._queue_webhook("manual")
            r._log_webhook(_('Webhook “%s” agendado.') % "manual")
            r._set_stage_by_code("enviado")

        next_action = {"type": "ir.actions.client", "tag": "reload"}

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Webhook"),
                "message": _("%s ordem(ns) adicionada(s) à fila de envio.") % len(self),
                "type": "success",
                "sticky": False,
                "next": next_action,
            },
        }
