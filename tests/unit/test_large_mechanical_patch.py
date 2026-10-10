import subprocess
from pathlib import Path

from prism.core.tokens import estimate_tokens
from prism.lifecycle import apply_init, plan_init, scan
from prism.navigator.api import op_task
from prism.navigator.store import IndexStore
from prism.navigator.task_pack import render_task


def indexed(root: Path, sites: int) -> IndexStore:
    for n in range(12):
        (root / f"m{n}.py").write_text(
            "".join(f"TARGET_SYMBOL = {i}\n" for i in range(n, sites, 12)), encoding="utf-8"
        )
    apply_init(plan_init(root))
    scan(root, warm=False)
    return IndexStore.open(root)


def test_eighty_sites_get_checked_compact_patch(tmp_path: Path) -> None:
    store = indexed(tmp_path, 80)
    try:
        pack = op_task(store, "rename TARGET_SYMBOL to NEW_SYMBOL everywhere")
        assert pack["patch"]["sites"] == 80
        text = render_task(pack)
        assert estimate_tokens(text) <= 400
        result = subprocess.run(
            ["git", "apply", "--check", str(tmp_path / pack["patch"]["path"])],
            cwd=tmp_path,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr
    finally:
        store.close()


def test_450_sites_are_refused_explicitly(tmp_path: Path) -> None:
    store = indexed(tmp_path, 450)
    try:
        pack = op_task(store, "rename TARGET_SYMBOL to NEW_SYMBOL everywhere")
        assert pack["patch_reason"] == "too_many_sites"
    finally:
        store.close()
