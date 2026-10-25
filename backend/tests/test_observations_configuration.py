"""Independent observation rollout never silently enables comparisons."""

from dataclasses import replace

import pytest

from app.snowflake.config import SnowflakeConfig


def test_observations_are_separately_opted_in(monkeypatch):
    monkeypatch.delenv("SNOWFLAKE_ENABLED", raising=False)
    monkeypatch.delenv("SNOWFLAKE_OBSERVATIONS_ENABLED", raising=False)
    monkeypatch.delenv("SNOWFLAKE_OBSERVATION_POLL_SECONDS", raising=False)
    config = SnowflakeConfig.from_env()
    assert not config.enabled and not config.observations_enabled
    assert config.observation_poll_seconds == 30
    monkeypatch.setenv("SNOWFLAKE_OBSERVATIONS_ENABLED", "true")
    monkeypatch.setenv("SNOWFLAKE_OBSERVATION_POLL_SECONDS", "5")
    config = SnowflakeConfig.from_env()
    assert config.observations_enabled and not config.enabled
    assert config.observation_poll_seconds == 5
    with pytest.raises(ValueError):
        config.validate()  # Observation-only installations still require real credentials.


def test_observation_poll_interval_and_credentials(tmp_path):
    key = tmp_path / "test-key.pem"
    key.write_text("fake key: configuration tests never sign or connect")
    config = SnowflakeConfig(
        observations_enabled=True,
        account="test-account",
        user="TEST",
        database="TEST",
        schema="TEST",
        warehouse="TEST",
        role="TEST",
        private_key_file=str(key),
    )
    config.validate()
    for interval in (0, float("nan"), 301):
        with pytest.raises(ValueError):
            replace(config, observation_poll_seconds=interval).validate()
