<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2025 The Linux Foundation
-->

# 🐍 Python Project Dynamic Versioning

Detects whether a Python project uses dynamic versioning. The action
recognises signals across the full range of legacy and modern project
layouts:

- `pyproject.toml`:
  - `[project] dynamic = ["version"]`
  - `[build-system].requires` lists `setuptools_scm` / `setuptools-scm`,
    `hatch-vcs`, or `pbr`
- `setup.cfg`:
  - A `[pbr]` section
  - `[metadata] version = attr:` or `[metadata] version = file:`
    indirection
  - `[options] setup_requires` containing `pbr`, `setuptools_scm`,
    `setuptools-scm`, or `versioneer`
- `setup.py`:
  - `pbr=True` or `setup_requires=[..., 'pbr', ...]`
  - `use_scm_version=...` or `setup_requires` referencing
    `setuptools_scm` / `setuptools-scm`
  - `versioneer.get_version` / `versioneer.get_cmdclass`

## Usage Example

```yaml
- name: 'Check for dynamic project versioning'
  id: dyn
  uses: lfreleng-actions/python-dynamic-version-action@main

- name: 'Branch on the result'
  run: |
    echo "dynamic_version:  ${{ steps.dyn.outputs.dynamic_version }}"
    echo "dynamic_provider: ${{ steps.dyn.outputs.dynamic_provider }}"
    echo "source:           ${{ steps.dyn.outputs.source }}"
```

## Inputs

<!-- markdownlint-disable MD013 -->

| Input         | Required | Default | Description                           |
| ------------- | -------- | ------- | ------------------------------------- |
| `path_prefix` | False    | `.`     | Path/directory to Python project code |

<!-- markdownlint-enable MD013 -->

## Outputs

<!-- markdownlint-disable MD013 -->

| Output             | Description                                                                                                                                             |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `dynamic_version`  | `true` when the project uses dynamic versioning, `false` otherwise.                                                                                     |
| `dynamic_provider` | Identifier of the provider: `pbr` \| `setuptools-scm` \| `versioneer` \| `setuptools-dynamic` \| `hatch-vcs` \| `pyproject-dynamic`. Empty when static. |
| `source`           | Path to the file that supplied the dynamic-versioning signal. Empty when the project declares no dynamic-versioning signal.                             |

<!-- markdownlint-enable MD013 -->

## Implementation

The action delegates detection to `scripts/detect_dynamic_version.py`,
a small Python helper bundled with the action. The helper uses the
standard library's `tomllib` (Python 3.11+) / `tomli` (3.10 fallback)
for `pyproject.toml` and `configparser` for `setup.cfg`, and falls back
to regex for `setup.py`. The full unit-test suite lives under `tests/`.
