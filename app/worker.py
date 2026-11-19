import asyncio
import logging
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, StateSnapshot
from langsmith import traceable

from app.config import MAX_ERROR_CHARS, QUEUE_POLL_TIMEOUT_S, Settings
from app.hitl import resume_with
from app.jobs import JobStore
from app.logging_setup import configure_logging
from app.observability import job_config
from app.schemas import JobRecord, JobStatus, QueueItem

log = logging.getLogger("api")

GraphInput = dict[str, Any] | Command


def graph_input(record: JobRecord, item: QueueItem) -> GraphInput:
    if item.tipo == "resume" and item.decision is not None:
        return resume_with(item.decision)
    return {"messages": [HumanMessage(record.solicitud)], "publish_requested": record.publicar}


def outcome(snapshot: StateSnapshot) -> dict[str, Any]:
    values = snapshot.values
    trail = [f"[{item.agente}] {item.detalle}" for item in values.get("contributions", [])]
    if snapshot.interrupts:
        return {
            "estado": JobStatus.WAITING_APPROVAL,
            "aprobacion_pendiente": snapshot.interrupts[0].value,
            "respuesta": values.get("final_answer"),
            "delegacion": trail,
        }
    return {
        "estado": JobStatus.DONE,
        "respuesta": values.get("final_answer"),
        "publicado": bool(values.get("published")),
        "aprobacion": values.get("approval"),
        "delegacion": trail,
    }


def without_graph(inputs: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in inputs.items() if key != "graph"}


@traceable(name="job_orquestador", run_type="chain", process_inputs=without_graph)
async def execute(graph: CompiledStateGraph, payload: GraphInput, config: dict[str, Any]) -> dict[str, Any]:
    return await graph.ainvoke(payload, config)


class Worker:
    def __init__(
        self,
        jobs: JobStore,
        graph: CompiledStateGraph,
        concurrency: int,
        poll_timeout_s: int = QUEUE_POLL_TIMEOUT_S,
    ):
        self.jobs = jobs
        self.graph = graph
        self.concurrency = concurrency
        self.poll_timeout_s = poll_timeout_s

    async def run(self) -> None:
        log.info("Worker iniciado con %d tareas concurrentes", self.concurrency)
        async with asyncio.TaskGroup() as group:
            for _ in range(self.concurrency):
                group.create_task(self.consume())

    async def consume(self) -> None:
        while True:
            item = await self.jobs.next_item(self.poll_timeout_s)
            if item is not None:
                await self.process(item)

    async def process(self, item: QueueItem) -> JobRecord | None:
        record = await self.jobs.get(item.job_id)
        if record is None:
            log.warning("El trabajo %s ya no existe en Redis: se descarta", item.job_id)
            return None
        record = await self.jobs.update(record, estado=JobStatus.RUNNING, aprobacion_pendiente=None)
        config = job_config(record.job_id, record.publicar)
        log.info("Trabajo %s: %s", record.job_id, "reanudado" if item.tipo == "resume" else "iniciado")
        try:
            await execute(self.graph, graph_input(record, item), config)
            snapshot = await self.graph.aget_state(config)
        except Exception as exc:
            log.exception("Trabajo %s falló", record.job_id)
            error = f"{type(exc).__name__}: {exc}"[:MAX_ERROR_CHARS]
            return await self.jobs.update(record, estado=JobStatus.FAILED, error=error)
        record = await self.jobs.update(record, **outcome(snapshot))
        log.info("Trabajo %s: %s", record.job_id, record.estado)
        return record


async def main() -> None:
    from app.runtime import open_runtime

    load_dotenv()
    configure_logging()
    settings = Settings.from_env()
    async with open_runtime(settings) as runtime:
        await Worker(runtime.jobs, runtime.graph, settings.worker_concurrency).run()


if __name__ == "__main__":
    asyncio.run(main())
