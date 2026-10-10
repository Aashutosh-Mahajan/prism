"""The finish-time check (Claude Code, Codex), the opt-in read dedupe, and overview prompts."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from prism.hooks import user_prompt
from prism.hooks.dedupe import decide
from prism.hooks.gate import stop
from prism.lifecycle import apply_init, plan_init, scan


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def age_repo(tmp_path: Path) -> Path:
    write(tmp_path, "pyproject.toml", "[project]\nname='x'\n")
    write(tmp_path, "backend/accounts.py", "# doctor age\nMIN_DOCTOR_AGE = 23\n")
    write(tmp_path, "backend/patients.py", "# doctor age\nLIMIT = 23  # minimum doctor age\n")
    write(tmp_path, "backend/messages.py", "MSG = 'Doctor must be at least 23 years old'\n")
    apply_init(plan_init(tmp_path))
    scan(tmp_path)
    return tmp_path


REQUEST = "The minimum doctor age is changing from 23 to 25. Update the code and the messages."


def prompt(root: Path, session: str, text: str = REQUEST) -> str:
    payload = json.dumps({"cwd": str(root), "session_id": session, "prompt": text})
    return user_prompt(payload, time_budget=30, inline_build=True)


def stop_payload(root: Path, session: str, **extra: object) -> str:
    return json.dumps({"cwd": str(root), "session_id": session, **extra})


# --- finish-time check ---------------------------------------------------------------------


def test_the_agent_is_sent_back_once_when_the_old_value_remains(age_repo: Path) -> None:
    assert "exhaustive" in prompt(age_repo, "s1")
    # nothing edited yet: the agent may stop
    assert stop(stop_payload(age_repo, "s1")) == ""
    # two of three sites changed
    write(age_repo, "backend/accounts.py", "# doctor age\nMIN_DOCTOR_AGE = 25\n")
    write(age_repo, "backend/patients.py", "# doctor age\nLIMIT = 25  # minimum doctor age\n")
    decision = json.loads(stop(stop_payload(age_repo, "s1")))
    assert decision["decision"] == "block"
    assert "backend/messages.py" in decision["reason"] and "accounts.py" not in decision["reason"]
    assert stop(stop_payload(age_repo, "s1")) == ""  # only once


def test_a_clean_finish_costs_nothing(age_repo: Path) -> None:
    prompt(age_repo, "s2")
    for rel, old in (
        ("backend/accounts.py", "MIN_DOCTOR_AGE = 23"),
        ("backend/patients.py", "LIMIT = 23"),
        ("backend/messages.py", "least 23 years"),
    ):
        path = age_repo / rel
        path.write_text(path.read_text(encoding="utf-8").replace("23", "25"), encoding="utf-8")
        assert old
    assert stop(stop_payload(age_repo, "s2")) == ""


def test_the_check_never_loops_and_ignores_other_requests(age_repo: Path) -> None:
    prompt(age_repo, "s3")
    write(age_repo, "backend/accounts.py", "# doctor age\nMIN_DOCTOR_AGE = 25\n")
    assert stop(stop_payload(age_repo, "s3", stop_hook_active=True)) == ""
    prompt(age_repo, "s4", "Where is MIN_DOCTOR_AGE used in the backend?")
    write(age_repo, "backend/patients.py", "# doctor age\nLIMIT = 25  # minimum doctor age\n")
    assert stop(stop_payload(age_repo, "s4")) == ""  # not a value change: nothing to verify


@pytest.mark.parametrize("raw", ["", "not json", "{}", '{"session_id": "zz"}', "[1]"])
def test_hostile_input_gives_silence(raw: str) -> None:
    assert stop(raw) == ""
    assert decide(raw) == ""


# --- read dedupe ---------------------------------------------------------------------------


def read_payload(root: Path, rel: str, session: str = "r1", **tool_input: object) -> str:
    return json.dumps(
        {
            "cwd": str(root),
            "session_id": session,
            "tool_name": "Read",
            "tool_input": {"file_path": str(root / rel), **tool_input},
        }
    )


def remember(
    root: Path, rel: str, session: str = "r1", now: float | None = None, **tool_input: object
) -> None:
    payload = json.loads(read_payload(root, rel, session, **tool_input))
    lo = int(tool_input.get("offset", 1))
    limit = int(tool_input.get("limit", 2000))
    rows = (root / rel).read_text(encoding="utf-8").splitlines()[lo - 1 : lo - 1 + limit]
    payload["hook_event_name"] = "PostToolUse"
    payload["tool_response"] = {
        "type": "text",
        "file": {"startLine": lo, "numLines": len(rows), "content": "\n".join(rows)},
    }
    assert decide(json.dumps(payload), now=now) == ""


def test_an_unchanged_file_is_not_read_twice(age_repo: Path) -> None:
    assert decide(read_payload(age_repo, "backend/accounts.py")) == ""
    remember(age_repo, "backend/accounts.py")
    denied = json.loads(decide(read_payload(age_repo, "backend/accounts.py", limit=2)))
    out = denied["hookSpecificOutput"]
    assert (
        out["permissionDecision"] == "deny"
        and "already in your context" in out["permissionDecisionReason"]
    )
    assert "backend/accounts.py" in out["permissionDecisionReason"]


def test_it_only_ever_denies(age_repo: Path) -> None:
    for _ in range(3):
        assert "allow" not in decide(read_payload(age_repo, "backend/accounts.py"))


def test_a_changed_file_or_a_new_range_is_readable(age_repo: Path) -> None:
    remember(age_repo, "backend/accounts.py", offset=1, limit=1)
    # a range not read yet: allowed, then remembered
    assert decide(read_payload(age_repo, "backend/accounts.py", offset=2, limit=1)) == ""
    remember(age_repo, "backend/accounts.py", offset=2, limit=1)
    assert decide(read_payload(age_repo, "backend/accounts.py", offset=2, limit=1)) != ""
    # the whole file after both halves were read is covered
    assert decide(read_payload(age_repo, "backend/accounts.py", offset=1, limit=2)) != ""
    # an edit changes the file: reading it again is allowed
    path = age_repo / "backend/accounts.py"
    path.write_text(path.read_text(encoding="utf-8") + "# edited\n", encoding="utf-8")
    assert decide(read_payload(age_repo, "backend/accounts.py", offset=1, limit=2)) == ""


def test_entries_expire_and_sessions_are_separate(age_repo: Path) -> None:
    remember(age_repo, "backend/accounts.py", now=1_000.0)
    assert decide(read_payload(age_repo, "backend/accounts.py"), now=1_000.0 + 25 * 60) == ""
    assert decide(read_payload(age_repo, "backend/accounts.py", session="other")) == ""


def test_it_can_be_switched_off(age_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    remember(age_repo, "backend/accounts.py")
    monkeypatch.setenv("PRISM_DEDUPE", "0")
    assert decide(read_payload(age_repo, "backend/accounts.py")) == ""
    assert os.environ["PRISM_DEDUPE"] == "0"


def test_failed_reads_and_unknown_response_formats_never_block_a_retry(age_repo: Path) -> None:
    raw = read_payload(age_repo, "backend/accounts.py", limit=2)
    assert decide(raw) == decide(raw) == ""
    payload = json.loads(raw)
    payload.update(hook_event_name="PostToolUseFailure", tool_response="error")
    assert decide(json.dumps(payload)) == decide(raw) == ""
    payload.update(hook_event_name="PostToolUse", tool_response={"success": True})
    assert decide(json.dumps(payload)) == decide(raw) == ""


def test_only_actual_returned_lines_are_remembered(age_repo: Path) -> None:
    remember(age_repo, "backend/accounts.py", limit=1)
    assert decide(read_payload(age_repo, "backend/accounts.py", limit=1))
    assert decide(read_payload(age_repo, "backend/accounts.py", limit=2)) == ""


def test_compaction_and_resume_invalidate_read_coverage(age_repo: Path) -> None:
    remember(age_repo, "backend/accounts.py", limit=1)
    assert decide(read_payload(age_repo, "backend/accounts.py", limit=1))
    assert (
        decide(stop_payload(age_repo, "r1", hook_event_name="SessionStart", source="compact")) == ""
    )
    assert decide(read_payload(age_repo, "backend/accounts.py", limit=1)) == ""


def test_new_reads_do_not_extend_old_ranges_expiry(age_repo: Path) -> None:
    remember(age_repo, "backend/accounts.py", now=1000, limit=1)
    remember(age_repo, "backend/accounts.py", now=2100, offset=2, limit=1)
    assert decide(read_payload(age_repo, "backend/accounts.py", limit=1), now=2201) == ""


def test_other_tools_and_unknown_repos_are_left_alone(
    age_repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    other = json.loads(read_payload(age_repo, "backend/accounts.py"))
    other["tool_name"] = "Grep"
    assert decide(json.dumps(other)) == ""
    stranger = tmp_path_factory.mktemp("stranger")
    write(stranger, "f.py", "x = 1\n")
    decide(read_payload(stranger, "f.py"))
    assert (
        decide(read_payload(stranger, "f.py")) == ""
    )  # PRISM is not enabled there: no memory kept


# --- overview prompts ----------------------------------------------------------------------


def make_big_repo(root: Path) -> None:
    write(root, "pyproject.toml", "[project]\nname='x'\n")
    for i in range(25):
        text = (
            f'"""Module {i} handles feature {i}."""'
            + "\n\n"
            + f"class Thing{i}:\n    def run(self):\n        return {i}\n\n"
            + f"def helper_{i}(x):\n    return Thing{i}().run() + x\n"
        )
        write(root, f"pkg{i % 5}/m{i}.py", text)
    apply_init(plan_init(root))
    scan(root)


def test_an_explain_the_project_request_gets_the_map_unless_switched_off(tmp_path: Path) -> None:
    make_big_repo(tmp_path)
    asked = "Without changing any files, explain the architecture of this project and its main components"
    text = prompt(tmp_path, "o1", asked)
    assert text and "overview" in text and "Map:" in text
    write(tmp_path, "prism.toml", "prompt_overview = false\n")
    assert prompt(tmp_path, "o2", asked) == ""
