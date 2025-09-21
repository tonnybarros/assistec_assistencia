/** @odoo-module **/
import { Component, onWillStart, onMounted, onPatched, useState, useRef } from '@odoo/owl';
import { registry } from '@web/core/registry';
import { useService } from '@web/core/utils/hooks';

class FinanceDashboard extends Component {
    setup() {
        this.orm = useService('orm');
        this.state = useState({
            loading: true,
            data: { kpis: {}, series: [] }, // Inicia com estrutura vazia
            period: 'month',
        });
        this.chartRef = useRef('chart');

        onWillStart(() => this._loadData());
        
        // onMounted é para a primeira renderização
        onMounted(() => this._renderChart());

        // onPatched é para TODAS as atualizações subsequentes
        onPatched(() => this._renderChart());
    }

    async _loadData() {
        this.state.loading = true;
        const data = await this.orm.call(
            'assistec.finance.dashboard', 'get_data', [this.state.period]
        );
        this.state.data = data;
        this.state.loading = false;
    }

    onPeriodChange(ev) {
        this.state.period = ev.target.value;
        this._loadData();
    }

    _renderChart() {
        // Se estiver carregando ou se o canvas não estiver na tela, não faz nada.
        if (this.state.loading || !this.chartRef.el) {
            return;
        }

        // Limpa o gráfico anterior para evitar sobreposição ou memory leaks
        if (this._chart) {
            this._chart.destroy();
        }

        const series = this.state.data.series || [];
        const labels = series.map(([m]) => m);
        const data = series.map(([, v]) => v);
        const ctx = this.chartRef.el.getContext('2d');

        this._chart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels,
                datasets: [{
                    label: `Receita (6m)`,
                    data,
                    backgroundColor: 'rgba(54, 162, 235, 0.6)',
                    borderColor: 'rgba(54, 162, 235, 1)',
                    borderWidth: 1,
                    borderRadius: 5,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: true, position: 'top' }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            callback: function(value) {
                                return 'R$ ' + value.toLocaleString('pt-BR');
                            }
                        }
                    }
                }
            }
        });
    }
}

FinanceDashboard.template = 'assistec_assistencia.FinanceDashboard';
registry.category('actions').add('assistec_finance_dashboard', FinanceDashboard);
export default FinanceDashboard;