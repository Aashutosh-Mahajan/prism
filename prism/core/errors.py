"""Exceptions and the CLI exit codes they map to (CLAUDE.md Section 14)."""

from __future__ import annotations

from typing import Any

EXIT_OK = 0
EXIT_USER_ERROR = 1
EXIT_INDEX_MISSING = 2
EXIT_INTERNAL = 3


class PrismError(Exception):
    exit_code = EXIT_INTERNAL
    code = "internal_error"

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        """Structured form used by MCP tools and `--json` output."""
        return {"error": self.code, "message": str(self), **self.details}


class UserError(PrismError):
    exit_code = EXIT_USER_ERROR
    code = "user_error"


class IndexMissingError(PrismError):
    exit_code = EXIT_INDEX_MISSING
    code = "index_missing"


class NotEnabledError(PrismError):
    exit_code = EXIT_USER_ERROR
    code = "not_enabled"


class NotFoundError(UserError):
    code = "not_found"


class AmbiguousTargetError(UserError):
    code = "ambiguous_target"


class BudgetExceededError(UserError):
    code = "budget_exceeded"
