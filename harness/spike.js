// E3/E4: the match-day spike (plan §6.2), 12 min 30 s at SPEED=1.
//   0:00-2:00 pre-match 0.3*C1 · 2:00-3:30 ramp to 3*C1 (Hotstar's ~90 s window) · hold
//   wickets (4.2*C1 bursts) at 5:00, 7:00, 9:00 · 9:30-12:30 innings break down to 0.5*C1
import { pick, C1, BASE_SCN, THRESHOLDS, dur, secs, stagesTotal, summaryWriter } from "./lib.js";

const s = (x, sec) => ({ target: Math.round(x * C1), duration: dur(sec) });
const burst = () => [s(4.2, 5), s(4.2, 20), s(3.0, 5)];
const stages = [
  s(0.3, 120), // pre-match
  s(3.0, 90), //  match start ramp
  s(3.0, 90), //  hold
  ...burst(), s(3.0, 90), // wicket 1 + hold
  ...burst(), s(3.0, 90), // wicket 2 + hold
  ...burst(), //  wicket 3
  s(0.5, 180), // innings break
];

// Event markers in (scaled) seconds from k6 start, for plots and the analysis.
const ev = (a, b) => [secs(a), secs(b)];
const PROFILE = {
  name: "spike",
  stages,
  total_s: stagesTotal(stages),
  events_s: { ramp: ev(120, 210), bursts: [ev(300, 330), ev(420, 450), ev(540, 570)] },
};

export const options = {
  scenarios: { match: { ...BASE_SCN, startRate: Math.max(1, Math.round(0.3 * C1)), stages } },
  thresholds: THRESHOLDS,
};

export default function () {
  pick();
}

export const handleSummary = summaryWriter(PROFILE);
