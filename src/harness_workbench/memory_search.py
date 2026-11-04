"""Small-corpus BM25/RRF with an optional offline, isolated FastEmbed worker."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from .store import encode

MODEL = "BAAI/bge-small-zh-v1.5"
PREFIX = "为这个句子生成表示以用于检索相关文章："
STOP = {"如何", "怎么", "什么", "一个", "这个", "那个", "问题", "修复", "请问"}


def tokens(text):
    result = re.findall(r"[a-z0-9_]+", text.casefold())
    for sequence in re.findall(r"[\u4e00-\u9fff]+", text):
        result.extend(sequence[i : i + 2] for i in range(max(1, len(sequence) - 1)))
    return [word for word in result if word not in STOP]


def bm25(query, documents):
    counts = [Counter(tokens(text)) for text in documents]
    lengths = [sum(counter.values()) for counter in counts]
    average = sum(lengths) / max(1, len(lengths)) or 1
    scores = [0.0] * len(documents)
    for word in set(tokens(query)):
        frequency = sum(word in counter for counter in counts)
        idf = math.log(1 + (len(counts) - frequency + 0.5) / (frequency + 0.5))
        for i, counter in enumerate(counts):
            tf = counter[word]
            scores[i] += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * lengths[i] / average))
    return scores


def cosine(first, second):
    if len(first) != len(second) or not first:
        raise ValueError("Embedding dimensions changed")
    denominator = math.sqrt(sum(x * x for x in first) * sum(x * x for x in second))
    return (
        sum(a * b for a, b in zip(first, second, strict=True)) / denominator if denominator else 0
    )


def rank(query, documents, vectors=None, *, mode="hybrid", threshold=0.5):
    lexical = bm25(query, documents)
    dense = [cosine(vectors[0], vector) for vector in vectors[1:]] if vectors else []
    if vectors and len(dense) != len(documents):
        raise ValueError("Embedding count changed")
    lexical_order = sorted(
        (i for i, value in enumerate(lexical) if value > 0), key=lambda i: (-lexical[i], i)
    )
    dense_order = sorted(
        (i for i, value in enumerate(dense) if value >= threshold), key=lambda i: (-dense[i], i)
    )
    orders = (
        [lexical_order]
        if mode == "bm25" or not vectors
        else ([dense_order] if mode == "dense" else [lexical_order, dense_order])
    )
    scores = {}
    for order in orders:
        for position, index in enumerate(order[:20], 1):
            scores[index] = scores.get(index, 0) + 1 / (60 + position)
    return [
        {"index": i, "rrf": scores[i], "bm25": lexical[i], "cosine": dense[i] if dense else None}
        for i in sorted(scores, key=lambda i: (-scores[i], -lexical[i], i))
    ]


class LocalMemoryEncoder:
    """Cache vectors, never memory eligibility. Lifecycle checks remain authoritative."""

    def __init__(self, store):
        self.store = store
        self.profile = store.path.parent / "memory-model.json"

    def embed(self, texts):
        if not self.profile.is_file():
            raise ValueError("model_not_prepared")
        profile = json.loads(self.profile.read_text(encoding="utf-8"))
        identity = profile["identity"]
        hashes = [hashlib.sha256(text.encode()).hexdigest() for text in texts]
        values = {}
        with self.store.connect() as db:
            for key in set(hashes):
                row = db.execute(
                    "SELECT vector FROM memory_vectors WHERE model=? AND digest=?", (identity, key)
                ).fetchone()
                if row:
                    vector = json.loads(row["vector"])
                    validate_vectors([vector], 1, profile["dimensions"])
                    values[key] = vector
        missing = {key: text for key, text in zip(hashes, texts, strict=True) if key not in values}
        if missing:
            result = worker(
                profile["python"],
                {
                    "cache_dir": profile["cache_dir"],
                    "texts": list(missing.values()),
                    "download": False,
                },
            )
            if result["identity"] != identity:
                raise ValueError("model_identity_changed")
            validate_vectors(result["vectors"], len(missing), profile["dimensions"])
            with self.store.connect() as db:
                for key, vector in zip(missing, result["vectors"], strict=True):
                    db.execute(
                        "INSERT OR IGNORE INTO memory_vectors VALUES (?,?,?)",
                        (identity, key, encode(vector)),
                    )
                    values[key] = vector
        return [values[key] for key in hashes]

    def prepare(self, python, cache_dir, *, download=False):
        result = worker(
            str(Path(python).resolve()),
            {
                "cache_dir": str(Path(cache_dir).resolve()),
                "texts": ["项目记忆模型检查"],
                "download": download,
            },
            timeout=300 if download else 30,
        )
        validate_vectors(result["vectors"], 1, len(result["vectors"][0]))
        profile = {
            "model": MODEL,
            "identity": result["identity"],
            "dimensions": len(result["vectors"][0]),
            "python": str(Path(python).resolve()),
            "cache_dir": str(Path(cache_dir).resolve()),
        }
        # This local profile has no model credentials and is outside imported workspaces.
        temp = self.profile.with_suffix(".tmp")
        temp.write_text(encode(profile), encoding="utf-8")
        os.replace(temp, self.profile)
        return {k: profile[k] for k in ("model", "identity", "dimensions")}


def validate_vectors(vectors, count, dimensions):
    if not 1 <= dimensions <= 4096 or len(vectors) != count:
        raise ValueError("Invalid embedding shape")
    for vector in vectors:
        if (
            len(vector) != dimensions
            or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in vector)
            or not any(vector)
        ):
            raise ValueError("Invalid embedding vector")


def worker(python, payload, *, timeout=12):
    result = subprocess.run(
        [python, "-I", str(Path(__file__).with_name("memory_embedding_worker.py"))],
        input=encode(payload),
        encoding="utf-8",
        capture_output=True,
        timeout=timeout,
        env={
            k: v
            for k, v in os.environ.items()
            if k.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "LANG"}
        }
        | {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        check=False,
    )
    if result.returncode:
        raise ValueError("embedding_worker_failed")
    return json.loads(result.stdout)


def main():
    """Explicit preparation, kept separate from application startup."""
    import argparse

    from .store import Store

    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path(".workbench"))
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    store = Store(args.data_dir.resolve() / "application.sqlite")
    print(
        encode(
            LocalMemoryEncoder(store).prepare(args.python, args.cache_dir, download=args.download)
        )
    )


if __name__ == "__main__":
    main()
