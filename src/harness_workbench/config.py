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
    context_enabled: bool = True
    context_max_tokens: int = 32_768
    context_output_reserve: int = 2048
    context_memory_tokens: int = 1800
    context_recent_turns: int = 2

    def __post_init__(self):
        if self.context_max_tokens <= self.context_output_reserve + 512:
            raise ValueError("Context budget must exceed output reserve by at least 512")
        if (
            min(self.context_output_reserve, self.context_memory_tokens, self.context_recent_turns)
            < 1
        ):
            raise ValueError("Context budgets and recent turns must be positive")

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        return cls(
            data_dir=Path(os.getenv("WORKBENCH_DATA_DIR", ".workbench")).resolve(),
            model_mode=os.getenv("WORKBENCH_MODEL_MODE", "demo"),
            max_workers=max(1, int(os.getenv("WORKBENCH_MAX_WORKERS", "2"))),
            test_timeout=max(1, int(os.getenv("WORKBENCH_TEST_TIMEOUT", "20"))),
            context_enabled=os.getenv("WORKBENCH_CONTEXT_ENABLED", "true").lower() == "true",
            context_max_tokens=int(os.getenv("WORKBENCH_CONTEXT_MAX_TOKENS", "32768")),
            context_output_reserve=int(os.getenv("WORKBENCH_CONTEXT_OUTPUT_RESERVE", "2048")),
            context_memory_tokens=int(os.getenv("WORKBENCH_CONTEXT_MEMORY_TOKENS", "1800")),
            context_recent_turns=int(os.getenv("WORKBENCH_CONTEXT_RECENT_TURNS", "2")),
        )
