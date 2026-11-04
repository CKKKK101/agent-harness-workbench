"""Actual local embeddings; authored retrieval set, not coding-quality improvement."""

import argparse
import json
import statistics
import time
from pathlib import Path

from harness_workbench.memory_search import PREFIX, LocalMemoryEncoder, rank
from harness_workbench.store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("artifacts/memory-retrieval.json"))
    args = parser.parse_args()
    fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/memory_retrieval.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    notes = list(data["notes"])
    documents = [key + " " + data["notes"][key] for key in notes]
    encoder = LocalMemoryEncoder(Store(args.data_dir.resolve() / "application.sqlite"))
    start = time.perf_counter()
    vectors = encoder.embed([*[PREFIX + q["query"] for q in data["queries"]], *documents])
    embedding_ms = (time.perf_counter() - start) * 1000
    count = len(data["queries"])
    rows, summaries = [], {}
    for mode in ("bm25", "dense", "hybrid"):
        for i, query in enumerate(data["queries"]):
            start = time.perf_counter()
            result = rank(query["query"], documents, [vectors[i], *vectors[count:]], mode=mode)
            elapsed = (time.perf_counter() - start) * 1000
            found = [notes[item["index"]] for item in result[:3]]
            rows.append(
                query
                | {
                    "mode": mode,
                    "found": found,
                    "hit": bool(set(query["relevant"]) & set(found)),
                    "rejected": not found,
                    "ranking_ms": round(elapsed, 3),
                }
            )
        for split in ("dev", "heldout"):
            group = [row for row in rows if row["mode"] == mode and row["split"] == split]
            positive = [row for row in group if row["relevant"]]
            negative = [row for row in group if not row["relevant"]]
            summaries[f"{mode}/{split}"] = {
                "positive_count": len(positive),
                "hit_count": sum(row["hit"] for row in positive),
                "hit_at_3": sum(row["hit"] for row in positive) / len(positive),
                "negative_count": len(negative),
                "correct_rejection_count": sum(row["rejected"] for row in negative),
                "ranking_p50_ms": statistics.median(row["ranking_ms"] for row in group),
            }
    report = {
        "scope": data["scope"],
        "queries": count,
        "notes": len(notes),
        "model": json.loads(encoder.profile.read_text(encoding="utf-8"))["identity"],
        "batch_embedding_ms": round(embedding_ms, 3),
        "dense_threshold": 0.5,
        "summaries": summaries,
        "results": rows,
        "limits": "Self-authored retrieval set; no real-LLM repair-rate or token-cost claim",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
