from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    model_mode: str = "demo"
    max_workers: int = 2
    test_timeout: int = 20
    recursion_limit: int = 40

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        return cls(
            data_dir=Path(os.getenv("WORKBENCH_DATA_DIR", ".workbench")).resolve(),
            model_mode=os.getenv("WORKBENCH_MODEL_MODE", "demo"),
            max_workers=max(1, int(os.getenv("WORKBENCH_MAX_WORKERS", "2"))),
            test_timeout=max(1, int(os.getenv("WORKBENCH_TEST_TIMEOUT", "20"))),
        )
