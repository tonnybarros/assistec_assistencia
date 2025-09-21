/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onMounted, onPatched, useRef, useState, onWillUnmount } from "@odoo/owl";

class AssistecDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.trendRef = useRef("trend");

        this.state = useState({
            loading: true,
            cards: [],
            kpis: {},
            trend: [],
            // ADICIONADO: Inicializa a estrutura de notificações para evitar erros
            notifications: { due_soon: [], urgent: [] },
        });

        onWillStart(async () => {
            const data = await this.orm.call("assistec.dashboard", "get_dashboard_data", [ {} ]);
            this.state.cards = data.cards || [];
            this.state.kpis  = data.kpis  || {};
            this.state.trend = data.trend || [];
            // Garante que a notificação sempre exista, mesmo que vazia
            this.state.notifications = data.notifications || { due_soon: [], urgent: [] };
            this.state.loading = false;
        });

        // Sua lógica original de altura e gráfico, 100% mantida
        const setCanvasHeight = (el) => {
            if (!el) return;
            const w = window.innerWidth;
            const h = w < 576 ? 140 : w < 992 ? 170 : 210;
            el.height = h;
            el.style.height = h + "px";
            el.style.maxHeight = h + "px";
            el.style.touchAction = "pan-y";
        };

        const renderChart = () => {
            const el = this.trendRef.el;
            if (!el || !window.Chart || !this.state.trend.length) return;
            setCanvasHeight(el);
            const root = getComputedStyle(document.documentElement);
            const brand = (root.getPropertyValue("--ass-brand") || root.getPropertyValue("--o-brand-600") || root.getPropertyValue("--o-brand") || "#7c4dff").trim();
            const alpha = (color, a = 0.22) => {
                if (/^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(color)) {
                    let r, g, b;
                    if (color.length === 4) { r = parseInt(color[1] + color[1], 16); g = parseInt(color[2] + color[2], 16); b = parseInt(color[3] + color[3], 16);
                    } else { r = parseInt(color.slice(1, 3), 16); g = parseInt(color.slice(3, 5), 16); b = parseInt(color.slice(5, 7), 16); }
                    return `rgba(${r}, ${g}, ${b}, ${a})`;
                }
                if (color.startsWith("rgba(")) return color.replace(/rgba\((.+),\s*[\d.]+\)/, `rgba($1, ${a})`);
                if (color.startsWith("rgb("))  return color.replace("rgb(", "rgba(").replace(")", `, ${a})`);
                if (color.startsWith("hsla(")) return color.replace(/hsla\((.+),\s*[\d.]+\)/, `hsla($1, ${a})`);
                if (color.startsWith("hsl("))  return color.replace("hsl(", "hsla(").replace(")", `, ${a})`);
                return color;
            };
            if (this._chart) { try { this._chart.destroy(); } catch (e) {} }
            this._chart = new Chart(el, {
                type: "bar",
                data: {
                    labels: this.state.trend.map(p => p.label),
                    datasets: [{
                        data: this.state.trend.map(p => p.qty),
                        backgroundColor: alpha(brand, 0.22),
                        borderColor: brand, borderWidth: 1,
                        hoverBackgroundColor: alpha(brand, 0.30),
                        hoverBorderColor: brand,
                    }],
                },
                options: {
                    responsive: true, maintainAspectRatio: true,
                    events: ["mousemove","mouseout","click","touchstart","touchend"],
                    interaction: { mode: "nearest", intersect: false },
                   plugins: {
                       legend:  { display: false },
                       tooltip: {
                           enabled: this.state.trend.some(p => p.qty),
                       },
                   },
                    elements: { bar: { borderRadius: 6 } },
                    scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
                },
            });
        };
        onMounted(() => {
            renderChart();
            this._onResize = () => {
                const el = this.trendRef.el;
                if (!el) return;
                const oldH = el.height;
                const w = window.innerWidth;
                const newH = w < 576 ? 140 : w < 992 ? 170 : 210;
                if (newH !== oldH) {
                    el.height = newH;
                    el.style.height = newH + "px";
                    if (this._chart) this._chart.resize();
                }
            };
            window.addEventListener("resize", this._onResize, { passive: true });
        });
        onPatched(renderChart);
    }

    // Seu método openAction original
    openAction(xmlid, domain = []) {
        this.action.doAction(xmlid, { domain });
    }

    // ===============================================
    // ==== NOVA FUNÇÃO ADICIONADA PARA O CLIQUE ====
    // ===============================================
    openOrder(orderId) {
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'assistec.order',
            res_id: orderId,
            views: [[false, 'form']],
            target: 'current',
        });
    }

    willUnmount() {
        if (this._onResize) window.removeEventListener("resize", this._onResize);
        if (this._chart) {
            try { this._chart.destroy(); } catch(_) {}
        }
    }
}

AssistecDashboard.template = "assistec.Dashboard";
registry.category("actions").add("assistec_dashboard_client", AssistecDashboard);

export default AssistecDashboard;