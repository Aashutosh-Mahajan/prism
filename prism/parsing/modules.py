"""Map repo-relative file paths to dotted module names."""

from __future__ import annotations

from collections.abc import Sequence

SOURCE_EXTENSIONS = (".pyi", ".py", ".tsx", ".ts", ".jsx", ".mjs", ".cjs", ".js", ".go", ".java")
# Files that stand for their directory, like Python's __init__.py.
PACKAGE_FILES = {"python": "__init__", "javascript": "index", "typescript": "index"}


def module_name(
    path: str, source_roots: Sequence[str] = ("src",), language: str = "python"
) -> tuple[str, bool]:
    """Return (module_name, is_package) for a source file path.

    `src/shop/pricing/__init__.py` -> ("shop.pricing", True) when "src" is a source root.
    `src/web/components/index.ts`  -> ("web.components", True)
    `internal/store/user.go`       -> ("internal.store.user", False)
    Java files get their module from the `package` declaration (see the Java parser).
    """
    rel = path
    for root in source_roots:
        prefix = root.strip("/") + "/"
        if rel.startswith(prefix):
            rel = rel[len(prefix) :]
            break
    for suffix in SOURCE_EXTENSIONS:
        if rel.endswith(suffix):
            rel = rel[: -len(suffix)]
            break
    parts = [p for p in rel.split("/") if p]
    if parts:
        parts[-1] = parts[-1].replace(".", "_")  # `cart.test` is one module, not two
    package_file = PACKAGE_FILES.get(language)
    is_package = bool(parts) and package_file is not None and parts[-1] == package_file
    if is_package:
        parts = parts[:-1]
    name = ".".join(parts) if parts else (package_file or "__init__")
    return name.replace("-", "_"), is_package
