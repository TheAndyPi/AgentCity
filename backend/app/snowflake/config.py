import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SnowflakeConfig:
    enabled: bool = False
    account: str = ""
    user: str = ""
    database: str = ""
    schema: str = ""
    warehouse: str = ""
    role: str = ""
    private_key_file: str = ""
    passphrase_file: str = ""
    model: str = "llama3.1-8b"
    deadline: float = 12
    daily_model_calls: int = 20

    @classmethod
    def from_env(cls):
        return cls(
            enabled=os.getenv("SNOWFLAKE_ENABLED", "false").lower() == "true",
            **{
                name: os.getenv("SNOWFLAKE_" + name.upper(), "")
                for name in ("account", "user", "database", "schema", "warehouse", "role", "private_key_file")
            },
            passphrase_file=os.getenv("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE_FILE", ""),
            model=os.getenv("SNOWFLAKE_CORTEX_MODEL", "llama3.1-8b"),
            deadline=float(os.getenv("SNOWFLAKE_DEADLINE_SECONDS", "30")),
        )

    def validate(self):
        if not self.enabled:
            return
        if not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*", self.account):
            raise ValueError("Invalid Snowflake account identifier")
        for name in ("user", "database", "schema", "warehouse", "role"):
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", getattr(self, name)):
                raise ValueError("Snowflake configuration requires simple unquoted identifiers")
        if not Path(self.private_key_file).is_file():
            raise ValueError("Snowflake private key file is unavailable")
        if self.passphrase_file and not Path(self.passphrase_file).is_file():
            raise ValueError("Snowflake passphrase file is unavailable")
        if not 0 < self.deadline <= 30 or not 1 <= self.daily_model_calls <= 100:
            raise ValueError("Invalid Snowflake budgets")
