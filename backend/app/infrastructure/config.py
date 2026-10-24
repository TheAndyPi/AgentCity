import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    data_dir: Path = Path("data")
    host: str = "127.0.0.1"
    auth_mode: str = "local"
    session_secret: str = ""
    demo_passphrase: str = ""
    allowed_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    )
    llm_mode: str = "rules"
    gemini_api_key: str = ""
    gemini_model: str = ""
    llm_concurrency: int = 4
    llm_timeout: float = 8
    llm_rpm: int = 30
    llm_output_tokens: int = 512
    llm_token_budget: int = 200000
    base_tps: float = 2
    max_agents: int = 100
    max_running: int = 1
    autosave_interval: int = 20
    persistence_mode: str = "local"

    @classmethod
    def from_env(cls):
        return cls(
            data_dir=Path(os.getenv("DATA_DIR", "data")),
            host=os.getenv("HOST", "127.0.0.1"),
            auth_mode=os.getenv("AUTH_MODE", "local"),
            session_secret=os.getenv("SESSION_SECRET", ""),
            demo_passphrase=os.getenv("DEMO_PASSPHRASE", ""),
            allowed_origins=tuple(
                x.strip()
                for x in os.getenv("ALLOWED_ORIGINS", ",".join(cls.allowed_origins)).split(",")
                if x.strip()
            ),
            llm_mode=os.getenv("LLM_MODE", "rules"),
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_model=os.getenv("GEMINI_MODEL", ""),
            llm_concurrency=int(os.getenv("LLM_MAX_CONCURRENCY", "4")),
            llm_timeout=float(os.getenv("LLM_REQUEST_TIMEOUT_SECONDS", "8")),
            llm_rpm=int(os.getenv("LLM_REQUESTS_PER_MINUTE", "30")),
            llm_output_tokens=int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "512")),
            llm_token_budget=int(os.getenv("LLM_SESSION_TOKEN_BUDGET", "200000")),
            base_tps=float(os.getenv("SIM_BASE_TICKS_PER_SECOND", "2")),
            max_agents=int(os.getenv("SIM_MAX_AGENTS", "100")),
            max_running=int(os.getenv("SIM_MAX_RUNNING", "1")),
            autosave_interval=int(os.getenv("AUTOSAVE_INTERVAL_TICKS", "20")),
            persistence_mode=os.getenv("PERSISTENCE_MODE", "local"),
        )

    @property
    def gemini_enabled(self):
        return self.llm_mode == "gemini" and bool(self.gemini_api_key and self.gemini_model)

    def validate(self):
        if self.auth_mode not in {"local", "session"} or self.llm_mode not in {"rules", "gemini"}:
            raise ValueError("invalid AUTH_MODE or LLM_MODE")
        if self.auth_mode == "local" and self.host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("AUTH_MODE=local requires a loopback HOST")
        if self.auth_mode == "session" and (len(self.session_secret) < 32 or not self.demo_passphrase):
            raise ValueError("session mode requires SESSION_SECRET (32+ chars) and DEMO_PASSPHRASE")
        if self.persistence_mode != "local":
            raise ValueError("PostgreSQL adapter is unavailable; use PERSISTENCE_MODE=local")
        if not 10 <= self.max_agents <= 100 or self.max_running < 1 or self.base_tps <= 0:
            raise ValueError("invalid simulation limits")
        if (
            min(
                self.llm_concurrency,
                self.llm_timeout,
                self.llm_rpm,
                self.llm_output_tokens,
                self.llm_token_budget,
                self.autosave_interval,
            )
            <= 0
        ):
            raise ValueError("runtime budgets and intervals must be positive")
