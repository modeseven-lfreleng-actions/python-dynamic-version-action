#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation
"""Detect whether a Python project uses dynamic versioning.

A project is considered to use dynamic versioning when ANY of the
following signals is present:

* ``pyproject.toml`` declares ``dynamic = ["version"]`` under ``[project]``
  (the provider is then inferred from ``[build-system].requires`` when
  one of ``setuptools_scm`` / ``setuptools-scm``, ``hatch-vcs``, or
  ``pbr`` is present; otherwise ``pyproject-dynamic`` is reported).
* ``setup.cfg`` has a ``[pbr]`` section, or a ``[metadata] version``
  field starting with ``attr:`` or ``file:``, or ``[options] setup_requires``
  contains ``pbr`` / ``setuptools_scm`` / ``versioneer``.
* ``setup.py`` contains ``pbr=True``, ``setup_requires=[..., 'pbr', ...]``,
  ``use_scm_version``, a ``setup_requires`` entry referencing
  ``setuptools_scm`` / ``setuptools-scm``, or a ``versioneer.get_version`` /
  ``get_cmdclass`` call.

Outputs to ``$GITHUB_OUTPUT`` (or stdout when running stand-alone):

* ``dynamic_version`` -- ``true`` or ``false``.
* ``dynamic_provider`` -- when ``dynamic_version`` is ``true``: ``pbr`` |
  ``setuptools-scm`` | ``versioneer`` | ``setuptools-dynamic`` |
  ``hatch-vcs`` | ``pyproject-dynamic``. Empty otherwise.
* ``source`` -- path to the file that supplied the dynamic-versioning
  signal. Empty when no signal was found.
"""

from __future__ import annotations

import argparse
import ast
import configparser
import io
import os
import re
import sys
import tokenize
from pathlib import Path

try:  # pragma: no cover - exercised on Python >= 3.11
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib  # type: ignore[import-not-found,no-redef]


_PBR_IN_SETUP_REQUIRES = re.compile(
    r"setup_requires\s*=\s*\[[^\]]*['\"]pbr['\"]",
    re.IGNORECASE,
)
_SCM_IN_SETUP_REQUIRES = re.compile(
    r"setup_requires\s*=\s*\[[^\]]*['\"]setuptools[_-]scm['\"]",
    re.IGNORECASE,
)
_VERSIONEER_IN_SETUP_REQUIRES = re.compile(
    r"setup_requires\s*=\s*\[[^\]]*['\"]versioneer['\"]",
    re.IGNORECASE,
)
_PBR_KWARG = re.compile(r"\bpbr\s*=\s*True\b", re.IGNORECASE)

# PEP 508 separators that terminate a distribution name.
_REQ_NAME_RE = re.compile(r"^([A-Za-z0-9_.\-]+)")


def _requirement_name(raw: str) -> str:
    """Return the normalised (PEP 503) distribution name of ``raw``.

    Strips ``#`` comments and whitespace, then extracts the leading
    PEP 508 name and lowercases / underscore-to-hyphen normalises it.
    Returns an empty string when no name can be parsed.
    """
    text = raw.split("#", 1)[0].strip()
    if not text:
        return ""
    match = _REQ_NAME_RE.match(text)
    if not match:
        return ""
    return match.group(1).lower().replace("_", "-")


def detect_from_pyproject(path: Path) -> str:
    """Return the dynamic-versioning provider implied by pyproject.toml,
    or empty string when the project's version is static.
    """
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except Exception:
        return ""

    project = data.get("project") or {}
    dynamic_fields = project.get("dynamic") or []
    requires = data.get("build-system", {}).get("requires", []) or []
    requirement_names = {_requirement_name(str(r)) for r in requires}
    requirement_names.discard("")

    # Robust against the (technically invalid) ``dynamic = "version"``
    # string form: only a list of strings is honoured.
    has_dynamic_version = (
        isinstance(dynamic_fields, list) and "version" in dynamic_fields
    )

    # Provider inference is gated on ``[project].dynamic`` actually
    # listing ``"version"``. A static ``version = "1.0"`` paired with,
    # say, ``setuptools_scm`` in build-system requires (leftover from a
    # refactor, or used for unrelated tooling) MUST report as static.
    if not has_dynamic_version:
        return ""

    if {"setuptools-scm"} & requirement_names:
        return "setuptools-scm"
    if "hatch-vcs" in requirement_names:
        return "hatch-vcs"
    if "pbr" in requirement_names:
        return "pbr"
    return "pyproject-dynamic"


def detect_from_setup_cfg(path: Path) -> str:
    """Return the dynamic-versioning provider implied by setup.cfg, or
    empty string when the version field is static (or absent).
    """
    cfg = configparser.ConfigParser(
        interpolation=None,
        strict=False,
        empty_lines_in_values=False,
    )
    try:
        cfg.read(path, encoding="utf-8")
    except configparser.Error:
        return ""

    if cfg.has_section("pbr"):
        return "pbr"

    if cfg.has_option("metadata", "version"):
        version = cfg.get("metadata", "version").strip()
        if version.startswith("attr:") or version.startswith("file:"):
            return "setuptools-dynamic"

    if cfg.has_option("options", "setup_requires"):
        for line in cfg.get("options", "setup_requires").splitlines():
            name = _requirement_name(line)
            if not name:
                continue
            if name == "pbr":
                return "pbr"
            if name == "setuptools-scm":
                return "setuptools-scm"
            if name == "versioneer":
                return "versioneer"

    return ""


def _is_setup_call(node: ast.AST) -> bool:
    """Return True when ``node`` is a call to ``setup(...)``."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name) and func.id == "setup":
        return True
    if isinstance(func, ast.Attribute) and func.attr == "setup":
        return True
    return False


def _setup_requires_provider(value: ast.AST) -> str:
    """Inspect a ``setup_requires=`` AST value for known providers."""
    if not isinstance(value, (ast.List, ast.Tuple, ast.Set)):
        return ""
    for element in value.elts:
        if not isinstance(element, ast.Constant):
            continue
        if not isinstance(element.value, str):
            continue
        name = _requirement_name(element.value)
        if name == "pbr":
            return "pbr"
        if name == "setuptools-scm":
            return "setuptools-scm"
        if name == "versioneer":
            return "versioneer"
    return ""


def _detect_from_setup_py_ast(tree: ast.AST) -> str:
    """AST-based provider detection for a parsed setup.py module."""
    setup_provider = ""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_setup_call(node):
            continue
        for keyword in node.keywords:
            if keyword.arg == "pbr":
                val = keyword.value
                if isinstance(val, ast.Constant) and val.value is True:
                    return "pbr"
            elif keyword.arg == "use_scm_version":
                # Any non-False, non-None value indicates SCM in use.
                val = keyword.value
                if isinstance(val, ast.Constant) and val.value in (False, None):
                    continue
                setup_provider = setup_provider or "setuptools-scm"
            elif keyword.arg == "setup_requires":
                provider = _setup_requires_provider(keyword.value)
                if provider:
                    setup_provider = setup_provider or provider
            elif keyword.arg == "version":
                # ``version=versioneer.get_version()`` clinches versioneer.
                val = keyword.value
                if isinstance(val, ast.Call):
                    func = val.func
                    if (
                        isinstance(func, ast.Attribute)
                        and isinstance(func.value, ast.Name)
                        and func.value.id == "versioneer"
                        and func.attr in {"get_version", "get_cmdclass"}
                    ):
                        return "versioneer"
    if setup_provider:
        return setup_provider

    # Module-level versioneer.get_version() / get_cmdclass() calls.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "versioneer"
            and func.attr in {"get_version", "get_cmdclass"}
        ):
            return "versioneer"
    return ""


def _strip_py_comments_and_strings(text: str) -> str:
    """Remove ``#`` comments and string literals from ``text``.

    Used as a fallback when ``ast.parse`` fails (e.g. Python 2 syntax
    or syntax errors). Robust enough to avoid the obvious false
    positives from docstrings / commented-out code.
    """
    out: list[str] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        for tok in tokens:
            tok_type = tok.type
            if tok_type in (tokenize.COMMENT, tokenize.STRING):
                continue
            if tok_type in (
                tokenize.NL,
                tokenize.NEWLINE,
                tokenize.INDENT,
                tokenize.DEDENT,
                tokenize.ENCODING,
                tokenize.ENDMARKER,
            ):
                out.append("\n" if tok_type in (tokenize.NL, tokenize.NEWLINE) else "")
                continue
            out.append(tok.string)
            out.append(" ")
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # Last-ditch: strip line comments only.
        return "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    return "".join(out)


def detect_from_setup_py(path: Path) -> str:
    """Return the dynamic-versioning provider implied by setup.py, or
    empty string when no dynamic-versioning marker is present.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""

    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        # Fallback: strip comments / strings, then run the original
        # regex-based heuristics. Suppresses false positives from
        # docstrings and commented-out code without losing coverage
        # for Python 2 era setup.py shims that ``ast`` cannot parse.
        sanitised = _strip_py_comments_and_strings(text)
        if _PBR_KWARG.search(sanitised) or _PBR_IN_SETUP_REQUIRES.search(sanitised):
            return "pbr"
        if "use_scm_version" in sanitised or _SCM_IN_SETUP_REQUIRES.search(sanitised):
            return "setuptools-scm"
        if (
            "versioneer.get_version" in sanitised
            or "versioneer.get_cmdclass" in sanitised
            or _VERSIONEER_IN_SETUP_REQUIRES.search(sanitised)
        ):
            return "versioneer"
        return ""

    return _detect_from_setup_py_ast(tree)


def emit(outputs: dict[str, str]) -> None:
    """Write ``key=value`` lines to ``$GITHUB_OUTPUT`` (or stdout)."""
    target = os.environ.get("GITHUB_OUTPUT")
    handle = open(target, "a", encoding="utf-8") if target else sys.stdout
    try:
        for key, value in outputs.items():
            print(f"{key}={value}", file=handle)
    finally:
        if target:
            handle.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--path-prefix",
        default=os.environ.get("INPUT_PATH_PREFIX", "."),
        help="Directory containing the project metadata files.",
    )
    args = parser.parse_args(argv)

    prefix = Path(args.path_prefix)
    if not prefix.is_dir():
        print(
            f"Error: invalid path/prefix to project directory: {prefix}",
            file=sys.stderr,
        )
        return 1

    pyproject = prefix / "pyproject.toml"
    setup_cfg = prefix / "setup.cfg"
    setup_py = prefix / "setup.py"

    provider = ""
    source = ""

    if pyproject.is_file():
        provider = detect_from_pyproject(pyproject)
        if provider:
            source = str(pyproject)

    if not provider and setup_cfg.is_file():
        provider = detect_from_setup_cfg(setup_cfg)
        if provider:
            source = str(setup_cfg)

    if not provider and setup_py.is_file():
        provider = detect_from_setup_py(setup_py)
        if provider:
            source = str(setup_py)

    if provider:
        print(f"Dynamic versioning configured ({provider}) [{source}] ✅")
        emit(
            {
                "dynamic_version": "true",
                "dynamic_provider": provider,
                "source": source,
            }
        )
    else:
        print("Dynamic versioning is NOT configured 💬")
        emit(
            {
                "dynamic_version": "false",
                "dynamic_provider": "",
                "source": "",
            }
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
