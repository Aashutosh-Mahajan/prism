"""The Antigravity PreInvocation hook: the packet for the user's request, once per request."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from prism.hooks.antigravity import latest_request, pre_invocation
from prism.lifecycle import apply_init, plan_init, scan

FIXTURE = Path(__file__).parents[1] / "fixtures" / "repos" / "small"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = shutil.copytree(FIXTURE, tmp_path / "small")
    apply_init(plan_init(root))
    scan(root)
    return root


def transcript(path: Path, requests: list[str]) -> Path:
    rows = [
        {
            "step_index": i * 3,
            "source": "USER_EXPLICIT",
            "type": "USER_INPUT",
            "content": f"<USER_REQUEST>\n{text}\n</USER_REQUEST>\n<ADDITIONAL_METADATA>x</ADDITIONAL_METADATA>",
        }
        for i, text in enumerate(requests)
    ]
    rows.insert(1, {"step_index": 1, "type": "PLANNER_RESPONSE", "content": "thinking"})
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def payload(root: Path, transcript_path: Path, conversation: str = "c1") -> str:
    return json.dumps(
        {
            "conversationId": conversation,
            "invocationNum": 0,
            "workspacePaths": [str(root)],
            "transcriptPath": str(transcript_path),
        }
    )


def test_injected_steps_are_not_mistaken_for_new_requests(tmp_path: Path) -> None:
    path = transcript(tmp_path / "t.jsonl", ["fix the cart total"])
    with path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "step_index": 3,
                    "source": "SYSTEM_SDK",
                    "type": "USER_INPUT",
                    "content": "<USER_REQUEST>PRISM looked up this request</USER_REQUEST>",
                }
            )
            + chr(10)
        )
    assert latest_request(path) == (0, "fix the cart total")


def test_latest_request_is_read_from_the_user_request_tags(tmp_path: Path) -> None:
    path = transcript(tmp_path / "t.jsonl", ["first one", "second one"])
    assert latest_request(path) == (3, "second one")
    assert latest_request(tmp_path / "missing.jsonl") is None


def test_the_packet_is_injected_as_a_persistent_user_message(repo: Path, tmp_path: Path) -> None:
    path = transcript(
        tmp_path / "t.jsonl", ["Make apply_discount ignore coupons above 100 percent"]
    )
    out = json.loads(pre_invocation(payload(repo, path)))
    (step,) = out["injectSteps"]
    assert "apply_discount" in step["userMessage"] and "ephemeralMessage" not in step


def test_one_injection_per_user_request(repo: Path, tmp_path: Path) -> None:
    path = transcript(
        tmp_path / "t.jsonl", ["Make apply_discount ignore coupons above 100 percent"]
    )
    assert "injectSteps" in json.loads(pre_invocation(payload(repo, path)))
    assert pre_invocation(payload(repo, path)) == "{}"  # the next model call of the same request
    path = transcript(
        tmp_path / "t.jsonl",
        [
            "Make apply_discount ignore coupons above 100 percent",
            "Where is the Cart total computed?",
        ],
    )
    assert "injectSteps" in json.loads(pre_invocation(payload(repo, path)))  # a new request


@pytest.mark.parametrize("raw", ["", "not json", "{}", '{"workspacePaths": []}', "[1, 2]"])
def test_hostile_input_always_yields_an_empty_object(raw: str) -> None:
    assert pre_invocation(raw) == "{}"


def test_greetings_and_unrelated_requests_inject_nothing(repo: Path, tmp_path: Path) -> None:
    path = transcript(tmp_path / "t.jsonl", ["thanks, looks good"])
    assert pre_invocation(payload(repo, path)) == "{}"


def test_the_command_line_hook_prints_one_json_object(repo: Path, tmp_path: Path) -> None:
    path = transcript(
        tmp_path / "t.jsonl", ["Make apply_discount ignore coupons above 100 percent"]
    )
    done = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "prism", "hook", "pre-invocation"],
        input=payload(repo, path),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0
    assert "injectSteps" in json.loads(done.stdout)


def test_stop_gate_sends_the_agent_back_when_the_old_value_remains(
    repo: Path, tmp_path: Path
) -> None:
    from prism.hooks.antigravity import stop_gate

    (repo / "src" / "shop" / "limits.py").write_text("ITEM_LIMIT = 250\n", encoding="utf-8")
    (repo / "src" / "shop" / "caps.py").write_text("CART_LIMIT = 250\n", encoding="utf-8")
    scan(repo)
    path = transcript(tmp_path / "t.jsonl", ["Change the limit from 250 to 300 everywhere"])
    injected = json.loads(pre_invocation(payload(repo, path)))
    assert "(current value)" in injected["injectSteps"][0]["userMessage"]

    # Nothing edited yet: nothing to verify, the agent may stop.
    assert stop_gate(payload(repo, path)) == "{}"

    # One site changed, one forgotten: the agent is sent back once with the remaining line.
    (repo / "src" / "shop" / "limits.py").write_text("ITEM_LIMIT = 300\n", encoding="utf-8")
    gate = json.loads(stop_gate(payload(repo, path)))
    assert gate["decision"] == "continue"
    assert "caps.py" in gate["reason"] and "limits.py" not in gate["reason"]
    assert stop_gate(payload(repo, path)) == "{}"  # only once per request


def test_stop_gate_is_silent_for_requests_that_are_not_value_changes(
    repo: Path, tmp_path: Path
) -> None:
    from prism.hooks.antigravity import stop_gate

    path = transcript(tmp_path / "t.jsonl", ["Where is the Cart total computed?"])
    pre_invocation(payload(repo, path))
    (repo / "src" / "shop" / "utils.py").write_text("X = 1\n", encoding="utf-8")
    assert stop_gate(payload(repo, path)) == "{}"
