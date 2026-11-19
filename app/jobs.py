import uuid
from typing import Any

from redis.asyncio import Redis

from app.config import DEFAULT_JOB_TTL_S
from app.schemas import JobRecord, JobReport, JobStatus, QueueItem, utc_now

JOB_KEY = "job:{job_id}"
APPROVAL_LOCK_KEY = "job:{job_id}:approval-lock"
QUEUE_KEY = "queue:tasks"
PUBLISHED_REPORT_KEY = "report:{job_id}"
PUBLISHED_INDEX_KEY = "reports:published"


class JobStore:
    def __init__(self, redis: Redis, ttl_s: int = DEFAULT_JOB_TTL_S):
        self.redis = redis
        self.ttl_s = ttl_s

    async def create(self, request: str, publish: bool) -> JobRecord:
        record = JobRecord(job_id=uuid.uuid4().hex, estado=JobStatus.PENDING, solicitud=request, publicar=publish)
        await self.save(record)
        await self.enqueue(QueueItem(job_id=record.job_id, tipo="start"))
        return record

    async def get(self, job_id: str) -> JobRecord | None:
        raw = await self.redis.get(JOB_KEY.format(job_id=job_id))
        return JobRecord.model_validate_json(raw) if raw else None

    async def save(self, record: JobRecord) -> None:
        await self.redis.set(JOB_KEY.format(job_id=record.job_id), record.model_dump_json(), ex=self.ttl_s)

    async def update(self, record: JobRecord, **changes: Any) -> JobRecord:
        updated = record.model_copy(update={**changes, "actualizado": utc_now()})
        await self.save(updated)
        return updated

    async def enqueue(self, item: QueueItem) -> None:
        await self.redis.lpush(QUEUE_KEY, item.model_dump_json())

    async def next_item(self, timeout_s: int) -> QueueItem | None:
        popped = await self.redis.brpop([QUEUE_KEY], timeout=timeout_s)
        return QueueItem.model_validate_json(popped[1]) if popped else None

    async def claim_approval(self, job_id: str) -> bool:
        return bool(await self.redis.set(APPROVAL_LOCK_KEY.format(job_id=job_id), "1", nx=True, ex=self.ttl_s))


class ReportStore:
    def __init__(self, redis: Redis):
        self.redis = redis

    async def publish(self, job_id: str, report: str, reviewer: str) -> None:
        payload = JobReport(job_id=job_id, informe=report, aprobado_por=reviewer).model_dump_json()
        await self.redis.set(PUBLISHED_REPORT_KEY.format(job_id=job_id), payload)
        await self.redis.lrem(PUBLISHED_INDEX_KEY, 0, job_id)
        await self.redis.lpush(PUBLISHED_INDEX_KEY, job_id)

    async def get(self, job_id: str) -> JobReport | None:
        raw = await self.redis.get(PUBLISHED_REPORT_KEY.format(job_id=job_id))
        return JobReport.model_validate_json(raw) if raw else None
