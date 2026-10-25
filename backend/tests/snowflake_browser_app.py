"""Test-only composition: real application, controlled external HTTP transport."""

from pathlib import Path

from snowflake_fake import SnowflakeFake

from app.infrastructure.config import AppConfig
from app.snowflake.application import create_app as compose
from app.snowflake.config import SnowflakeConfig


def create_app():
    fake = SnowflakeFake()
    config = SnowflakeConfig(
        enabled=True,
        account="fake-account",
        user="TEST",
        database="TEST",
        schema="TEST",
        warehouse="TEST",
        role="TEST",
        private_key_file=str(Path(__file__)),
    )
    return compose(AppConfig.from_env(), config, fake.transport(config))
