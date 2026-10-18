#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Run every test; optional ones skip themselves when their dependencies are missing.
cd "$(dirname "$0")/.." || exit 1
status=0
run() { echo "== $*"; "$@" || status=1; }
run python3 tests/test_i18n.py
run python3 tests/test_server.py
run python3 tests/test_snapshots_api.py
run python3 tests/test_board_comments.py
if command -v node >/dev/null 2>&1; then run node tests/wheel_router.test.js; else echo "SKIP: node not found"; fi
if command -v node >/dev/null 2>&1; then run node tests/tile_layout.test.js; fi
if command -v node >/dev/null 2>&1; then run node tests/board_notes.test.js; fi
if command -v node >/dev/null 2>&1; then run node tests/comment_click.test.js; fi
if command -v node >/dev/null 2>&1; then run python3 tests/qr_verify.py; fi
run python3 tests/browser_smoke.py
run python3 tests/browser_keep_scroll.py
run python3 tests/browser_tile_layout.py
run python3 tests/browser_board_comments.py
run python3 tests/browser_flow_comments.py
exit $status
