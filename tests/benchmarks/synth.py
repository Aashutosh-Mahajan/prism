"""Deterministic synthetic Python repos for benchmarks and the medium fixture.

`generate(root, packages, modules_per_package, functions_per_module)` writes a
repo with packages, cross-module imports and calls, classes with methods,
routes, env reads, and tests. Same arguments always produce the same bytes.
"""

from __future__ import annotations

import random
from pathlib import Path


def _module_source(
    rng: random.Random, pkg: int, mod: int, n_funcs: int, n_pkgs: int, n_mods: int
) -> str:
    lines = [f'"""Package {pkg} module {mod}: synthetic business logic."""', "", "import os", ""]
    deps = set()
    for _ in range(3):
        dp, dm = rng.randrange(n_pkgs), rng.randrange(n_mods)
        if (dp, dm) != (pkg, mod) and (dp, dm) < (pkg, mod):
            deps.add((dp, dm))
    for dp, dm in sorted(deps):
        lines.append(f"from app.p{dp}.m{dm} import f{dp}_{dm}_0")
    lines += ["", ""]
    for i in range(n_funcs):
        name = f"f{pkg}_{mod}_{i}"
        lines.append(f"def {name}(value: int, factor: int = {i + 1}) -> int:")
        lines.append(f'    """Compute step {i} of pipeline {pkg}.{mod}."""')
        lines.append("    total = value * factor")
        for j in range(rng.randrange(3, 9)):
            lines.append(f"    if total % {j + 2} == 0:")
            lines.append(f"        total += {j}")
            lines.append("    else:")
            lines.append(f"        total -= {j}")
        if i > 0:
            lines.append(f"    total += f{pkg}_{mod}_{rng.randrange(i)}(value)")
        if deps and rng.random() < 0.3:
            dp, dm = sorted(deps)[rng.randrange(len(deps))]
            lines.append(f"    total += f{dp}_{dm}_0(total)")
        if rng.random() < 0.05:
            lines.append(f'    total += int(os.environ.get("SETTING_{pkg}_{mod}", "0"))')
        lines.append("    return total")
        lines += ["", ""]
    lines.append(f"class Service{pkg}_{mod}:")
    lines.append(f'    """Service wrapper for module {pkg}.{mod}."""')
    lines.append("")
    lines.append("    def __init__(self, base: int) -> None:")
    lines.append("        self.base = base")
    lines.append("")
    lines.append("    def run(self) -> int:")
    lines.append(f"        return f{pkg}_{mod}_0(self.base) + self.helper()")
    lines.append("")
    lines.append("    def helper(self) -> int:")
    lines.append("        return self.base * 2")
    return "\n".join(lines) + "\n"


def generate(
    root: Path, packages: int = 5, modules_per_package: int = 12, functions_per_module: int = 10
) -> int:
    """Write the repo and return its line count."""
    rng = random.Random(1234)
    total = 0
    (root / "app").mkdir(parents=True, exist_ok=True)
    (root / "app" / "__init__.py").write_text('"""Synthetic app."""\n', encoding="utf-8")
    (root / "tests").mkdir(exist_ok=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "synth"\nversion = "0"\ndependencies = ["flask"]\n', encoding="utf-8"
    )
    for p in range(packages):
        pkg_dir = root / "app" / f"p{p}"
        pkg_dir.mkdir(exist_ok=True)
        (pkg_dir / "__init__.py").write_text(f'"""Package {p}."""\n', encoding="utf-8")
        for m in range(modules_per_package):
            src = _module_source(rng, p, m, functions_per_module, packages, modules_per_package)
            (pkg_dir / f"m{m}.py").write_text(src, encoding="utf-8")
            total += src.count("\n")
        test = (
            f"from app.p{p}.m0 import f{p}_0_0\n\n\n"
            f"def test_p{p}() -> None:\n    assert f{p}_0_0(1) is not None\n"
        )
        (root / "tests" / f"test_p{p}.py").write_text(test, encoding="utf-8")
    routes = [
        "from flask import Flask",
        "",
        "from app.p0.m0 import f0_0_0",
        "",
        'app = Flask("synth")',
        "",
        "",
    ]
    for r in range(10):
        routes += [
            f'@app.get("/items/{r}")',
            f"def item_{r}() -> int:",
            "    return f0_0_0(1)",
            "",
            "",
        ]
    (root / "app" / "web.py").write_text("\n".join(routes), encoding="utf-8")
    return total


if __name__ == "__main__":  # pragma: no cover
    import sys

    out = Path(sys.argv[1])
    print(generate(out, *(int(a) for a in sys.argv[2:])))
