"""Independent small behavioural checks for the frozen T41 tasks.

The runner executes this file outside candidate workspaces. Django/DRF checks
load only function/class definitions with standard-library stubs, not settings,
databases, imports or arbitrary module-level executable statements.
"""

from __future__ import annotations
import __future__

import argparse
import ast
import re
import sys
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def pure_definitions(path: Path) -> dict[str, Any]:
    class ValidationError(Exception):
        pass

    namespace: dict[str, Any] = {
        "re": re,
        "date": date,
        "ValidationError": ValidationError,
        "_": lambda value: value,
        "BasePermission": object,
    }
    tree = ast.parse(path.read_text(encoding="utf-8"))
    body = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            body.append(node)
        elif isinstance(node, ast.Assign):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    namespace[target.id] = value
    module = ast.Module(body=body, type_ignores=[])
    exec(compile(module, str(path), "exec", flags=__future__.annotations.compiler_flag), namespace)
    return namespace


def check(root: Path, name: str) -> None:
    confirmation = {
        "filter_threshold",
        "find_pattern_limit",
        "file_size_default",
        "file_size_bool",
        "drift_bool",
        "find_constant_rename",
        "dedupe_constant_rename",
        "doctor_min_age",
        "doctor_max_age",
        "upload_size",
        "registration_length",
        "registration_type",
        "doctor_age_rename",
        "registration_rename",
    }
    if name in confirmation:
        check_confirmation(root, name)
        return
    if name == "registration_colon":
        namespace = pure_definitions(root / "backend/accounts/validators.py")
        validator = namespace["validate_medical_registration"]
        for value in ("AA:123", " aa:123 ", "AB-123", "AB/123", "AB1234", "A" * 20):
            validator(value)
        for value in ("AB:12", "A" * 21, "AA?123", "AA_123", "", "AA.123"):
            try:
                validator(value)
            except namespace["ValidationError"]:
                pass
            else:
                raise AssertionError(f"invalid identifier accepted: {value!r}")
    elif name == "owner_permission":
        permission = pure_definitions(root / "backend/accounts/permissions.py")["IsOwnerOrAdmin"]()

        def allowed(
            pk: int | None,
            owner: int | None,
            *,
            authenticated: bool = True,
            admin: bool = False,
            superuser: bool = False,
            custom: bool = False,
        ) -> bool:
            user = SimpleNamespace(
                pk=pk, is_authenticated=authenticated, is_admin=admin, is_superuser=superuser
            )
            view = SimpleNamespace(get_owner_id=lambda obj: owner) if custom else SimpleNamespace()
            obj = SimpleNamespace(user_id=owner, user=None)
            return bool(permission.has_object_permission(SimpleNamespace(user=user), view, obj))

        assert not allowed(None, None, authenticated=False)
        assert not allowed(None, None)
        assert not allowed(3, None)
        assert not allowed(3, 3, authenticated=False)
        assert not allowed(3, 4)
        assert not allowed(3, 4, authenticated=False, admin=True)
        assert allowed(3, 3)
        assert allowed(0, 0)
        assert allowed(0, 0, custom=True)
        assert allowed(3, 3, custom=True)
        assert allowed(3, 4, admin=True)
        assert allowed(3, 4, superuser=True)
    elif name == "upload_rename":
        for path in (root / "backend").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            assert not any(
                (isinstance(node, ast.Name) and node.id == "validate_medical_certificate")
                or (isinstance(node, ast.alias) and node.name == "validate_medical_certificate")
                or (
                    isinstance(node, ast.FunctionDef)
                    and node.name == "validate_medical_certificate"
                )
                for node in ast.walk(tree)
            ), path
        namespace = pure_definitions(root / "backend/accounts/validators.py")
        validator = namespace["validate_registration_upload"]
        for extension in ("PDF", "jpg", "jpeg", "png"):
            validator(SimpleNamespace(name=f"certificate.{extension}", size=10 * 1024 * 1024))
        for upload in (
            SimpleNamespace(name="certificate.exe", size=1),
            SimpleNamespace(name="certificate.pdf", size=10 * 1024 * 1024 + 1),
        ):
            try:
                validator(upload)
            except namespace["ValidationError"]:
                pass
            else:
                raise AssertionError("invalid upload accepted")
    elif name in {"slow_threshold", "prompt_constant"}:
        sys.path.insert(0, str(root))
        if name == "slow_threshold":
            from prism.navigator.test_timing import record_full_suite, slow_suite_warning

            with tempfile.TemporaryDirectory() as temp:
                fixture = Path(temp)
                record_full_suite(fixture, "pytest -q", 150)
                assert slow_suite_warning(fixture) is None
                record_full_suite(fixture, "pytest tests/unit -q", 500)
                assert slow_suite_warning(fixture) is None
                record_full_suite(fixture, "pytest -q", 181)
                assert "~3 min" in (slow_suite_warning(fixture) or "")
                record_full_suite(fixture, "pytest -q", 10)
                (fixture / "pyproject.toml").write_text(
                    "[tool.prism]\nslow_tests = true\n", encoding="utf-8"
                )
                assert "marked slow" in (slow_suite_warning(fixture) or "")
        else:
            for path in (root / "prism").rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                assert not any(
                    isinstance(node, ast.Name) and node.id == "MIN_WORDS" for node in ast.walk(tree)
                ), path
            from prism.hooks import prompt

            assert prompt.MIN_PROMPT_WORDS == 4
            assert prompt.should_retrieve("where is the discount calculated")
            assert not prompt.should_retrieve("thanks")
            assert not prompt.should_retrieve("/context")
    else:
        raise ValueError(f"unknown frozen checker: {name}")


def check_confirmation(root: Path, name: str) -> None:
    if name.startswith("doctor_") or name in {
        "upload_size",
        "registration_length",
        "registration_type",
        "registration_rename",
    }:
        namespace = pure_definitions(root / "backend/accounts/validators.py")
        if name in {"doctor_age_rename", "registration_rename"}:
            old, new = (
                ("validate_doctor_age", "validate_registration_age")
                if name == "doctor_age_rename"
                else ("validate_medical_registration", "validate_registration_identifier")
            )
            for path in (root / "backend").rglob("*.py"):
                assert not re.search(
                    r"\b" + re.escape(old) + r"\b", path.read_text(encoding="utf-8-sig")
                ), path
            assert new in namespace
            validator = namespace[new]
        else:
            validator = namespace[
                "validate_doctor_age"
                if name.startswith("doctor_")
                else "validate_medical_certificate"
                if name == "upload_size"
                else "validate_medical_registration"
            ]

        def rejected(value):
            try:
                validator(value)
            except namespace["ValidationError"]:
                return
            raise AssertionError("invalid value accepted")

        if name in {"doctor_min_age", "doctor_max_age", "doctor_age_rename"}:
            today = date.today()

            def birthday(age):
                try:
                    return today.replace(year=today.year - age)
                except ValueError:
                    return today.replace(year=today.year - age, day=28)

            minimum = 21 if name == "doctor_min_age" else 23
            maximum = 85 if name == "doctor_max_age" else 80
            validator(birthday(minimum))
            validator(birthday(maximum))
            rejected(birthday(minimum - 1))
            rejected(birthday(maximum + 1))
            rejected(birthday(-1))
        elif name == "upload_size":
            for extension in ("PDF", "jpg", "jpeg", "png"):
                validator(SimpleNamespace(name="upload." + extension, size=12 * 1024 * 1024))
            rejected(SimpleNamespace(name="upload.pdf", size=12 * 1024 * 1024 + 1))
            rejected(SimpleNamespace(name="upload.exe", size=1))
        else:
            maximum = 25 if name == "registration_length" else 20
            for value in ("AA-123", " aa/123 ", "A" * maximum):
                validator(value)
            for value in ("AA123", "A" * (maximum + 1), "AA_123", "AA:123", "AA?123"):
                rejected(value)
            if name == "registration_type":
                for value in (True, 123456, ["ABC123"], {"value": "ABC123"}):
                    rejected(value)
        return
    import site

    sys.path.append(site.getusersitepackages())  # packages only; do not execute site .pth files
    sys.path.insert(0, str(root))
    if name == "filter_threshold":
        from prism.outputfilter import filter_output

        text = "\n".join(["."] * 79) + "\n"
        assert filter_output("pytest -q", text).text == text
        assert filter_output("pytest -q", "\n".join(["."] * 80)).text != "\n".join(["."] * 80)
    elif name == "find_pattern_limit":
        from prism.core.errors import UserError
        from prism.navigator.find import run_find

        try:
            run_find(None, ["x"] * 7)
        except UserError as error:
            assert "6" in str(error)
        else:
            raise AssertionError("seven patterns accepted")
        try:
            run_find(None, ["x"] * 6)
        except UserError:
            raise AssertionError("six patterns rejected") from None
        except (AttributeError, TypeError):
            pass  # valid input progressed to store access
    elif name in {"file_size_default", "file_size_bool", "drift_bool"}:
        from prism.config import load_config
        from prism.core.errors import UserError

        with tempfile.TemporaryDirectory() as temp:
            fixture = Path(temp)
            if name == "file_size_default":
                assert load_config(fixture).max_file_size == 2_000_000
                (fixture / "prism.toml").write_text("max_file_size = 512\n", encoding="utf-8")
                assert load_config(fixture).max_file_size == 512
            else:
                key = "max_file_size" if name == "file_size_bool" else "drift_threshold"
                for value in ("true", "false", "0", "-1"):
                    (fixture / "prism.toml").write_text(f"{key} = {value}\n", encoding="utf-8")
                    try:
                        load_config(fixture)
                    except UserError:
                        pass
                    else:
                        raise AssertionError(f"invalid config accepted: {key}={value}")
                (fixture / "prism.toml").write_text(f"{key} = 10\n", encoding="utf-8")
                assert getattr(load_config(fixture), key) == 10
    else:
        old, new, value, module = (
            ("MAX_MATCHES_PER_PATTERN", "MATCH_LIMIT_PER_PATTERN", 400, "prism.navigator.find")
            if name == "find_constant_rename"
            else ("EXPIRY_SECONDS", "READ_EXPIRY_SECONDS", 1200, "prism.hooks.dedupe")
        )
        for path in (root / "prism").rglob("*.py"):
            assert not re.search(
                r"\b" + re.escape(old) + r"\b", path.read_text(encoding="utf-8")
            ), path
        import importlib

        assert getattr(importlib.import_module(module), new) == value


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("checker")
    args = parser.parse_args()
    check(args.root.resolve(), args.checker)
    print("Independent checks passed")
