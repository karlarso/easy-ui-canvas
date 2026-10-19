# Tests

```bash
sh tests/run_all.sh
```

| File | What it checks | Needs |
| --- | --- | --- |
| `test_i18n.py` | zh/en dictionary alignment, placeholders, used/unused keys, HTML fallbacks, no stray Chinese outside zh files | Python |
| `test_server.py` | real processes on free ports in a temporary runtime: loopback-only bind, Host guard, same-origin writes, language stored server-side and shared across ports, localized API errors/pages/CLI | Python |
| `test_snapshots_api.py` | read-only snapshot API, path safety, symlinks, writes rejected, `columns` / `groupColumns` validation | Python |
| `test_board_comments.py` | board-wide comments on the server: frame title / subtitle and group title bar targets (ids for repeated and odd group names), notes (`project.notes`) and their elements, the "Canvas" frame column in both languages, stored position, notes validation, annotated serving (live and snapshot), and that comments inside a phone and comments saved earlier keep their exact shape | Python |
| `test_gzip.py` | gzip for HTML / JS / CSS / JSON: `Accept-Encoding` parsing (q values, `*`, `q=0`), `Content-Encoding` / `Content-Length` / `Vary`, small bodies, images and error replies left as they are, `HEAD`, `Cache-Control: no-store` kept, the list service | Python |
| `wheel_router.test.js` | wheel round locking / panning rules (`<scroll-lock>` block of `canvas.js`) | Node.js |
| `tile_layout.test.js` | the tile layout function (`<tile-layout>` block of `canvas.js`): sections, per-section columns, `groupColumns`, equality with the old grid when no frame has a group | Node.js |
| `board_notes.test.js` | the notes helpers (`<board-notes>` block of `canvas.js`): which `project.notes` entries are kept, anchor and board coordinates, notes never move frames, the target ids of group title bars (same table as the Python test) | Node.js |
| `comment_click.test.js` | what the board's comment click does (`commentClickPlan` in the `<flow-core>` block of `canvas.js`): select vs jump in the tile view, the Flow view and history, an open comment box blocks clicks | Node.js |
| `lazy_frames.test.js` | the lazy-loading helpers (`<lazy-frames>` block of `canvas.js`): start camera (fit when it is at least 50%, else 50% from the top-left corner), which frames are near the view and in what order | Node.js |
| `qr_verify.py` (+ `qr_matrix.js`) | the QR encoder decodes correctly (versions 1–10) | Node.js, numpy, opencv-python, zxing-cpp, Pillow (optional; skips) |
| `browser_smoke.py` | headless browser: default language from `navigator.language`, switch on the list page reaches canvas/phone pages on other ports, no console errors; `--shots DIR` writes screenshots | playwright + Chrome/Chromium (optional; skips) |
| `browser_keep_scroll.py` | headless browser: `data-keep-scroll` carries the inner scroll position between frames of the same group (Flow view and `/m/`), unchanged defaults without it, "Back to start", content that grows late, resize, no console errors | playwright + Chrome/Chromium (optional; skips) |
| `browser_tile_layout.py` | headless browser: tile view sections (frame boxes from `group` runs, per-section columns / `groupColumns`, title bars, no bar without a group), a project without `group` keeps the old global grid exactly, minimap, Flow view, history, comment mode (Space types in the comment box even with the pointer over the canvas, and still holds the hand elsewhere), `/m/`, no console errors | playwright + Chrome/Chromium (optional; skips) |
| `browser_board_comments.py` | headless browser: frame title and subtitle, group title bars (also a group that comes back, a renamed group) and notes can be selected and commented, the layer picker's "Canvas" top layer, the frame column and stored position of canvas comments, panel / copy for AI / export / locate (scrolls a far-away bar into view and highlights it), element removed, comments saved earlier, history (read-only, notes shown), Flow view and `/m/` untouched, wheel / drag / Space / C / D unchanged, board and minimap cover the notes, a project without notes is unchanged | playwright + Chrome/Chromium (optional; skips) |
| `browser_flow_comments.py` | headless browser: comments in the Flow view (comment mode selects instead of jumping, off restores the jump, no "End of demo" in comment mode, the comment is stored for the frame on screen in the same shape as a tile comment, locating from the panel switches frame, history stays read-only, `/m/` stays a preview) | playwright + Chrome/Chromium (optional; skips) |
| `browser_lazy_frames.py` | headless browser: start zoom and position, resize keeps the camera, only frames near the view are fetched (nearest to the centre first, at most 5 at a time, shells at full size), panning / zooming loads more, `data-load` markers and `?load=all` / `uicLoadAllFrames()`, Flow view and deep links load their screen first and prefetch `data-goto` targets, comments on frames not loaded yet are not shown as removed, locate loads the frame, a history version with a missing frame file still opens, no console errors | playwright + Chrome/Chromium (optional; skips) |

Browser tests that need every frame on the board call `tests/lazy_helpers.py` (`show_all`: fit the window and load all frames).

Tests never touch `~/ui-canvas-runtime` and do not use the default ports.
