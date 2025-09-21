# -*- coding: utf-8 -*- 
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

class AssistecStage(models.Model):
    _name = "assistec.stage"
    _description = "Estágio da OS"
    _order = "sequence, id"

    name = fields.Char("Nome", required=True)
    code = fields.Char("Código", help="Identificador técnico (ex.: draft, confirmed, in_progress, done, cancelled).", index=True)
    sequence = fields.Integer(default=10, index=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company.id)

    # Classe visual para usar em lista/kanban (futuro)
    ui_class = fields.Selection([
        # --- Cores Padrão do Odoo (para referência) ---
        ("success",  "Sucesso (Verde Padrão)"),
        ("warning",  "Aviso (Laranja Padrão)"),
        ("danger",   "Perigo (Vermelho Padrão)"),
        
        # --- NOSSA PALETA DE CORES CUSTOMIZADA ---
        ('roxo',        "Roxo"),
        ('ciano',       "Ciano"),
        ('marrom',      "Marrom"),
        ('rosa',        "Rosa"),
        ('verde_limao', "Verde Limão"),
        ('cinza_escuro',"Cinza Escuro"),
        ('amarelo',     "Amarelo Sol"),
        
        # --- Cores Padrão Opcionais ---
        ('primary',  "Primária (Azul Padrão)"),
        ('info',     "Info (Azul Claro Padrão)"),

        # ---Ultima Cores adicionadas ---
        ('azul_escuro',   "Azul escuro"),
        ('verde_escuro',  "Verde escuro"),
        ('preto',         "Preto"),
        ('cinza_claro',   "Cinza claro"),
        ('vermelho_claro',"Vermelho claro"),
        
        ('',         "Sem cor"),
    ], string="Cor", default="")

    # Gatilhos automáticos (opcionais)
    is_default = fields.Boolean("Padrão ao criar")
    mark_repaired = fields.Boolean("Marcar 'Reparado' ao entrar")
    mark_closed = fields.Boolean("Marcar 'Fechada' ao entrar")
    is_cancel = fields.Boolean("Estágio de cancelamento")

    _sql_constraints = [
        ("code_company_unique", "unique(code, company_id)", "Já existe um estágio com esse código nesta empresa."),
    ]

    @api.constrains("is_default", "company_id")
    def _check_single_default(self):
        for rec in self.filtered("is_default"):
            dom = [("is_default", "=", True), ("company_id", "=", rec.company_id.id), ("id", "!=", rec.id)]
            if self.search_count(dom):
                raise ValidationError(_("Só pode existir um estágio padrão por empresa."))

    def name_get(self):
        res = []
        for rec in self:
            label = rec.name
            if rec.code:
                label = f"[{rec.code}] {rec.name}"
            res.append((rec.id, label))
        return res
