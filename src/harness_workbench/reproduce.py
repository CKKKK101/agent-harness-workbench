"""Minimal, key-free reproduction of the pinned upstream tool-calling graph."""

from deepagents import create_deep_agent
from langchain.tools import tool
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage


class ReproductionModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self

    def get_num_tokens_from_messages(self, messages, tools=None):
        return sum(max(1, len(str(m.content)) // 4) for m in messages)


def reproduce_upstream() -> dict:
    @tool
    def multiply(a: int, b: int) -> int:
        """Multiply two integers."""
        return a * b

    model = ReproductionModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "multiply",
                        "args": {"a": 6, "b": 7},
                        "id": "reproduce_1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="42"),
        ]
    )
    graph = create_deep_agent(model=model, tools=[multiply])
    result = graph.invoke({"messages": [{"role": "user", "content": "What is 6 * 7?"}]})
    messages = result["messages"]
    tool_results = [m for m in messages if m.type == "tool"]
    passed = messages[-1].content == "42" and any(str(m.content) == "42" for m in tool_results)
    if not passed:
        raise AssertionError("Pinned upstream graph did not complete the expected tool round trip")
    return {"upstream": "deepagents==0.7.32", "model": "deterministic_fixture", "passed": passed}
