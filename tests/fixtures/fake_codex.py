"""Stand-in for `codex exec --json`, for tests only. Fewer tokens when PRISM's Codex files are present."""

import json
import os
import sys
from pathlib import Path

task = sys.stdin.read()
with_prism = Path(".codex").is_dir()


def emit(value: dict) -> None:
    print(json.dumps(value), flush=True)


emit({"type": "thread.started", "thread_id": "t1"})
emit(
    {
        "type": "item.started",
        "item": {"id": "c1", "type": "command_execution", "command": "ls", "status": "in_progress"},
    }
)
emit(
    {
        "type": "item.completed",
        "item": {
            "id": "c1",
            "type": "command_execution",
            "command": "ls",
            "aggregated_output": "src\n",
            "exit_code": 0,
            "status": "completed",
        },
    }
)
if os.environ.get("FAKE_CODEX_BREAK") != ("with" if with_prism else "without"):
    path = Path("src/shop/money.py")
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace(
            "\n\ndef zero()",
            '\n    def __sub__(self, other: "Money") -> "Money":\n'
            "        return Money(self.cents - other.cents)\n\n\ndef zero()",
        ),
        encoding="utf-8",
    )
emit(
    {
        "type": "item.completed",
        "item": {"id": "f1", "type": "file_change", "changes": [{"path": "src/shop/money.py"}]},
    }
)
emit(
    {
        "type": "item.completed",
        "item": {"id": "m1", "type": "agent_message", "text": "Added Money.__sub__."},
    }
)
usage = (
    {"input_tokens": 1000, "cached_input_tokens": 600, "output_tokens": 40}
    if with_prism
    else {"input_tokens": 9000, "cached_input_tokens": 5000, "output_tokens": 300}
)
emit({"type": "turn.completed", "usage": usage})
