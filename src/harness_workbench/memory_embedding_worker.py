"""Native ONNX inference is isolated from API/Agent workers; no implicit downloads."""

import hashlib
import json
import sys
from pathlib import Path

MODEL = "BAAI/bge-small-zh-v1.5"


def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    payload = json.load(sys.stdin)
    from fastembed import TextEmbedding

    encoder = TextEmbedding(
        model_name=MODEL,
        cache_dir=payload["cache_dir"],
        threads=2,
        local_files_only=not payload["download"],
    )
    vectors = [v.tolist() for v in encoder.embed(payload["texts"])]
    cache = Path(payload["cache_dir"]) / "models--Qdrant--bge-small-zh-v1.5"
    files = sorted(
        p
        for p in cache.rglob("*")
        if p.is_file() and p.suffix in {".onnx", ".json", ".txt"} and "snapshots" in p.parts
    )
    if not any(p.suffix == ".onnx" for p in files):
        raise ValueError("Cannot fingerprint local model weights")
    fingerprint = hashlib.sha256(MODEL.encode())
    for path in files:
        fingerprint.update(path.relative_to(cache).as_posix().encode())
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                fingerprint.update(chunk)
    print(json.dumps({"identity": fingerprint.hexdigest(), "vectors": vectors}))


if __name__ == "__main__":
    main()
