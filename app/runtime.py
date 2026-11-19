from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from langgraph.checkpoint.redis.jsonplus_redis import JsonPlusRedisSerializer
from langgraph.graph.state import CompiledStateGraph
from redis.asyncio import Redis

from app.config import Settings
from app.graph import build_graph
from app.jobs import JobStore, ReportStore
from app.observability import configure_tracing
from app.orchestrator.llm import build_models
from app.orchestrator.state import (
    AnalysisReport,
    ApprovalDecision,
    Contribution,
    ProductAnalysis,
    ProductFindings,
    RatingStats,
    ResearchReport,
    Review,
    SentimentSummary,
    ValidationReport,
)

STATE_TYPES = (
    Review,
    ProductFindings,
    ResearchReport,
    RatingStats,
    SentimentSummary,
    ProductAnalysis,
    AnalysisReport,
    ValidationReport,
    Contribution,
    ApprovalDecision,
)


def state_serializer() -> JsonPlusRedisSerializer:
    symbols = [(*cls.__module__.split("."), cls.__name__) for cls in STATE_TYPES]
    return JsonPlusRedisSerializer(allowed_json_modules=symbols, allowed_msgpack_modules=STATE_TYPES)


@dataclass(frozen=True)
class Runtime:
    redis: Redis
    jobs: JobStore
    graph: CompiledStateGraph


@asynccontextmanager
async def open_runtime(settings: Settings) -> AsyncIterator[Runtime]:
    configure_tracing()
    models = build_models()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        async with AsyncRedisSaver.from_conn_string(settings.redis_url) as checkpointer:
            checkpointer.serde = state_serializer()
            yield Runtime(
                redis=redis,
                jobs=JobStore(redis, settings.job_ttl_s),
                graph=build_graph(models, checkpointer, ReportStore(redis)),
            )
    finally:
        await redis.aclose()
