from odoo import api, fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    order_sequence_id = fields.Many2one(
        "ir.sequence",
        string="Sequência das OS",
        domain="[('code', '=', 'assistec.order')]",
        config_parameter="assistec.order_sequence_id",
        help="Sequência usada para numerar as Ordens de Serviço.",
    )

    # Flags de desconto (mantidas)
    discount_allow_percent = fields.Boolean(
        string="Permitir desconto percentual", default=True,
        config_parameter="assistec.discount_allow_percent"
    )
    discount_allow_amount = fields.Boolean(
        string="Permitir desconto em valor", default=True,
        config_parameter="assistec.discount_allow_amount"
    )

    # ✅ Webhook
    webhook_url = fields.Char(
        string="URL Webhook n8n",
        config_parameter="assistec.webhook_url",
        help="URL do webhook para integração com n8n ou outros sistemas."
    )
    webhook_verify_ssl = fields.Boolean(
        string="Verificar SSL no webhook",
        default=True,
        config_parameter="assistec.webhook_verify_ssl",
    )
    webhook_enabled = fields.Boolean(
        string="Ativar envio de webhook",
        default=True,
        config_parameter="assistec.webhook_enabled",
    )
    webhook_on_create = fields.Boolean(
        string="Enviar ao criar OS",
        default=True,
        config_parameter="assistec.webhook_on_create",
    )
    webhook_on_state_change = fields.Boolean(
        string="Enviar ao mudar o estado",
        default=True,
        config_parameter="assistec.webhook_on_state_change",
    )
    webhook_state_whitelist = fields.Char(
        string="States para disparar (lista)",
        default="confirmed,in_progress,done,cancelled",
        config_parameter="assistec.webhook_state_whitelist",
        help="Lista separada por vírgulas dos states que disparam webhook. Deixe vazio para enviar em qualquer state."
    )
    webhook_timeout = fields.Integer(
        string="Timeout (s)",
        default=10,
        config_parameter="assistec.webhook_timeout",
    )
    webhook_headers_json = fields.Char(
        string="Headers adicionais (JSON)",
        help="Ex.: {'Authorization':'Bearer XXX'}",
        config_parameter="assistec.webhook_headers_json",
    )

    # Toggle global para maiúsculas (mantido)
    uppercase_enabled = fields.Boolean(
        string="Forçar maiúsculas (cliente e aparelho)",
        default=True,
        config_parameter="assistec.uppercase_enabled",
        help="Quando marcado, converte para MAIÚSCULAS os campos de texto do cliente e do aparelho."
    )

    # >>> NOVO: método chamado pelo botão nas Configurações
    def action_open_discount_catalog(self):
        """
        Abre a ação do Catálogo de Descontos (assistec.discount).
        Use este método com um botão type='object' na view de Configurações.
        """
        action = self.env.ref(
            'assistec_assistencia.action_assistec_discount',
            raise_if_not_found=False
        )
        if action:
            res = action.read()[0]
            # opcional: deixar só ativos por padrão
            res.setdefault('context', {})
            res['context'].update({'search_default_active': 1})
            return res
        # fallback caso a ação ainda não exista
        return {'type': 'ir.actions.act_window_close'}

    warranty_days = fields.Integer(
        string="Dias de garantia",
        default=90,
        config_parameter="assistec.warranty_days",
        help="Quantidade de dias que serão somados à Data de saída para calcular a data final de garantia."
    )

    delivery_workdays = fields.Integer(
        string="Prazo padrão de entrega (dias úteis)",
        default=5,
        config_parameter="assistec.delivery_workdays",
        help=("Número de dias úteis somados à data de entrada quando a OS é "
            "autorizada. Deixe 0 para não gerar automaticamente.")
    )

    webhook_stage_ids = fields.Many2many(
        "assistec.stage",
        string="Disparar nos estágios",
        help="Selecione em quais estágios o webhook deve disparar. "
             "Deixe vazio para disparar em qualquer estágio."
    )

    # ------------------  sincroniza <--> ir.config_parameter  ------------------
    def set_values(self):
        super().set_values()
        ICP = self.env["ir.config_parameter"].sudo()
        codes = ",".join(self.webhook_stage_ids.mapped("code"))
        ICP.set_param("assistec.webhook_state_whitelist", codes)

    @api.model
    def get_values(self):
        vals = super().get_values()
        ICP = self.env["ir.config_parameter"].sudo()
        codes = (ICP.get_param("assistec.webhook_state_whitelist") or "").split(",")
        stages = self.env["assistec.stage"].search([("code", "in", codes)])
        vals["webhook_stage_ids"] = [(6, 0, stages.ids)]
        return vals

    commission_percent = fields.Float(
        string="Percentual de comissão (%)",
        default=15.0,
        config_parameter="assistec.commission_percent",
        help="Percentual aplicado SOMENTE sobre o total de serviços."
    )

    header_text_id = fields.Many2one(
        "assistec.print.text",
        string="Cabeçalho",
        domain=[("code", "=", "header")],
        config_parameter="assistec.header_text_id",
    )
    entry_text_id = fields.Many2one(
        "assistec.print.text",
        string="Aviso Entrada",
        domain=[("code", "=", "entry_notice")],
        config_parameter="assistec.entry_text_id",
    )
    exit_text_id = fields.Many2one(
        "assistec.print.text",
        string="Aviso Saída",
        domain=[("code", "=", "exit_notice")],
        config_parameter="assistec.exit_notice_id",
    )