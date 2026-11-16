// Case facts: peak concurrency timeline with a confidence badge per bar (sources: docs/sources.md).
"use strict";
const SOURCES_URL = "https://github.com/Yug1707/Hotstar_dummy_Project/blob/main/docs/sources.md";
const PEAKS = [
  { label: "IPL 2019", m: 10.3, src: "S3", conf: "verify" },
  { label: "IPL 2019 final", m: 18.6, src: "S3", conf: "verify" },
  { label: "World Cup 2019 semi-final", m: 25.3, src: "S4", conf: "verify" },
  { label: "World Cup 2023 final", m: 59, src: "S1", conf: "official" },
];
const CONF_TEXT = { official: "official", secondary: "secondary", verify: "to verify" };

whenReady(() => {
  const ul = $("#peak-badges");
  for (const p of PEAKS) {
    ul.append(el("li", {}, el("a", { class: `badge ${p.conf}`, href: SOURCES_URL, title: "Open the sources log" },
      el("b", { text: `${p.label}: ${p.m} M` }), ` · ${p.src} · ${CONF_TEXT[p.conf]}`)));
  }
  ul.append(el("li", {}, el("span", { class: "badge secondary" }, el("b", { text: "61 M" }), " reported for the 2023 final · S2 · secondary, conflicts with S1")));
  new Chart($("#peaks"), {
    type: "bar",
    data: {
      labels: PEAKS.map((p) => p.label),
      datasets: [{ data: PEAKS.map((p) => p.m), backgroundColor: PEAKS.map((p) => (p.conf === "official" ? css("--accent") : css("--warn"))), borderRadius: 4 }],
    },
    options: {
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `${c.parsed.y} M concurrent viewers` } } },
      scales: { y: { title: { display: true, text: "concurrent viewers (millions)" }, beginAtZero: true }, x: { ticks: { maxRotation: 0, autoSkip: false } } },
    },
  });
});
