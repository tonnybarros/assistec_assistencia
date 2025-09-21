# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AssistecPart(models.Model):
    _name = "assistec.part"
    _description = "Peça / Componente"
    _order = "name"

    # ──────────────────────────────
    # Campos
    # ──────────────────────────────
    name = fields.Char(required=True)
    list_price = fields.Monetary("Preço", default=0.0)
    active = fields.Boolean(default=True)
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id.id,
    )

    # ──────────────────────────────
    # Uppercase helpers
    # ──────────────────────────────
    @staticmethod
    def _to_upper(name):
        return name.strip().upper() if isinstance(name, str) else name

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "name" in vals:
                vals["name"] = self._to_upper(vals["name"])
        return super().create(vals_list)

    def write(self, vals):
        if "name" in vals:
            vals["name"] = self._to_upper(vals["name"])
        return super().write(vals)
