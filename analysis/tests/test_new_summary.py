from __future__ import annotations

from analysis import common, fake_run, new_summary, parse_k6


def test_draft_has_five_numbered_lines_and_leaves_human_parts_as_todo(tmp_path):
    fake_run.make_run(tmp_path, "E3", 1, "spike", "reactive", 1, 10, 1)
    fake_run.make_run(tmp_path, "E3", 2, "spike", "reactive", 1, 10, 2)
    cfg = common.global_cfg()
    for run in common.run_dirs(tmp_path, "E3"):
        parse_k6.parse_any(run, cfg, force=True)
    text = new_summary.draft(tmp_path / "E3")
    lines = [ln for ln in text.splitlines() if ln]
    assert [ln[:2] for ln in lines] == ["1.", "2.", "3.", "4.", "5."]
    assert "2 run(s)" in lines[0] and "reactive" in lines[0]
    assert "critical p95 median" in lines[1]
    assert "Surprise:** TODO" in lines[2] and "Next:** TODO" in lines[4]
    assert "2 of 2 valid" in lines[3]
