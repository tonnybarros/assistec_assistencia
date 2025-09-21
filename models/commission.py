# -*- coding: utf-8 -*-
from datetime import datetime, time, date, timedelta
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _

# CLASSE 1: O ASSISTENTE (WIZARD)
class AssistecCommissionWizard(models.TransientModel):
    _name = "assistec.commission.wizard"
    _description = "Gerar Comissão"

    period_preset = fields.Selection([
        ('custom', 'Período Customizado'), ('day', 'Hoje'),
        ('week', 'Esta Semana'), ('month', 'Este Mês'),
    ], string="Período Pré-definido", default='month')
    
    responsible_id = fields.Many2one(
        "res.users", string="Responsável", domain=[("share", "=", False)],
        help="(Opcional) filtra por responsável."
    )
    date_from = fields.Date(
        string="Data de Início", required=True, 
        default=lambda self: fields.Date.today().replace(day=1)
    )
    date_to = fields.Date(
        string="Data Final", required=True, 
        default=fields.Date.today
    )
    
    @api.onchange('period_preset')
    def _onchange_period_preset(self):
        if self.period_preset == 'day':
            today = date.today()
            self.date_from = today
            self.date_to = today
        elif self.period_preset == 'week':
            today = date.today()
            self.date_from = today - timedelta(days=today.weekday())
            self.date_to = self.date_from + timedelta(days=6)
        elif self.period_preset == 'month':
            today = date.today()
            self.date_from = today.replace(day=1)
            self.date_to = (self.date_from + relativedelta(months=1)) - timedelta(days=1)

    # GARANTA QUE ESTE MÉTODO ESTEJA CORRETAMENTE INDENTADO DENTRO DA CLASSE
    def action_generate(self):
        self.ensure_one()
        # Lógica de cálculo...
        order_domain = [
            ("date_repaired", "!=", False), ("date_out", "!=", False),
            ("date_out", ">=", self.date_from), ("date_out", "<=", self.date_to),
        ]
        if self.responsible_id:
            order_domain.append(("responsible_id", "=", self.responsible_id.id))
        orders = self.env["assistec.order"].search(order_domain)
        Line = self.env["assistec.commission.line"]
        commission_domain_to_delete = [
            ('date_out', '>=', self.date_from), ('date_out', '<=', self.date_to),
        ]
        if self.responsible_id:
            commission_domain_to_delete.append(('responsible_id', '=', self.responsible_id.id))
        Line.search(commission_domain_to_delete).unlink()
        percent = float(self.env["ir.config_parameter"].sudo().get_param("assistec.commission_percent", "15.0")) / 100.0
        vals_list = []
        for o in orders:
            base = sum(o.line_ids.mapped("subtotal"))
            comm = base * percent
            if comm > 0:
                vals_list.append({
                    "order_id": o.id, "responsible_id": o.responsible_id.id,
                    "base_amount": base, "commission": comm, "date_out": o.date_out.date(),
                })
        if vals_list:
            Line.create(vals_list)
            message = {
                'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {
                    'title': _('Sucesso!'), 'message': '%s comissões foram calculadas.' % len(vals_list),
                    'type': 'success', 'sticky': False,
                }
            }
        else:
            message = {
                'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {
                    'title': _('Aviso'), 'message': 'Nenhuma nova comissão encontrada.',
                    'type': 'info', 'sticky': False,
                }
            }
        return message

# CLASSE 2: O MODELO DA LINHA DE COMISSÃO
class AssistecCommissionLine(models.Model):
    _name = "assistec.commission.line"
    _description = "Linha de Comissão"
    _order = "date_out desc"

    order_id = fields.Many2one("assistec.order", string="OS")
    partner_id = fields.Many2one(related="order_id.partner_id", string="Cliente", store=True)
    responsible_id = fields.Many2one("res.users", string="Responsável")
    base_amount = fields.Monetary("Valor Total")
    commission = fields.Monetary("Comissão")
    date_out = fields.Date("Data de Saída")
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id.id)