"""Stand-in for `claude -p --output-format stream-json`, for tests only.

Emits the same event shapes as Claude Code. When the working copy has PRISM's Claude Code hooks
(`.claude/settings.json`) it reports fewer tokens, so the runner's With/Without accounting can be
checked. FAKE_CLAUDE_BREAK=with|without makes that arm skip the edit (a degraded solution).
"""

import json
import os
import sys
from pathlib import Path

task = sys.stdin.read()
with_prism = Path(".claude/settings.json").is_file()
arm = "with" if with_prism else "without"


def emit(value: dict) -> None:
    print(json.dumps(value), flush=True)


emit({"type": "system", "subtype": "init", "model": "fake-model", "cwd": os.getcwd()})
usage = (
    {
        "input_tokens": 100,
        "cache_creation_input_tokens": 50,
        "cache_read_input_tokens": 500,
        "output_tokens": 50,
    }
    if with_prism
    else {
        "input_tokens": 2000,
        "cache_creation_input_tokens": 500,
        "cache_read_input_tokens": 8000,
        "output_tokens": 300,
    }
)
emit(
    {
        "type": "assistant",
        "message": {
            "id": "msg_1",
            "content": [
                {"type": "text", "text": f"Working on: {task.strip()[:60]}"},
                {"type": "tool_use", "name": "Edit", "input": {"file_path": "src/shop/money.py"}},
            ],
            "usage": usage,
        },
    }
)
if os.environ.get("FAKE_CLAUDE_BREAK") != arm:
    path = Path("src/shop/money.py")
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "\n\ndef zero()",
        '\n    def __sub__(self, other: "Money") -> "Money":\n        return Money(self.cents - other.cents)\n\n\ndef zero()',
    )
    path.write_text(text, encoding="utf-8")
emit(
    {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "content": "edited", "is_error": False}]},
    }
)
emit(
    {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "num_turns": 2,
        "result": "Added Money.__sub__.",
        "total_cost_usd": 0.01 if with_prism else 0.05,
        "usage": usage,
    }
)
