import fakeredis
import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import MemorySaver

from app.graph import build_graph
from app.jobs import QUEUE_KEY, JobStore, ReportStore
from app.main import app
from app.orchestrator.llm import RoleModels
from app.schemas import JobStatus

from app.worker import Worker
from demo_scripts import headphones_comparison

REQUEST = "Compara los audífonos AuraSound X2 y Nimbus Pro."
APPROVAL = {"aprobado": True, "revisor": "jhovan", "comentario": "Revisado."}


@pytest.fixture
async def redis():
    client = fakeredis.FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
def jobs(redis):
    return JobStore(redis)


@pytest.fixture
async def client(redis, jobs):
    app.state.jobs = jobs
    app.state.reports = ReportStore(redis)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


def worker_for(jobs: JobStore, redis, models: RoleModels) -> Worker:
    return Worker(jobs, build_graph(models, MemorySaver(), ReportStore(redis)), concurrency=1)


async def drain(worker: Worker, jobs: JobStore) -> None:
    while (item := await jobs.next_item(timeout_s=1)) is not None:
        await worker.process(item)


async def test_post_persists_the_job_before_queueing_and_returns_its_id(client, jobs, redis):
    response = await client.post("/tasks", json={"solicitud": REQUEST})
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    assert response.json()["consultar_en"] == f"/tasks/{job_id}"
    assert (await jobs.get(job_id)).estado == JobStatus.PENDING
    assert await redis.llen(QUEUE_KEY) == 1


async def test_blank_request_is_rejected(client):
    assert (await client.post("/tasks", json={"solicitud": "   "})).status_code == 422


async def test_unknown_job_returns_404(client):
    assert (await client.get("/tasks/no-existe")).status_code == 404


async def test_worker_runs_the_orchestrator_and_marks_done(client, jobs, redis):
    job_id = (await client.post("/tasks", json={"solicitud": REQUEST})).json()["job_id"]
    await drain(worker_for(jobs, redis, headphones_comparison()), jobs)
    body = (await client.get(f"/tasks/{job_id}")).json()
    assert body["estado"] == "DONE"
    assert body["respuesta"].startswith("Recomiendo los AuraSound X2")
    assert any(step.startswith("[researcher]") for step in body["delegacion"])
    assert body["publicado"] is False


async def test_an_exception_in_the_background_marks_the_job_failed(client, jobs, redis):
    models = headphones_comparison()
    models.supervisor.script[:] = [RuntimeError("fallo inesperado")]
    job_id = (await client.post("/tasks", json={"solicitud": REQUEST})).json()["job_id"]
    await drain(worker_for(jobs, redis, models), jobs)
    body = (await client.get(f"/tasks/{job_id}")).json()
    assert body["estado"] == "FAILED"
    assert body["error"] == "RuntimeError: fallo inesperado"


async def test_publishing_waits_for_human_approval_and_resumes_after_it(client, jobs, redis):
    worker = worker_for(jobs, redis, headphones_comparison())
    job_id = (await client.post("/tasks", json={"solicitud": REQUEST, "publicar": True})).json()["job_id"]
    await drain(worker, jobs)

    waiting = (await client.get(f"/tasks/{job_id}")).json()
    assert waiting["estado"] == "WAITING_APPROVAL"
    assert waiting["aprobacion_pendiente"]["accion"] == "publicar_informe"
    assert (await client.get(f"/reports/{job_id}")).status_code == 404

    approved = await client.post(f"/tasks/{job_id}/approve", json=APPROVAL)
    assert approved.status_code == 202 and approved.json()["estado"] == "PENDING"
    await drain(worker, jobs)

    done = (await client.get(f"/tasks/{job_id}")).json()
    assert done["estado"] == "DONE" and done["publicado"] is True
    assert done["delegacion"][-2:] == ["[human] jhovan aprobó la publicación: Revisado.", f"[publisher] Informe publicado como report:{job_id}"]
    report = (await client.get(f"/reports/{job_id}")).json()
    assert report["aprobado_por"] == "jhovan"


async def test_rejected_publication_ends_without_side_effects(client, jobs, redis):
    worker = worker_for(jobs, redis, headphones_comparison())
    job_id = (await client.post("/tasks", json={"solicitud": REQUEST, "publicar": True})).json()["job_id"]
    await drain(worker, jobs)
    await client.post(f"/tasks/{job_id}/approve", json={**APPROVAL, "aprobado": False})
    await drain(worker, jobs)
    body = (await client.get(f"/tasks/{job_id}")).json()
    assert body["estado"] == "DONE" and body["publicado"] is False
    assert (await client.get(f"/reports/{job_id}")).status_code == 404


async def test_approval_is_only_accepted_once_and_only_while_waiting(client, jobs, redis):
    job_id = (await client.post("/tasks", json={"solicitud": REQUEST, "publicar": True})).json()["job_id"]
    assert (await client.post(f"/tasks/{job_id}/approve", json=APPROVAL)).status_code == 409
    await drain(worker_for(jobs, redis, headphones_comparison()), jobs)
    assert (await client.post(f"/tasks/{job_id}/approve", json=APPROVAL)).status_code == 202
    assert (await client.post(f"/tasks/{job_id}/approve", json=APPROVAL)).status_code == 409


async def test_requests_without_publication_never_pause(client, jobs, redis):
    job_id = (await client.post("/tasks", json={"solicitud": REQUEST, "publicar": False})).json()["job_id"]
    await drain(worker_for(jobs, redis, headphones_comparison()), jobs)
    body = (await client.get(f"/tasks/{job_id}")).json()
    assert body["estado"] == "DONE" and body["aprobacion_pendiente"] is None


async def test_health_checks_redis(client):
    assert (await client.get("/health")).json() == {"estado": "ok", "redis": "ok"}
