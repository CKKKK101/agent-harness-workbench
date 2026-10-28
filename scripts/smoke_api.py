"""Smoke-test a running local service, using only the deterministic fixture."""

import json
import time
import urllib.request
from pathlib import Path

base = "http://127.0.0.1:8000"


def fetch(path, *, post=False):
    request = urllib.request.Request(
        base + path,
        data=b"{}" if post else None,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


health = fetch("/health")
created = fetch("/tasks/demo", post=True)
task_id = created["id"]
for _ in range(100):
    result = fetch(f"/tasks/{task_id}")
    if result["status"] != "running":
        break
    time.sleep(0.1)
assert result["status"] == "succeeded", result
files = fetch(f"/tasks/{task_id}/files")
assert "return a + b" in files["calculator.py"]
events = fetch(f"/tasks/{task_id}/events")
with urllib.request.urlopen(base + f"/tasks/{task_id}/stream", timeout=10) as response:
    stream = response.read().decode("utf-8")
assert "event: task.succeeded" in stream
output = {
    "health": health,
    "task_id": task_id,
    "status": result["status"],
    "metrics": result["metrics"],
    "events": len(events),
    "sse_verified": True,
}
Path("artifacts").mkdir(exist_ok=True)
Path("artifacts/api-smoke.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
print(json.dumps(output, indent=2))
