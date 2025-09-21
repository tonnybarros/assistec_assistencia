# models/order_public.py  ← renomeie ou sobrescreva o antigo
# -*- coding: utf-8 -*-
"""
Gera token, URL pública e QR-Code sem alterar as regras de negócio do modelo
principal.  Um único campo 'qr_code' — sem duplicidade.
"""
import base64, io, secrets
from urllib.parse import quote_plus

from odoo import api, fields, models, _
from odoo.tools.safe_eval import json

try:
    import qrcode          # pip install qrcode[pil]
except ImportError:
    qrcode = None


class AssistecOrderPublic(models.Model):
    _inherit = "assistec.order"

    # ---------- novos campos ----------
    access_token = fields.Char(
        string="Token público", copy=False, readonly=True, index=True
    )
    public_url = fields.Char(
        string="URL pública", compute="_compute_public", store=False
    )
    qr_code = fields.Binary(
        string="QR-Code", compute="_compute_public", store=False
    )

    # ---------- helpers ----------
    def _base_url(self):
        return (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("web.base.url", default="http://localhost:8069")
        )

    def _gen_token(self, size=18):
        return base64.urlsafe_b64encode(secrets.token_bytes(size)).rstrip(b"=").decode()

    # ---------- hooks ----------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault("access_token", self._gen_token())
        return super().create(vals_list)

    def write(self, vals):
        # Se o usuário limpar o campo → gera outro token
        if vals.get("access_token") is False:
            vals["access_token"] = self._gen_token()
        return super().write(vals)

    # ---------- compute ----------
    @api.depends("name", "partner_mobile", "access_token")
    def _compute_public(self):
        base = self._base_url()
        for rec in self:
            if not rec.access_token:
                rec.public_url = False
                rec.qr_code = False
                continue

            # URL curta por token
            rec.public_url = f"{base}/os/{rec.access_token}"

            # Gera QR (string base64, sem o b'…')
            if qrcode:
                buf = io.BytesIO()
                qrcode.make(rec.public_url, box_size=4, border=2).save(buf, format="PNG")
                rec.qr_code = base64.b64encode(buf.getvalue()).decode("ascii")
            else:
                rec.qr_code = False
