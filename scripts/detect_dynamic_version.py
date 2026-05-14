#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation
"""Detect whether a Python project uses dynamic versioning.

A project is considered to use dynamic versioning when ANY of the
following signals is present:

* ``pyproject.toml`` declares ``dynamic = ["version"]`` under ``[project]``.
* ``pyproject.toml`` ``[build-system].requires`` lists a known dynamic
  versioning provider (``setuptools_scm`` / ``setuptools-scm``,
  ``hatch-vcs``, ``pbr``).
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
import configparser
import os
import re
import sys
from pathlib import Path

try:  # pragma: no cover - exercised on Python >= 3.11
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib  # type: ignore[import-not-found,no-redef]


_PBR_IN_SETUP_REQUIRES = re.compile(
    r"setup_requires\s*=\s*\[[^\]]*['\"]pbr",
    re.IGNORECASE,
)
_SCM_IN_SETUP_REQUIRES = re.compile(
    r"setup_requires\s*=\s*\[[^\]]*['\"]setuptools[_-]scm",
    re.IGNORECASE,
)
_PBR_KWARG = re.compile(r"\bpbr\s*=\s*True\b", re.IGNORECASE)


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
    joined = " ".join(str(r) for r in requires).lower()

    # Robust against the (technically invalid) ``dynamic = "version"``
    # string form: only a list of strings is honoured.
    has_dynamic_version = (
        isinstance(dynamic_fields, list) and "version" in dynamic_fields
    )

    # Provider inference from build-system.requires, even when [project]
    # declares no dynamic version explicitly (occasional Hatch / SCM
    # layouts rely solely on the build-system marker).
    if "setuptools_scm" in joined or "setuptools-scm" in joined:
        return "setuptools-scm"
    if "hatch-vcs" in joined:
        return "hatch-vcs"
    if "pbr" in joined:
        return "pbr"
    if has_dynamic_version:
        return "pyproject-dynamic"
    return ""


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
            line = line.strip().lower()
            if not line:
                continue
            if "pbr" in line:
                return "pbr"
            if "setuptools_scm" in line or "setuptools-scm" in line:
                return "setuptools-scm"
            if "versioneer" in line:
                return "versioneer"

    return ""


def detect_from_setup_py(path: Path) -> str:
    """Return the dynamic-versioning provider implied by setup.py, or
    empty string when no dynamic-versioning marker is present.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""

    if _PBR_KWARG.search(text) or _PBR_IN_SETUP_REQUIRES.search(text):
        return "pbr"
    if "use_scm_version" in text or _SCM_IN_SETUP_REQUIRES.search(text):
        return "setuptools-scm"
    if "versioneer.get_version" in text or "versioneer.get_cmdclass" in text:
        return "versioneer"
    return ""


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
