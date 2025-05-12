<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2025 The Linux Foundation
-->

# 🐍 Python Project Dynamic Versioning

Checks dynamic versioning setup in the pyproject.toml file.

## python-dynamic-version-action

## Usage Example

```yaml
- name: 'Check for dynamic project versioning'
  uses: lfreleng-actions/python-dynamic-version-action@main
```

##  Inputs

<!-- markdownlint-disable MD013 -->

| Variable Name       | Required | Description                           |
| ------------------- | -------- | ------------------------------------- |
| path_prefix         | False    | Path/directory to Python project code |

## Outputs

<!-- markdownlint-disable MD013 -->

| Variable Name   | Description                              |
| --------------- | ---------------------------------------- |
| dynamic_version | Set true when dynamic versioning enabled |

<!-- markdownlint-enable MD013 -->
