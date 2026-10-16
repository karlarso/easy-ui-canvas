# Tests

```bash
sh tests/run_all.sh
```

| File | What it checks | Needs |
| --- | --- | --- |
| `test_i18n.py` | zh/en dictionary alignment, placeholders, used/unused keys, HTML fallbacks, no stray Chinese outside zh files | Python |
| `test_server.py` | real processes on free ports in a temporary runtime: loopback-only bind, Host guard, same-origin writes, language stored server-side and shared across ports, localized API errors/pages/CLI | Python |
| `test_snapshots_api.py` | read-only snapshot API, path safety, symlinks, writes rejected | Python |
| `wheel_router.test.js` | wheel round locking / panning rules (`<scroll-lock>` block of `canvas.js`) | Node.js |
| `qr_verify.py` (+ `qr_matrix.js`) | the QR encoder decodes correctly (versions 1–10) | Node.js, numpy, opencv-python, zxing-cpp, Pillow (optional; skips) |
| `browser_smoke.py` | headless browser: default language from `navigator.language`, switch on the list page reaches canvas/phone pages on other ports, no console errors; `--shots DIR` writes screenshots | playwright + Chrome/Chromium (optional; skips) |

Tests never touch `~/ui-canvas-runtime` and do not use the default ports.
