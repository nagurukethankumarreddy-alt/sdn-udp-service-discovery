#!/usr/bin/env bash
# Prepare an isolated Python 3.11 environment for the legacy Ryu controller.
# Run from the project root, with the project's current .venv activated.
set -euo pipefail

if [[ ! -f controller/sdn_controller.py ]]; then
  echo "ERROR: Run this script from the project root (the folder containing controller/)." >&2
  exit 2
fi

# Use a small bootstrap venv so the script works in a freshly extracted folder
# and never writes packages into Ubuntu's system Python.
if [[ ! -x .bootstrap/bin/python ]]; then
  python3 -m venv .bootstrap
fi
.bootstrap/bin/python -m pip install --upgrade pip uv
.bootstrap/bin/uv python install 3.11
.bootstrap/bin/uv venv --python 3.11 .venv311

# Ryu's setup.py relies on an API removed from newer setuptools. Disable pip's
# isolated build environment so the pinned setuptools version is actually used.
.venv311/bin/python -m pip install --upgrade pip
.venv311/bin/python -m pip install 'setuptools==58.0.4' wheel pbr
.venv311/bin/python -m pip install --no-build-isolation ryu

.venv311/bin/python - <<'PY'
import sys
import ryu
print('Python:', sys.version)
print('Ryu import: OK')
PY
.venv311/bin/ryu-manager --version
printf '\nSetup completed. Start the controller with:\n'
printf '  .venv311/bin/ryu-manager --verbose controller/sdn_controller.py\n'
