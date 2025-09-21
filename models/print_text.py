# -*- coding: utf-8 -*-
from odoo import fields, models


class AssistecPrintText(models.Model):
    _name = "assistec.print.text"
    _description = "Textos apresentados nos comprovantes (HTML editável)"
    _order = "code"

    name = fields.Char(required=True)
    code = fields.Selection([
        ("header",        "Cabeçalho"),
        ("entry_notice",  "Aviso Entrada"),
        ("exit_notice",   "Aviso Saída"),
    ], required=True, readonly=True)

    body_html = fields.Html(string="Conteúdo", sanitize=False)

    _sql_constraints = [
        ("code_unique", "unique(code)",
         "Já existe um registro para esse código.")
    ]
