from odoo import api, fields, models

class AssistecBrand(models.Model):
    _name = "assistec.brand"
    _description = "Marca"
    _order = "name"

    name   = fields.Char(required=True)
    active = fields.Boolean(default=True)

    # ---------- grava MAIÚSCULO ----------
    @api.model_create_multi
    def create(self, vals_list):
        for v in vals_list:
            if isinstance(v.get("name"), str):
                v["name"] = v["name"].strip().upper()
        return super().create(vals_list)

    def write(self, vals):
        if isinstance(vals.get("name"), str):
            vals["name"] = vals["name"].strip().upper()
        return super().write(vals)

    # ---------- quick-create ----------
    @api.model
    def name_create(self, value):
        # value pode ser str  OU  dict com 'name'
        if isinstance(value, dict):
            name = (value.get("name") or "").strip()
            extra = {k: v for k, v in value.items() if k != "name"}
        else:
            name = (value or "").strip()
            extra = {}
        rec = self.create({"name": name.upper(), **extra})
        return rec.name_get()[0]

    # ---------- exibição ----------
    def name_get(self):
        return [(r.id, (r.name or "").upper()) for r in self]

    def _compute_display_name(self):
        for r in self:
            r.display_name = (r.name or "").upper()
