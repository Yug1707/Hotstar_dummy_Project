// Results section: key-number tiles, F1 and F2 as Chart.js from results.json "series", the rest as PNGs.
// With results.json missing or pending the section shows a notice and the page keeps working.
"use strict";

function captionFor(res, id) {
  const f = res.figures.find((x) => x.id === id);
  return f ? f.caption : "";
}

function renderTiles(res) {
  const box = $("#tiles");
  for (const k of res.key_numbers) {
    box.append(el("div", { class: "card tile" },
      el("div", { class: "v", text: k.value }),
      el("div", { class: "l", text: k.label }),
      el("div", { class: "e", text: [k.exp, k.detail].filter(Boolean).join(" · ") })));
  }
}

function renderF1(res) {
  const s = res.series.F1;
  const card = $("#f1").closest(".chart");
  if (!s) { card.replaceWith(el("div", { class: "pending", text: "F1 pending: E2 has not run yet." })); $("#f1-cap").remove(); return; }
  const slo = res.slo.critical_p95_ms;
  const err = s.n.map((_, i) => [s.p95_ms[i] - s.p95_min[i], s.p95_max[i] - s.p95_ms[i]]);
  new Chart($("#f1"), {
    type: "line",
    data: {
      labels: s.n,
      datasets: [
        { label: "critical p95 (median of runs)", data: s.p95_ms, borderColor: css("--fg"), backgroundColor: css("--fg"), tension: 0, pointRadius: 4 },
        { label: "min", data: s.p95_min, borderColor: "transparent", backgroundColor: css("--line"), pointRadius: 0, fill: "+1" },
        { label: "max", data: s.p95_max, borderColor: "transparent", pointRadius: 0 },
        { label: `SLO ${slo} ms`, data: s.n.map(() => slo), borderColor: css("--bad"), borderDash: [6, 4], pointRadius: 0 },
      ],
    },
    options: {
      plugins: { legend: { labels: { filter: (i) => i.text !== "min" && i.text !== "max" } },
        tooltip: { callbacks: { afterLabel: (c) => (c.datasetIndex === 0 ? `range ${err[c.dataIndex].map((x) => Math.round(x)).join(" / ")} ms (down / up)` : "") } } },
      scales: { y: { type: "logarithmic", title: { display: true, text: "critical p95 (ms, log)" } }, x: { title: { display: true, text: "instances in service (N)" } } },
    },
  });
  $("#f1-cap").textContent = captionFor(res, "F1");
}

function renderF2(res) {
  const s = res.series.F2;
  const card = $("#f2").closest(".chart");
  if (!s) { card.replaceWith(el("div", { class: "pending", text: "F2 pending: E3 and E4 have not run yet." })); $("#f2-cap").remove(); return; }
  const ev = s.events_s || {};
  const bands = [];
  if (ev.ramp) bands.push({ from: ev.ramp[0], to: ev.ramp[1], color: "rgba(241,196,15,.16)" });
  for (const b of ev.bursts || []) bands.push({ from: b[0], to: b[1], color: "rgba(231,76,60,.12)" });
  const shade = {
    id: "bands",
    beforeDraw(chart) {
      const { ctx, chartArea: a, scales: { x } } = chart;
      for (const b of bands) {
        const x0 = x.getPixelForValue(b.from), x1 = x.getPixelForValue(b.to);
        ctx.fillStyle = b.color; ctx.fillRect(x0, a.top, x1 - x0, a.bottom - a.top);
      }
    },
  };
  const line = (label, data, color, extra = {}) => ({ label, data: s.t.map((t, i) => ({ x: t, y: data[i] })), borderColor: color, backgroundColor: color, pointRadius: 0, borderWidth: 1.6, ...extra });
  new Chart($("#f2"), {
    type: "line",
    plugins: [shade],
    data: {
      datasets: [
        line("reactive p95", s.reactive_p95, css("--warn")),
        line("proactive p95", s.proactive_p95, css("--accent")),
        line("reactive instances", s.reactive_n, css("--warn"), { yAxisID: "y2", borderDash: [3, 3], stepped: "before" }),
        line("proactive instances", s.proactive_n, css("--accent"), { yAxisID: "y2", borderDash: [3, 3], stepped: "before" }),
        { label: `SLO ${res.slo.critical_p95_ms} ms`, data: [{ x: 0, y: res.slo.critical_p95_ms }, { x: s.t[s.t.length - 1], y: res.slo.critical_p95_ms }], borderColor: css("--bad"), borderDash: [6, 4], pointRadius: 0, borderWidth: 1 },
      ],
    },
    options: {
      parsing: false,
      plugins: { legend: { labels: { boxWidth: 14, font: { size: 11 } } } },
      scales: {
        x: { type: "linear", title: { display: true, text: "time since load start (s)" }, max: s.t[s.t.length - 1] },
        y: { type: "logarithmic", title: { display: true, text: "critical p95 (ms, log)" } },
        y2: { position: "right", min: 0, title: { display: true, text: "healthy instances" }, grid: { drawOnChartArea: false }, ticks: { stepSize: 1 } },
      },
    },
  });
  $("#f2-cap").textContent = captionFor(res, "F2");
}

function renderFigures(res) {
  const box = $("#figures");
  for (const f of res.figures.filter((x) => x.id !== "F1" && x.id !== "F2")) {
    box.append(el("figure", { id: f.id.toLowerCase() },
      el("h3", { text: `${f.id}: ${f.title}` }),
      el("img", { src: f.png, alt: f.caption, loading: "lazy" }),
      el("figcaption", { text: f.caption })));
  }
}

whenReady(async () => {
  const res = await loadResults();
  if (!res) { $("#results-pending").hidden = false; return; }
  $("#results-body").hidden = false;
  renderTiles(res); renderF1(res); renderF2(res); renderFigures(res);
});
