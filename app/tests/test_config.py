import pytest

import config


def test_defaults_valid():
    config.Config.from_env().validate()


@pytest.mark.parametrize(
    "env",
    [{"WORK_SCALE": "0"}, {"DEGRADE_LEVEL": "2"}, {"SSM_MODE": "maybe"}, {"SHED_INFLIGHT": "64", "THREADS": "64"}],
)
def test_invalid_env_rejected(monkeypatch, env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(ValueError):
        config.Config.from_env()


def test_imds_fallback_is_local():
    import imds

    imds.load()  # IMDS_ENABLED=false in tests
    assert imds.INSTANCE_ID.startswith("local-") and imds.AZ == "local" and imds.ON_EC2 is False
