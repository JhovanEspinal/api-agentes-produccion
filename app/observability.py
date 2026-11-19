import logging
import os
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.config import env_flag
from app.orchestrator.config import GRAPH_RECURSION_LIMIT

log = logging.getLogger("api")

PROMPT_VERSION = "m6-v1"
DEFAULT_PROJECT = "api-agentes-produccion"


def configure_tracing() -> bool:
    if not env_flag("LANGSMITH_TRACING", False):
        log.info("Trazas de LangSmith desactivadas (LANGSMITH_TRACING no es true)")
        return False
    if not os.getenv("LANGSMITH_API_KEY"):
        log.warning("LANGSMITH_TRACING está activo pero falta LANGSMITH_API_KEY: se desactivan las trazas")
        os.environ["LANGSMITH_TRACING"] = "false"
        return False
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ.setdefault("LANGSMITH_PROJECT", DEFAULT_PROJECT)
    log.info("Trazas activas en el proyecto de LangSmith %s", os.environ["LANGSMITH_PROJECT"])
    return True


def job_config(job_id: str, publish: bool) -> RunnableConfig:
    metadata: dict[str, Any] = {"job_id": job_id, "publicar": publish, "prompt_version": PROMPT_VERSION}
    return {
        "configurable": {"thread_id": job_id},
        "recursion_limit": GRAPH_RECURSION_LIMIT,
        "run_name": "orquestador",
        "tags": ["api", f"prompt:{PROMPT_VERSION}"],
        "metadata": metadata,
    }
