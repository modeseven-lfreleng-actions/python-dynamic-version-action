#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation
"""Fixture-based tests for ``detect_dynamic_version.py``."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parent.parent / "scripts" / "detect_dynamic_version.py"
)


def _run(tmp_path: Path, files: dict[str, str]) -> tuple[int, dict[str, str], str, str]:
    """Materialise ``files`` under ``tmp_path`` and run the detector."""
    for name, content in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    github_output = tmp_path / ".github_output"
    github_output.write_text("", encoding="utf-8")

    env = os.environ.copy()
    env["GITHUB_OUTPUT"] = str(github_output)
    env["INPUT_PATH_PREFIX"] = str(tmp_path)

    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    outputs: dict[str, str] = {}
    for line in github_output.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            outputs[key] = value

    return proc.returncode, outputs, proc.stdout, proc.stderr


# -- pyproject.toml -----------------------------------------------------


def test_pyproject_static(tmp_path: Path) -> None:
    """Static-version pyproject.toml must report dynamic_version=false."""
    rc, out, _, _ = _run(
        tmp_path,
        {
            "pyproject.toml": ('[project]\nname = "static-pkg"\nversion = "1.0"\n'),
        },
    )
    assert rc == 0
    assert out["dynamic_version"] == "false"
    assert out["dynamic_provider"] == ""
    assert out["source"] == ""


def test_pyproject_dynamic_setuptools_scm(tmp_path: Path) -> None:
    """``dynamic=['version']`` with setuptools-scm build-system."""
    rc, out, _, _ = _run(
        tmp_path,
        {
            "pyproject.toml": (
                "[build-system]\n"
                'requires = ["setuptools>=61", "setuptools_scm>=6.0"]\n'
                "\n"
                "[project]\n"
                'name = "scm-pkg"\n'
                'dynamic = ["version"]\n'
            ),
        },
    )
    assert rc == 0
    assert out["dynamic_version"] == "true"
    assert out["dynamic_provider"] == "setuptools-scm"
    assert out["source"].endswith("pyproject.toml")


def test_pyproject_dynamic_hatch_vcs(tmp_path: Path) -> None:
    """``dynamic=['version']`` with hatch-vcs build-system."""
    rc, out, _, _ = _run(
        tmp_path,
        {
            "pyproject.toml": (
                "[build-system]\n"
                'requires = ["hatchling", "hatch-vcs"]\n'
                "\n"
                "[project]\n"
                'name = "hatch-pkg"\n'
                'dynamic = ["version"]\n'
            ),
        },
    )
    assert rc == 0
    assert out["dynamic_provider"] == "hatch-vcs"


def test_pyproject_dynamic_unattributed(tmp_path: Path) -> None:
    """``dynamic=['version']`` without an inferable provider."""
    rc, out, _, _ = _run(
        tmp_path,
        {
            "pyproject.toml": (
                '[project]\nname = "unknown-pkg"\ndynamic = ["version"]\n'
            ),
        },
    )
    assert rc == 0
    assert out["dynamic_version"] == "true"
    assert out["dynamic_provider"] == "pyproject-dynamic"


def test_pyproject_dynamic_string_form_is_not_dynamic(tmp_path: Path) -> None:
    """``dynamic = "version"`` (string, not list) is technically invalid;
    do not treat it as dynamic. Regression test against substring matching.
    """
    rc, out, _, _ = _run(
        tmp_path,
        {
            "pyproject.toml": ('[project]\nname = "weird-pkg"\ndynamic = "version"\n'),
        },
    )
    assert rc == 0
    assert out["dynamic_version"] == "false"


def test_pyproject_dynamic_only_name_not_version(tmp_path: Path) -> None:
    """``dynamic = ["name"]`` (no version) must not signal dynamic."""
    rc, out, _, _ = _run(
        tmp_path,
        {
            "pyproject.toml": (
                '[project]\nname = "name-only"\nversion = "1.0"\ndynamic = ["name"]\n'
            ),
        },
    )
    assert rc == 0
    assert out["dynamic_version"] == "false"


# -- pyproject.toml syntactic variants (regression coverage) -----------
#
# The original action.yaml carried ten case-by-case TOML syntactic
# variants in its testing workflow. Each one targeted a quirk of the
# previous regex-based detector; with tomllib doing the parsing they
# now all reduce to a single semantic question ("is 'version' in the
# project.dynamic list?"), but we preserve them as regression tests
# so the case coverage does not silently atrophy.


@pytest.mark.parametrize(
    "content,expected",
    [
        ('[project]\ndynamic = ["version"]\n', "true"),
        ("[project]\ndynamic=['version']\n", "true"),
        ("[project]\ndynamic = [ 'name', 'version' ]\n", "true"),
        ('[project]\ndynamic=["version","name",]\n', "true"),
        ('[project]\n   dynamic    =    ["version"]\n', "true"),
        ('[project]\ndynamic = ["name"]\n', "false"),
        ('[project]\n# dynamic = ["version"]\nversion = "1.0"\n', "false"),
        ("[project]\ndynamic = ['description','version','readme']\n", "true"),
        ('[project]\ndynamic = ["VERSION"]\nversion = "1.0"\n', "false"),
        ('[project]\ndynamic = "version"\n', "false"),
    ],
    ids=[
        "double-quoted",
        "single-quoted-compact",
        "spaced-mixed-items",
        "trailing-comma",
        "extra-whitespace",
        "name-only-not-version",
        "commented-out",
        "single-quoted-multiple",
        "uppercase-not-recognised",
        "string-not-list",
    ],
)
def test_pyproject_dynamic_syntactic_variants(
    tmp_path: Path, content: str, expected: str
) -> None:
    """Sweep the original action's case 1..10 regression matrix."""
    rc, out, _, _ = _run(tmp_path, {"pyproject.toml": content})
    assert rc == 0
    assert out["dynamic_version"] == expected


# -- setup.cfg ----------------------------------------------------------


def test_setup_cfg_static(tmp_path: Path) -> None:
    """A setup.cfg with a literal version must NOT report dynamic."""
    rc, out, _, _ = _run(
        tmp_path,
        {
            "setup.cfg": ("[metadata]\nname = static-cfg\nversion = 0.1.0\n"),
        },
    )
    assert rc == 0
    assert out["dynamic_version"] == "false"


def test_setup_cfg_attr_indirection(tmp_path: Path) -> None:
    """``version = attr:`` indicates dynamic versioning."""
    rc, out, _, _ = _run(
        tmp_path,
        {
            "setup.cfg": (
                "[metadata]\nname = attr-pkg\nversion = attr: attr_pkg.__version__\n"
            ),
        },
    )
    assert rc == 0
    assert out["dynamic_provider"] == "setuptools-dynamic"
    assert out["source"].endswith("setup.cfg")


def test_setup_cfg_file_indirection(tmp_path: Path) -> None:
    """``version = file:`` indicates dynamic versioning."""
    rc, out, _, _ = _run(
        tmp_path,
        {
            "setup.cfg": ("[metadata]\nname = file-pkg\nversion = file: VERSION\n"),
        },
    )
    assert rc == 0
    assert out["dynamic_provider"] == "setuptools-dynamic"


def test_setup_cfg_pbr_section(tmp_path: Path) -> None:
    """A standalone ``[pbr]`` section signals PBR dynamic versioning."""
    rc, out, _, _ = _run(
        tmp_path,
        {
            "setup.cfg": ("[metadata]\nname = pbr-pkg\n\n[pbr]\nwarnerrors = True\n"),
        },
    )
    assert rc == 0
    assert out["dynamic_provider"] == "pbr"


def test_setup_cfg_scm_in_setup_requires(tmp_path: Path) -> None:
    """``setup_requires`` containing setuptools_scm signals dynamic."""
    rc, out, _, _ = _run(
        tmp_path,
        {
            "setup.cfg": (
                "[metadata]\n"
                "name = scm-cfg-pkg\n"
                "\n"
                "[options]\n"
                "setup_requires =\n"
                "    setuptools_scm\n"
            ),
        },
    )
    assert rc == 0
    assert out["dynamic_provider"] == "setuptools-scm"


# -- setup.py -----------------------------------------------------------


def test_setup_py_static(tmp_path: Path) -> None:
    """Plain setup.py with a literal version is not dynamic."""
    rc, out, _, _ = _run(
        tmp_path,
        {
            "setup.py": (
                "from setuptools import setup\nsetup(name='p', version='1.0')\n"
            ),
        },
    )
    assert rc == 0
    assert out["dynamic_version"] == "false"


def test_setup_py_pbr_kwarg(tmp_path: Path) -> None:
    """``pbr=True`` signals PBR dynamic versioning."""
    rc, out, _, _ = _run(
        tmp_path,
        {
            "setup.py": (
                "from setuptools import setup\n"
                "setup(setup_requires=['pbr'], pbr=True)\n"
            ),
        },
    )
    assert rc == 0
    assert out["dynamic_provider"] == "pbr"
    assert out["source"].endswith("setup.py")


def test_setup_py_use_scm_version(tmp_path: Path) -> None:
    """``use_scm_version`` signals setuptools-scm."""
    rc, out, _, _ = _run(
        tmp_path,
        {
            "setup.py": (
                "from setuptools import setup\nsetup(name='p', use_scm_version=True)\n"
            ),
        },
    )
    assert rc == 0
    assert out["dynamic_provider"] == "setuptools-scm"


def test_setup_py_versioneer(tmp_path: Path) -> None:
    """``versioneer.get_version()`` signals versioneer."""
    rc, out, _, _ = _run(
        tmp_path,
        {
            "setup.py": (
                "import versioneer\n"
                "from setuptools import setup\n"
                "setup(name='p', version=versioneer.get_version())\n"
            ),
        },
    )
    assert rc == 0
    assert out["dynamic_provider"] == "versioneer"


# -- Copilot regression coverage ---------------------------------------


def test_pyproject_static_with_scm_in_build_requires(tmp_path: Path) -> None:
    """Static ``version = "1.0"`` with ``setuptools_scm`` in build-system
    requires MUST report as static (regression: build-system requires
    alone no longer imply dynamic versioning).
    """
    rc, out, _, _ = _run(
        tmp_path,
        {
            "pyproject.toml": (
                "[build-system]\n"
                'requires = ["setuptools>=61", "setuptools_scm>=6.0"]\n'
                "\n"
                "[project]\n"
                'name = "static-scm-leftover"\n'
                'version = "1.0"\n'
            ),
        },
    )
    assert rc == 0
    assert out["dynamic_version"] == "false"
    assert out["dynamic_provider"] == ""


def test_pyproject_static_with_pbr_and_hatch_in_build_requires(tmp_path: Path) -> None:
    """Same regression for ``pbr`` and ``hatch-vcs`` in build-system."""
    for requires in (
        '["hatchling", "hatch-vcs"]',
        '["setuptools", "pbr"]',
    ):
        rc, out, _, _ = _run(
            tmp_path,
            {
                "pyproject.toml": (
                    "[build-system]\n"
                    f"requires = {requires}\n"
                    "\n"
                    "[project]\n"
                    'name = "static-pkg"\n'
                    'version = "1.0"\n'
                ),
            },
        )
        assert rc == 0
        assert out["dynamic_version"] == "false", requires


def test_setup_cfg_libpbr_is_not_pbr(tmp_path: Path) -> None:
    """``setup_requires = libpbr`` must NOT match ``pbr`` (substring
    regression: PEP 503 name comparison only).
    """
    rc, out, _, _ = _run(
        tmp_path,
        {
            "setup.cfg": (
                "[metadata]\n"
                "name = libpbr-user\n"
                "version = 1.0\n"
                "\n"
                "[options]\n"
                "setup_requires =\n"
                "    libpbr\n"
            ),
        },
    )
    assert rc == 0
    assert out["dynamic_version"] == "false"


def test_setup_cfg_pbr_with_version_specifier(tmp_path: Path) -> None:
    """``setup_requires = pbr>=2`` SHOULD match ``pbr``."""
    rc, out, _, _ = _run(
        tmp_path,
        {
            "setup.cfg": (
                "[metadata]\n"
                "name = pbr-pinned\n"
                "\n"
                "[options]\n"
                "setup_requires =\n"
                "    pbr>=2.0\n"
            ),
        },
    )
    assert rc == 0
    assert out["dynamic_provider"] == "pbr"


def test_setup_cfg_comment_is_not_pbr(tmp_path: Path) -> None:
    """A ``# pbr is not used here`` comment line must NOT match pbr."""
    rc, out, _, _ = _run(
        tmp_path,
        {
            "setup.cfg": (
                "[metadata]\n"
                "name = pkg\n"
                "version = 1.0\n"
                "\n"
                "[options]\n"
                "setup_requires =\n"
                "    # pbr is not used here\n"
                "    wheel\n"
            ),
        },
    )
    assert rc == 0
    assert out["dynamic_version"] == "false"


def test_setup_py_docstring_mentioning_pbr(tmp_path: Path) -> None:
    """A docstring discussing ``pbr=True`` must NOT trip the detector."""
    rc, out, _, _ = _run(
        tmp_path,
        {
            "setup.py": (
                '"""This shim used pbr=True historically; '
                "use_scm_version was also tried. versioneer.get_version() "
                'was considered."""\n'
                "# pbr=True is deprecated\n"
                "from setuptools import setup\n"
                "setup(name='p', version='1.0')\n"
            ),
        },
    )
    assert rc == 0
    assert out["dynamic_version"] == "false", out


def test_setup_py_libpbr_in_setup_requires(tmp_path: Path) -> None:
    """``setup_requires=['libpbr']`` must NOT report pbr."""
    rc, out, _, _ = _run(
        tmp_path,
        {
            "setup.py": (
                "from setuptools import setup\n"
                "setup(name='p', version='1.0', setup_requires=['libpbr'])\n"
            ),
        },
    )
    assert rc == 0
    assert out["dynamic_version"] == "false"


def test_setup_py_malformed_syntax_falls_back(tmp_path: Path) -> None:
    """A setup.py with malformed syntax must not crash; the fallback
    tokenizer still rejects mentions inside comments / strings.
    """
    rc, out, _, _ = _run(
        tmp_path,
        {
            "setup.py": (
                "# stray syntax error follows\n"
                "from setuptools import setup\n"
                "setup(name='p' version='1.0')  # missing comma; "
                "# pbr=True only in comment\n"
            ),
        },
    )
    assert rc == 0
    # Must not crash and must not falsely report pbr from the comment.
    assert out["dynamic_version"] == "false"


def test_setup_py_pbr_via_attribute_call(tmp_path: Path) -> None:
    """``setuptools.setup(pbr=True)`` (attribute form) is recognised."""
    rc, out, _, _ = _run(
        tmp_path,
        {
            "setup.py": ("import setuptools\nsetuptools.setup(name='p', pbr=True)\n"),
        },
    )
    assert rc == 0
    assert out["dynamic_provider"] == "pbr"


# -- multi-file precedence ---------------------------------------------


def test_pyproject_precedence_over_setup_cfg(tmp_path: Path) -> None:
    """pyproject.toml signal beats setup.cfg signal."""
    rc, out, _, _ = _run(
        tmp_path,
        {
            "pyproject.toml": (
                "[build-system]\n"
                'requires = ["hatchling", "hatch-vcs"]\n'
                "\n"
                "[project]\n"
                'name = "p"\n'
                'dynamic = ["version"]\n'
            ),
            "setup.cfg": ("[metadata]\nname = p\n\n[pbr]\n"),
        },
    )
    assert rc == 0
    assert out["dynamic_provider"] == "hatch-vcs"
    assert out["source"].endswith("pyproject.toml")


def test_setup_cfg_fallback_to_setup_py(tmp_path: Path) -> None:
    """When setup.cfg signals nothing dynamic, fall through to setup.py.

    Canonical OpenStack PBR layout: declarative setup.cfg + minimal
    setup.py shim that carries the pbr=True marker.
    """
    rc, out, _, _ = _run(
        tmp_path,
        {
            "setup.cfg": ("[metadata]\nname = pbr-pkg\n"),
            "setup.py": (
                "from setuptools import setup\n"
                "setup(setup_requires=['pbr'], pbr=True)\n"
            ),
        },
    )
    assert rc == 0
    assert out["dynamic_provider"] == "pbr"
    assert out["source"].endswith("setup.py")


# -- error paths --------------------------------------------------------


def test_no_metadata_files(tmp_path: Path) -> None:
    """An empty project must report dynamic_version=false (not error)."""
    rc, out, _, _ = _run(tmp_path, {})
    assert rc == 0
    assert out["dynamic_version"] == "false"


def test_invalid_path_prefix(tmp_path: Path) -> None:
    """A non-existent path_prefix must fail cleanly."""
    env = os.environ.copy()
    env["INPUT_PATH_PREFIX"] = str(tmp_path / "missing")
    env["GITHUB_OUTPUT"] = str(tmp_path / "out")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode != 0
    assert "invalid path/prefix" in proc.stderr


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
