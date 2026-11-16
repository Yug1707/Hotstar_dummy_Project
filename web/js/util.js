// Small helpers shared by the dashboard scripts. No build step, no dependencies besides Chart.js.
"use strict";
const $ = (sel, root = document) => root.querySelector(sel);

// Colours follow the page theme; read the live CSS variables so charts match light and dark.
function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
function chartDefaults() {
  if (!window.Chart) return false;
  Chart.defaults.color = css("--muted");
  Chart.defaults.borderColor = css("--line");
  Chart.defaults.font.family = "system-ui, sans-serif";
  Chart.defaults.maintainAspectRatio = false; // charts live in fixed-height containers
  return true;
}
// Chart.js loads with `defer`; run `fn` once it and the page are ready.
function whenReady(fn) {
  const go = () => (window.Chart ? (chartDefaults(), fn()) : setTimeout(go, 50));
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", go); else go();
}
function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v; else if (k === "text") n.textContent = v; else n.setAttribute(k, v);
  }
  for (const k of kids) n.append(k);
  return n;
}
const fmtInt = (x) => (x == null ? "n/a" : Math.round(x).toLocaleString("en-US"));
const fmtUsd = (x) => (x == null ? "price pending" : "$" + x.toLocaleString("en-US", { maximumFractionDigits: x < 10 ? 2 : 0 }));

// results.json, or null when missing / pending. The page must work either way (plan 9.2).
let _raw;
async function loadRaw() {
  if (_raw !== undefined) return _raw;
  try {
    const r = await fetch("data/results.json", { cache: "no-cache" });
    if (!r.ok) throw new Error(r.status);
    _raw = await r.json();
  } catch (e) { _raw = null; }
  return _raw;
}
async function loadResults() { const j = await loadRaw(); return j && !j.pending ? j : null; }
