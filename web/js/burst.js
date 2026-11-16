// Mini burst test: 100 GETs of /api/v1/recommendations spread over 5 s, latency per request coloured by instance.
// 20 req/s is the public rate limit, so a 429 is handled as a normal outcome, not an error.
"use strict";
whenReady(() => {
  const N = 100, SPREAD_MS = 5000, COOLDOWN_S = 10;
  const COLORS = ["#1b9e77", "#d95f02", "#7570b3", "#e7298a", "#66a61e", "#e6ab02"];
  const btn = $("#burst-btn"), status = $("#burst-status"), summary = $("#burst-summary");
  let chart = null, running = false;

  function plot(samples) {
    const byInstance = new Map();
    for (const s of samples) {
      const key = s.status === 429 ? "rate-limited (429)" : s.instance || "unknown";
      if (!byInstance.has(key)) byInstance.set(key, []);
      byInstance.get(key).push({ x: s.at / 1000, y: s.ms });
    }
    const datasets = [...byInstance].map(([k, pts], i) => ({
      label: `${k} (${pts.length})`, data: pts, backgroundColor: k.startsWith("rate-limited") ? css("--bad") : COLORS[i % COLORS.length], pointRadius: 3,
    }));
    if (chart) chart.destroy();
    chart = new Chart($("#burst-chart"), {
      type: "scatter", data: { datasets },
      options: { scales: { x: { title: { display: true, text: "time since the first request (s)" }, min: 0 }, y: { beginAtZero: true, title: { display: true, text: "latency (ms)" } } },
        plugins: { legend: { labels: { boxWidth: 12, font: { size: 11 } } } } },
    });
  }

  function describe(samples) {
    const ok = samples.filter((s) => s.status === 200), limited = samples.filter((s) => s.status === 429), failed = samples.filter((s) => s.status === 0);
    const lat = ok.map((s) => s.ms).sort((a, b) => a - b);
    const q = (p) => (lat.length ? Math.round(lat[Math.min(lat.length - 1, Math.floor(p * lat.length))]) : null);
    const instances = new Set(ok.map((s) => s.instance));
    let text = `${ok.length} answered by ${instances.size} instance${instances.size === 1 ? "" : "s"}, median ${q(0.5)} ms, p95 ${q(0.95)} ms.`;
    if (limited.length) text += ` ${limited.length} rate-limited: this protects the demo, it is not a fault.`;
    if (failed.length) text += ` ${failed.length} failed (network error or timeout).`;
    if (ok.some((s) => s.degraded)) text += " Some answers were degraded: the platform is shedding non-critical work.";
    return text;
  }

  async function one(i, t0) {
    const started = performance.now();
    const rec = { at: started - t0, ms: 0, status: 0, instance: null, degraded: false };
    try {
      const ctl = new AbortController(), kill = setTimeout(() => ctl.abort(), 5000);
      const r = await fetch("/api/v1/recommendations", { cache: "no-store", signal: ctl.signal });
      clearTimeout(kill);
      rec.status = r.status; rec.instance = r.headers.get("X-Instance-Id");
      if (r.ok) rec.degraded = !!(await r.json()).degraded; else await r.text();
    } catch (e) { rec.status = 0; }
    rec.ms = performance.now() - started;
    return rec;
  }

  btn.addEventListener("click", async () => {
    if (running) return;
    running = true; btn.disabled = true; summary.textContent = ""; status.textContent = "sending…";
    const t0 = performance.now(), jobs = [];
    for (let i = 0; i < N; i++) jobs.push(new Promise((res) => setTimeout(() => one(i, t0).then(res), (i * SPREAD_MS) / N)));
    const samples = await Promise.all(jobs);
    plot(samples);
    summary.textContent = describe(samples);
    running = false;
    let left = COOLDOWN_S;
    const iv = setInterval(() => {
      status.textContent = `available again in ${left} s`;
      if (left-- <= 0) { clearInterval(iv); btn.disabled = false; status.textContent = ""; }
    }, 1000);
  });
});
