// Shared k6 code for all profiles (plan §6.1): traffic mix, tags, load-test token, open model.
// Env: BASE_URL (required), C1, TOKEN, N_USERS, MIX, MAX_VUS, SPEED, OUT.
// SPEED > 1 compresses every duration (dry runs only: SPEED=10 runs the 12.5 min spike in 75 s).
import http from "k6/http";
import { Counter } from "k6/metrics";

export const BASE = (__ENV.BASE_URL || "").replace(/\/$/, "");
if (!BASE) throw new Error("BASE_URL is required, e.g. -e BASE_URL=http://$ALB_DNS");
export const C1 = Number(__ENV.C1 || 100);
export const SPEED = Number(__ENV.SPEED || 1);
const TOKEN = __ENV.TOKEN || "";
const N_USERS = Number(__ENV.N_USERS || 50000);
const MIX_NAME = __ENV.MIX || "default";

const MIXES = {
  default: [["heartbeat", 0.55], ["playback", 0.10], ["state", 0.20], ["reco", 0.15]],
  match_only: [["state", 1.0]],
};
const MIX = MIXES[MIX_NAME];
if (!MIX) throw new Error(`unknown MIX ${MIX_NAME}; use one of ${Object.keys(MIXES).join(", ")}`);

const H = { "Content-Type": "application/json", "X-Load-Test": TOKEN };
const P = (cls, name) => ({ headers: H, tags: { class: cls, name }, timeout: "5s" });
const rid = () => 1 + Math.floor(Math.random() * N_USERS);
const body = () => JSON.stringify({ user_id: rid(), match_id: "m1" });

const http429 = new Counter("http_429"); // validity check: the token must bypass the rate limit

export function pick() {
  let r = Math.random();
  let k = MIX[MIX.length - 1][0];
  for (const [name, w] of MIX) {
    if ((r -= w) < 0) { k = name; break; }
  }
  let res;
  switch (k) {
    case "heartbeat": res = http.post(`${BASE}/api/v1/heartbeat`, body(), P("critical", "heartbeat")); break;
    case "playback": res = http.post(`${BASE}/api/v1/playback/start`, body(), P("critical", "playback")); break;
    case "state": res = http.get(`${BASE}/api/v1/match/state`, P("public", "state")); break;
    case "reco": res = http.get(`${BASE}/api/v1/recommendations`, P("noncritical", "reco")); break;
  }
  if (res && res.status === 429) http429.add(1);
  return res;
}

// Reported, never aborting: an SLO breach is a result, not a failed run.
export const THRESHOLDS = {
  "http_req_duration{class:critical}": [{ threshold: "p(95)<300", abortOnFail: false }],
  "http_req_failed": [{ threshold: "rate<0.01", abortOnFail: false }],
};

export const BASE_SCN = {
  executor: "ramping-arrival-rate",
  timeUnit: "1s",
  preAllocatedVUs: 200,
  maxVUs: Number(__ENV.MAX_VUS || 2500), // rate x 5 s timeout (plan §14)
  gracefulStop: "10s",
};

// Duration in (scaled) seconds -> k6 duration string.
export const secs = (s) => Math.max(1, Math.round(s / SPEED));
export const dur = (s) => `${secs(s)}s`;

export function stagesTotal(stages) {
  return stages.reduce((t, s) => t + parseInt(s.duration, 10), 0);
}

// handleSummary: raw k6 summary + the profile description (stages, event markers) into OUT,
// plus a short text summary on stdout. summary.json itself is produced later by parse_k6.py.
export function summaryWriter(profile) {
  return function (data) {
    const m = data.metrics;
    const v = (name, key) => (m[name] && m[name].values[key] !== undefined ? m[name].values[key] : null);
    const crit = m["http_req_duration{class:critical}"];
    const lines = [
      `profile=${profile.name} c1=${C1} speed=${SPEED} mix=${MIX_NAME} base=${BASE}`,
      `requests=${v("http_reqs", "count")} rate=${(v("http_reqs", "rate") || 0).toFixed(1)}/s ` +
        `failed=${((v("http_req_failed", "rate") || 0) * 100).toFixed(2)}%`,
      `p95 all=${(v("http_req_duration", "p(95)") || 0).toFixed(1)}ms ` +
        `critical=${crit ? crit.values["p(95)"].toFixed(1) : "n/a"}ms`,
      `dropped_iterations=${v("dropped_iterations", "count") || 0} http_429=${v("http_429", "count") || 0} ` +
        `vus_max=${v("vus_max", "value")}`,
    ];
    const out = { stdout: lines.join("\n") + "\n" };
    if (__ENV.OUT) {
      out[`${__ENV.OUT}/k6_summary.json`] = JSON.stringify(data, null, 1);
      out[`${__ENV.OUT}/profile.json`] = JSON.stringify({ ...profile, c1: C1, speed: SPEED, mix: MIX_NAME }, null, 1);
    }
    return out;
  };
}
