"""Runnable composition without modifying A-owned app/main.py.

uvicorn app.snowflake.application:create_app --factory --workers 1
"""

from app.main import create_app as create_core_app
from app.snowflake.router import install_snowflake


def create_app(config=None, snowflake_config=None, transport=None):
    return install_snowflake(create_core_app(config), snowflake_config, transport)
