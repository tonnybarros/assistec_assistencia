/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onMounted, onPatched, onWillUnmount, useRef, useState } from "@odoo/owl";

class AssistecDashboard extends Component {
  static template = "assistec.Dashboard";

  setup() {
    this.orm = useService("orm");
    this.action = useService("action");
    this.trendRef = useRef("trend");
    this.state = useState({
      loading: true,
      cards: [],
      kpis: {},
      trend: [],
      notifications: { due_soon: [], urgent: [] },
    });

    onWillStart(async () => {
      const data = await this.orm.call("assistec.dashboard", "get_dashboard_data", [{}]);
      this.state.cards = data.cards || [];
      this.state.kpis  = data.kpis  || {};
      this.state.trend = data.trend || [];
      this.state.notifications = data.notifications || { due_soon: [], urgent: [] };
      this.state.loading = false;
    });

    const setCanvasHeight = (el) => { if (!el) return;
      const w = window.innerWidth; const h = w < 576 ? 140 : w < 992 ? 170 : 210;
      el.height = h; el.style.height = h + "px"; el.style.maxHeight = h + "px"; el.style.touchAction = "pan-y";
    };

    const renderChart = () => {
      const el = this.trendRef.el;
      if (!el || !window.Chart || !this.state.trend.length) return;
      setCanvasHeight(el);
      const root = getComputedStyle(document.documentElement);
      const brand = (root.getPropertyValue("--ass-brand") || root.getPropertyValue("--o-brand-600") || root.getPropertyValue("--o-brand") || "#7c4dff").trim();
      const alpha = (c,a=0.22)=>/^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(c)?
        ((h)=>(`rgba(${parseInt(h.slice(1,3)||h[1]+h[1],16)}, ${parseInt(h.slice(3,5)||h[2]+h[2],16)}, ${parseInt(h.slice(5,7)||h[3]+h[3],16)}, ${a})`))(c):c.startsWith("rgba(")?c.replace(/rgba\((.+),\s*[\d.]+\)/,`rgba($1, ${a})`):c.startsWith("rgb(")?c.replace("rgb(","rgba(").replace(")",`, ${a})`):c.startsWith("hsla(")?c.replace(/hsla\((.+),\s*[\d.]+\)/,`hsla($1, ${a})`):c.startsWith("hsl(")?c.replace("hsl(","hsla(").replace(")",`, ${a})`):c;
      if (this._chart) { try { this._chart.destroy(); } catch {} }
      this._chart = new Chart(el, { type:"bar",
        data:{ labels:this.state.trend.map(p=>p.label),
          datasets:[{ data:this.state.trend.map(p=>p.qty), backgroundColor:alpha(brand,0.22), borderColor:brand, borderWidth:1, hoverBackgroundColor:alpha(brand,0.30), hoverBorderColor:brand }]},
        options:{ responsive:true, maintainAspectRatio:true, interaction:{mode:"nearest",intersect:false},
          plugins:{ legend:{display:false}, tooltip:{enabled:this.state.trend.some(p=>p.qty)} },
          elements:{ bar:{ borderRadius:6 } }, scales:{ y:{ beginAtZero:true, ticks:{ precision:0 } } } }
      });
    };

    onMounted(() => {
      renderChart();
      this._onResize = () => {
        const el = this.trendRef.el; if (!el) return;
        const w = window.innerWidth; const newH = w < 576 ? 140 : w < 992 ? 170 : 210;
        if (el.height !== newH) { el.height = newH; el.style.height = newH + "px"; if (this._chart) this._chart.resize(); }
      };
      window.addEventListener("resize", this._onResize, { passive: true });
    });
    onPatched(renderChart);
    onWillUnmount(()=>{ if (this._onResize) window.removeEventListener("resize", this._onResize); if (this._chart){try{this._chart.destroy();}catch{}} });
  }

  openAction(xmlid, domain=[]) { this.action.doAction(xmlid, { domain }); }
  openOrder(orderId) {
    this.action.doAction({ type:"ir.actions.act_window", res_model:"assistec.order", res_id:orderId, views:[[false,"form"]], target:"current" });
  }

  reload = async () => {
    this.state.loading = true;
    const data = await this.orm.call("assistec.dashboard", "get_dashboard_data", [{}]);
    this.state.cards = data.cards || [];
    this.state.kpis  = data.kpis  || {};
    this.state.trend = data.trend || [];
    this.state.notifications = data.notifications || { due_soon: [], urgent: [] };
    this.state.loading = false;
  };
}

registry.category("actions").add("assistec_dashboard_client", AssistecDashboard);
export default AssistecDashboard;
