"""`prism hook user-prompt`: the request's code arrives with the request, or nothing does."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from prism.consent import registry_path
from prism.core.tokens import estimate_tokens
from prism.hooks import user_prompt
from prism.hooks.formats import render_context
from prism.hooks.prompt import should_retrieve
from prism.hooks.runner import edited_paths
from prism.lifecycle import apply_init, plan_init, scan, set_paused

pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_typescript")

FIXTURE = Path(__file__).parents[1] / "fixtures" / "repos" / "webapp"
T1 = (
    "Email verification codes should stay valid for 15 minutes instead of 10. Change the app so "
    "the real expiry and everything users are told about it say 15 minutes."
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = shutil.copytree(FIXTURE, tmp_path / "webapp")
    apply_init(plan_init(root))
    scan(root)
    return root


def payload(root: Path, prompt: str, session: str = "s1") -> str:
    return json.dumps(
        {
            "cwd": str(root),
            "session_id": session,
            "hook_event_name": "UserPromptSubmit",
            "prompt": prompt,
        }
    )


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and "cache" not in p.relative_to(root).parts
    }


@pytest.mark.parametrize(
    "prompt",
    ["", "   ", "thanks!", "ok", "Yes.", "continue", "go ahead", "/clear", "!ls -la", "commit it"],
)
def test_chat_commands_and_confirmations_add_nothing(prompt: str) -> None:
    assert not should_retrieve(prompt)


@pytest.mark.parametrize(
    "prompt",
    [
        T1,
        "fix the crash in parse_api_error when the body is empty",
        "why does backend/core/models.py reject valid codes",
        "rename verifyEmail",
    ],
)
def test_requests_about_the_code_retrieve(prompt: str) -> None:
    assert should_retrieve(prompt)


def test_a_request_gets_the_code_it_needs(repo: Path) -> None:
    text = user_prompt(payload(repo, T1))
    assert 'Literal "10 minutes"' in text and "LIFETIME_MINUTES = 10" in text
    assert "VerifyEmailPage.tsx:11" in text and "ForgotPasswordPage.tsx:12" in text
    assert text.startswith("PRISM looked up this request")
    assert estimate_tokens(text) <= 1300


def test_unrelated_or_empty_prompts_cost_zero_tokens(repo: Path) -> None:
    assert user_prompt(payload(repo, "thanks")) == ""
    assert user_prompt(payload(repo, "quantum entanglement flux capacitor design review")) == ""
    assert user_prompt("not json") == ""


def test_repeats_in_one_session_become_references(repo: Path) -> None:
    first = user_prompt(payload(repo, T1, "a"))
    again = user_prompt(payload(repo, T1, "a"))
    other = user_prompt(payload(repo, T1, "b"))
    assert "shown earlier in this session" in again
    assert estimate_tokens(again) < estimate_tokens(first)
    assert "shown earlier" not in other


def test_no_consent_no_pause_no_output_no_writes(repo: Path) -> None:
    set_paused(repo, True)
    before = snapshot(repo)
    assert user_prompt(payload(repo, T1)) == ""
    set_paused(repo, False)
    registry_path().unlink()
    assert user_prompt(payload(repo, T1)) == ""
    assert snapshot(repo) == before


def test_the_user_can_switch_it_off(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert user_prompt(payload(repo, T1)) != ""
    monkeypatch.setenv("PRISM_PROMPT_CONTEXT", "0")
    assert user_prompt(payload(repo, T1)) == ""
    monkeypatch.delenv("PRISM_PROMPT_CONTEXT")
    (repo / "prism.toml").write_text("prompt_context = false\n")
    assert user_prompt(payload(repo, T1)) == ""


def test_the_budget_is_configurable_and_respected(repo: Path) -> None:
    (repo / "prism.toml").write_text("prompt_budget = 500\n")
    text = user_prompt(payload(repo, T1))
    assert text and estimate_tokens(text) <= 560  # the budget plus the one-line header


def test_adaptive_packet_remembers_only_delivered_attempt(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from prism.hooks.prompt import _retrieve
    from prism.navigator import api
    from prism.navigator.session import load_seen
    from prism.writers.manifest import load_manifest

    original = api.op_task
    budgets: list[int] = []
    discarded = ("not-delivered.py", 1, 2)

    def retrieve(store, query, budget, seen=None):
        assert discarded not in (seen or set())
        budgets.append(budget)
        pack = original(store, query, budget, seen)
        if len(budgets) == 1:
            pack["sufficient"] = False
            if seen is not None:
                seen.add(discarded)
        return pack

    monkeypatch.setattr(api, "op_task", retrieve)
    text = _retrieve(str(repo), T1, "adaptive", 2000)
    assert text and len(budgets) == 2 and budgets[0] < budgets[1]
    assert estimate_tokens(text) <= 2000
    assert discarded not in load_seen(repo, "adaptive", load_manifest(repo))


def test_output_formats_match_each_agents_contract() -> None:
    assert render_context("hello", "text", "UserPromptSubmit") == "hello"
    codex = json.loads(render_context("hello", "json", "UserPromptSubmit"))
    assert codex == {
        "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "hello"}
    }
    gemini = json.loads(render_context("hi", "json", "BeforeAgent"))
    assert gemini["hookSpecificOutput"]["hookEventName"] == "BeforeAgent"
    assert json.loads(render_context("hi", "cursor", "SessionStart")) == {
        "additional_context": "hi"
    }
    assert render_context("", "json", "x") == ""


def test_every_agents_edit_payload_names_the_files() -> None:
    assert edited_paths({"tool_input": {"file_path": "a.py"}}) == ["a.py"]  # Claude Code, Gemini
    assert edited_paths({"file_path": "/r/b.ts", "edits": []}) == ["/r/b.ts"]  # Cursor
    patch = (
        "*** Begin Patch\n*** Update File: src/a.py\n@@\n-x\n+y\n"
        "*** Add File: src/new.py\n+z\n*** Delete File: old.py\n*** End Patch"
    )
    assert edited_paths({"tool_name": "apply_patch", "tool_input": {"command": patch}}) == [
        "src/a.py",
        "src/new.py",
        "old.py",
    ]
    assert edited_paths({"tool_input": {"command": ["apply_patch", "*** Add File: q.py"]}}) == [
        "q.py"
    ]
    assert edited_paths({"tool_input": "a string"}) == []
    assert edited_paths({}) == []


def test_hook_process_speaks_utf8_whatever_the_console_code_page(repo: Path) -> None:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONIOENCODING"}
    env["PYTHONUTF8"] = "0"
    prompt = T1 + " Show ₹ amounts, résumé and 日本語 in the page."
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "prism",
            "hook",
            "user-prompt",
            "--format",
            "json",
            "--event",
            "BeforeAgent",
        ],
        input=payload(repo, prompt).encode("utf-8"),
        capture_output=True,
        env=env,
        cwd=repo,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout.decode("utf-8"))
    context = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "BeforeAgent"
    assert "10 minutes" in context


def test_cold_caches_start_one_background_warmup_instead_of_blocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh clone has an index but no query caches. Building them would blow a hook's time
    budget on every prompt, so the hook starts the warm-up once, says nothing, and the next
    prompt finds everything ready."""
    from prism.navigator.freshness import caches_ready, warm_caches

    root = shutil.copytree(FIXTURE, tmp_path / "cold")
    apply_init(plan_init(root))
    scan(root, warm=False)
    assert not caches_ready(root)
    started: list[bool] = []

    def fake_spawn(_root: Path, _files: object, warm_only: bool = False) -> bool:
        started.append(warm_only)
        return True

    monkeypatch.setattr("prism.hooks.prompt._spawn_update", fake_spawn)
    assert user_prompt(payload(root, T1)) == ""
    assert user_prompt(payload(root, T1)) == ""  # the marker stops a second warm-up
    assert started == [True]
    warm_caches(root)
    assert caches_ready(root)
    assert 'Literal "10 minutes"' in user_prompt(payload(root, T1))


def test_a_scan_leaves_the_caches_warm(tmp_path: Path) -> None:
    from prism.navigator.freshness import caches_ready

    root = shutil.copytree(FIXTURE, tmp_path / "warm")
    apply_init(plan_init(root))
    scan(root)
    assert caches_ready(root)


def test_a_result_the_agent_never_received_is_not_remembered(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the hook runs out of time its thread may still finish. What it found was never shown to
    the agent, so it must not be recorded as shown (the next answer would skip that code)."""
    import time

    from prism.navigator import api
    from prism.navigator.session import load_seen

    real = api.op_task

    def slow(*args: object, **kwargs: object) -> dict[str, object]:
        time.sleep(0.5)
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(api, "op_task", slow)
    monkeypatch.setattr("prism.hooks.prompt.TIME_BUDGET_SECONDS", 0.05)
    assert user_prompt(payload(repo, T1, "late")) == ""
    time.sleep(1.5)  # the abandoned thread finishes
    assert load_seen(repo, "late") == set()
    monkeypatch.undo()
    assert "shown earlier" not in user_prompt(payload(repo, T1, "late"))
