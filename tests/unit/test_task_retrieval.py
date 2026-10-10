"""`prism task` on a full-stack fixture: the cases a real coding agent fell short on.

The fixture mirrors three requests an agent could not finish from the first pack: a lifetime
constant that is also written into UI copy, a KPI helper with several callers (whose file also
opens with a docstring full of the same words), and an error parser whose message also appears
in an unrelated component.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from prism.core.tokens import estimate_tokens
from prism.lifecycle import apply_init, plan_init, scan
from prism.navigator.api import op_task
from prism.navigator.store import IndexStore
from prism.navigator.task_pack import render_task

pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_typescript")

FIXTURE = Path(__file__).parents[1] / "fixtures" / "repos" / "webapp"

T1 = (
    "Email verification codes should stay valid for 15 minutes instead of 10. Change the app so "
    "the real expiry and everything users are told about it say 15 minutes."
)
T2 = (
    "Every KPI object the analytics endpoints return (value / previous / kind) should also "
    "include a change_pct field: the percentage change of value versus previous."
)
T3 = (
    "On the login page, if the server rejects a request with a body like "
    "{error: {message: 'Invalid credentials'}} (a message but no field details), the user sees a "
    "generic 'Something went wrong' message. Make the app show the server's message instead."
)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[IndexStore]:
    import shutil

    repo = shutil.copytree(FIXTURE, tmp_path / "webapp")
    apply_init(plan_init(repo))
    scan(repo)
    opened = IndexStore.open(repo)
    try:
        yield opened
    finally:
        opened.close()


def covered(pack: dict[str, object], file: str, line: int) -> bool:
    """Is `file:line` in the answer, as a literal occurrence or inside a returned block?"""
    for lit in pack.get("literals", []):  # type: ignore[attr-defined]
        if any(o["file"] == file and o["line"] == line for o in lit["occurrences"]):
            return True
    for block in pack["blocks"]:  # type: ignore[attr-defined]
        start, end = block["lines"]
        if block["file"] == file and start <= line <= end and "source" in block:
            return True
    return False


def test_every_site_of_a_quantity_is_found_in_one_call(store: IndexStore) -> None:
    pack = op_task(store, T1)
    # The constant and both UI strings, found with no grep.
    assert covered(pack, "backend/core/models.py", 19)
    assert covered(pack, "frontend/src/pages/auth/VerifyEmailPage.tsx", 11)
    assert covered(pack, "frontend/src/pages/auth/ForgotPasswordPage.tsx", 12)
    ten = next(lit for lit in pack["literals"] if lit["text"] == "10 minutes")
    assert ten["total"] == 3 and ten["complete"]
    # "15 instead of 10" is an explicit mechanical change at exhaustive sites: a checked patch is offered.
    assert pack["confidence"] == "high"
    assert pack["patch"]["old"] == "10" and pack["patch"]["new"] == "15"
    assert pack["patch"]["sites"] >= 3 and "Mechanical change" in pack["next"]


def test_paraphrased_request_finds_the_same_sites(store: IndexStore) -> None:
    pack = op_task(store, "email verification code expires in 10 minutes")
    assert covered(pack, "backend/core/models.py", 19)
    assert covered(pack, "frontend/src/pages/auth/VerifyEmailPage.tsx", 11)
    assert covered(pack, "frontend/src/pages/auth/ForgotPasswordPage.tsx", 12)


def test_function_is_returned_not_the_file_header(store: IndexStore) -> None:
    pack = op_task(store, T2)
    first = pack["blocks"][0]
    assert first["symbol"] == "backend.core.analytics.build_kpis"
    assert "def build_kpis" in first["source"] and not first["truncated"]
    # No block is just the module docstring.
    assert all(
        not (b["file"] == "backend/core/analytics.py" and b["lines"][0] == 1)
        for b in pack["blocks"]
    )
    assert pack["absent"] == ["change_pct"]
    assert "new" in pack["next"]


def test_callers_come_with_their_call_sites(store: IndexStore) -> None:
    pack = op_task(store, T2)
    callers = {
        c["symbol"]: c
        for c in pack["links"]
        if c["role"] == "caller" and c["target"] == "backend.core.analytics.build_kpis"
    }
    assert set(callers) == {
        "backend.core.analytics.platform_summary",
        "backend.core.analytics.restaurant_summary",
    }
    assert "build_kpis(" in callers["backend.core.analytics.platform_summary"]["snippet"]
    assert pack["impact"]["symbols"] == 2


def test_quoted_strings_are_found_everywhere_they_occur(store: IndexStore) -> None:
    pack = op_task(store, T3)
    something = next(lit for lit in pack["literals"] if lit["text"] == "Something went wrong")
    assert something["total"] == 2 and something["complete"]
    assert {o["file"] for o in something["occurrences"]} == {
        "frontend/src/api/auth.ts",
        "frontend/src/components/shared/ErrorBoundary.tsx",
    }
    assert pack["blocks"][0]["symbol"] == "frontend.src.api.auth.parseApiError"


def test_exact_symbol_comes_first_and_callers_belong_to_it(store: IndexStore) -> None:
    pack = op_task(store, "EmailCode.verify", 1500)
    assert pack["blocks"][0]["symbol"] == "backend.core.models.EmailCode.verify"
    callers = [
        c["symbol"]
        for c in pack["links"]
        if c["role"] == "caller" and c["target"] == "backend.core.models.EmailCode.verify"
    ]
    assert callers == ["backend.core.views.VerifyEmailView.post"]


def test_structural_question_lists_callers_and_impact(store: IndexStore) -> None:
    pack = op_task(store, "who calls build_kpis")
    assert pack["intent"] == "structural"
    assert len([c for c in pack["links"] if c["role"] == "caller"]) == 2
    assert pack["impact"]["symbols"] == 2


def test_unknown_request_is_honest_about_a_weak_match(store: IndexStore) -> None:
    pack = op_task(store, "quantum entanglement flux capacitor")
    assert pack["confidence"] == "low" and not pack["sufficient"]
    assert "grep" in pack["next"]


@pytest.mark.parametrize("budget", [128, 400, 800, 2000])
@pytest.mark.parametrize("query", [T1, T2, T3, "EmailCode.verify", "who calls build_kpis"])
def test_budget_is_a_hard_cap_on_json_and_text(store: IndexStore, query: str, budget: int) -> None:
    pack = op_task(store, query, budget)
    assert estimate_tokens(json.dumps(pack, separators=(",", ":"), ensure_ascii=False)) <= budget
    assert estimate_tokens(render_task(pack)) <= budget
    assert pack["budget"]["used_est"] <= budget


def test_blocks_are_verbatim_numbered_source(store: IndexStore) -> None:
    pack = op_task(store, T1)
    for block in pack["blocks"]:
        lines = (store.root / block["file"]).read_text(encoding="utf-8").splitlines()
        start, end = block["lines"]
        assert block["source"] == "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))


def test_blocks_already_shown_are_not_repeated(store: IndexStore) -> None:
    seen: set[tuple[str, int, int]] = set()
    first = op_task(store, T3, seen=seen)
    again = op_task(store, T3, seen=seen)
    assert seen
    assert any("source" in b for b in first["blocks"])
    assert all("source" not in b and b["seen"] for b in again["blocks"])
    assert "shown earlier" in render_task(again)
    assert again["budget"]["used_est"] < first["budget"]["used_est"]


def test_tests_are_the_ones_that_mention_the_code_not_every_importer(store: IndexStore) -> None:
    pack = op_task(store, "EmailCode")
    tests = [link["file"] for link in pack["links"] if link["role"] == "test"]
    assert tests == ["backend/core/tests.py"]  # it names EmailCode; nothing else does


def test_related_words_widen_the_search_but_never_outrank_the_requests_own(
    store: IndexStore,
) -> None:
    # "signing in" finds the redirect helpers, which say "auth" and "route", not "sign in".
    pack = op_task(store, "where do we decide which dashboard a user lands on after signing in")
    assert any(b["file"] == "frontend/src/utils/helpers.ts" for b in pack["blocks"])
