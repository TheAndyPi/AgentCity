"""Real HTTP application and journal worker with an explicit offline warehouse."""

from pathlib import Path

from observations_fake import ObservationFake

from app.infrastructure.config import AppConfig
from app.snowflake.application import create_app as compose
from app.snowflake.config import SnowflakeConfig


def create_app():
    config = SnowflakeConfig(
        observations_enabled=True,
        observation_poll_seconds=1,
        account="fake-account",
        user="TEST",
        database="TEST",
        schema="TEST",
        warehouse="TEST",
        role="TEST",
        private_key_file=str(Path(__file__)),
    )
    return compose(AppConfig.from_env(), config, ObservationFake())
