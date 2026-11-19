import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Annotated

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, status
from redis.exceptions import RedisError

from app.config import Settings
from app.jobs import JobStore, ReportStore
from app.logging_setup import configure_logging
from app.orchestrator.state import ApprovalDecision
from app.runtime import open_runtime
from app.schemas import JobRecord, JobReport, JobStatus, QueueItem, TaskAccepted, TaskRequest
from app.worker import Worker

log = logging.getLogger("api")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    load_dotenv()
    configure_logging()
    settings = Settings.from_env()
    async with open_runtime(settings) as runtime:
        app.state.jobs = runtime.jobs
        app.state.reports = ReportStore(runtime.redis)
        worker_task = None
        if settings.run_worker_in_api:
            worker_task = asyncio.create_task(Worker(runtime.jobs, runtime.graph, settings.worker_concurrency).run())
        try:
            yield
        finally:
            if worker_task is not None:
                worker_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await worker_task


app = FastAPI(
    title="API del orquestador multi-agente",
    description="Encola análisis de reseñas, informa su estado y pide aprobación humana antes de publicar.",
    lifespan=lifespan,
)


def jobs_from(request: Request) -> JobStore:
    return request.app.state.jobs


def reports_from(request: Request) -> ReportStore:
    return request.app.state.reports


Jobs = Annotated[JobStore, Depends(jobs_from)]
Reports = Annotated[ReportStore, Depends(reports_from)]


async def existing_job(job_id: str, jobs: JobStore) -> JobRecord:
    record = await jobs.get(job_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No existe el trabajo {job_id}")
    return record


@app.post("/tasks", status_code=status.HTTP_202_ACCEPTED)
async def create_task(body: TaskRequest, jobs: Jobs) -> TaskAccepted:
    record = await jobs.create(body.solicitud, body.publicar)
    log.info("Trabajo %s encolado (%d caracteres, publicar=%s)", record.job_id, len(body.solicitud), body.publicar)
    return TaskAccepted(job_id=record.job_id, estado=record.estado, consultar_en=f"/tasks/{record.job_id}")


@app.get("/tasks/{job_id}")
async def get_task(job_id: str, jobs: Jobs) -> JobRecord:
    return await existing_job(job_id, jobs)


@app.post("/tasks/{job_id}/approve", status_code=status.HTTP_202_ACCEPTED)
async def approve_task(job_id: str, decision: ApprovalDecision, jobs: Jobs) -> JobRecord:
    record = await existing_job(job_id, jobs)
    if record.estado != JobStatus.WAITING_APPROVAL:
        raise HTTPException(status.HTTP_409_CONFLICT, f"El trabajo no espera aprobación (estado {record.estado})")
    if not await jobs.claim_approval(job_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya se registró una decisión para este trabajo")
    record = await jobs.update(record, estado=JobStatus.PENDING, aprobacion=decision)
    await jobs.enqueue(QueueItem(job_id=job_id, tipo="resume", decision=decision))
    log.info("Trabajo %s: decisión de %s (aprobado=%s)", job_id, decision.revisor, decision.aprobado)
    return record


@app.get("/reports/{job_id}")
async def get_report(job_id: str, reports: Reports) -> JobReport:
    report = await reports.get(job_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"El trabajo {job_id} no tiene un informe publicado")
    return report


@app.get("/health")
async def health(jobs: Jobs) -> dict[str, str]:
    try:
        await jobs.redis.ping()
    except RedisError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Redis no responde") from exc
    return {"estado": "ok", "redis": "ok"}
