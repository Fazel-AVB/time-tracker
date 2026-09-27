// Small SVG charts for the Weekly Report tab: grouped bars, a line and a donut.
//
// Drawn here instead of with a chart library (the Streamlit version used
// Plotly) so the page loads nothing from the internet and the package adds no
// JavaScript dependency. Each function fills `el` with one <svg> that scales
// to the container's width; hovering a bar or point shows its value (<title>).
"use strict";

const Charts = (() => {
  const NS = "http://www.w3.org/2000/svg";

  function svgEl(tag, attrs = {}, text) {
    const el = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    if (text !== undefined) el.textContent = text;
    return el;
  }

  function tip(el, text) { el.append(svgEl("title", {}, text)); return el; }

  // A round axis maximum (1, 2, 2.5, 5 x 10^n) at or above v, so gridlines fall on even numbers.
  function niceMax(v) {
    if (!(v > 0)) return 1;
    const p = 10 ** Math.floor(Math.log10(v));
    for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
    return 10 * p;
  }

  function shorten(s, n) { return s.length > n ? s.slice(0, n - 1) + "…" : s; }

  function frame(el, W, H) {
    const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" });
    el.replaceChildren(svg);
    return svg;
  }

  function yAxis(svg, m, W, H, max) {
    // 5 steps: every niceMax value (1, 2, 2.5, 5, 10 x 10^n) divides into round ticks.
    const ticks = 5;
    for (let i = 0; i <= ticks; i++) {
      const v = (max * i) / ticks;
      const y = H - m.b - ((H - m.t - m.b) * i) / ticks;
      svg.append(svgEl("line", { x1: m.l, x2: W - m.r, y1: y, y2: y, stroke: "#E4DEFB" }));
      svg.append(svgEl("text", { x: m.l - 6, y: y + 4, "text-anchor": "end", "font-size": 11 }, +v.toFixed(1) + "h"));
    }
  }

  // series: [{name, color, values: [..one per label]}]
  function bars(el, labels, series) {
    const W = 560, H = 300, m = { l: 44, r: 10, t: 30, b: labels.length > 4 ? 70 : 40 };
    const svg = frame(el, W, H);
    const max = niceMax(Math.max(0, ...series.flatMap((s) => s.values)));
    yAxis(svg, m, W, H, max);
    const gw = (W - m.l - m.r) / Math.max(labels.length, 1);
    const bw = Math.min(40, (gw * 0.75) / series.length);
    const plotH = H - m.t - m.b;
    labels.forEach((label, i) => {
      const x0 = m.l + gw * i + (gw - bw * series.length) / 2;
      series.forEach((s, j) => {
        const v = s.values[i] || 0;
        const h = (plotH * v) / max;
        svg.append(tip(svgEl("rect", { x: x0 + j * bw, y: H - m.b - h, width: bw - 2, height: Math.max(h, 0), fill: s.color, rx: 2 }),
          `${label} · ${s.name}: ${v.toFixed(2)} h`));
      });
      const cx = m.l + gw * i + gw / 2, cy = H - m.b + 14;
      const t = svgEl("text", { x: cx, y: cy, "font-size": 11, "text-anchor": labels.length > 4 ? "end" : "middle" }, shorten(label, 16));
      if (labels.length > 4) t.setAttribute("transform", `rotate(-35 ${cx} ${cy})`);
      svg.append(tip(t, label));
    });
    // Legend, top right.
    let x = W - m.r;
    [...series].reverse().forEach((s) => {
      const t = svgEl("text", { x, y: 14, "font-size": 12, "text-anchor": "end" }, s.name);
      svg.append(t);
      x -= s.name.length * 6.6 + 8;
      svg.append(svgEl("rect", { x: x - 12, y: 4, width: 12, height: 12, rx: 2, fill: s.color }));
      x -= 24;
    });
  }

  function line(el, labels, values, color) {
    const W = 560, H = 300, m = { l: 44, r: 28, t: 20, b: 40 };  // r: room for the last date label
    const svg = frame(el, W, H);
    const max = niceMax(Math.max(0, ...values));
    yAxis(svg, m, W, H, max);
    const plotW = W - m.l - m.r, plotH = H - m.t - m.b;
    const pts = values.map((v, i) => [m.l + (labels.length > 1 ? (plotW * i) / (labels.length - 1) : plotW / 2), H - m.b - (plotH * v) / max]);
    svg.append(svgEl("polyline", { points: pts.map((p) => p.join(",")).join(" "), fill: "none", stroke: color, "stroke-width": 2.5, "stroke-linejoin": "round" }));
    const every = Math.ceil(labels.length / 10);  // at most ~10 x labels
    pts.forEach(([x, y], i) => {
      svg.append(tip(svgEl("circle", { cx: x, cy: y, r: 5, fill: "#A78BFA", stroke: color, "stroke-width": 1.5 }),
        `Week of ${labels[i]}: ${values[i].toFixed(2)} h`));
      if (i % every === 0 || i === labels.length - 1) {
        svg.append(svgEl("text", { x, y: H - m.b + 18, "font-size": 11, "text-anchor": "middle" }, labels[i]));
      }
    });
  }

  function donut(el, labels, values, colors) {
    const W = 300, H = 300, cx = 150, cy = 150, R = 130, r = 60;
    const svg = frame(el, W, H);
    const total = values.reduce((a, b) => a + b, 0);
    if (!(total > 0)) return;
    let a0 = -Math.PI / 2;
    values.forEach((v, i) => {
      const frac = v / total;
      // An arc of 100% has start = end and draws nothing, so a lone slice is drawn as 99.99%.
      const a1 = a0 + Math.min(frac, 0.9999) * 2 * Math.PI;
      const large = a1 - a0 > Math.PI ? 1 : 0;
      const p = (rad, a) => `${cx + rad * Math.cos(a)} ${cy + rad * Math.sin(a)}`;
      const d = `M ${p(R, a0)} A ${R} ${R} 0 ${large} 1 ${p(R, a1)} L ${p(r, a1)} A ${r} ${r} 0 ${large} 0 ${p(r, a0)} Z`;
      svg.append(tip(svgEl("path", { d, fill: colors[i % colors.length], stroke: "#fff", "stroke-width": 2 }),
        `${labels[i]}: ${v.toFixed(2)} h (${Math.round(frac * 100)}%)`));
      if (frac >= 0.06) {
        const mid = (a0 + a1) / 2, lr = (R + r) / 2;
        svg.append(svgEl("text", { x: cx + lr * Math.cos(mid), y: cy + lr * Math.sin(mid) + 4, "text-anchor": "middle", "font-size": 12, fill: "#fff", style: "fill:#fff" }, `${Math.round(frac * 100)}%`));
      }
      a0 += frac * 2 * Math.PI;
    });
  }

  return { bars, line, donut };
})();
