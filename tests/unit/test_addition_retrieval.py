from pathlib import Path

import pytest

from prism.lifecycle import apply_init, plan_init, scan
from prism.navigator.api import op_task
from prism.navigator.request import introduced_identifiers
from prism.navigator.store import IndexStore


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (
            "Make the JSON provider also serialize pathlib.PurePath objects",
            {"pathlib.PurePath", "PurePath"},
        ),
        ("Add support for `CustomValue` to the encoder", {"CustomValue"}),
        ("The provider should serialize pathlib.PurePath", {"pathlib.PurePath", "PurePath"}),
        ("Extend the decoder to accept custom_value", {"custom_value"}),
        ("Find pathlib.PurePath usages", set()),
        ("Fix how we serialize pathlib.PurePath objects", set()),
        ("Add logging to serialize_payload", set()),
    ],
)
def test_new_arguments_are_not_existing_edit_targets(query: str, expected: set[str]) -> None:
    assert introduced_identifiers(query) == expected


@pytest.mark.parametrize("budget", [1200, 2000])
def test_feature_addition_prefers_provider_and_includes_its_helper(
    tmp_path: Path, budget: int
) -> None:
    (tmp_path / "provider.py").write_text(
        "import uuid\n\n"
        "def _default(value):\n"
        "    if isinstance(value, uuid.UUID):\n"
        "        return str(value)\n"
        "    raise TypeError(type(value).__name__)\n\n"
        "class DefaultJSONProvider:\n"
        '    """Default JSON provider. Serializes uuid.UUID to a string."""\n'
        "    default = staticmethod(_default)\n\n"
        "    def dumps(self, value):\n"
        '        """Serialize JSON values using the default JSON provider."""\n'
        "        return self.default(value)\n",
        encoding="utf-8",
    )
    (tmp_path / "scaffold.py").write_text(
        "import pathlib\n\n"
        "def find_package(package_path):\n"
        "    return pathlib.PurePath(package_path).parent\n",
        encoding="utf-8",
    )
    apply_init(plan_init(tmp_path))
    scan(tmp_path)
    store = IndexStore.open(tmp_path)
    try:
        packet = op_task(
            store,
            "Make the default JSON provider also serialize pathlib.PurePath objects to a string; "
            "update the documented serialized types.",
            budget,
        )
    finally:
        store.close()
    assert packet["blocks"][0]["file"] == "provider.py"
    source = "\n".join(block.get("source", "") for block in packet["blocks"])
    assert "def _default(value):" in source
    assert not packet.get("read_next")
    assert any(lit["text"] == "pathlib.PurePath" for lit in packet["literals"])
    assert packet["budget"]["used_est"] <= budget


def test_api_calls_in_a_request_are_not_quantities() -> None:
    from prism.navigator.literals import _quantities

    # `.min(3)` names an API, not "3 minutes"; only the prose quantity survives.
    query = "z.string().min(3) accepts a string that has only 2 characters"
    assert _quantities(query) == [("2", "characters")]
    assert _quantities("stay valid for 15 minutes instead of 10") == [("10", "minutes")]
