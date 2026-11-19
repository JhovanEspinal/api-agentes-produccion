from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.hitl import human_approval, route_after_approval, route_after_synthesis
from app.jobs import ReportStore
from app.orchestrator.agents.analyst_agent import make_analyst_node
from app.orchestrator.agents.research_agent import make_research_node
from app.orchestrator.agents.supervisor import make_supervisor_node, route_after_supervisor
from app.orchestrator.agents.synthesizer import make_synthesizer_node
from app.orchestrator.agents.validator import route_after_validation, validate_results
from app.orchestrator.llm import RoleModels
from app.orchestrator.state import Contribution, OrchestratorState


def make_publisher_node(
    reports: ReportStore,
) -> Callable[[OrchestratorState, RunnableConfig], Awaitable[dict[str, Any]]]:
    async def publish(state: OrchestratorState, config: RunnableConfig) -> dict[str, Any]:
        job_id = config["configurable"]["thread_id"]
        await reports.publish(job_id, state["final_answer"], state["approval"].revisor)
        return {
            "published": True,
            "contributions": [Contribution(agente="publisher", detalle=f"Informe publicado como report:{job_id}")],
        }

    return publish


def build_graph(
    models: RoleModels, checkpointer: BaseCheckpointSaver, reports: ReportStore
) -> CompiledStateGraph:
    workflow = StateGraph(OrchestratorState)
    workflow.add_node("supervisor", make_supervisor_node(models.supervisor))
    workflow.add_node("researcher", make_research_node(models.researcher))
    workflow.add_node("analyst", make_analyst_node(models.analyst))
    workflow.add_node("validator", validate_results)
    workflow.add_node("synthesizer", make_synthesizer_node(models.synthesizer))
    workflow.add_node("human_approval", human_approval)
    workflow.add_node("publisher", make_publisher_node(reports))

    workflow.add_edge(START, "supervisor")
    workflow.add_conditional_edges("supervisor", route_after_supervisor)
    workflow.add_edge("researcher", "supervisor")
    workflow.add_edge("analyst", "supervisor")
    workflow.add_conditional_edges("validator", route_after_validation)
    workflow.add_conditional_edges("synthesizer", route_after_synthesis)
    workflow.add_conditional_edges("human_approval", route_after_approval)
    workflow.add_edge("publisher", END)
    return workflow.compile(checkpointer=checkpointer)
