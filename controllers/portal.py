# controllers/portal.py
# -*- coding: utf-8 -*-
from urllib.parse import unquote_plus
from odoo import http, _, fields
from odoo.http import request
from markupsafe import Markup


class AssistecPortal(http.Controller):
    """
    Rotas públicas:
        • /                     → redireciona
        • /os/status            → formulário GET/POST
        • /os/<token>           → via QR-Code (recomendado)
        • /os/<os>/<phone>      → acesso rápido opcional
        • /os/view?os=…&phone=… → legado
        • /os/<token>/(approve|reject) → decisão do cliente
    """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_stage_history(self, order):
        """
        Devolve lista cronológica de alterações de estágio da OS.
        O método é à prova de diferenças entre versões, usando vários
        atributos possíveis do `mail.tracking.value`.
        """
        history = []
        if not order:
            return history

        def _is_stage_tracking(tv):
            # Versões antigas tinham `field`; versões mais novas não.
            name = ''
            if hasattr(tv, 'field') and tv.field:
                name = tv.field.name or ''
            elif hasattr(tv, '_field_id') and tv._field_id:
                name = tv._field_id.name or ''
            # fallback textual
            desc = (getattr(tv, 'field_desc', '') or '').lower()
            return name == 'stage_id' or 'etapa' in desc or 'stage' in desc

        for msg in order.message_ids.sorted(lambda m: m.date or m.create_date):
            for tv in msg.tracking_value_ids:
                if not _is_stage_tracking(tv):
                    continue
                history.append({
                    "date": msg.date or msg.create_date,
                    "old":  tv.old_value_char or tv.old_value_text or '',
                    "new":  tv.new_value_char or tv.new_value_text or '',
                })
        return history

    # ------------------------------------------------------------------
    # Página inicial
    # ------------------------------------------------------------------
    @http.route("/", type="http", auth="public", website=True)
    def index(self, **kw):
        return request.redirect("/os/status")

    # ------------------------------------------------------------------
    # Formulário  GET  /os/status
    # ------------------------------------------------------------------
    @http.route("/os/status", type="http", auth="public",
                website=True, methods=["GET"])
    def os_status_form(self, **kw):
        return request.render("assistec_assistencia.os_status_form", {})

    # ------------------------------------------------------------------
    # Formulário  POST  /os/status
    # ------------------------------------------------------------------
    @http.route("/os/status", type="http", auth="public",
                website=True, methods=["POST"])
    def os_status_submit(self, os_number=None, phone=None, **kw):
        errors, order = [], False
        if not os_number or not phone:
            errors.append(_("Informe Nº da OS e telefone."))
        else:
            digits = "".join(c for c in phone if c.isdigit())
            if len(digits) != 11:
                errors.append(_("Telefone deve ter 11 dígitos sem formatação."))
            else:
                order = request.env["assistec.order"].sudo().search(
                    [("name", "=", os_number),
                     ("partner_mobile", "=", digits)], limit=1
                )
                if not order:
                    errors.append(_("OS não encontrada com esses dados."))

        ctx = {
            "order": order,
            "errors": errors,
            "stage_history": self._get_stage_history(order) if order else [],
            "token": order.access_token if order else None,
        }
        return request.render("assistec_assistencia.os_status_result", ctx)

    # ------------------------------------------------------------------
    # Acesso principal via TOKEN  /os/<token>
    # ------------------------------------------------------------------
    @http.route("/os/<string:token>", type="http", auth="public",
                website=True, methods=["GET"])
    def os_status_token(self, token, **kw):
        order = request.env["assistec.order"].sudo().search(
            [("access_token", "=", token)], limit=1
        )
        errors = [] if order else [_("Token inválido ou OS não encontrada.")]

        if order:
            try:
                ip_address = request.httprequest.remote_addr
                user_agent = request.httprequest.user_agent.string
                
                message_body = f"""
                    <div style='font-family: sans-serif; font-size: 13px;'>
                        <p style='margin: 0;'>
                            <i class='fa fa-desktop' style='margin-right: 5px;'/>
                            <b>Portal do Cliente Acessado</b>
                        </p>
                        <ul style='list-style-type: none; padding-left: 18px; margin-top: 5px;'>
                            <li><b>IP:</b> {ip_address}</li>
                            <li><b>Dispositivo/Navegador:</b> {user_agent}</li>
                        </ul>
                    </div>
                """
                
                # CORREÇÃO: Usamos Markup() para avisar ao Odoo que este é um HTML seguro
                order.message_post(
                    body=Markup(message_body),
                    message_type='comment',
                    subtype_xmlid='mail.mt_note'
                )
            except Exception as e:
                import logging
                _logger = logging.getLogger(__name__)
                _logger.warning("Falha ao registrar acesso ao portal da OS %s: %s", order.name, e)

        ctx = {
            "order": order,
            "errors": errors,
            "stage_history": self._get_stage_history(order) if order else [],
            "token": token, 
        }
        return request.render("assistec_assistencia.os_status_result", ctx)

    # ------------------------------------------------------------------
    # Acesso opcional  /os/<os>/<phone>
    # ------------------------------------------------------------------
    @http.route("/os/<string:os_number>/<string:phone>", type="http",
                auth="public", website=True, methods=["GET"])
    def os_status_path(self, os_number, phone, **kw):
        digits = "".join(c for c in phone if c.isdigit())
        order = request.env["assistec.order"].sudo().search(
            [("name", "=", os_number), ("partner_mobile", "=", digits)], limit=1
        )
        errors = [] if order else [_("OS não encontrada com esses dados.")]
        ctx = {
            "order": order,
            "errors": errors,
            "stage_history": self._get_stage_history(order) if order else [],
            "token": order.access_token if order else None,
        }
        return request.render("assistec_assistencia.os_status_result", ctx)

    # ------------------------------------------------------------------
    # Rota legado  /os/view?os=…&phone=…
    # ------------------------------------------------------------------
    @http.route("/os/view", type="http", auth="public",
                website=True, methods=["GET"])
    def os_status_view(self, os=None, phone=None, **kw):
        errors, order = [], False

        os_number = unquote_plus(os or kw.get("os", "")).strip()
        phone_raw = unquote_plus(phone or kw.get("phone", "")).strip()
        digits = "".join(c for c in phone_raw if c.isdigit())

        if not os_number or not digits:
            errors.append(_("Parâmetros ausentes ou inválidos."))
        elif len(digits) != 11:
            errors.append(_("Telefone deve ter 11 dígitos."))
        else:
            order = request.env["assistec.order"].sudo().search(
                [("name", "=", os_number),
                 ("partner_mobile", "=", digits)], limit=1
            )
            if not order:
                errors.append(_("OS não encontrada com esses dados."))

        ctx = {
            "order": order,
            "errors": errors,
            "stage_history": self._get_stage_history(order) if order else [],
            "token": order.access_token if order else None,
        }
        return request.render("assistec_assistencia.os_status_result", ctx)

    # ------------------------------------------------------------------
    # Botões de decisão  /os/<token>/approve  |  /os/<token>/reject
    # ------------------------------------------------------------------
    @http.route("/os/<string:token>/approve", type="http", auth="public",
                website=True, methods=["POST"])
    def os_approve(self, token, **kw):
        order, err = self._apply_customer_decision(token, approve=True)
        errors = [err] if err else []
        success = _("Você autorizou o orçamento. Obrigado!")
        ctx = {
            "order": order,
            "errors": errors,
            "stage_history": self._get_stage_history(order) if order else [],
            "token": token,
            "success": None if errors else success,
        }
        return request.render("assistec_assistencia.os_status_result", ctx)

    @http.route("/os/<string:token>/reject", type="http", auth="public",
                website=True, methods=["POST"])
    def os_reject(self, token, **kw):
        order, err = self._apply_customer_decision(token, approve=False)
        errors = [err] if err else []
        success = _("Você indicou que NÃO autoriza o orçamento.")
        ctx = {
            "order": order,
            "errors": errors,
            "stage_history": self._get_stage_history(order) if order else [],
            "token": token,
            "success": None if errors else success,
        }
        return request.render("assistec_assistencia.os_status_result", ctx)

    # ------------------------------------------------------------------
    # Core: grava decisão do cliente + webhook
    # ------------------------------------------------------------------
    def _apply_customer_decision(self, token, approve):
        Order = request.env["assistec.order"].sudo()
        order = Order.search([("access_token", "=", token)], limit=1)
        if not order:
            return None, _("Token inválido ou OS não encontrada.")

        # evita resposta duplicada
        if order.stage_id.code in ("autorizado", "nao_autorizado"):
            return order, _("Decisão já registrada anteriormente.")

        code_needed = "autorizado" if approve else "nao_autorizado"
        stage = request.env["assistec.stage"].sudo().search(
            [("code", "=", code_needed),
             ("company_id", "=", order.company_id.id)], limit=1
        )
        if not stage:
            msg = _("Etapa '%s' não encontrada na empresa %s.")
            return order, msg % (code_needed, order.company_id.display_name)

        order.stage_id = stage.id  # grava etapa

        # ---- webhook ----------------------------------------------------
        try:
            payload = {
                "marker": "resposta_cliente",
                "os_id": order.id,
                "os_name": order.name,
                "decision": code_needed,
                "amount_total": order.amount_total,
                "phone": order.partner_mobile,          # ← agora vai o celular
                "timestamp": fields.Datetime.to_string(fields.Datetime.now()),
            }
            order._send_webhook(payload)   # método já existente no mixin
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "Webhook resposta_cliente falhou: %s", e
            )
        # -----------------------------------------------------------------

        return order, False

