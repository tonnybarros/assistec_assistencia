/** @odoo-module **/
import { Component, onWillStart, onMounted, onPatched, onWillUnmount, useState, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class FinanceDashboard extends Component {
    static template = "assistec_assistencia.FinanceDashboard"; // mantenha igual ao t-name do XML

    // Exibe Control Panel padrão (sem portal)
    reload = async () => {
    await this._loadData();
    };

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            loading: true,
            data: { kpis: {}, series: [] },
            period: "month",
        });
        this.chartRef = useRef("chart");

        onWillStart(() => this._loadData());
        onMounted(() => this._renderChart());
        onPatched(() => this._renderChart());

        onWillUnmount(() => {
            if (this._chart) {
                try { this._chart.destroy(); } catch (_) {}
            }
        }); 
    }

    async _loadData() {
        this.state.loading = true;
        const data = await this.orm.call("assistec.finance.dashboard", "get_data", [this.state.period]);
        this.state.data = data || { kpis: {}, series: [] };
        this.state.loading = false;
    }

    onPeriodChange(ev) {
        this.state.period = ev.target.value;
        this._loadData();
    }

    _renderChart() {
        if (this.state.loading || !this.chartRef.el) return;

        if (this._chart) {
            try { this._chart.destroy(); } catch (_) {}
        }

        const series = this.state.data.series || [];
        const labels = series.map(([m]) => m);
        const values = series.map(([, v]) => v);
        const ctx = this.chartRef.el.getContext("2d");

        this._chart = new Chart(ctx, {
            type: "bar",
            data: {
                labels,
                datasets: [{
                    label: "Receita (6m)",
                    data: values,
                    backgroundColor: "rgba(54, 162, 235, 0.6)",
                    borderColor: "rgba(54, 162, 235, 1)",
                    borderWidth: 1,
                    borderRadius: 5,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: true, position: "top" },
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            callback: (value) => "R$ " + Number(value).toLocaleString("pt-BR"),
                        },
                    },
                },
            },
        });
    }

    reload = async () => {
    await this._loadData();
    this._renderChart();   // opcional: redesenha se já estava na tela
    };

}

// Registra a ação com a mesma tag usada no menu/ir.actions.client
registry.category("actions").add("assistec_finance_dashboard_client", FinanceDashboard);
// (Opcional) mantém um alias antigo, se existir menu usando essa tag:
registry.category("actions").add("assistec_finance_dashboard", FinanceDashboard);

export default FinanceDashboard;
