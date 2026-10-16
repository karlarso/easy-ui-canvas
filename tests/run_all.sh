#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Run every test; optional ones skip themselves when their dependencies are missing.
cd "$(dirname "$0")/.." || exit 1
status=0
run() { echo "== $*"; "$@" || status=1; }
run python3 tests/test_i18n.py
run python3 tests/test_server.py
run python3 tests/test_snapshots_api.py
if command -v node >/dev/null 2>&1; then run node tests/wheel_router.test.js; else echo "SKIP: node not found"; fi
if command -v node >/dev/null 2>&1; then run python3 tests/qr_verify.py; fi
run python3 tests/browser_smoke.py
exit $status
