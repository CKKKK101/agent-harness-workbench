"""Download the exact upstream archive recorded in UPSTREAM.json, with hash checks."""

import argparse
import hashlib
import json
import urllib.request
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
metadata = json.loads((root / "UPSTREAM.json").read_text(encoding="utf-8"))
parser = argparse.ArgumentParser()
parser.add_argument("--check", action="store_true")
args = parser.parse_args()
archive = root / "upstream-0.7.32.zip"
if not archive.exists() and not args.check:
    url = "https://codeload.github.com/langchain-ai/deepagents/zip/refs/tags/deepagents%3D%3D0.7.32"
    with urllib.request.urlopen(url, timeout=60) as response, archive.open("wb") as out:
        while chunk := response.read(1024 * 1024):
            out.write(chunk)
actual = hashlib.sha256(archive.read_bytes()).hexdigest()
if actual != metadata["archive_sha256"]:
    raise RuntimeError("Upstream archive hash mismatch; refusing to extract")
if not args.check:
    target = (root / "upstream").resolve()
    with zipfile.ZipFile(archive) as source:
        for member in source.infolist():
            if not (target / member.filename).resolve().is_relative_to(target):
                raise RuntimeError("Unsafe archive path")
        source.extractall(target)
print(json.dumps({"verified": True, "sha256": actual, "tag": metadata["tag"]}))
