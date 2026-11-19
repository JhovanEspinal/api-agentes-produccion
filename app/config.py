import os
from dataclasses import dataclass

DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_WORKER_CONCURRENCY = 5
DEFAULT_JOB_TTL_S = 7 * 24 * 60 * 60
QUEUE_POLL_TIMEOUT_S = 5
MAX_ERROR_CHARS = 500
TRUE_VALUES = {"1", "true", "yes", "si", "sí"}


def env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in TRUE_VALUES


@dataclass(frozen=True)
class Settings:
    redis_url: str
    worker_concurrency: int
    run_worker_in_api: bool
    job_ttl_s: int

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            redis_url=os.getenv("REDIS_URL", DEFAULT_REDIS_URL),
            worker_concurrency=int(os.getenv("WORKER_CONCURRENCY", DEFAULT_WORKER_CONCURRENCY)),
            run_worker_in_api=env_flag("RUN_WORKER_IN_API", True),
            job_ttl_s=int(os.getenv("JOB_TTL_S", DEFAULT_JOB_TTL_S)),
        )
