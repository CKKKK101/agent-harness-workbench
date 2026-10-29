"""Internal inert gate: starts trusted test command only after tree assignment."""

import json
import subprocess
import sys


def main():
    line = sys.stdin.readline()
    if not line:
        return 1
    options = json.loads(line)
    return subprocess.call(
        options["command"], cwd=options["workspace"], env=options["env"],
        stdin=subprocess.DEVNULL,
    )


if __name__ == "__main__":
    raise SystemExit(main())
