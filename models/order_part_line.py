# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class AssistecOrderPartLine(models.Model):
    _name = "assistec.order.part.line"
    _description = "Linha de Peça"

    order_id = fields.Many2one(
        "assistec.order",
        string="Ordem",
        required=True,
        ondelete="cascade",
        index=True,
    )
    part_id = fields.Many2one(
        "assistec.part",
        string="Peça",
        required=True,
        index=True,
    )
    description = fields.Char("Descrição (opcional)")
    quantity = fields.Float("Qtd.", default=1.0)
    uom_id = fields.Many2one("uom.uom", string="Unidade")

    # Preço independente
    price_unit = fields.Monetary(
        string="Preço",
        store=True,
        currency_field="currency_id",
    )

    @api.onchange("part_id")
    def _onchange_part_price(self):
        for line in self:
            line.price_unit = line.part_id.list_price if line.part_id else 0.0

    subtotal = fields.Monetary(
        string="Subtotal",
        compute="_compute_subtotal",
        store=True,
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        related="order_id.currency_id",
        string="Moeda",
        store=True,
        readonly=True,
    )

    # ---------- Cálculo ----------
    @api.depends("quantity", "price_unit")
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = (line.quantity or 0.0) * (line.price_unit or 0.0)

    # ---------- CRUD ----------
    @api.model_create_multi
    def create(self, vals_list):
        Part = self.env["assistec.part"]
        for vals in vals_list:
            if not vals.get("price_unit") and vals.get("part_id"):
                vals["price_unit"] = Part.browse(vals["part_id"]).list_price or 0.0
        records = super().create(vals_list)
        for rec in records:
            if rec.order_id:
                rec.order_id.message_post(
                    body=_("Peça adicionada: %s (Qtd %s)") %
                    (rec.part_id.display_name, rec.quantity),
                    message_type="comment",
                    subtype_xmlid="mail.mt_note",
                )
        return records

    def write(self, vals):
        res = super().write(vals)
        for rec in self:
            if rec.order_id:
                rec.order_id.message_post(
                    body=_("Peça atualizada: %s") % rec.part_id.display_name,
                    message_type="comment",
                    subtype_xmlid="mail.mt_note",
                )
        return res

    def unlink(self):
        for rec in self:
            if rec.order_id:
                rec.order_id.message_post(
                    body=_("Peça removida: %s") % rec.part_id.display_name,
                    message_type="comment",
                    subtype_xmlid="mail.mt_note",
                )
        return super().unlink()
