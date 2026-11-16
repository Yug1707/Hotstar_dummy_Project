// Cost calculator (plan 9.1 item 7). Same formulas as analysis/cost_model.py; inputs from results.json "cost".
//   viewers_per_instance = C1 x planning_utilisation x viewers_per_rps
//   instances            = ceil(viewers / viewers_per_instance)
//   $/h                  = instances x price x (1 - spot_share x spot_discount)
// No price is hard-coded: with a null price the calculator shows instance counts only.
"use strict";
(() => {
  const FALLBACK = { c1: 100, cost: { price_per_instance_h: null, spot_discount_pct: null, planning_utilisation: 0.8, viewers_per_rps: 25, match_hours: 4 } };
  const MIN = 1e6, MAX = 6e7; // slider is logarithmic between 1 M and 60 M

  const viewersFrom = (pos) => Math.round(MIN * Math.pow(MAX / MIN, pos / 100) / 1e5) * 1e5;
  const compute = (viewers, c1, util, vpr, price, spotShare, spotDiscount) => {
    const perInstance = c1 * util * vpr;
    const instances = Math.ceil(viewers / perInstance);
    const hourly = price == null ? null : instances * price * (1 - spotShare * ((spotDiscount ?? 0) / 100));
    return { perInstance, instances, hourly };
  };

  async function init() {
    const raw = (await loadRaw()) || FALLBACK;
    const c = raw.cost || FALLBACK.cost, c1 = raw.c1 || FALLBACK.c1;
    const util = c.planning_utilisation, hours = c.match_hours, price = c.price_per_instance_h, disc = c.spot_discount_pct;
    const vIn = $("#cc-viewers"), pIn = $("#cc-vpr"), sIn = $("#cc-spot");
    pIn.value = c.viewers_per_rps;

    function update() {
      const viewers = viewersFrom(Number(vIn.value)), vpr = Number(pIn.value), spot = Number(sIn.value);
      const r = compute(viewers, c1, util, vpr, price, spot, disc);
      $("#cc-viewers-out").textContent = `${(viewers / 1e6).toFixed(1)} M`;
      $("#cc-vpr-out").textContent = String(vpr);
      $("#cc-inst").textContent = fmtInt(r.instances);
      $("#cc-hour").textContent = fmtUsd(r.hourly);
      $("#cc-match").textContent = fmtUsd(r.hourly == null ? null : r.hourly * hours);
      $("#cc-match-l").textContent = `for a ${hours}-hour match`;
      $("#cc-formula").textContent =
        `viewers per instance = ${c1} rps x ${util} x ${vpr} = ${fmtInt(r.perInstance)}; instances = ceil(${fmtInt(viewers)} / ${fmtInt(r.perInstance)}) = ${fmtInt(r.instances)}` +
        (price == null ? "" : `; per hour = ${fmtInt(r.instances)} x $${price} x (1 - ${spot} x ${disc ?? 0} %)`);
      const notes = [];
      if (raw.pending) notes.push(`C1 = ${c1} rps is the planning value: E1 has not run yet.`);
      if (price == null) notes.push("Prices are filled in from the AWS Pricing Calculator after the first deploy; until then only instance counts are shown.");
      else if (c.prices_retrieved) notes.push(`Prices retrieved ${c.prices_retrieved}.`);
      notes.push("Out of scope: CDN and egress, databases, caches, Kubernetes control plane, support, people. 25 viewers per rps is a derived ratio; 70 % Spot is an unverified claim being tested.");
      $("#cc-note").textContent = notes.join(" ");
    }
    for (const i of [vIn, pIn, sIn]) i.addEventListener("input", update);
    update();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
