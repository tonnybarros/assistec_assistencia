/** @odoo-module **/

import { Many2ManyBinaryField } from "@web/views/fields/many2many_binary/many2many_binary_field";
import { patch } from "@web/core/utils/patch";

/**
 * Abre o anexo em nova aba ao clicar na miniatura ou no link
 * (sem alterar o widget nem baixar arquivo).
 */
patch(Many2ManyBinaryField.prototype, {
    /**
     * Sobrescreve o manipulador usado pelo template XML.
     * @param {Number} id  ID do ir.attachment
     */
    onClickURL(id) {
        // `content` já trata permissões + token
        window.open(`/web/content/${id}?download=false`, "_blank");
    },
});
