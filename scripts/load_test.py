import argparse
import asyncio
import math
import time
from dataclasses import dataclass

import httpx

TERMINAL_STATES = {"DONE", "FAILED", "WAITING_APPROVAL"}
POLL_INTERVAL_S = 2.0
DEFAULT_TIMEOUT_S = 600
P95 = 0.95

REQUESTS = [
    "Compara lo que opinan los clientes de los audífonos AuraSound X2 y Nimbus Pro, y dime cuál recomiendas.",
    "¿Cómo les va en las reseñas a la cafetera Brava 300 y al molino Molienda Fina?",
    "¿Qué opinan los clientes del parlante AuraSound Mini?",
    "¿Cuál tiene mejores reseñas: la cafetera Brava 300 o los audífonos Nimbus Pro?",
    "Resume la opinión de los clientes sobre el molino Molienda Fina.",
]


@dataclass(frozen=True)
class Result:
    job_id: str
    estado: str
    segundos: float


async def run_one(client: httpx.AsyncClient, request: str, timeout_s: float) -> Result:
    started = time.perf_counter()
    response = await client.post("/tasks", json={"solicitud": request})
    response.raise_for_status()
    job_id = response.json()["job_id"]
    while time.perf_counter() - started < timeout_s:
        await asyncio.sleep(POLL_INTERVAL_S)
        estado = (await client.get(f"/tasks/{job_id}")).json()["estado"]
        if estado in TERMINAL_STATES:
            return Result(job_id, estado, time.perf_counter() - started)
    return Result(job_id, "TIMEOUT", time.perf_counter() - started)


def nearest_rank(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    return ordered[max(math.ceil(percentile * len(ordered)) - 1, 0)]


async def main(base_url: str, timeout_s: float) -> None:
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        started = time.perf_counter()
        results = await asyncio.gather(*(run_one(client, request, timeout_s) for request in REQUESTS))
        total = time.perf_counter() - started
    for result in results:
        print(f"{result.job_id}  {result.estado:<17} {result.segundos:7.1f} s")
    durations = [result.segundos for result in results]
    print(f"\n{len(results)} peticiones concurrentes en {total:.1f} s")
    print(f"Latencia de punta a punta medida por el cliente: p95 = {nearest_rank(durations, P95):.1f} s (rango más cercano)")
    print("El costo y la latencia p95 por ejecución se toman del dashboard de LangSmith.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lanza 5 peticiones concurrentes contra la API.")
    parser.add_argument("--url", default="http://localhost:8000", help="dirección base de la API")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S, help="segundos máximos por trabajo")
    args = parser.parse_args()
    asyncio.run(main(args.url, args.timeout))
