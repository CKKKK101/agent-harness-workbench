"""Start a disposable local server and execute the existing UI regression scripts."""

import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def main():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    artifacts = Path("artifacts")
    artifacts.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="harness-ui-") as data:
        env = os.environ | {
            "WORKBENCH_DATA_DIR": data, "WORKBENCH_MODEL_MODE": "demo",
            "WORKBENCH_UI_URL": f"http://127.0.0.1:{port}",
        }
        with (artifacts / "ui-server.log").open("wb") as log:
            server = subprocess.Popen(
                [sys.executable, "-m", "harness_workbench.cli", "serve", "--port", str(port)],
                env=env, stdout=log, stderr=subprocess.STDOUT,
            )
            try:
                for _ in range(100):
                    if server.poll() is not None:
                        raise RuntimeError("UI server exited; see artifacts/ui-server.log")
                    try:
                        with urllib.request.urlopen(env["WORKBENCH_UI_URL"] + "/health", timeout=1):
                            break
                    except (urllib.error.URLError, TimeoutError):
                        time.sleep(0.1)
                else:
                    raise RuntimeError("UI server startup timed out")
                subprocess.run(
                    ["npm.cmd" if os.name == "nt" else "npm", "run", "test:ui"],
                    env=env, check=True, timeout=180,
                )
            finally:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(server.pid), "/T", "/F"],
                        capture_output=True, check=False,
                    )
                else:
                    server.terminate()
                server.wait(timeout=15)


if __name__ == "__main__":
    main()
