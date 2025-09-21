# -*- coding: utf-8 -*-
from odoo import models, fields

class AssistecPaymentMethod(models.Model):
    _name = "assistec.payment.method"
    _description = "Forma de Pagamento"
    _order = "sequence, name"

    name = fields.Char("Nome", required=True)
    sequence = fields.Integer("Sequência", default=10)
    active = fields.Boolean("Ativo", default=True)

    _sql_constraints = [
        ('name_uniq', 'unique(name)', "Esta forma de pagamento já existe.")
    ]
