"""Exercise the real ChatOpenAI adapter against an in-memory HTTP transport, not an LLM."""

import json

import httpx

from harness_workbench.fixtures import DEMO_PROMPT, demo_files


def test_compatible_api_round_trip(service, monkeypatch):
    import langchain_openai

    real_class = langchain_openai.ChatOpenAI
    requests = []

    def reply(request: httpx.Request):
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(request.content)
        requests.append(payload)
        tool_results = [m for m in payload["messages"] if m["role"] == "tool"]
        if not tool_results:
            name, arguments = "inspect_file", {"path": "calculator.py"}
        elif len(tool_results) == 1:
            inspected = json.loads(tool_results[-1]["content"])
            name, arguments = (
                "replace_text",
                {
                    "path": "calculator.py",
                    "expected_sha256": inspected["sha256"],
                    "old": "return a - b",
                    "new": "return a + b",
                },
            )
        elif len(tool_results) == 2:
            name, arguments = "run_tests", {"target": "test_calculator.py"}
        else:
            name, arguments = None, {}
        message = {"role": "assistant", "content": "Done" if not name else None}
        if name:
            message["tool_calls"] = [
                {
                    "id": f"http_call_{len(tool_results)}",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }
            ]
        return httpx.Response(
            200,
            json={
                "id": f"chatcmpl-{len(requests)}",
                "object": "chat.completion",
                "created": 1,
                "model": "fixture-api-model",
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "tool_calls" if name else "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        monkeypatch.setattr(
            langchain_openai,
            "ChatOpenAI",
            lambda **kwargs: real_class(http_client=client, **kwargs),
        )
        monkeypatch.setenv("OPENAI_API_KEY", "fixture-not-a-secret")
        monkeypatch.setenv("OPENAI_MODEL", "fixture-api-model")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://fixture.invalid/v1")
        task = service.create_task(DEMO_PROMPT, demo_files(), mode="openai")
        final = service.run_sync(task["id"])
    assert final["status"] == "succeeded"
    assert len(requests) == 4
    assert {tool["function"]["name"] for tool in requests[0]["tools"]} == {
        "inspect_file",
        "replace_text",
        "run_tests",
    }
