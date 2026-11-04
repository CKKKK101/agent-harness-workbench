"""Recall eligibility, ranking and post-inference revision validation."""

import json
import subprocess
import time

from .memory_search import PREFIX, rank
from .tools import digest, read_bytes, safe_path


def eligibility(bank, item, workspace):
    if item["status"] != "active":
        return item["status"]
    if item["expires_at"] is not None and item["expires_at"] <= time.time():
        return "expired"
    matches = True
    for path, expected in item["evidence"].items():
        try:
            matches &= digest(read_bytes(safe_path(workspace, path))) == expected
        except (ValueError, OSError):
            matches = False
    details = item.get("details") or {}
    if item["kind"] == "experience" and details.get("record_type") == "verified_repair":
        try:
            source = bank.store.task(item["source_task"])
            row = bank.store.tool(item["source_task"], "harness:acceptance:v1")
            result = json.loads(row["result"]) if row and row["state"] == "succeeded" else {}
            if (
                source["status"] != "succeeded"
                or source["memory_scope"] != item["scope"]
                or not result.get("verified")
                or result.get("fingerprint") != details["verification"]["fingerprint"]
            ):
                return "unverified_source"
        except (KeyError, TypeError, ValueError):
            return "unverified_source"
        item["use_policy"] = "reference_only; inspect current code and rerun acceptance"
        item["evidence_status"] = "matching_files" if matches else "changed_or_missing_files"
    elif not matches:
        return "stale_for_workspace"
    else:
        item["use_policy"] = "project_constraint" if item["kind"] == "constraint" else "reference"
        item["evidence_status"] = "matching_files" if item["evidence"] else "user_note"
    return None


def recall(bank, scope, query, workspace, *, limit=3, mode="hybrid"):
    if mode not in {"bm25", "dense", "hybrid"} or not 1 <= limit <= 10:
        raise ValueError("Invalid recall mode or limit")
    if not scope:
        return {"scope": None, "selected": [], "excluded": []}
    started = time.perf_counter()
    eligible, excluded = [], []

    def reject(item, reason):
        excluded.append({"key": item["key"], "version": item["version"], "reason": reason})

    for item in bank.list(scope):
        reason = eligibility(bank, item, workspace)
        if reason:
            reject(item, reason)
        else:
            eligible.append(item)
    unique, seen = [], set()
    for item in sorted(eligible, key=lambda m: (-m["created_at"], m["key"])):
        signature = (item.get("details") or {}).get("signature", item["id"])
        if signature in seen:
            reject(item, "duplicate")
        else:
            seen.add(signature)
            unique.append(item)
    unique.sort(key=lambda m: m["key"])
    documents = [item["key"] + " " + item["content"] for item in unique]
    vectors, fallback = None, None
    if mode != "bm25" and documents:
        try:
            vectors = bank.encoder.embed([PREFIX + query, *documents])
        except (
            ValueError,
            OSError,
            KeyError,
            TypeError,
            RuntimeError,
            subprocess.TimeoutExpired,
        ) as exc:
            fallback = (
                "model_not_prepared" if str(exc) == "model_not_prepared" else "encoder_unavailable"
            )
    ranking = rank(query, documents, vectors, mode=mode)
    by_index = {row["index"]: row for row in ranking}
    order = [i for i, m in enumerate(unique) if m["kind"] == "constraint"]
    order += [row["index"] for row in ranking if row["index"] not in order]
    selected = []
    # Re-check AFTER potentially slow inference; vector caches never authorize reuse.
    current = {item["key"]: item for item in bank.list(scope)}
    for index in order:
        item = unique[index]
        latest = current.get(item["key"])
        reason = (
            "revision_changed"
            if not latest or latest["id"] != item["id"]
            else (eligibility(bank, item, workspace))
        )
        if reason:
            reject(item, reason)
        elif len(selected) < limit:
            item["retrieval"] = {k: v for k, v in by_index.get(index, {}).items() if k != "index"}
            selected.append(item)
    for index, item in enumerate(unique):
        if index not in order:
            reject(item, "irrelevant")
    return {
        "scope": scope,
        "selected": selected,
        "excluded": excluded,
        "retrieval": {
            "requested": mode,
            "used": mode if vectors else "bm25",
            "fallback": fallback,
            "eligible_count": len(unique),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        },
    }
