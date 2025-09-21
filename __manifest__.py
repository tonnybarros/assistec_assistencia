{
    "name": "Assistec Assistência",
    "summary": "Gestão simples de Ordens de Serviço (independente do módulo Repair)",
    "version": "18.0.2.0.6",
    "author": "Tectonny + ChatGPT",
    "sequence": 1,
    "category": "Services",
    "license": "LGPL-3",
    "depends": [
        "base", "website", "contacts", "mail", "uom",
    ],
    "external_dependencies": {
        "python": ["requests", "brazilcep", "qrcode", "python-dateutil"]
    },

    # ─── Dados do servidor (views, menus, security) ───
    "data": [
        # 1) GRUPOS — antes de qualquer menu que use esses grupos
        "security/grupos_usuarios.xml",
        "views/finance_menu.xml",
        "views/menu.xml",
        "views/commission_views.xml",
        "views/report_cleanup.xml",
        "security/ir.model.access.csv",
        "data/sequences.xml",
        "data/stage_data.xml",
        "data/print_text.xml",
        "data/payment_method_data.xml",
        "views/dashboard_views.xml",
        "views/report_order_actions.xml",
        "views/order_views.xml",
        "views/report_order_templates.xml",
        "views/order_kanban.xml",
        "views/order_calendar_views.xml",
        "views/order_graph.xml",
        "views/service_views.xml",
        "views/brand_views.xml",
        "views/repair_product_views.xml",
        "views/stage_views.xml",
        "views/discount_views.xml",
        "views/res_config_settings_views.xml",
        "views/part_views.xml",
        "wizards/change_stage_wizard_views.xml",
        "views/whatsapp_wizard_views.xml",
        "views/portal_templates.xml",
        "views/print_text_views.xml",
        "views/payment_method_views.xml",
    ],

    # ─── Assets (JS, CSS, QWeb) ────────────────────────
    "assets": {
        "web.assets_backend": [
            "assistec_assistencia/static/src/scss/assistec.scss",
            "assistec_assistencia/static/src/scss/order_list.scss",
            "assistec_assistencia/static/src/scss/dashboard.scss",
            "assistec_assistencia/static/src/scss/assistec_badges.scss",
            "assistec_assistencia/static/src/js/list_row_color_patch.js",
            "assistec_assistencia/static/src/js/image_open_in_tab.js",
            "assistec_assistencia/static/src/finance_dashboard/finance_dashboard.xml",
            "assistec_assistencia/static/src/xml/dashboard.xml",
            "assistec_assistencia/static/src/xml/many2many_binary_field.xml",
            "web/static/lib/Chart/Chart.js",
            "assistec_assistencia/static/src/js/dashboard.js",
            "assistec_assistencia/static/src/finance_dashboard/finance_dashboard.js",
            "assistec_assistencia/static/src/finance_dashboard/finance_dashboard.css",
        ],
    },

    "application": True,
    "icon": "/assistec_assistencia/static/description/icon.png",
    "images": ["/assistec_assistencia/static/description/icon.png"],
    "installable": True,
}
