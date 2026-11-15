// E1/E2b: ten rate steps from 0.1x to 2.0x GUESS (plan §6.2). Each step = 5 s ramp + 55 s hold, 10 min total.
import { pick, C1, BASE_SCN, THRESHOLDS, dur, secs, stagesTotal, summaryWriter } from "./lib.js";

const GUESS = Number(__ENV.GUESS || C1);
const LEVELS = Array.from({ length: 10 }, (_, i) => Math.max(1, Math.round((0.1 + (i * 1.9) / 9) * GUESS)));

const stages = LEVELS.flatMap((r) => [
  { target: r, duration: dur(5) },
  { target: r, duration: dur(55) },
]);

// The parser labels samples by step: hold_start_s..end_s is the window that is judged.
let t = 0;
const steps = LEVELS.map((rate, i) => {
  const start = t;
  t += secs(5) + secs(55);
  return { i, rate, start_s: start, hold_start_s: start + secs(5), end_s: t };
});

const PROFILE = { name: "step", guess: GUESS, stages, total_s: stagesTotal(stages), steps };

export const options = {
  scenarios: { step: { ...BASE_SCN, startRate: 1, stages } },
  thresholds: THRESHOLDS,
};

export default function () {
  pick();
}

export const handleSummary = summaryWriter(PROFILE);
