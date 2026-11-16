from __future__ import annotations

import json

import pytest

from analysis import common, export_results, fake_campaign, make_plots, parse_k6

CFG = common.CONFIG_DIR


@pytest.fixture(scope="module")
def campaign(tmp_path_factory):
    out = tmp_path_factory.mktemp("results")
    fake_campaign.main(["--out", str(out), "--runs", "1"])
    cfg = common.global_cfg()
    for run in common.run_dirs(out, "FAKE_E*"):
        parse_k6.parse_any(run, cfg, force=True)
    make_plots.make_all(out, "FAKE_", out / "figures")
    return out


def test_export_full(campaign, tmp_path):
    web = tmp_path / "web"
    r = export_results.export(campaign, "FAKE_", web, campaign / "figures", CFG / "model.yaml", CFG / "prices.yaml")
    data = json.loads((web / "data" / "results.json").read_text())
    assert data["pending"] is False and data == json.loads(json.dumps(r))
    assert {f["id"] for f in data["figures"]} == {"F1", "F2", "F3", "F4", "F5", "F6"}
    assert all((web / f["png"]).exists() for f in data["figures"])
    assert {"F1", "F2"} <= set(data["series"])
    assert len(data["series"]["F1"]["n"]) == 5 and len(data["series"]["F2"]["t"]) > 100
    labels = [k["label"] for k in data["key_numbers"]]
    assert any("C1" in x for x in labels) and any("naive" in x for x in labels)
    assert data["cost"]["peaks"]["wc_2023_final"] == 59_000_000


def test_export_pending_when_nothing_analysed(tmp_path):
    web = tmp_path / "web"
    r = export_results.export(tmp_path, "", web, tmp_path / "none", CFG / "model.yaml", CFG / "prices.yaml")
    assert r["pending"] is True and r["figures"] == [] and r["key_numbers"] == []
    assert json.loads((web / "data" / "results.json").read_text())["pending"] is True
