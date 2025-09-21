# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class AssistecOrderLine(models.Model):
    _name = "assistec.order.line"
    _description = "Linha de Serviço"

    # --------------------------------------------------
    #  Relacionamentos básicos
    # --------------------------------------------------
    order_id = fields.Many2one(
        "assistec.order",
        string="Ordem",
        required=True,
        ondelete="cascade",
        index=True,
    )
    service_id = fields.Many2one(
        "assistec.service",
        string="Serviço",
        required=True,
        index=True,
    )
    description = fields.Char("Descrição (opcional)")
    quantity = fields.Float("Qtd.", default=1.0)
    uom_id = fields.Many2one("uom.uom", string="Unidade")

    # --------------------------------------------------
    #  Preço – agora independente, não altera list_price
    # --------------------------------------------------
    price_unit = fields.Monetary(
        string="Preço",
        store=True,
        currency_field="currency_id",
    )

    @api.onchange("service_id")
    def _onchange_service_price(self):
        """Ao escolher o serviço, traz o preço de tabela como padrão."""
        for line in self:
            line.price_unit = line.service_id.list_price if line.service_id else 0.0

    # --------------------------------------------------
    #  Descontos
    # --------------------------------------------------
    discount_type = fields.Selection(
        [
            ("percent", "Percentual (%)"),
            ("amount", "Valor (moeda)"),
            ("price",  "Preço fixo"),
        ],
        string="Tipo de Desconto",
        default=lambda self: self._default_discount_type(),
    )
    discount_value = fields.Float("Valor do Desconto")

    # --------------------------------------------------
    #  Subtotal
    # --------------------------------------------------
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

    # --------------------------------------------------
    #  Helpers de configuração (já existiam)
    # --------------------------------------------------
    @api.model
    def _discount_flags(self):
        icp = self.env["ir.config_parameter"].sudo()

        def truthy(v):
            return str(v or "").lower() in ("1", "true", "yes", "y", "on")

        allow_percent = truthy(icp.get_param("assistec.discount_allow_percent", True))
        allow_amount  = truthy(icp.get_param("assistec.discount_allow_amount",  True))
        return allow_percent, allow_amount

    @api.model
    def _default_discount_type(self):
        allow_percent, allow_amount = self._discount_flags()
        if allow_percent and not allow_amount:
            return "percent"
        if allow_amount and not allow_percent:
            return "amount"
        return "percent"

    def _sanitize_discount_type(self):
        allow_percent, allow_amount = self._discount_flags()
        for line in self:
            if line.discount_type == "percent" and not allow_percent:
                line.discount_type = "amount" if allow_amount else False
            elif line.discount_type == "amount" and not allow_amount:
                line.discount_type = "percent" if allow_percent else False
            if not allow_percent and not allow_amount:
                line.discount_value = 0.0

    # --------------------------------------------------
    #  Cálculo de Subtotal
    # --------------------------------------------------
    @api.depends("quantity", "price_unit", "discount_type", "discount_value")
    def _compute_subtotal(self):
        for line in self:
            qty   = line.quantity or 0.0
            price = line.price_unit or 0.0
            base  = qty * price
            disc  = 0.0
            if line.discount_type == "percent":
                disc = base * (line.discount_value or 0.0) / 100.0
            elif line.discount_type == "amount":
                disc = line.discount_value or 0.0
            elif line.discount_type == "price":
                line.subtotal = qty * (line.discount_value or 0.0)
                continue
            line.subtotal = max(base - disc, 0.0)

    # --------------------------------------------------
    #  CRUD – garante preço default fora do onchange
    # --------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        Service = self.env["assistec.service"]
        for vals in vals_list:
            if not vals.get("price_unit") and vals.get("service_id"):
                vals["price_unit"] = Service.browse(vals["service_id"]).list_price or 0.0
        records = super().create(vals_list)
        records._sanitize_discount_type()
        for rec in records:
            if rec.order_id:
                rec.order_id.message_post(
                    body=_("Linha adicionada: %s (Qtd %s)")
                    % (rec.service_id.display_name, rec.quantity),
                    message_type="comment",
                    subtype_xmlid="mail.mt_note",
                )
        return records

    def write(self, vals):
        res = super().write(vals)
        self._sanitize_discount_type()
        for rec in self:
            if rec.order_id:
                rec.order_id.message_post(
                    body=_("Linha atualizada: %s") % rec.service_id.display_name,
                    message_type="comment",
                    subtype_xmlid="mail.mt_note",
                )
        return res

    def unlink(self):
        for rec in self:
            if rec.order_id:
                rec.order_id.message_post(
                    body=_("Linha removida: %s") % rec.service_id.display_name,
                    message_type="comment",
                    subtype_xmlid="mail.mt_note",
                )
        return super().unlink()
