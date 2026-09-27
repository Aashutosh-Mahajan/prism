"""Language detection by extension, falling back to the shebang line."""

from __future__ import annotations

EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".swift": "swift",
    ".scala": "scala",
    ".sh": "shell",
    ".bash": "shell",
    ".sql": "sql",
}

SHEBANGS: dict[str, str] = {
    "python": "python",
    "node": "javascript",
    "bash": "shell",
    "sh": "shell",
    "ruby": "ruby",
}


def detect_language(path: str, first_line: str | None = None) -> str | None:
    """Return a language name, or None if the file is not source code PRISM tracks."""
    dot = path.rfind(".")
    slash = path.rfind("/")
    if dot > slash:
        return EXTENSIONS.get(path[dot:].lower())
    if first_line and first_line.startswith("#!"):
        parts = first_line[2:].strip().split()
        if not parts:
            return None
        interpreter = parts[0].rsplit("/", 1)[-1]
        if interpreter == "env" and len(parts) > 1:
            interpreter = parts[1]
        for prefix, language in SHEBANGS.items():
            if interpreter.startswith(prefix):
                return language
    return None
