from __future__ import annotations

import pytest

from analysis import common, fake_campaign, make_plots, parse_k6


@pytest.fixture(scope="module")
def campaign(tmp_path_factory):
    out = tmp_path_factory.mktemp("results")
    fake_campaign.main(["--out", str(out), "--runs", "1"])
    cfg = common.global_cfg()
    for run in common.run_dirs(out, "FAKE_E*"):
        parse_k6.parse_any(run, cfg, force=True)
    return out


def test_all_figures_are_made(campaign, tmp_path):
    made = make_plots.make_all(campaign, "FAKE_", tmp_path)
    assert set(made) == {"F1", "F2", "F3", "F4", "F5", "F6"}
    for fid in made:
        assert (tmp_path / f"{fid}.png").stat().st_size > 5_000
        assert (tmp_path / f"{fid}.svg").exists()


def test_missing_experiments_are_skipped_not_fatal(tmp_path):
    assert make_plots.make_all(tmp_path, "", tmp_path / "out") == {}
