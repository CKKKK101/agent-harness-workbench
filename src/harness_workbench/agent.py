"""Application middleware around the real Deep Agents graph."""

from __future__ import annotations

from deepagents import create_deep_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.tools import tool
from langchain_core.messages import ToolMessage

from .models import create_model
from .store import encode
from .tools import TOOL_NAMES, ToolRunner


@tool
def inspect_file(path: str) -> str:
    """Read a UTF-8 workspace file and obtain its SHA256 for an optimistic edit."""
    raise RuntimeError("Must be dispatched through JournalMiddleware")


@tool
def replace_text(path: str, expected_sha256: str, old: str, new: str) -> str:
    """Replace one exact occurrence in an inspected file. Supply its latest SHA256."""
    raise RuntimeError("Must be dispatched through JournalMiddleware")


@tool
def run_tests(target: str) -> str:
    """Run one supplied test_*.py unittest file and return verification evidence."""
    raise RuntimeError("Must be dispatched through JournalMiddleware")


class JournalMiddleware(AgentMiddleware):
    """Restrict the tool surface, journal effects, and recover stable tool call IDs."""

    def __init__(self, runner: ToolRunner):
        self.runner = runner

    def wrap_model_call(self, request, handler):
        selected = [
            t
            for t in request.tools
            if (t.get("name") if isinstance(t, dict) else t.name) in TOOL_NAMES
        ]
        # Built-in shell/file/subagent tools are intentionally not exposed in this profile.
        # Their effects must not bypass this application's recovery protocol.
        response = handler(request.override(tools=selected))
        self.runner.store.event(self.runner.task_id, "model.completed", {"mode": "graph"})
        return response

    def wrap_tool_call(self, request, handler):
        call = request.tool_call
        try:
            schemas = {t.name: t.args_schema for t in (inspect_file, replace_text, run_tests)}
            if call["name"] not in schemas:
                raise ValueError(f"Tool not enabled: {call['name']}")
            arguments = schemas[call["name"]].model_validate(call["args"]).model_dump()
            result = self.runner.execute(call["id"], call["name"], arguments)
        except (ValueError, FileNotFoundError, UnicodeError) as exc:
            # Correctable input errors are visible to the model. Recovery conflicts and
            # uncertain side effects deliberately escape and block the task instead.
            result = {"error": str(exc), "recoverable_input_error": True}
            self.runner.store.event(
                self.runner.task_id, "tool.input_error", {"call_id": call["id"], "error": str(exc)}
            )
        return ToolMessage(content=encode(result), tool_call_id=call["id"], name=call["name"])


SYSTEM_PROMPT = """You repair a small Python workspace using only the supplied tools.
Read files with inspect_file, apply minimal exact replacements with replace_text, then
run the supplied unittest target. Never edit test files to make a failure disappear.
The expected_sha256 prevents overwriting changes since your read. If an edit reports
an input error, read again and correct your arguments. A run is complete only when
verification passes. Do not claim success from a textual answer alone.
There is no general shell or network tool. All paths are relative to your workspace.
"""


def build_agent(mode: str, runner: ToolRunner, checkpointer):
    return create_deep_agent(
        model=create_model(mode),
        system_prompt=SYSTEM_PROMPT,
        tools=[inspect_file, replace_text, run_tests],
        middleware=[JournalMiddleware(runner)],
        checkpointer=checkpointer,
    )
