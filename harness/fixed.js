// E2a/E6/E7: 30 s ramp to FIXED_RPS, then hold for HOLD (default 5m). The parser drops the first 30 s.
import { pick, C1, BASE_SCN, THRESHOLDS, dur, secs, stagesTotal, summaryWriter } from "./lib.js";

const FIXED_RPS = Math.round(Number(__ENV.FIXED_RPS || 2 * C1));
if (!(FIXED_RPS > 0)) throw new Error("FIXED_RPS must be a positive number");

function toSeconds(d) {
  const m = /^(\d+)(s|m)$/.exec(d);
  if (!m) throw new Error(`HOLD must look like 90s or 5m, got ${d}`);
  return Number(m[1]) * (m[2] === "m" ? 60 : 1);
}
const HOLD_S = toSeconds(__ENV.HOLD || "5m");

const stages = [
  { target: FIXED_RPS, duration: dur(30) },
  { target: FIXED_RPS, duration: dur(HOLD_S) },
];

const PROFILE = {
  name: "fixed",
  fixed_rps: FIXED_RPS,
  stages,
  total_s: stagesTotal(stages),
  warmup_s: secs(30),
};

export const options = {
  scenarios: { fixed: { ...BASE_SCN, startRate: 1, stages } },
  thresholds: THRESHOLDS,
};

export default function () {
  pick();
}

export const handleSummary = summaryWriter(PROFILE);
