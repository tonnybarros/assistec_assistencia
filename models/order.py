# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models, tools, _
from odoo.exceptions import UserError, ValidationError
from odoo.osv.expression import OR, AND
from markupsafe import Markup, escape
import re
import requests


_logger = logging.getLogger(__name__)

try:
    import brazilcep
except Exception:
    brazilcep = None
from datetime import timedelta
try:
    from dateutil.relativedelta import relativedelta
except Exception:
    relativedelta = None

PHONE_RE = re.compile(r"\D+")

def _format_msisdn(raw):
    """Converte ‘(11) 91234-5678’ → ‘5511912345678’ ou None."""
    if not raw:
        return None
    digits = PHONE_RE.sub("", raw)
    if len(digits) < 10:      # ajuste conforme sua regra
        return None
    if digits.startswith("0"):
        digits = digits[1:]
    if not digits.startswith("55"):     # Brasil fixo; adapte se preciso
        digits = "55" + digits
    return digits
    
# ---------------------------------------------------------------------------
# País BR por padrão ao criar contato (inclusive criação rápida)
# ---------------------------------------------------------------------------
class ResPartner(models.Model):
    _inherit = "res.partner"

    country_id = fields.Many2one(
        "res.country",
        default=lambda self: self.env.ref("base.br", raise_if_not_found=False),
    )

    def _assistec_uppercase_enabled(self):
        return (
            self.env["ir.config_parameter"].sudo()
            .get_param("assistec.uppercase_enabled", "True")
            in ("1", "true", "True")
        )

    @api.model_create_multi
    def create(self, vals_list):
        if self._assistec_uppercase_enabled():
            for vals in vals_list:
                n = vals.get("name")
                if isinstance(n, str):
                    vals["name"] = n.strip().upper()
        return super().create(vals_list)

    def write(self, vals):
        if self._assistec_uppercase_enabled():
            n = vals.get("name")
            if isinstance(n, str):
                vals["name"] = n.strip().upper()
        return super().write(vals)

# ---------------------------------------------------------------------------
# Configurações do módulo
# ---------------------------------------------------------------------------
class AssistecSettings(models.TransientModel):
    _inherit = "res.config.settings"

    order_sequence_id = fields.Many2one(
        "ir.sequence",
        string="Sequência das OS",
        config_parameter="assistec.order_sequence_id",
        help="Sequência usada para numerar as Ordens de Serviço.",
    )

    assistec_uppercase_enabled = fields.Boolean(
        string="Forçar maiúsculas (cliente e aparelho)",
        config_parameter="assistec.uppercase_enabled",
        default=True,
        help="Quando ativo, converte para MAIÚSCULAS os campos de texto do cliente e do aparelho.",
    )


# ---------------------------------------------------------------------------
# Marcadores (tags) da OS
# ---------------------------------------------------------------------------
class AssistecTag(models.Model):
    _name = "assistec.tag"
    _description = "Marcadores de OS"
    _order = "name"

    name = fields.Char("Nome", required=True)
    color = fields.Integer("Cor")  # usado pelo widget many2many_tags

    _sql_constraints = [
        ("name_unique", "unique(name)", "Já existe um marcador com esse nome."),
    ]

def add_workdays(env, start_date, days=None):
    if days is None:
        ICP = env["ir.config_parameter"].sudo()
        days = int(ICP.get_param("assistec.delivery_workdays", default="5"))
    if not days:
        return start_date
    if isinstance(start_date, str):
        start_date = fields.Date.from_string(start_date)
    added = 0
    while added < days:
        start_date += timedelta(days=1)
        if start_date.weekday() < 5:
            added += 1
    return start_date

# ---------------------------------------------------------------------------
# Ordem de Serviço
# ---------------------------------------------------------------------------
class AssistecOrder(models.Model):
    _name = "assistec.order"
    _description = "Ordem de Serviço"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _rec_name = "name"

    # Identificação
    name = fields.Char(
        "Número",
        default=lambda self: _("Novo"),
        tracking=True,
        copy=False,
        required=True,
        index=True,
    )

    # Cliente
    partner_id = fields.Many2one(
        "res.partner", string="Cliente", required=True, tracking=True, index=True
    )

    # Espelhos do partner (sempre existentes)
    partner_zip = fields.Char(related="partner_id.zip", string="CEP", readonly=False, tracking=True)
    partner_street2 = fields.Char(related="partner_id.street2", string="Bairro", readonly=False, tracking=True)
    partner_city = fields.Char(related="partner_id.city", string="Cidade", readonly=False, tracking=True)
    partner_state_id = fields.Many2one(
        "res.country.state", related="partner_id.state_id", string="Estado", readonly=False, tracking=True
    )
    partner_country_id = fields.Many2one(
        "res.country", related="partner_id.country_id", string="País", readonly=False, tracking=True
    )
    partner_mobile = fields.Char(
        related="partner_id.mobile",
        string="Celular",
        readonly=False,   # permite editar direto na OS
        store=True,       # grava a cópia na tabela assistec_order
        index=True,
        tracking=True,
    )


    # Nome da rua (apenas o nome). Lê de street_name quando existir; senão, street.
    partner_street = fields.Char(
        string="Endereço",
        compute="_compute_partner_street",
        inverse="_inverse_partner_street",
        store=False,
        tracking=True
    )

    # Número / Complemento (locais na OS; espelhados depois no partner)
    customer_street_number = fields.Char("Número")
    customer_street_comp = fields.Char("Compl.")

    # Documento (tipo + número como no contato)
    partner_ident_type_id = fields.Many2one(
        "l10n_latam.identification.type",
        string="Tipo doc.",
        help="Selecione CPF/CNPJ (se o módulo LATAM estiver instalado).",
        tracking=True
    )
    partner_vat = fields.Char(
        related="partner_id.vat", string="CPF", readonly=False, index=True, tracking=True
    )

    # Atendimento
    responsible_id = fields.Many2one(
        "res.users",
        string="Responsável",
        default=lambda self: self.env.user,
        tracking=True,
        index=True,
    )
    date_in = fields.Datetime("Data de entrada", default=fields.Datetime.now, tracking=True)
    warranty = fields.Boolean("Está na garantia?", tracking=True)

    # Datas de atendimento
    date_repaired = fields.Datetime("Data reparado", tracking=True)
    date_out = fields.Datetime("Data de saída", tracking=True)

    # Garantia calculada = date_out + warranty_days (configuração)
    date_warranty = fields.Datetime(
        "Garantia até",
        compute="_compute_warranty_date",
        store=True,
    )

    # CAMPOS NOVOS PARA CONTROLAR A VISIBILIDADE DOS BOTÕES
    stage_is_default = fields.Boolean(
        string="Estágio é Inicial?",
        related='stage_id.is_default',
        store=True,
        readonly=True
    )
    stage_is_closed = fields.Boolean(
        string="Estágio é Final?",
        related='stage_id.mark_closed',
        store=True,
        readonly=True
    )
    stage_is_repaired = fields.Boolean(
        string="Estágio é Reparado?",
        related="stage_id.mark_repaired",  # usa o bool nativo do estágio
        readonly=True
    )

    # NOVO ▸ True só nas etapas em que o botão “Consertado” faz sentido
    stage_can_mark_repaired = fields.Boolean(
        compute="_compute_stage_can_mark_repaired",
        store=False,
    )

    # ajuste aqui os códigos/IDs das etapas ‘aprovadas’
    _STAGES_CAN_MARK = {"autorizado", "aguardando_reparo", "aprovado"}

    @api.depends("stage_id.code")
    def _compute_stage_can_mark_repaired(self):
        for rec in self:
            rec.stage_can_mark_repaired = (
                rec.stage_id and                    # tem etapa
                not rec.stage_id.mark_repaired and  # ainda NÃO reparada
                (rec.stage_id.code or "").lower() in self._STAGES_CAN_MARK
            )


    def action_open_close_wizard(self):
        """Abre o wizard Encerrar OS já usado pelo menu Situação ▸ Encerrar OS."""
        self.ensure_one()
        action = self.env.ref(
            "assistec_assistencia.action_open_close_stage_wizard"
        ).read()[0]
        action["context"] = {
            **self.env.context,
            "active_id": self.id,
            "active_model": "assistec.order",
        }
        return action

    def action_mark_repaired(self):
        """Leva a OS para a primeira etapa que tenha mark_repaired=True."""
        self.ensure_one()

        if not self.stage_can_mark_repaired:
            raise UserError(_("Esta OS não está em etapa apropriada para ser marcada como reparada."))

        Stage = self.env["assistec.stage"].sudo()
        new_stage = Stage.search(
            [("mark_repaired", "=", True),
            ("active", "=", True),
            ("company_id", "in", [False, self.company_id.id])],
            order="sequence asc",
            limit=1,
        )
        if not new_stage:
            raise UserError(_("Configure ao menos uma etapa marcada como 'Reparado'."))

        self.write({"stage_id": new_stage.id})

        body = Markup(
            _("Situação alterada para <b>%s</b> (Reparado).") % escape(new_stage.name)
        )
        self.message_post(body=body, subtype_xmlid="mail.mt_comment", message_type="comment")
        return True

    @api.model
    def _name_search(self, name, args=None, operator="ilike", limit=80, name_get_uid=None):
        """
        Permite que a quick-search procure por:
        - Número da OS (name)
        - Nome do cliente
        - Cidade
        - Celular
        - Responsável
        - CPF/CNPJ
        """
        if not name:
            return super()._name_search(name, args, operator, limit, name_get_uid)

        domain_or = [
            ("name", operator, name),                       # Nº da OS
            ("partner_id.name", operator, name),            # Cliente
            ("partner_city", operator, name),               # Cidade
            ("partner_mobile", operator, name),             # Celular
            ("responsible_id.name", operator, name),        # Responsável
            ("partner_vat", operator, name),                # CPF/CNPJ
        ]
        domain = OR([[d] for d in domain_or])              # junta com OR
        if args:
            domain = AND([args, domain])

        recs = self.search(domain, limit=limit)
        return recs.name_get()


    @api.depends("date_out")
    def _compute_warranty_date(self):
        Param = self.env["ir.config_parameter"].sudo()
        try:
            days = int(Param.get_param("assistec.warranty_days", 90))
        except Exception:
            days = 90

        for rec in self:
            if rec.date_out:
                rec.date_warranty = (
                    rec.date_out + (relativedelta(days=days) if relativedelta else timedelta(days=days))
                )
            else:
                rec.date_warranty = False

    # Marcadores
    tag_ids = fields.Many2many(
        "assistec.tag",
        "assistec_order_tag_rel", "order_id", "tag_id",
        string="Marcadores",
        help="Classifique a OS com etiquetas (ex.: Urgente, Garantia, VIP).",
    )

    # --- Aparelho -----------------------------------------------------------
    repair_product_id = fields.Many2one(
        "assistec.repair.product",
        string="Produto para Reparar",
        required=True,
        tracking=True,
        ondelete="restrict",
    )
    brand_id = fields.Many2one(
        "assistec.brand",
        string="Marca",
        required=True,
        tracking=True,
        ondelete="restrict",
    )
    model = fields.Char(
        string="Modelo",
        required=True,
        tracking=True,
    )
    serial_number = fields.Char(
        string="Número de Série",
        required=True, 
        tracking=True,
    )
    color = fields.Char(
        string="Cor",
        required=True,
        tracking=True,
    )

    # --- Complementos -------------------------------------------------------
    issue_description = fields.Text(
        string="Descrição do defeito",
        required=True,
        tracking=True,
    )
    accessories = fields.Char(
        string="Acessórios",
        required=True,
        tracking=True,
    )
    image_ids = fields.Many2many(
        "ir.attachment",
        string="Imagens do Aparelho",
        tracking=True,
    )
    notes = fields.Text(
        string="Observações",
        tracking=True,
    )
    defeito_real = fields.Text(
        string="Defeito Real",
        tracking=True,
    )
    laudo_tecnico = fields.Text(
        string="Laudo Técnico",
        tracking=True,
    )
    repair_notes = fields.Text(
        string="Notas de reparo",
        tracking=True,
    )

    kanban_cover_image = fields.Binary(
        "Imagem de Capa", 
        compute='_compute_kanban_cover_image',
        store=False # Não precisa salvar no banco, é calculado sob demanda
    )

    # NOVA FUNÇÃO PARA CALCULAR A IMAGEM
    def _compute_kanban_cover_image(self):
        for order in self:
            # Procura pelo primeiro anexo que seja uma imagem
            first_image = next((
                att for att in order.image_ids 
                if att.mimetype and att.mimetype.startswith('image')
            ), False)
            
            if first_image:
                order.kanban_cover_image = first_image.datas
            else:
                order.kanban_cover_image = False

    # Campo único para o calendário
    calendar_delivery_date = fields.Date(
        string="Data para Calendário",
        compute='_compute_calendar_delivery_date',
        store=True
    )

    @api.depends('delivery_date')
    def _compute_calendar_delivery_date(self):
        for order in self:
            order.calendar_delivery_date = order.delivery_date

    # NOVO CAMPO PARA CONTROLAR A COR DINAMICAMENTE
    calendar_color_index = fields.Integer(
        string="Índice de Cor do Calendário",
        compute='_compute_calendar_color_index'
    )

    @api.depends('priority', 'responsible_id')
    def _compute_calendar_color_index(self):
        for order in self:
            if order.priority == '1':  # '1' é o valor para "Favorito/Estrela"
                # Usamos um índice de cor fixo para urgentes. O índice 10 é tipicamente vermelho.
                order.calendar_color_index = 10
            else:
                # Para os normais, usamos o ID do responsável para ter cores variadas por usuário.
                order.calendar_color_index = order.responsible_id.id if order.responsible_id else 0

    # Adicione este campo à sua classe AssistecOrder
    payment_method_id = fields.Many2one(
        "assistec.payment.method",
        string="Forma de Pagamento",
        tracking=True,
        index=True
    )


    # Linhas
    line_ids = fields.One2many("assistec.order.line", "order_id", string="Serviços", copy=True)

    # Totais
    currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        store=True,
        readonly=True,
    )
    amount_untaxed  = fields.Monetary("Subtotal",
                                    currency_field="currency_id",
                                    compute="_compute_amounts", store=True)

    amount_total    = fields.Monetary("Total",
                                    currency_field="currency_id",
                                    compute="_compute_amounts", 
                                    store=True,
                                    default=0.0)

    amount_gross    = fields.Monetary("Valor Sem Descontos",
                                    currency_field="currency_id",
                                    compute="_compute_amounts", store=True)
    amount_discount = fields.Monetary("Descontos",
                                    currency_field="currency_id",
                                    compute="_compute_amounts", store=True)

    # --- Estágio selecionável (novo) ---
    company_id = fields.Many2one(
        "res.company",
        string="Empresa",
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )

    # ⭐ Favorito / Estrela
    priority = fields.Selection(
        [("0", "Normal"), ("1", "Starred")],
        string="Favorito",
        default="0",
        index=True,
    )

    def _default_stage_id(self):
        Stage = self.env["assistec.stage"]
        if not Stage:
            return False
        stg = Stage.search([
            ("company_id", "in", [False, self.env.company.id]),
            ("is_default", "=", True),
            ("active", "=", True),
        ], limit=1)
        if not stg:
            stg = Stage.search([
                ("company_id", "in", [False, self.env.company.id]),
                ("active", "=", True),
            ], order="sequence, id", limit=1)
        return stg.id or False


    stage_id = fields.Many2one(
        "assistec.stage",
        string="Etapa",
        tracking=True,
        index=True,
        default=_default_stage_id,
        ondelete="restrict",
    )
    # ajuda para a lista (cores do badge)
    stage_ui_class = fields.Selection(
        selection=[
            ("",         "Sem cor"),
            ("primary",  "Roxo"),    # roxo-claro / standard
            ("secondary","Cinza"),  # cinza-médio
            ("info",     "Azul"),        # azul-claro
            ("warning",  "Laranja"),     # amarelo/laranja
            ("muted",    "Cinza"),       # cinza-claro
            ("success",  "Verde"),     # verde-claro
            ("danger",   "Vermelho"),    # vermelho
        ],
        related="stage_id.ui_class",
        store=True,
        readonly=True,
        index=True,
    )


    # Estado “legacy” (mantido só p/compatibilidade), agora deriva do stage
    state = fields.Selection([
        ("draft", "Rascunho"),
        ("confirmed", "Confirmada"),
        ("in_progress", "Em andamento"),
        ("done", "Finalizada"),
        ("cancelled", "Cancelada"),
    ], compute="_compute_state_from_stage", store=True, readonly=True, index=True)

    @api.depends("stage_id.code")
    def _compute_state_from_stage(self):
        map_codes = {
            "draft": "draft",
            "confirmed": "confirmed",
            "in_progress": "in_progress",
            "progress": "in_progress",
            "running": "in_progress",
            "done": "done",
            "finished": "done",
            "closed": "done",
            "cancel": "cancelled",
            "cancelled": "cancelled",
            "canceled": "cancelled",
        }
        for rec in self:
            code = (rec.stage_id.code or "").strip().lower()
            rec.state = map_codes.get(code, rec.state or "draft")

    # ---------------- Utils ----------------
    def _uppercase_enabled(self):
        return (
            self.env["ir.config_parameter"].sudo()
            .get_param("assistec.uppercase_enabled", "True")
            in ("1", "true", "True")
        )

    @staticmethod
    def _only_digits(s): return "".join(ch for ch in (s or "") if ch.isdigit())
    @staticmethod
    def _format_cpf(d):  return f"{d[0:3]}.{d[3:6]}.{d[6:9]}-{d[9:11]}"
    @staticmethod
    def _format_cnpj(d): return f"{d[0:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:14]}"

    @staticmethod
    def _is_valid_cpf(d):
        if len(d) != 11 or d == d[0] * 11:
            return False
        nums = list(map(int, d))
        s1 = sum(nums[i] * (10 - i) for i in range(9))
        d1 = (s1 * 10) % 11
        d1 = 0 if d1 == 10 else d1
        if nums[9] != d1:
            return False
        s2 = sum(nums[i] * (11 - i) for i in range(10))
        d2 = (s2 * 10) % 11
        d2 = 0 if d2 == 10 else d2
        return nums[10] == d2

    @staticmethod
    def _is_valid_cnpj(d):
        if len(d) != 14 or d == d[0] * 14:
            return False
        nums = list(map(int, d))
        w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        w2 = [6] + w1
        r1 = sum(n * w for n, w in zip(nums[:12], w1)) % 11
        d1 = 0 if r1 < 2 else 11 - r1
        if nums[12] != d1:
            return False
        r2 = sum(n * w for n, w in zip(nums[:13], w2)) % 11
        d2 = 0 if r2 < 2 else 11 - r2
        return nums[13] == d2

    def _is_type_cpf(self):
        t = self.partner_ident_type_id
        code = ((getattr(t, "code", "") or "")).upper()
        name = ((t.name or "")).upper() if t else ""
        if "CPF" in code or "CPF" in name:
            return True
        return len(self._only_digits(self.partner_vat)) == 11

    def _is_type_cnpj(self):
        t = self.partner_ident_type_id
        code = ((getattr(t, "code", "") or "")).upper()
        name = ((t.name or "")).upper() if t else ""
        if "CNPJ" in code or "CNPJ" in name:
            return True
        return len(self._only_digits(self.partner_vat)) == 14

    def _find_ident_type(self, code):
        Type = self.env.get("l10n_latam.identification.type")
        if not Type:
            return Type
        rec = Type.search([("code", "=", code)], limit=1)
        if not rec:
            rec = Type.search([("name", "ilike", code)], limit=1)
        return rec

    # ---------------- Compute/Inverse do nome da rua ----------------
    @api.depends("partner_id", "partner_id.street", "partner_id.write_date")
    def _compute_partner_street(self):
        Partner = self.env["res.partner"]
        has_street_name = "street_name" in Partner._fields
        for rec in self:
            p = rec.partner_id
            if not p:
                rec.partner_street = False
                continue
            rec.partner_street = p.street_name if has_street_name else p.street

    def _inverse_partner_street(self):
        Partner = self.env["res.partner"]
        has_street_name = "street_name" in Partner._fields
        for rec in self.filtered("partner_id"):
            val = rec.partner_street or ""
            if rec._uppercase_enabled() and isinstance(val, str):
                val = val.upper()
            vals = {"street_name": val} if has_street_name else {"street": val}
            rec.partner_id.sudo().write(vals)

    # ---------------- Onchanges ----------------
    @api.onchange("partner_vat", "partner_ident_type_id")
    def _onchange_partner_vat(self):
        for rec in self:
            raw = rec._only_digits(rec.partner_vat)
            if not raw:
                continue
            if rec._is_type_cpf() and len(raw) == 11:
                if not rec._is_valid_cpf(raw):
                    raise UserError(_("CPF inválido: %s") % (rec.partner_vat or ""))
                rec.partner_vat = rec._format_cpf(raw)
            elif rec._is_type_cnpj() and len(raw) == 14:
                if not rec._is_valid_cnpj(raw):
                    raise UserError(_("CNPJ inválido: %s") % (rec.partner_vat or ""))
                rec.partner_vat = rec._format_cnpj(raw)

    @api.constrains("partner_vat", "partner_ident_type_id")
    def _check_partner_vat(self):
        for rec in self:
            raw = rec._only_digits(rec.partner_vat)
            if not raw:
                continue
            if rec._is_type_cpf() and len(raw) == 11 and not rec._is_valid_cpf(raw):
                raise ValidationError(_("CPF inválido: %s") % (rec.partner_vat or ""))
            if rec._is_type_cnpj() and len(raw) == 14 and not rec._is_valid_cnpj(raw):
                raise ValidationError(_("CNPJ inválido: %s") % (rec.partner_vat or ""))

    @api.onchange("partner_id")
    def _onchange_partner(self):
        for rec in self:
            p = rec.partner_id
            if not p:
                continue

            # País BR default
            if not p.country_id:
                br = rec.env.ref("base.br", raise_if_not_found=False)
                if br:
                    rec.partner_country_id = br.id

            # Fallback mobile
            if not rec.partner_mobile and p.phone:
                rec.partner_mobile = p.phone

            # Número/Complemento
            if "street_number" in p._fields and p.sudo().street_number and not rec.customer_street_number:
                rec.customer_street_number = p.sudo().street_number
            elif "l10n_br_number" in p._fields and p.sudo().l10n_br_number and not rec.customer_street_number:
                rec.customer_street_number = p.sudo().l10n_br_number

            if "street_number2" in p._fields and p.sudo().street_number2 and not rec.customer_street_comp:
                rec.customer_street_comp = p.sudo().street_number2
            elif "l10n_br_street2" in p._fields and p.sudo().l10n_br_street2 and not rec.customer_street_comp:
                rec.customer_street_comp = p.sudo().l10n_br_street2

            # Copiar tipo doc do partner se existir (LATAM)
            if "l10n_latam_identification_type_id" in p._fields and p.l10n_latam_identification_type_id:
                rec.partner_ident_type_id = p.l10n_latam_identification_type_id.id

            # Normalizar CPF/CNPJ conforme tipo
            if rec.partner_vat:
                raw = rec._only_digits(rec.partner_vat)
                if rec._is_type_cpf() and len(raw) == 11:
                    if not rec._is_valid_cpf(raw):
                        raise UserError(_("CPF inválido: %s") % (rec.partner_vat or ""))
                    rec.partner_vat = rec._format_cpf(raw)
                elif rec._is_type_cnpj() and len(raw) == 14:
                    if not rec._is_valid_cnpj(raw):
                        raise UserError(_("CNPJ inválido: %s") % (rec.partner_vat or ""))
                    rec.partner_vat = rec._format_cnpj(raw)

    # Maiúsculas na pré-visualização quando toggle estiver ativo
    @api.onchange(
        "partner_street", "partner_street2", "partner_city",
        "customer_street_number", "customer_street_comp",
        "model", "serial_number", "color",
        "issue_description", "accessories", "notes", "repair_notes"
    )
    def _onchange_upper_preview(self):
        for rec in self:
            if rec._uppercase_enabled():
                for fname in [
                    "partner_street", "partner_street2", "partner_city",
                    "customer_street_comp", "model", "serial_number",
                    "color", "issue_description", "accessories", "notes", "repair_notes",
                ]:
                    val = getattr(rec, fname)
                    if isinstance(val, str):
                        setattr(rec, fname, val.upper())

    # CEP
    @api.onchange("partner_zip")
    def _onchange_zip(self):
        for rec in self:
            cep_raw = rec._only_digits(rec.partner_zip)
            if not brazilcep or not cep_raw or len(cep_raw) < 8:
                continue
            try:
                data = brazilcep.get_address_from_cep(cep_raw)
                rec.partner_street = data.get("street") or ""   # nome da rua
                rec.partner_street2 = data.get("district") or ""
                rec.partner_city = data.get("city") or ""

                uf = (data.get("uf") or "").upper()
                if uf:
                    state = rec.env["res.country.state"].search([("code", "=", uf)], limit=1)
                    rec.partner_state_id = state.id or False

                br = rec.env.ref("base.br", raise_if_not_found=False)
                if br:
                    rec.partner_country_id = br.id

                rec._onchange_upper_preview()
            except Exception as e:
                _logger.warning("Falha ao consultar CEP %s: %s", cep_raw, e)

    # ---------------- Persistência no partner ----------------
    def _prepare_partner_vals_from_order(self):
        self.ensure_one()
        vals = {}

        if not self.partner_id.country_id and self.partner_country_id:
            vals["country_id"] = self.partner_country_id.id

        Partner = self.env["res.partner"]
        has_street_name = "street_name" in Partner._fields

        street_name_val = self.partner_street or ""
        if self._uppercase_enabled() and isinstance(street_name_val, str):
            street_name_val = street_name_val.upper()

        if has_street_name:
            vals["street_name"] = street_name_val
        else:
            vals["street"] = street_name_val

        if self.partner_zip:
            vals["zip"] = self.partner_zip
        if self.partner_street2:
            vals["street2"] = self.partner_street2.upper() if self._uppercase_enabled() else self.partner_street2
        if self.partner_city:
            vals["city"] = self.partner_city.upper() if self._uppercase_enabled() else self.partner_city
        if self.partner_state_id:
            vals["state_id"] = self.partner_state_id.id
        if self.partner_country_id:
            vals["country_id"] = self.partner_country_id.id
        if self.partner_mobile:
            vals["mobile"] = self.partner_mobile
        if self.partner_vat:
            vals["vat"] = self.partner_vat
        if self.partner_ident_type_id and "l10n_latam_identification_type_id" in self.partner_id._fields:
            vals["l10n_latam_identification_type_id"] = self.partner_ident_type_id.id

        # Número/compl.
        Partner = self.env["res.partner"]
        has_num_std = "street_number" in Partner._fields
        has_comp_std = "street_number2" in Partner._fields
        has_num_br = "l10n_br_number" in Partner._fields
        has_comp_br = "l10n_br_street2" in Partner._fields

        if self.customer_street_number:
            if has_num_std:
                vals["street_number"] = self.customer_street_number
            elif has_num_br:
                vals["l10n_br_number"] = self.customer_street_number

        if self.customer_street_comp:
            comp_val = self.customer_street_comp.upper() if self._uppercase_enabled() else self.customer_street_comp
            if has_comp_std:
                vals["street_number2"] = comp_val
            elif has_comp_br:
                vals["l10n_br_street2"] = comp_val
            else:
                base = vals.get("street2") or self.partner_id.street2 or ""
                if comp_val and comp_val not in (base or ""):
                    vals["street2"] = (base + (" - " if base else "") + comp_val)

        return vals

    def _write_back_partner(self):
        for rec in self.filtered("partner_id"):
            vals = rec._prepare_partner_vals_from_order()
            if vals:
                rec.partner_id.sudo().write(vals)

    # ---------------- Helpers de estágio ----------------
    def _find_stage_by_code(self, code):
        if not code:
            return self.env["assistec.stage"]
        return self.env["assistec.stage"].search([
            ("code", "=", code),
            ("company_id", "in", [False, self.env.company.id]),
            ("active", "=", True),
        ], limit=1)

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        if "stage_id" in self._fields and "stage_id" in fields_list:
            stg = self.env["assistec.stage"].search([
                ("is_default", "=", True),
                ("company_id", "in", [False, self.env.company.id]),
                ("active", "=", True),
            ], limit=1)
            if not stg:
                stg = self._find_stage_by_code("draft")
            if stg:
                vals["stage_id"] = stg.id
        return vals

    def _apply_stage_triggers(self, new_stage):
        if not new_stage:
            return
        now = fields.Datetime.now()
        for rec in self:
            vals = {}
            if getattr(new_stage, "mark_repaired", False) and not rec.date_repaired:
                vals["date_repaired"] = now
            if getattr(new_stage, "mark_closed", False) and not rec.date_out:
                vals["date_out"] = now
            if vals:
                rec.sudo().write(vals)

    # ---------------- Sequência ----------------
    def _get_sequence_for_create(self):
        param = self.env["ir.config_parameter"].sudo().get_param("assistec.order_sequence_id")
        seq = None
        if param:
            try:
                seq = self.env["ir.sequence"].sudo().browse(int(param))
                if not seq.exists():
                    seq = None
            except Exception:
                seq = None
        if not seq:
            seq = self.env["ir.sequence"].sudo().search([("code", "=", "assistec.order")], limit=1)
        return seq

    # ---------------- Maiúsculas (aparelho/obs) ----------------
    _uppercase_device_fields = ["model", "serial_number", "color", "issue_description", "accessories", "notes", "repair_notes"]

    @api.model_create_multi
    def create(self, vals_list):

        # 2) Validação obrigatória de celular no parceiro (sempre executa)
        for vals in vals_list:
            mobile = vals.get("partner_mobile")  # tenta pegar o campo relacionado
            if not mobile or not str(mobile).strip():
                # fallback: tenta pegar do partner_id se já existir
                partner_id = vals.get("partner_id")
                partner = self.env["res.partner"].browse(partner_id) if partner_id else None
                mobile_db = partner.mobile or partner.phone if partner else None
                if not mobile_db or not str(mobile_db).strip():
                    raise ValidationError(_("O cliente precisa ter um CELULAR cadastrado para criar a OS."))

        # 1) Maiúsculas (se habilitado)
        if self._uppercase_enabled():
            for vals in vals_list:
                for fname in self._uppercase_device_fields:
                    if fname in vals and isinstance(vals[fname], str):
                        vals[fname] = vals[fname].upper()

        # 2) Cria registros
        orders = super().create(vals_list)

        # 3) Sequência + pós-processamentos
        seq = self._get_sequence_for_create()
        placeholders = {False, "", "/", "Novo", "New"}

        for order in orders:
            # 3.1) Sequência
            if order.name in placeholders:
                order.name = (
                    seq.next_by_id() if seq
                    else self.env["ir.sequence"].next_by_code("assistec.order")
                    or _("Novo")
                )

            # 3.2) País do partner (quick create)
            if order.partner_id and not order.partner_id.country_id:
                br = self.env.ref("base.br", raise_if_not_found=False)
                if br:
                    order.partner_id.sudo().write({"country_id": br.id})

            # 3.3) Persistir espelhos no partner
            order._write_back_partner()

            # 3.4) Delivery date se estágio 'autorizado'
            try:
                if (order.stage_id and (order.stage_id.code or "").lower() == "autorizado") and not order.delivery_date:
                    order.delivery_date = add_workdays(order.env, fields.Date.today())
            except Exception as e:
                _logger.warning("Falha ao calcular delivery_date: %s", e)

            # 3.5) Seguidores + mensagem
            followers = []
            if order.partner_id:
                followers.append(order.partner_id.commercial_partner_id.id)
            if order.responsible_id and order.responsible_id.partner_id:
                followers.append(order.responsible_id.partner_id.id)
            if followers:
                order.message_subscribe(partner_ids=list(set(followers)))
            order.message_post(body=_("Ordem criada."), message_type="notification", subtype_xmlid="mail.mt_comment")

        return orders

    def write(self, vals):
        """Escrita unificada:
        - normaliza maiúsculas
        - reflete dados no partner
        - aplica gatilhos por estágio
        - seta delivery_date quando entra em 'autorizado'
        - posta mensagens no chatter
        """
        # 1) Maiúsculas (se habilitado)
        if self._uppercase_enabled():
            for fname in self._uppercase_device_fields:
                if fname in vals and isinstance(vals[fname], str):
                    vals[fname] = vals[fname].upper()

        # 2) Guardar estágio novo (p/ gatilhos)
        new_stage = self.env["assistec.stage"].browse(vals["stage_id"]) if vals.get("stage_id") else False
        stage_changed = "stage_id" in vals

        # 3) Escrever
        res = super().write(vals)

        # 4) Refletir alterações no partner
        self._write_back_partner()

        # 5) Gatilhos de estágio
        if new_stage:
            self._apply_stage_triggers(new_stage)

        # 6) Delivery date se mudou para 'autorizado'
        # (bloco incorporado da sua função curta)
        if stage_changed:
            for order in self:
                if (
                    order.stage_id
                    and (order.stage_id.code == "autorizado")
                    and not order.delivery_date
                ):
                    order.delivery_date = add_workdays(
                        order.env,
                        fields.Date.today()
                    )

        # 7) Chatter (histórico simples)
        for rec in self:
            msgs = []
            if stage_changed:
                stage_msg = Markup(_("Status alterado para: <b>%s</b>") % (rec.stage_id.name or _("(sem estágio)")))
                msgs.append(stage_msg)
            if "responsible_id" in vals:
                new_resp = rec.responsible_id.display_name or _("(sem responsável)")
                resp_msg = Markup(_("Responsável definido para: <b>%s</b>") % new_resp)
                msgs.append(resp_msg)
            if "warranty" in vals:
                warranty_msg = _("Garantia: %s") % (_("Sim") if rec.warranty else _("Não"))
                msgs.append(warranty_msg)
            if msgs:
                rec.message_post(body=Markup("<br/>").join(msgs), message_type="comment", subtype_xmlid="mail.mt_comment")

        return res


    # Ações (agora alteram o estágio por código, se existir)
    def _set_stage_by_code(self, code):
        stg = self._find_stage_by_code(code)
        if stg:
            self.write({"stage_id": stg.id})
        else:
            _logger.info("Estágio com code=%s não encontrado; nenhuma mudança aplicada.", code)

    def action_confirm(self):  self._set_stage_by_code("confirmed")
    def action_start(self):    self._set_stage_by_code("in_progress")
    def action_done(self):     self._set_stage_by_code("done")
    def action_cancel(self):   self._set_stage_by_code("cancelled")
    def action_reopen(self):   self._set_stage_by_code("draft")


    part_line_ids = fields.One2many(
        "assistec.order.part.line", "order_id",
        string="Peças", copy=True
    )

    # Totais: soma serviços + peças
    @api.depends(
        "line_ids.subtotal", "line_ids.quantity", "line_ids.price_unit",
        "line_ids.discount_type", "line_ids.discount_value",
        "part_line_ids.subtotal", "part_line_ids.quantity", "part_line_ids.price_unit",
    )
    def _compute_amounts(self):
        for order in self:
            # NET (líquido) vindo dos subtotais das linhas
            svc_net  = sum(order.line_ids.mapped("subtotal"))
            part_net = sum(order.part_line_ids.mapped("subtotal"))
            net = svc_net + part_net

            # GROSS (sem descontos)
            svc_gross  = sum((l.quantity or 0.0) * (l.price_unit or 0.0) for l in order.line_ids)
            part_gross = sum((p.quantity or 0.0) * (p.price_unit or 0.0) for p in order.part_line_ids)
            gross = svc_gross + part_gross

            # DESCONTOS (serviços com tipo; peças por diferença base−subtotal)
            svc_disc = 0.0
            for l in order.line_ids:
                qty  = l.quantity or 0.0
                unit = l.price_unit or 0.0
                base = qty * unit
                t = (getattr(l, "discount_type", "") or "").lower()
                v = getattr(l, "discount_value", 0.0) or 0.0
                if t == "percent":
                    disc = base * (v / 100.0)
                elif t == "amount":
                    disc = min(v, base)
                else:
                    # inclui casos "price" ou linhas já com preço líquido
                    disc = max(0.0, base - (l.subtotal or 0.0))
                svc_disc += disc

            part_disc = 0.0
            for p in order.part_line_ids:
                qty  = p.quantity or 0.0
                unit = p.price_unit or 0.0
                base = qty * unit
                part_disc += max(0.0, base - (p.subtotal or 0.0))

            disc_total = svc_disc + part_disc

            # Atribuições
            order.amount_untaxed = net
            order.amount_total   = net
            if "amount_gross" in order._fields:
                order.amount_gross = gross
            if "amount_discount" in order._fields:
                order.amount_discount = disc_total
            
            amount_gross = fields.Monetary(
                "Valor Sem Descontos", compute="_compute_amounts", store=True
            )
            amount_discount = fields.Monetary(
                "Descontos", compute="_compute_amounts", store=True
            )

    # REOPEN AQUI

    def action_reopen_order(self):
        """Reabre SEMPRE criando nova OS, copiando dados e respeitando garantia."""
        self.ensure_one()
        old = self._get_order()
        open_stage = self._get_default_open_stage(old)
        if not open_stage:
            raise UserError(_("Não há etapa aberta configurada para iniciar a reabertura."))

        in_warranty = self._is_within_warranty(old)
        prefix_note = _("Esta OS é uma reabertura da OS %s.") % (old.name or "")
        new_notes = (prefix_note + ("\n\n" + (old.notes or "") if old.notes else "")).strip()

        new_order = old.with_context(
            mail_create_nosubscribe=True,
            skip_init_message=True,
            tracking_disable=True
        ).copy({
            "name": "/",
            "stage_id": open_stage.id,
            "warranty": bool(in_warranty),
            "date_in": fields.Datetime.now(),
            "date_repaired": False,
            "date_out": False,
            "notes": new_notes,
        })

        end_date = self._get_warranty_end_date(old)
        if in_warranty and end_date:
            msg = _("Reaberta em garantia (até %s).") % fields.Datetime.to_string(end_date)
        elif in_warranty:
            msg = _("Reaberta em garantia.")
        else:
            msg = _("Reaberta fora da garantia.")

        body_new = Markup(_("Reabertura criada a partir da OS <b>%s</b>. %s")
                        % (escape(old.name or ""), escape(msg)))
        new_order.message_post(body=body_new, subtype_xmlid="mail.mt_comment", message_type="comment")

        body_old = Markup(_("OS reaberta em nova OS: <b>%s</b>. %s")
                        % (escape(new_order.name or ""), escape(msg)))
        old.message_post(body=body_old, subtype_xmlid="mail.mt_comment", message_type="comment")

        return {
            "type": "ir.actions.act_window",
            "res_model": "assistec.order",
            "view_mode": "form",
            "res_id": new_order.id,
            "target": "current",
        }


    def button_open_stage_actions(self):
        self.ensure_one()
        xmlid = (
            "assistec_assistencia.action_open_reopen_wizard"
            if (self.stage_id and getattr(self.stage_id, "mark_closed", False))
            else "assistec_assistencia.action_open_change_stage_wizard"
        )
        action = self.env.ref(xmlid).read()[0]
        ctx = dict(self.env.context or {})
        ctx.update({
            "active_id": self.id,
            "active_model": "assistec.order",
        })
        action["context"] = ctx
        return action

    def _report_url_action(self, action_xmlid):
        self.ensure_one()
        # Agora passamos o XMLID de ir.actions.report
        return f"/report/html/{action_xmlid}/{self.id}?download=false"

    def action_open_entry_html_raw(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": self._report_url_action("assistec_assistencia.report_action_entry_html"),
            "target": "new",
        }

    def action_open_exit_html_raw(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": self._report_url_action("assistec_assistencia.report_action_exit_html"),
            "target": "new",
        }


    notify_customer = fields.Boolean(
        string="Notificar cliente",
        default=True,
        tracking=True,
        help="Quando desmarcado a OS não dispara webhook nem envia mensagem ao cliente.",
    )

    delivery_date = fields.Date(
        string="Previsão",
        tracking=True,
        help="Dia/hora combinados para devolução do aparelho ao cliente."
    )

    # ===================================================================
    #   INÍCIO DO CÓDIGO COMPLETO PARA AS CORES
    # ===================================================================
     
    row_color_class = fields.Char(
        compute='_compute_row_color_class',
        string="Classe de Cor da Linha",
        store=True,
    )

    @api.depends('stage_ui_class')
    def _compute_row_color_class(self):
        """
        Calcula o nome da classe CSS a ser usada na linha da lista,
        baseado na cor definida no estágio da OS.
        """
        # DICIONÁRIO COMPLETO COM TODAS AS CORES DO SEU stage.py
        COLOR_MAP = {
            # Cores Padrão do Odoo
            'success': 'success',
            'warning': 'warning',
            'danger': 'danger',
            'primary': 'primary',
            'info': 'info',

            # Nossas Cores Customizadas
            'roxo': 'assistec_roxo',
            'ciano': 'assistec_ciano',
            'marrom': 'assistec_marrom',
            'rosa': 'assistec_rosa',
            'verde_limao': 'assistec_verde_limao',
            'cinza_escuro': 'assistec_cinza_escuro',
            'amarelo': 'assistec_amarelo',

            # ↓ Novas cores
            'azul_escuro':    'assistec_azul_escuro',
            'verde_escuro':   'assistec_verde_escuro',
            'preto':          'assistec_preto',
            'cinza_claro':    'assistec_cinza_claro',
            'vermelho_claro': 'assistec_vermelho_claro',
        }
        for order in self:
            if order.stage_id and order.stage_id.ui_class:
                ui_class = order.stage_id.ui_class
                order.row_color_class = COLOR_MAP.get(ui_class, False)
            else:
                # Se não houver estágio ou cor, não define classe
                order.row_color_class = False

    # ===================================================================
    #   FIM DO CÓDIGO DE CORES
    # ===================================================================
    
    def action_open_customer_history(self):
        self.ensure_one()
        partner = self.partner_id.commercial_partner_id or self.partner_id

        list_view = self.env.ref("assistec_assistencia.view_assistec_order_list", raise_if_not_found=False)
        form_view = self.env.ref("assistec_assistencia.view_assistec_order_form", raise_if_not_found=False)
        views = []
        if list_view:
            views.append([list_view.id, "list"])
        if form_view:
            views.append([form_view.id, "form"])

        return {
            "type": "ir.actions.act_window",
            "name": _("Histórico de OS"),
            "res_model": "assistec.order",
            "view_mode": "list,form",
            "views": views or [(False, "list"), (False, "form")],
            "target": "current",
            "domain": [("partner_id.commercial_partner_id", "=", partner.id)],
            "context": {
                "default_partner_id": partner.id,
                # se tiver <search> com esse field, o Odoo marca o filtro automaticamente:
                "search_default_partner_id": partner.id,
            },
        }


    # --------------------------------------------------------------------- #
    #  COMPOSER → cria um mail.message; depois do super() ele já existe
    # --------------------------------------------------------------------- #
    def message_post(self, **kwargs):
        """Intercepta comentários do chatter para mandar via webhook."""
        msg = super().message_post(**kwargs)

        # 1) só comentários normais (sem internal / notifications)
        if msg.message_type != "comment" or msg.subtype_id.internal:
            return msg

        # 2) pega o cliente e o celular
        order = self  # self é 1 registro (chatter bloqueia edição multi)
        partner = order.partner_id
        phone   = _format_msisdn(partner.mobile or partner.phone)
        if not phone:
            _logger.info("[WhatsApp] OS %s sem celular válido; pulando", order.name)
            return msg

        # 3) prepara o payload
        payload = {
            "os_number": order.name,
            "partner_id": partner.id,
            "partner_name": partner.name,
            "phone": phone,
            "author": msg.author_id.name,
            "message": tools.html2plaintext(msg.body), 
            "postos":       "assistec_chatter",
        }

        # 4) pega URL do parâmetro do sistema
        url = self.env["ir.config_parameter"].sudo().get_param(
            "assistec.webhook_url"
        )
        if not url:
            _logger.warning("Parametro assistec.webhook_url vazio; webhook não enviado")
            return msg

        # 5) dispara (não bloqueia o usuário se falhar)
        try:
            requests.post(url, json=payload, timeout=4)
            self.with_context(from_webhook_note=True).message_post(
                body="✅ Mensagem enviada via WhatsApp",
                message_type="notification",
                subtype_xmlid="mail.mt_note",
            )
        except Exception as exc:
            _logger.warning("Webhook WhatsApp falhou: %s", exc)

        return msg

# --- Catálogo de descontos ----------------------------------------------------
class AssistecDiscount(models.Model):
    _name = "assistec.discount"
    _description = "Regra de Desconto"
    _order = "sequence, name"

    name = fields.Char("Nome", required=True, index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company",
                                 default=lambda self: self.env.company.id,
                                 required=True)
    discount_type = fields.Selection(
        [
            ("percent", "Percentual (%)"),
            ("amount", "Valor fixo"),
            ("price", "Preço por unidade"),
        ],
        required=True,
        default="percent",
        string="Tipo",
    )
    discount_value = fields.Float("Valor", required=True, digits=(16, 2))

    _sql_constraints = [
        ("name_company_uniq", "unique(name, company_id)",
         "Já existe uma regra com esse nome nesta empresa."),
    ]


# --- Linha da OS: incluir o vínculo e copiar tipo/valor ----------------------
class AssistecOrderLine(models.Model):
    _inherit = "assistec.order.line"

    discount_id = fields.Many2one(
        "assistec.discount",
        string="Regra de desconto",
        domain="[('active','=',True)]",
        help="Escolha uma regra cadastrada para preencher o tipo/valor automaticamente.",
    )

    @api.onchange("discount_id")
    def _onchange_discount_id(self):
        for line in self:
            if line.discount_id:
                line.discount_type = line.discount_id.discount_type
                line.discount_value = line.discount_id.discount_value
            else:
                # → campo limpo: remove qualquer vestígio do desconto
                line.discount_type  = False
                line.discount_value = 0.0
        line._sanitize_discount_type()   # se o método existir