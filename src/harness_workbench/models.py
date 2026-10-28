"""A transparent offline fixture model and a real, tool-calling model adapter."""

from __future__ import annotations

import json
import os
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class DemoRepairModel(BaseChatModel):
    """A deterministic fixture, not an LLM and not a coding-quality benchmark.

    It exercises the actual upstream graph, tools, checkpoints and recovery middleware.
    """

    @property
    def _llm_type(self) -> str:
        return "deterministic-repair-fixture"

    def bind_tools(self, tools: Any, **kwargs: Any):
        return self

    def get_num_tokens_from_messages(self, messages, tools=None) -> int:
        # Local estimate only; never download a tokenizer in the offline fixture.
        return sum(max(1, len(str(m.content)) // 4) for m in messages)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        last = next((m for m in reversed(messages) if isinstance(m, ToolMessage)), None)
        if last is None:
            name, args, call_id = "inspect_file", {"path": "calculator.py"}, "demo_read_1"
        elif last.name == "inspect_file":
            content = json.loads(str(last.content))
            if "return a - b" in content["content"]:
                name, args, call_id = (
                    "replace_text",
                    {
                        "path": "calculator.py",
                        "expected_sha256": content["sha256"],
                        "old": "return a - b",
                        "new": "return a + b",
                    },
                    "demo_edit_1",
                )
            else:
                name, args, call_id = "run_tests", {"target": "test_calculator.py"}, "demo_test_1"
        elif last.name == "replace_text":
            name, args, call_id = "run_tests", {"target": "test_calculator.py"}, "demo_test_1"
        else:
            result = json.loads(str(last.content))
            answer = (
                "Repair finished; the supplied unittest fixture passed."
                if result.get("verified")
                else "Verification failed; inspect the test output."
            )
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=answer))])
        message = AIMessage(
            content="",
            tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


def create_model(mode: str):
    if mode == "demo":
        return DemoRepairModel()
    if mode != "openai":
        raise ValueError("model_mode must be demo or openai")
    if not os.getenv("OPENAI_API_KEY") or not os.getenv("OPENAI_MODEL"):
        raise ValueError("Real model mode requires OPENAI_API_KEY and OPENAI_MODEL in .env")
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=os.environ["OPENAI_MODEL"],
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.getenv("OPENAI_BASE_URL") or None,
        temperature=0,
        timeout=60,
        max_retries=1,
        use_responses_api=False,
    )
