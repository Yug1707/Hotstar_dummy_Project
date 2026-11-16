# Report: Hotstar Scale Lab

IT457 Cloud Computing case study. The report is written as one file per section so several people can edit in parallel
without conflicts. Build a single document with `cat docs/report/0*.md > report.md` (pandoc takes the same list).

| File | Section | Status |
|---|---|---|
| [01-introduction.md](01-introduction.md) | 1 Introduction | drafted |
| [02-case-study.md](02-case-study.md) | 2 Case study | drafted; numbers cite `docs/sources.md`, and rows still marked _verify_ there are marked here too |
| [03-analysis.md](03-analysis.md) | 3 Analysis | drafted |
| [04-exercise-design.md](04-exercise-design.md) | 4 Exercise design (H1 to H6, metrics) | drafted |
| [05-results.md](05-results.md) | 5 Results (E1 to E7) | **setup written; every result is a `TODO(EX)` until the run exists** |
| [06-cost.md](06-cost.md) | 6 Cost analysis (E8) | method written; numbers pending prices and E3/E4 |
| [07-discussion.md](07-discussion.md) | 7 Discussion | threats to validity written; lessons pending |
| [08-team-process.md](08-team-process.md) | 8 Team and process | outline; fill from `git shortlog -sn` at the end |
| [09-references.md](09-references.md) | References and reproduction steps | drafted |

Rules for this report:

- **No number without a source.** Measured numbers come from `results/<EXP>/run*/summary.json` and are quoted as
  *median (min to max of N runs)*. Numbers about Hotstar cite an `S#` from `docs/sources.md` with its confidence label.
- **Every `TODO(EX)` is a missing measurement**, not a prompt to estimate. Run `grep -rn "TODO(" docs/report` before
  submitting; none may remain.
- Each results subsection follows one pattern: Hypothesis, Setup, Result (figure and numbers), Interpretation, Link to Hotstar.
- Figures are the PNGs in `results/figures/` (`make analyze`). Captions say what the figure shows, the one-sentence takeaway,
  N runs, the instance type and C1.
