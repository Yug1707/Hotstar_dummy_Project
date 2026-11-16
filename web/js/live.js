// Live panel: polls /api/v1/whoami every second, shows the serving instance and a per-instance hit counter.
// Polling stops while the tab is hidden (visibilitychange) so an idle tab costs the platform nothing.
"use strict";
(() => {
  const POLL_MS = 1000;
  const hits = new Map(); // instance id -> count
  let timer = null, total = 0, failures = 0;

  function drawBars() {
    const box = $("#live-bars");
    box.replaceChildren();
    const max = Math.max(1, ...hits.values());
    for (const [id, n] of [...hits].sort((a, b) => b[1] - a[1])) {
      const bar = el("div", { style: `height:10px;border-radius:5px;background:var(--accent);width:${Math.max(2, (100 * n) / max)}%` });
      box.append(el("div", { style: "margin-top:8px;font-size:.85rem" },
        el("div", { class: "row", style: "justify-content:space-between;gap:8px" }, el("code", { text: id }), el("span", { class: "muted", text: `${n} responses` })), bar));
    }
  }

  async function tick() {
    timer = null;
    if (document.hidden) return; // resumed by visibilitychange
    try {
      const r = await fetch("/api/v1/whoami", { cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      const j = await r.json();
      failures = 0; total += 1;
      hits.set(j.instance_id, (hits.get(j.instance_id) || 0) + 1);
      $("#live-instance").textContent = j.instance_id;
      $("#live-az").textContent = j.az;
      $("#live-meta").textContent = `up ${Math.round(j.uptime_s)} s · in flight ${j.in_flight} · degrade level ${j.degrade_level} · ${j.version} · ${total} polls, ${hits.size} instance${hits.size === 1 ? "" : "s"} seen`;
      drawBars();
    } catch (e) {
      failures += 1;
      $("#live-instance").textContent = "API unreachable";
      $("#live-az").textContent = "";
      $("#live-meta").textContent = "The backend answers only on the deployed site; run `make dev` and open http://localhost:8000 to see it locally.";
    }
    // back off after repeated failures so a dead backend is not hammered
    timer = setTimeout(tick, failures > 3 ? 10000 : POLL_MS);
  }

  function start() { if (timer === null && !document.hidden) timer = setTimeout(tick, 0); }
  document.addEventListener("visibilitychange", () => { if (document.hidden) { clearTimeout(timer); timer = null; } else start(); });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
