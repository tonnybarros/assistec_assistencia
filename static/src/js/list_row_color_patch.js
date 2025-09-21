/** @odoo-module **/

import { ListRenderer } from "@web/views/list/list_renderer";
import { patch } from "@web/core/utils/patch";

/* 1 ▪️ Salva o método original */
const origGetRowClass = ListRenderer.prototype.getRowClass;

/* 2 ▪️ Aplica o patch (apenas dois argumentos!) */
patch(ListRenderer.prototype, {
    getRowClass(record) {
        /* chama o original */
        const base = origGetRowClass.call(this, record);
        /* acrescenta nossa classe extra */
        const extra = record.data?.row_color_class || "";
        return extra ? `${base} ${extra}` : base;
    },
});
