# Canvas behaviour

Reference for the interactions of the canvas page, in case you change or test them.

## Camera and scrolling

- Opening or closing side panels (comments etc.) never fits, zooms or pans the canvas; the camera only changes when the user chooses "Fit", zooms, pans or jumps to an element.
- **Wheel rounds.** Consecutive wheel events form a round; a pause longer than 180 ms ends it (trackpad inertia stays in the same round). If the pointer starts the round inside a design screen and that screen can scroll in that direction (judged from the overflow, scroll range and direction of its inner scroll containers, including the screen root, not from fixed class names), the whole round scrolls the screen only, and it does not pan the canvas even at the end of the scroll range (pause to start a new round). While locked, the screen gets a 2 px light-blue outline that fades 200 ms after the round. If it cannot scroll that way, or the round starts on blank space, the whole round pans the canvas. Holding Space while scrolling over a screen pans the canvas. Ctrl/⌘+wheel (and trackpad pinch) always zooms the canvas, regardless of the lock. The logic is the `<scroll-lock>` block of `assets/canvas.js` and is covered by `tests/wheel_router.test.js`.
- **Dragging.** Dragging inside a scrollable screen scrolls its content; anywhere else it pans the canvas. Pointer capture and click suppression start after 3 px of movement, so a still click still selects an element for commenting. The side panel and comment inputs keep normal text selection and editing.
- Ctrl/⌘ with +, −, 0 zooms the canvas only; the toolbar and comment box keep their size. Native browser zoom is left to the browser.
- The background is a flat colour: no dot grid, no anchor points, no comment number dots. Comments are tied to elements by internal ids; selecting from the side panel highlights the element temporarily.

## Tile layout

- One layout function (`tileLayout()` in `canvas.js`) produces the board size, every frame position and the minimap boxes, so they cannot differ. Frames are absolutely placed from it (CSS variables `--x` / `--y`); the board is no longer a CSS grid.
- Sections are consecutive runs of the same `group` in frame order. Each starts on a new row (72 px below the previous section) and has its own column count and column widths. A grouped section has a 36 px title bar as wide as the section; sections without `group` have no bar. Board width is the widest section.
- Columns per section: `groupColumns[<group>]`, else `columns`, else 3, never more than the frames in the section. Invalid entries fall back to `columns`.
- Without any `group` the result is the old single grid (same columns, sizes and positions). Flow view and `/m/` ignore sections (title bars are hidden, one frame at a time); history shows the snapshot's own `project.json`.

## Toolbar

- "Tile | Flow" switches the view (default Tile).
- Zoom: one dropdown between "−" and "+" shows the live zoom (`85% ▾`) with Fit window, 100%, Zoom in, Zoom out (×1.2 / ÷1.2). Esc or an outside click closes it.
- "History ▾" lists `snapshots/` (newest first, with time, frame count and comment count); picking one shows that revision read-only in the same page.
- "Shortcuts" opens a dialog (comment toggle, save/newline, pan/zoom, minimap). No permanent hint line; the canvas fills the space below the toolbar. The button sits left of "Add comment".
- "Canvas list" reads `list_port` from this canvas's `/healthz` and opens the list page on the same host in a new tab.
- "Mobile preview": a dialog with a QR code and the link (`location.origin + '/m/'`, with `?rev=` in history mode). The QR code is generated locally by the pure-JS encoder in `canvas.js` (byte mode, error correction M, versions 1–10; longer links show the link only). Copy uses `navigator.clipboard` and falls back to `execCommand('copy')` in insecure contexts.
- "Export UI handoff": see the README.

## Flow view

One frame at a time inside the canvas. Desktop layout is left/right: the phone screen on the left (auto-scaled, never above 1×, always fully visible; when its content is taller than one screen only the inside scrolls) and the action/status area on the right ("Back" via the history stack, "Back to start" to `flow_start` or the first frame, current revision, page n of m, frame id, title and subtitle). Below 760 px canvas width it falls back to a vertical layout (phone at most 70% of the visible height). Buttons with `data-goto` jump; others show "End of demo". A jump starts the new frame at the top unless its scrolling element shares a `data-keep-scroll` group name with the frame being left, in which case the scroll position is carried over (see [project-format.md](project-format.md); also applies to `/m/`). The Flow view is read-only (no comments, no snapshots, no zoom/drag); switching back to Tile restores the camera exactly.

State is kept in the address-bar hash `#view=flow&frame=<frame id>&rev=<rN>` (written only in Flow view with `replaceState`, so no history entries; `rev` only in history mode). Reload returns to the same page and revision; invalid values fall back safely. The "Back" history does not survive a reload.

## Comments

- "Add comment" (or `C`) enters continuous comment mode; after saving or cancelling you can keep picking elements. `D` toggles the "Design comments" panel; with the panel open, Shift+C returns to "All comments", selects every comment of the current revision and runs "Copy for AI". C, D and Shift+C are ignored while typing, during IME composition and while a dialog is open, and do not repeat on key hold. Esc closes only the current comment box.
- The new-comment popover is fixed to the top right of the canvas (not draggable) and avoids the open side panel. It is non-blocking: you can still pan with Space or the wheel without losing the draft. Space pans when focus is outside any input; inside the comment box (or any input) it always types a space.
- Enter saves, Shift+Enter inserts a newline (IME composition and held Enter do not submit). Saving refreshes the list and keeps the panel state and camera.
- The panel supports editing text, marking Pending / Changed / Needs discussion, filtering by status and deleting single comments.
- **Selectable range.** Elements inside a screen, the frame title and subtitle above it, and the notes of the project (`project.notes`, see project-format.md) can all be selected. The layer picker lists the layers inside the screen for a screen element, and a disabled "Canvas" top layer over the titles and notes (with their elements) for anything outside a screen; "Parent layer" walks up inside the same tree. A comment outside every screen has the frame "Canvas". The click position is stored relative to the screen (inside a phone, as before, not saved), the frame (title, subtitle) or the board (notes). Locating pans to the element like any other; a removed element keeps its comment and says so. In history, in the Flow view and on `/m/` nothing outside a screen can be commented (history shows the snapshot's notes read-only, the Flow view hides them, `/m/` never had them).
- Saved comments are data, not commands for an AI; nothing is sent automatically.
