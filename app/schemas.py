from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.orchestrator.state import ApprovalDecision

MAX_REQUEST_CHARS = 2000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    FAILED = "FAILED"
    DONE = "DONE"


class TaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    solicitud: str = Field(min_length=1, max_length=MAX_REQUEST_CHARS, description="Pedido para el orquestador.")
    publicar: bool = Field(
        default=False,
        description="Si es True, el informe final se publica; es una acción crítica que requiere aprobación.",
    )

    @field_validator("solicitud")
    @classmethod
    def must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("solicitud no puede estar en blanco")
        return stripped


class TaskAccepted(BaseModel):
    job_id: str = Field(description="Identificador para consultar el estado del trabajo.")
    estado: JobStatus = Field(description="Estado inicial del trabajo.")
    consultar_en: str = Field(description="Ruta para consultar el estado por polling.")


class JobRecord(BaseModel):
    job_id: str = Field(description="Identificador del trabajo; también es el thread_id del grafo.")
    estado: JobStatus = Field(description="Estado actual del trabajo.")
    solicitud: str = Field(description="Pedido original del usuario.")
    publicar: bool = Field(description="Si se pidió publicar el informe.")
    creado: str = Field(default_factory=utc_now, description="Fecha de creación en ISO 8601.")
    actualizado: str = Field(default_factory=utc_now, description="Fecha de la última actualización.")
    respuesta: str | None = Field(default=None, description="Respuesta final del orquestador.")
    delegacion: list[str] = Field(default_factory=list, description="Aportes de cada agente, en orden.")
    aprobacion_pendiente: dict[str, Any] | None = Field(
        default=None, description="Lo que se debe aprobar, mientras el estado es WAITING_APPROVAL."
    )
    aprobacion: ApprovalDecision | None = Field(default=None, description="Decisión humana recibida.")
    publicado: bool = Field(default=False, description="Si el informe quedó publicado.")
    error: str | None = Field(default=None, description="Causa del fallo, si el estado es FAILED.")


class JobReport(BaseModel):
    job_id: str = Field(description="Trabajo que produjo el informe.")
    informe: str = Field(description="Texto publicado.")
    aprobado_por: str = Field(description="Revisor que autorizó la publicación.")
    publicado: str = Field(default_factory=utc_now, description="Fecha de publicación en ISO 8601.")


class QueueItem(BaseModel):
    job_id: str = Field(description="Trabajo a ejecutar.")
    tipo: Literal["start", "resume"] = Field(description="Iniciar el grafo o reanudarlo tras la aprobación.")
    decision: ApprovalDecision | None = Field(default=None, description="Decisión humana para reanudar.")
