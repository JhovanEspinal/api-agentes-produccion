from typing import Any, Literal

from langgraph.graph import END
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from app.orchestrator.state import ApprovalDecision, Contribution, OrchestratorState

CRITICAL_ACTION = "publicar_informe"
DRAFT_PREVIEW_CHARS = 1500


class ApprovalRequest(BaseModel):
    accion: str = Field(description="Acción crítica que espera aprobación.")
    motivo: str = Field(description="Por qué el sistema la considera crítica.")
    borrador: str = Field(description="Contenido que se publicaría si se aprueba.")


def requires_approval(state: OrchestratorState) -> bool:
    return bool(state.get("publish_requested")) and bool(state.get("final_answer"))


def route_after_synthesis(state: OrchestratorState) -> Literal["human_approval", "__end__"]:
    return "human_approval" if requires_approval(state) else END


async def human_approval(state: OrchestratorState) -> dict[str, Any]:
    request = ApprovalRequest(
        accion=CRITICAL_ACTION,
        motivo="Publicar el informe tiene efectos fuera del sistema: queda visible para otros equipos.",
        borrador=state["final_answer"][:DRAFT_PREVIEW_CHARS],
    )
    decision = ApprovalDecision.model_validate(interrupt(request.model_dump()))
    verdict = "aprobó" if decision.aprobado else "rechazó"
    detail = f"{decision.revisor} {verdict} la publicación" + (f": {decision.comentario}" if decision.comentario else "")
    return {"approval": decision, "contributions": [Contribution(agente="human", detalle=detail)]}


def route_after_approval(state: OrchestratorState) -> Literal["publisher", "__end__"]:
    approval = state.get("approval")
    return "publisher" if approval is not None and approval.aprobado else END


def resume_with(decision: ApprovalDecision) -> Command:
    return Command(resume=decision.model_dump())
