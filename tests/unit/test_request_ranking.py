from pathlib import Path

import pytest

from prism.lifecycle import apply_init, plan_init, scan
from prism.navigator.api import op_task
from prism.navigator.request import request_focus, request_operations
from prism.navigator.store import IndexStore


@pytest.fixture(params=[18, 140])
def helpers(tmp_path: Path, request: pytest.FixtureRequest) -> Path:
    root = tmp_path / "helpers"
    root.mkdir()
    noisy = "\n".join(
        '    result.append("repository address ValueError")' for _ in range(request.param)
    )
    (root / "addresses.py").write_text(
        "def create_request(address):\n    result = []\n"
        + noisy
        + "\n    return result\n\n"
        + "def parse_repository_address(address):\n"
        + '    """Extract repository address components."""\n'
        + '    if not address:\n        raise ValueError("invalid address")\n'
        + '    return address.split("/")\n',
        encoding="utf-8",
    )
    apply_init(plan_init(root))
    scan(root)
    return root


def test_small_helper_survives_many_matching_caller_lines(helpers: Path) -> None:
    store = IndexStore.open(helpers)
    try:
        pack = op_task(
            store,
            "Fix extraction of repository addresses. Reject invalid values with ValueError.",
            1200,
        )
        first = pack["blocks"][0]
        assert first["symbol"].endswith(".parse_repository_address")
        assert not first["truncated"]
        assert "return address.split" in first["source"]
        assert pack["budget"]["used_est"] <= 1200
    finally:
        store.close()


def test_generic_error_match_does_not_certify_an_absent_topic(helpers: Path) -> None:
    store = IndexStore.open(helpers)
    try:
        pack = op_task(
            store, "Fix lunar thermostat gradients. Reject invalid values with ValueError."
        )
        assert pack["confidence"] == "low"
        assert not pack["sufficient"]
    finally:
        store.close()


def test_focus_keeps_urls_and_qualified_names_intact() -> None:
    query = "Fix parsing https://example.com/a/b in catalog.parse_address. Reject ValueError cases."
    assert request_focus(query) == "Fix parsing https://example.com/a/b in catalog.parse_address"
    assert (
        request_focus("Fix this. Reject invalid addresses.")
        == "Fix this. Reject invalid addresses."
    )
    assert request_focus("How does catalog.parse_address work? Explain callers.").endswith(
        "Explain callers."
    )


def test_operation_expansion_uses_the_leading_request() -> None:
    assert "rank" in request_operations(
        "Fix final severity sorting. Parse error strings after ranking."
    )
    assert "pars" not in request_operations(
        "Fix final severity sorting. Parse error strings after ranking."
    )
