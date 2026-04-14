"""AG-UI streaming service.

Translates LangGraph ``astream_events`` into AG-UI protocol events so the
frontend receives token-by-token streaming, step visibility, and structured
interrupt payloads over a single SSE connection.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, AsyncIterator

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from ag_ui.core import (
    CustomEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    RunAgentInput,
    StepFinishedEvent,
    StepStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)
from ag_ui.encoder import EventEncoder

logger = logging.getLogger(__name__)

_SKIP_NODE_NAMES = frozenset({
    "LangGraph",
    "ChannelRead",
    "ChannelWrite",
    "__start__",
    "__end__",
    "RunnableSequence",
    "ChatPromptTemplate",
    "ChatOpenAI",
    "AzureChatOpenAI",
})


def _is_graph_node(name: str) -> bool:
    if name in _SKIP_NODE_NAMES or name.startswith("__"):
        return False
    if "Channel" in name or "Runnable" in name:
        return False
    return True


class AgUiService:
    def __init__(self, graph: Any) -> None:
        self._graph = graph

    def get_content_type(self, accept_header: str | None = None) -> str:
        return EventEncoder(accept=accept_header).get_content_type()

    async def stream_run(
        self,
        input_data: RunAgentInput,
        accept_header: str | None = None,
    ) -> AsyncIterator[str | bytes]:
        """Run the LangGraph graph and yield encoded AG-UI events."""
        encoder = EventEncoder(accept=accept_header)
        thread_id = input_data.thread_id
        run_id = input_data.run_id
        config = {"configurable": {"thread_id": thread_id}}

        yield encoder.encode(
            RunStartedEvent(thread_id=thread_id, run_id=run_id)
        )

        try:
            is_resume = (
                isinstance(input_data.state, dict)
                and "resume_data" in input_data.state
            )

            if is_resume:
                graph_input = Command(resume=input_data.state["resume_data"])
                logger.info("AG-UI resume  thread=%s", thread_id)
            else:
                user_content = ""
                for msg in input_data.messages:
                    if msg.role == "user" and msg.content:
                        user_content = msg.content
                graph_input = {
                    "messages": [HumanMessage(content=user_content)],
                    "thread_id": thread_id,
                    "user_id": "anonymous",
                }
                logger.info("AG-UI invoke  thread=%s", thread_id)

            message_id = str(uuid.uuid4())
            message_started = False
            current_step: str | None = None

            async for event in self._graph.astream_events(
                graph_input, config, version="v2"
            ):
                kind = event.get("event", "")
                name = event.get("name", "")
                data = event.get("data", {})

                if kind == "on_chain_start" and _is_graph_node(name):
                    if current_step:
                        if message_started:
                            yield encoder.encode(
                                TextMessageEndEvent(message_id=message_id)
                            )
                            message_started = False
                        yield encoder.encode(
                            StepFinishedEvent(step_name=current_step)
                        )
                    current_step = name
                    yield encoder.encode(StepStartedEvent(step_name=name))

                elif kind == "on_chat_model_stream":
                    chunk = data.get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        if not message_started:
                            yield encoder.encode(
                                TextMessageStartEvent(
                                    message_id=message_id,
                                    role="assistant",
                                )
                            )
                            message_started = True
                        yield encoder.encode(
                            TextMessageContentEvent(
                                message_id=message_id,
                                delta=chunk.content,
                            )
                        )

                elif kind == "on_chain_end" and _is_graph_node(name):
                    if name == current_step:
                        if message_started:
                            yield encoder.encode(
                                TextMessageEndEvent(message_id=message_id)
                            )
                            message_started = False
                            message_id = str(uuid.uuid4())
                        yield encoder.encode(
                            StepFinishedEvent(step_name=name)
                        )
                        current_step = None

            if message_started:
                yield encoder.encode(
                    TextMessageEndEvent(message_id=message_id)
                )
            if current_step:
                yield encoder.encode(
                    StepFinishedEvent(step_name=current_step)
                )

            interrupt_event = await self._get_interrupt_event(encoder, config)
            if interrupt_event is not None:
                yield interrupt_event

        except Exception as exc:
            logger.error("AG-UI run error: %s", exc, exc_info=True)
            yield encoder.encode(RunErrorEvent(message=str(exc)))
            return

        yield encoder.encode(
            RunFinishedEvent(thread_id=thread_id, run_id=run_id)
        )

    async def _get_interrupt_event(
        self,
        encoder: EventEncoder,
        config: dict,
    ) -> str | bytes | None:
        """Return an encoded CustomEvent if the graph is paused on an interrupt."""
        try:
            state = await self._graph.aget_state(config)
            if state and hasattr(state, "tasks"):
                for task in state.tasks:
                    if hasattr(task, "interrupts") and task.interrupts:
                        return encoder.encode(
                            CustomEvent(
                                name="interrupt",
                                value=task.interrupts[0].value,
                            )
                        )
        except Exception:
            logger.debug(
                "Could not read graph state for interrupt check",
                exc_info=True,
            )
        return None
