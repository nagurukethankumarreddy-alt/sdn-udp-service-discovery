#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m compileall -q app controller integration topology tests
python3 tests/test_local_stack.py
python3 tests/test_selection.py
python3 tests/test_failover_local.py
python3 tests/test_dashboard_lifecycle.py
