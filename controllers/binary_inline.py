# -*- coding: utf-8 -*-
from odoo import http
from odoo.addons.web.controllers.binary import Binary as BaseBinary

class BinaryInline(BaseBinary):
    """
    Mantém todo o comportamento padrão do /web/content, apenas
    troca o header para 'inline' – faz o browser renderizar a
    imagem/PDF dentro da aba nova.
    """

    @http.route()
    def content_common(self, **kw):
        res = super().content_common(**kw)
        # garante inline mesmo para tipos image/*
        res.headers['Content-Disposition'] = 'inline;'
        return res
