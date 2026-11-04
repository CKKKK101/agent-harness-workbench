import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    messages_to_dict,
)

from harness_workbench import agent as agent_module
from harness_workbench.context import (
    ContextBudgetExceeded,
    ContextIntegrityError,
    ContextProjector,
    split_turns,
)
from harness_workbench.faults import FaultInjector, InjectedCrash
from harness_workbench.models import DemoRepairModel
from harness_workbench.store import encode
from harness_workbench.tools import ToolRunner


def make_projector(service, *, scope=None, fault=None, budget=9000):
    task = service.create_demo(memory_scope=scope, fault=fault)
    runner = ToolRunner(
        service.store,
        task["id"],
        Path(service.store.task(task["id"])["workspace"]),
        FaultInjector(service.store, task["id"]),
    )
    settings = replace(service.settings, context_max_tokens=budget, context_output_reserve=1000)
    return task, ContextProjector(runner, settings)


def history(prompt, count=8, size=2200):
    messages = [HumanMessage(content=prompt, id="initial")]
    for i in range(count):
        messages += [
            AIMessage(
                content="",
                id=f"a{i}",
                tool_calls=[
                    {"id": f"call-{i}", "name": "inspect_file", "args": {"path": "calculator.py"}}
                ],
            ),
            ToolMessage(
                content="x" * size, name="inspect_file", tool_call_id=f"call-{i}", id=f"t{i}"
            ),
        ]
    return messages


def test_compression_retains_requirements_latest_turn_and_original_messages(service):
    task, projector = make_projector(service)
    prompt = service.store.task(task["id"])["prompt"]
    messages = history(prompt)
    original = messages_to_dict(messages)
    view, report = projector.project(messages)
    assert report["compressed"]
    assert report["after_estimated_tokens"] <= report["input_limit"]
    assert report["after_estimated_tokens"] < report["before_estimated_tokens"]
    assert report["facts"]["user_requirements"] == prompt
    assert "test_calculator.py" in report["facts"]["original_tests"]
    assert view[-1] == messages[-1] and view[-2] == messages[-2]
    assert messages_to_dict(messages) == original
    split_turns(view)


def test_followup_user_constraints_survive_compression(service):
    task, projector = make_projector(service)
    messages = history(service.store.task(task["id"])["prompt"])
    followup = HumanMessage(content="Never rename add, and preserve the public API")
    messages.insert(5, followup)
    view, _ = projector.project(messages)
    assert followup in view


def test_parallel_tool_turn_is_retained_as_an_indivisible_group(service):
    task, projector = make_projector(service, budget=10_000)
    messages = history(service.store.task(task["id"])["prompt"])
    parallel = [
        AIMessage(
            content="",
            tool_calls=[
                {"id": "parallel-a", "name": "inspect_file", "args": {"path": "a.py"}},
                {"id": "parallel-b", "name": "inspect_file", "args": {"path": "b.py"}},
            ],
        ),
        ToolMessage(content="a", tool_call_id="parallel-a"),
        ToolMessage(content="b", tool_call_id="parallel-b"),
    ]
    view, report = projector.project([*messages, *parallel])
    assert report["compressed"] and view[-3:] == parallel


@pytest.mark.parametrize(
    "messages",
    [
        [ToolMessage(content="orphan", tool_call_id="x")],
        [AIMessage(content="", tool_calls=[{"id": "x", "name": "read", "args": {}}])],
        [
            AIMessage(content="", tool_calls=[{"id": "x", "name": "read", "args": {}}]),
            ToolMessage(content="wrong", tool_call_id="y"),
        ],
    ],
)
def test_invalid_tool_protocol_is_blocked(messages):
    with pytest.raises(ContextIntegrityError):
        split_turns(messages)


def test_oversized_required_latest_turn_is_blocked_not_truncated(service):
    task, projector = make_projector(service)
    messages = history(service.store.task(task["id"])["prompt"], count=1, size=20_000)
    with pytest.raises(ContextBudgetExceeded):
        projector.project(messages)
    assert not service.context_views(task["id"])


def test_system_prompt_tool_schema_and_output_reserve_count_toward_budget(service):
    task, projector = make_projector(service, budget=4000)
    messages = [HumanMessage(content=service.store.task(task["id"])["prompt"])]
    with pytest.raises(ContextBudgetExceeded):
        projector.project(messages, system=SystemMessage(content="rule" * 2000))
    schema = {
        "type": "function",
        "function": {
            "name": "inspect_file",
            "description": "x" * 6000,
            "parameters": {"type": "object"},
        },
    }
    with pytest.raises(ContextBudgetExceeded):
        projector.project(messages, tools=[schema])
    _, report = projector.project(messages)
    assert report["input_limit"] == 3000


def test_context_snapshot_is_atomic_and_reused_for_identical_sources(service):
    task, projector = make_projector(service)
    messages = history(service.store.task(task["id"])["prompt"])
    _, first = projector.project(messages)
    _, second = ContextProjector(projector.runner, projector.settings).project(messages)
    assert not first["reused"] and second["reused"]
    assert first["checksum"] == second["checksum"]
    assert len(service.context_views(task["id"])) == 1
    assert (
        len([e for e in service.store.events(task["id"]) if e["kind"] == "context.prepared"]) == 1
    )


@pytest.mark.parametrize(
    "fault,committed", [("before_context_commit", False), ("after_context_commit", True)]
)
def test_context_commit_fault_recovery_never_uses_partial_view(service, fault, committed):
    task, projector = make_projector(service, fault=fault)
    messages = history(service.store.task(task["id"])["prompt"])
    with pytest.raises(InjectedCrash):
        projector.project(messages)
    assert bool(service.context_views(task["id"])) == committed
    _, result = ContextProjector(projector.runner, projector.settings).project(messages)
    assert result["reused"] == committed and result["compressed"]
    assert len(service.context_views(task["id"])) == 1


@pytest.mark.parametrize(
    "fault,committed", [("before_context_commit", False), ("after_context_commit", True)]
)
def test_actual_worker_exit_at_context_commit_boundary(service, fault, committed):
    task, projector = make_projector(service, fault=fault)
    # A separate process exits via os._exit: no finally/exception cleanup can hide the window.
    source = r"""
import sys
from pathlib import Path
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from harness_workbench.config import Settings
from harness_workbench.context import ContextProjector
from harness_workbench.faults import FaultInjector
from harness_workbench.store import Store
from harness_workbench.tools import ToolRunner
store = Store(Path(sys.argv[1]))
task = store.task(sys.argv[2])
runner = ToolRunner(store, task['id'], Path(task['workspace']),
                    FaultInjector(store, task['id'], hard=True))
messages = [HumanMessage(content=task['prompt'], id='initial')]
for i in range(8):
    messages += [AIMessage(content='', id=f'a{i}', tool_calls=[
        {'id': f'call-{i}', 'name': 'inspect_file', 'args': {'path': 'calculator.py'}}]),
        ToolMessage(content='x'*2200, name='inspect_file', tool_call_id=f'call-{i}', id=f't{i}')]
ContextProjector(runner, Settings(data_dir=Path(sys.argv[1]).parent,
    context_max_tokens=9000, context_output_reserve=1000)).project(messages)
"""
    result = subprocess.run(
        [sys.executable, "-c", source, str(service.store.path), task["id"]],
        env=os.environ | {"PYTHONUTF8": "1"},
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 86, result.stderr.decode("utf-8", errors="replace")
    assert bool(service.context_views(task["id"])) == committed
    _, recovered = projector.project(history(service.store.task(task["id"])["prompt"]))
    assert recovered["reused"] == committed


@pytest.mark.parametrize("corruption", ["{}", "not-json"])
def test_corrupt_persisted_context_is_rejected(service, corruption):
    task, projector = make_projector(service)
    messages = history(service.store.task(task["id"])["prompt"])
    projector.project(messages)
    with service.store.connect() as db:
        db.execute("UPDATE context_views SET payload=? WHERE task_id=?", (corruption, task["id"]))
    with pytest.raises(ContextIntegrityError):
        projector.project(messages)


def test_deleted_memory_is_not_reinjected_by_a_cached_context(service):
    task, projector = make_projector(service, scope="repo")
    memory = service.memory.put("repo", "style", "Type hints in calculator.py", kind="constraint")
    messages = [HumanMessage(content=service.store.task(task["id"])["prompt"], id="initial")]
    _, first = projector.project(messages)
    assert first["memory_references"][0]["version"] == 1
    service.memory.retire("repo", "style", expected_version=memory["version"], delete=True)
    view, second = projector.project(messages)
    assert not second["memory_references"]
    assert "Type hints" not in str(messages_to_dict(view))
    assert first["input_digest"] != second["input_digest"]


def test_low_priority_memory_is_dropped_as_whole_records_when_budget_is_small(service):
    task, projector = make_projector(service, scope="repo")
    projector.settings = replace(projector.settings, context_memory_tokens=150)
    service.memory.put("repo", "style", "Use type hints " * 100, kind="constraint")
    view, report = projector.project(
        [HumanMessage(content=service.store.task(task["id"])["prompt"])]
    )
    assert not report["memory_references"]
    assert report["memory_excluded"][0]["reason"] == "context_budget"
    assert "Use type hints" not in str(messages_to_dict(view))


def test_key_facts_preserve_actual_journal_progress_and_uncertainty(service):
    task, projector = make_projector(service)
    runner = projector.runner
    read = runner.execute("read", "inspect_file", {"path": "calculator.py"})
    service.store.prepare(
        task["id"], "pending-test", "run_tests", {"target": "test_calculator.py"}, {}
    )
    service.store.tool_started(task["id"], "pending-test")
    facts = projector.facts(service.store.task(task["id"]))
    assert facts["last_observed_files"]["calculator.py"]["sha256"] == read["sha256"]
    assert facts["unresolved_calls"] == [
        {"call_id": "pending-test", "tool": "run_tests", "state": "started"}
    ]


def test_actual_graph_compacts_inputs_but_keeps_full_checkpoint_history(service, monkeypatch):
    captured = []

    class LongReadModel(DemoRepairModel):
        def _generate(self, messages, **kwargs):
            captured.append(messages_to_dict(messages))
            count = sum(m.type == "tool" and m.name == "inspect_file" for m in messages)
            for message in messages:
                if isinstance(message.content, str) and message.content.startswith(
                    "HARNESS_KEY_FACTS"
                ):
                    facts = json.loads(message.content.split("\n", 1)[1])
                    count = max(count, facts["tool_counts"].get("inspect_file", 0))
            last = next((m for m in reversed(messages) if m.type == "tool"), None)
            if count < 9 and (last is None or last.name == "inspect_file"):
                return self._result(count)
            return super()._generate(messages, **kwargs)

        def _result(self, count):
            from langchain_core.outputs import ChatGeneration, ChatResult

            return ChatResult(
                generations=[
                    ChatGeneration(
                        message=AIMessage(
                            content="Reviewing the same file for this context fixture. " * 40,
                            tool_calls=[
                                {
                                    "id": f"read-{count}",
                                    "name": "inspect_file",
                                    "args": {"path": "calculator.py"},
                                }
                            ],
                        )
                    )
                ]
            )

    monkeypatch.setattr(agent_module, "create_model", lambda mode: LongReadModel())
    service.settings = replace(
        service.settings,
        context_max_tokens=12_000,
        context_output_reserve=1000,
        context_recent_turns=1,
    )
    task = service.create_demo()
    assert service.run_sync(task["id"])["status"] == "succeeded"
    reports = service.context_views(task["id"])
    assert any(r["compressed"] for r in reports)
    assert all(r["after_estimated_tokens"] <= r["input_limit"] for r in reports)
    assert any("HARNESS_KEY_FACTS" in encode(request) for request in captured)
    from langgraph.checkpoint.sqlite import SqliteSaver

    with SqliteSaver.from_conn_string(
        str(service.settings.data_dir / "checkpoints" / f"{task['id']}.sqlite")
    ) as saver:
        runner = ToolRunner(
            service.store,
            task["id"],
            Path(service.store.task(task["id"])["workspace"]),
            FaultInjector(service.store, task["id"]),
        )
        restored = agent_module.build_agent("demo", runner, saver, service.settings)
        full = restored.get_state({"configurable": {"thread_id": task["id"]}}).values["messages"]
    assert sum(m.type == "tool" and m.name == "inspect_file" for m in full) == 9
    assert not any("HARNESS_KEY_FACTS" in str(m.content) for m in full)
