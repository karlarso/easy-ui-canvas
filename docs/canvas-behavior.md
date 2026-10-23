# Canvas behaviour

Reference for the interactions of the canvas page, in case you change or test them.

## Camera and scrolling

- Opening or closing side panels (comments etc.) never fits, zooms or pans the canvas; the camera only changes when the user chooses "Fit", zooms, pans or jumps to an element.
- **Wheel rounds.** Consecutive wheel events form a round; a pause longer than 180 ms ends it (trackpad inertia stays in the same round). If the pointer starts the round inside a design screen and that screen can scroll in that direction (judged from the overflow, scroll range and direction of its inner scroll containers, including the screen root, not from fixed class names), the whole round scrolls the screen only, and it does not pan the canvas even at the end of the scroll range (pause to start a new round). While locked, the screen gets a 2 px light-blue outline that fades 200 ms after the round. If it cannot scroll that way, or the round starts on blank space, the whole round pans the canvas. Holding Space while scrolling over a screen pans the canvas. Ctrl/⌘+wheel (and trackpad pinch) always zooms the canvas, regardless of the lock. The logic is the `<scroll-lock>` block of `assets/canvas.js` and is covered by `tests/wheel_router.test.js`.
- **Dragging.** Dragging inside a scrollable screen scrolls its content; anywhere else it pans the canvas. A one-finger touch on the tile view does the same thing as the mouse, and the page itself does not scroll or rubber-band (`touch-action: none` on the viewport and everything inside it, plus a non-passive `touchmove` `preventDefault`). Pointer capture and click suppression start after 3 px of movement, so a still click or tap still selects an element for commenting. The side panel and comment inputs keep normal text selection and editing. Flow view has no drag-to-pan; its narrow layout and the screen itself keep native touch scrolling.
- Ctrl/⌘ with +, −, 0 zooms the canvas only; the toolbar and comment box keep their size. Native browser zoom is left to the browser.
- The background is a flat colour: no dot grid, no anchor points, no comment number dots. Comments are tied to elements by internal ids; selecting from the side panel highlights the element temporarily.

## Tile layout

- One layout function (`tileLayout()` in `canvas.js`) produces the board size, every frame position and the minimap boxes, so they cannot differ. Frames are absolutely placed from it (CSS variables `--x` / `--y`); the board is no longer a CSS grid.
- Sections are consecutive runs of the same `group` in frame order. Each starts on a new row (72 px below the previous section) and has its own column count and column widths. A grouped section has a 36 px title bar as wide as the section; sections without `group` have no bar. Board width is the widest section.
- Columns per section: `groupColumns[<group>]`, else `columns`, else 3, never more than the frames in the section. Invalid entries fall back to `columns`.
- Without any `group` the result is the old single grid (same columns, sizes and positions). Flow view and `/m/` ignore sections (title bars are hidden, one frame at a time); history shows the snapshot's own `project.json`. Title bars can be selected and commented in the tile view (comments on them have the frame "Canvas"); in history they are read-only.

## Opening and lazy loading

- Start view: if "Fit window" would show the whole board at 50% or more, the board is fitted and centred (at most 100%). Otherwise the board opens at 50% with its top-left corner 28 px from the top-left of the viewport; "Fit window" in the zoom menu still fits everything. Resizing the window keeps the camera; only the minimap is redrawn.
- Every frame is laid out at once as a shell of its exact size (title, subtitle, phone box with a "Loading" placeholder), so the layout, the minimap and the scroll range never move when content arrives. The fragment of a frame is fetched only when the frame comes within half a screen of the viewport, nearest to the centre of the view first, at most 5 requests at a time; each frame is shown as soon as it arrives. Frames that have been shown are never unloaded.
- Each frame article has `data-load`: `idle`, `loading`, `loaded` or `error`. A frame that fails to load shows an error placeholder; the rest of the board (and a history version with a missing file) still works. Notes are fetched in parallel at start.
- Flow view loads the screen being opened first and, when the browser is idle, prefetches the `data-goto` targets of that screen. A deep link (`#view=flow&frame=…`) loads its screen before anything else.
- Comments: a comment on a frame that is not loaded yet is not marked "element removed"; the panel re-checks once frames arrive. "Locate" loads the frame first.
- Tests and scripts: `?load=all` in the page URL, or `await uicLoadAllFrames()` in the page, loads every frame. The helpers are the `<lazy-frames>` block of `assets/canvas.js` (`tests/lazy_frames.test.js`).

## Toolbar

- "Tile | Flow" switches the view (default Tile).
- Zoom: one dropdown between "−" and "+" shows the live zoom (`85% ▾`) with Fit window, 100%, Zoom in, Zoom out (×1.2 / ÷1.2). Esc or an outside click closes it.
- "History ▾" lists `snapshots/` (newest first, with time, frame count and comment count); picking one shows that revision read-only in the same page.
- "Shortcuts" opens a dialog (comment toggle, save/newline, pan/zoom, minimap). No permanent hint line; the canvas fills the space below the toolbar. The button sits left of "Add comment".
- "Canvas list" reads `list_port` from this canvas's `/healthz` and opens the list page on the same host in a new tab.
- "Mobile preview": a dialog with a QR code and the link (`location.origin + '/m/'`, with `?rev=` in history mode). The QR code is generated locally by the pure-JS encoder in `canvas.js` (byte mode, error correction M, versions 1–10; longer links show the link only). Copy uses `navigator.clipboard` and falls back to `execCommand('copy')` in insecure contexts.
- "Design notes": opens a read-only dialog with the canvas's `DESIGN.md` (project-format.md). The button is hidden when the canvas has no `DESIGN.md`. In history mode it shows the `DESIGN.md` kept in that snapshot and is hidden when the snapshot has none (`snapshot` keeps it; snapshots made before that have none). The content is rendered by a small built-in renderer (no library, no CDN): headings, paragraphs (a line break stays a line break), ordered / unordered and nested lists, tables, quotes, rules, fenced code, `**bold**`, `` `code` `` and `[text](http(s) or mailto link)`. Everything is HTML-escaped, so raw HTML is shown as text. Images are shown as plain text and never requested; relative and other links show their text only. Not on `/m/`. No shortcut key.
- "Export UI handoff": see the README.

## Flow view

One frame at a time inside the canvas. Desktop layout is left/right: the phone screen on the left (auto-scaled, never above 1×, always fully visible; when its content is taller than one screen only the inside scrolls) and the action/status area on the right ("Back" via the history stack, "Back to start" to `flow_start` or the first frame, current revision, page n of m, frame id with a "Copy frame reference" button, title and subtitle). Below 760 px canvas width it falls back to a vertical layout (phone at most 70% of the visible height). Buttons with `data-goto` jump; others show "End of demo". A jump starts the new frame at the top unless its scrolling element shares a `data-keep-scroll` group name with the frame being left, in which case the scroll position is carried over (see [project-format.md](project-format.md); also applies to `/m/`). No zoom/drag in the Flow view; switching back to Tile restores the camera exactly. **Comments work here too** (see Comments below): with comment mode on (`C` or "Add comment"), a click only selects the element and opens the comment box, it never jumps and never shows "End of demo"; turn comment mode off and clicks jump again. History versions opened in the Flow view stay read-only.

State is kept in the address-bar hash `#view=flow&frame=<frame id>&rev=<rN>` (written only in Flow view with `replaceState`, so no history entries; `rev` only in history mode). Reload returns to the same page and revision; invalid values fall back safely. The "Back" history does not survive a reload.

## Copy frame reference

A small icon button at the top right of every frame title bar (tile view; it appears while the pointer is over that frame or its title bar and on keyboard focus, and is always shown on touch screens / without hover) and a "Copy frame reference" button next to the frame id in the Flow view copy a short plain-text pointer to that frame, to paste into a chat or an AI conversation:

```
UI Canvas frame reference
Canvas: http://192.168.1.20:4846/ (canvas id: #12)
Snapshot: r61
Frame: goal-select (01 · Choose a goal)
Link: http://192.168.1.20:4846/#view=flow&frame=goal-select
```

- The page builds the text itself (`<frame-ref>` block of `canvas.js`, `tests/frame_ref.test.js`); there is no server endpoint and the text never contains a file path. The address is `location.origin` of the page being viewed, so it is whatever host the canvas was opened with. The canvas id comes from `/healthz` (`display_id` when present, otherwise `id`). A numbered canvas is shown as `#12`; the stored id and `/healthz` `id` stay `12`, because `#` is a URL fragment. A canvas created before numbering keeps its 6-character id in that line, with no hash. If the id is not known yet the line has no "(canvas id: …)".
- Snapshot: the revision being viewed. In a history version it is that rev; otherwise it is the newest snapshot in `GET /api/snapshots` (not the live `project.revision`, which may not have a snapshot yet). The list is fetched at start and refreshed when the page regains focus, when the History menu loads, when the pointer reaches a copy button and after each copy, so the copy itself never waits for the network. A canvas without snapshots gets no "Snapshot" line.
- The link opens the Flow view on that frame (see the hash above). Copied from the latest version it has no `&rev=`, so it opens the live canvas (the "Snapshot" line still says which snapshot it was); copied from a history version it ends with `&rev=<that rev>` and opens that snapshot read-only.
- The title bar button is a sibling of the frame title, not part of any comment target: comment mode never selects it and a click never shows the design hint. It is placed inside the 68 px title bar and the title keeps clear of it at every zoom. It is hidden with `opacity` (not `visibility`), so Tab still reaches it. The Flow view button is always visible.
- Clipboard: `navigator.clipboard` in a secure context (https, localhost); a canvas opened over LAN http falls back to a hidden textarea + `execCommand('copy')` (same helper as "Copy for AI"). A toast confirms the copy.
- Text in both languages (`c.ref.*` in `i18n.json`). Not on `/m/`, and the comment panel is unchanged.

## Comments

- "Add comment" (or `C`) enters continuous comment mode; after saving or cancelling you can keep picking elements. `D` toggles the "Design comments" panel; with the panel open, Shift+C returns to "All comments", selects every comment of the current revision and runs "Copy for AI". C, D and Shift+C are ignored while typing, during IME composition and while a dialog is open, and do not repeat on key hold. Esc closes only the current comment box.
- The new-comment popover is fixed to the top right of the canvas (not draggable) and avoids the open side panel. It is non-blocking: you can still pan with Space or the wheel without losing the draft. Space pans when focus is outside any input; inside the comment box (or any input) it always types a space.
- Enter saves, Shift+Enter inserts a newline (IME composition and held Enter do not submit). Saving refreshes the list and keeps the panel state and camera.
- The panel supports editing text, marking Pending / Changed / Needs discussion, filtering by status and deleting single comments.
- **Selectable range.** Elements inside a screen, the frame title and subtitle above it, the title bar of a group section, and the notes of the project (`project.notes`, see project-format.md) can all be selected. The layer picker lists the layers inside the screen for a screen element, and a disabled "Canvas" top layer over the group title bars, frame titles and notes (with their elements) for anything outside a screen; "Parent layer" walks up inside the same tree. A comment outside every screen has the frame "Canvas". The click position is stored relative to the screen (inside a phone, as before, not saved), the frame (title, subtitle) or the board (group bars, notes). A group bar has the target id `group~<group>~title` (a repeated group: `group~<group>~2~title`, ...); see project-format.md. Locating scrolls to the element like any other (a group bar included: it is centred in the visible canvas and highlighted for 3 seconds); a removed element keeps its comment and says so. In history and on `/m/` nothing outside a screen can be commented (history shows the snapshot's notes read-only, `/m/` never had them); the Flow view hides frame titles, group bars and notes, so there only elements inside the current screen can be picked.
- **Comments in the Flow view.** The comment is saved for the frame on screen (its `frame` / `frame_id`), in exactly the same format as a comment made in the tile view: no source label, no step, no stored position. Locating a comment from the panel while in the Flow view switches to the frame that comment belongs to and scrolls to the element; a target the Flow view does not show (frame title, group bar, note) says so and leaves the view alone. History versions stay read-only in the Flow view, and `/m/` is a read-only preview that cannot comment.
- Saved comments are data, not commands for an AI; nothing is sent automatically.
