# Project format and element protocol

## Runtime layout

One fixed runtime directory, `~/ui-canvas-runtime/` (override with `UI_CANVAS_RUNTIME`):

```text
~/ui-canvas-runtime/
  app/                     synced copy of scripts/, assets/, examples/ (+ VERSION = content hash); background processes run from here
  config/lang.json         UI language shared by every process (see i18n.md)
  run/                     list.lock, create.lock, canvas.seq.lock, canvas.seq (last canvas number issued here)
  logs/list.log            list service log
  canvases/<port>-<id>/    one directory per canvas. <id> is a decimal number (1, 2, 3, …) or a legacy 6-character id. The name never contains '#'. Pattern: ^\d{2,5}-([1-9]\d*|[a-z0-9]{6})$
    canvas.json            {schema, id, id_scheme, name, project_path, created_at, created_by}; no port or pid inside. id is the digits ("1"), not "#1". id_scheme is "number" for a numbered canvas (absent on legacy canvases)
    project.json, DESIGN.md  DESIGN.md is optional: design notes (Markdown), shown read-only by "Design notes"
    frames/*.html
    media/                 optional: the project's own images and other assets
    runtime/feedback.sqlite3
    snapshots/<revision>/  explicitly created version snapshots (project.json, DESIGN.md if any, frames, media, comments.json)
    logs/serve.log
  trash/<time>-<dir>/      `remove` moves a canvas here (nothing is deleted)
```

The canvas directory is the data root: `project.json`, the comment database and snapshots all live in it. `canvas.json.project_path` is only a note pointing at the repository the design is based on; nothing depends on it at run time. The port in the directory name is authoritative: when a stopped canvas is started on a different port, the directory is renamed. `project.json.id` (the project id) is unrelated to the canvas id; keep it when copying a canvas. `canvas.json`, `runtime/`, `snapshots/`, `logs/` and `DESIGN.md` are never served as static files; `DESIGN.md` is readable only through `GET /api/design` (below). The tool front end always comes from `app/assets/`. The runtime needs only the Python standard library (3.9+) and the front end has no CDN dependency.

### Canvas id

New canvases are numbered like GitHub pull requests: #1, #2, #3. The counter belongs to one runtime directory (the workspace that holds `canvases/`), not to one design project and not to the whole machine. Two runtimes each start again at #1. `project.json` `id` is still the project id.

- **Stored form** (directory name, `canvas.json` `id`, `/healthz` `id`, `list` `id`, `/api/canvases/<id>`, `--canvas`) is the digits only: `1`. `#` is not used in paths or URLs. In a URL, `#` starts the fragment and is never sent to the server; in a shell it starts a comment.
- **Shown to people** (`display_id`, the list page, the copied frame reference) as `#1`. Pass that to a person. Pass `1` or `'#1'` to a command.
- **CLI**: `--canvas 1`, or `--canvas '#1'` with quotes. Both `1` and `#1` are accepted. A bare `#1` never reaches the program.
- **Counter**: `run/canvas.seq` is the last number issued. Allocation holds `run/canvas.seq.lock` (`flock`), and `new` also holds `run/create.lock`, so two processes creating canvases at the same time cannot get the same number. The number is written and synced before the lock is released and before the directory is published. A crash after that skips the number instead of repeating it.
- **No reuse**: `remove` moves the directory to `trash/` and does not recycle the number. The next `new` keeps counting up. Emptying `trash/` does not recycle numbers while `canvas.seq` remains. If that file is missing or behind, numbers still present under `canvases/` (including a half-created `.tmp-<id>/`) or `trash/` are skipped.
- **Legacy ids**: a canvas created before numbering keeps its 6-character id (`^[a-z0-9]{6}$`) and its directory name. It still opens, starts, stops and removes with `--canvas <that id>`. It is not renamed. A legacy id is not a sequence number, even when it is six digits (the old alphabet included digits). `id_scheme: "number"` in `canvas.json` is how a real numbered canvas is recognized, including once numbers themselves reach six digits; without it, a six-digit id does not move the counter. If the counter later lands on a taken id, that id is skipped.
- **Scope**: deleting a canvas in this runtime does not affect another runtime's counter. Copying a canvas directory by hand into `canvases/` keeps the id in its directory name; `new` will not issue that id again.

## `project.json`

See `examples/en/project.json` (or `examples/zh/`):

- `id`: stable project id; use a new id for a new project.
- `name`: display name of the canvas.
- `revision`: design revision. Snapshot before a substantial change, then bump it.
- `columns`: number of grid columns in the tile view (frames fill rows first; a column is as wide as its widest frame). Positive integer, default 3, capped by the number of frames in each section (see `group`).
- `groupColumns`: optional object, group name to column count, for example `{"Onboarding": 2, "Settings": 5}`. Overrides `columns` for that group's sections; each value is a positive integer, capped by the number of frames in the section. Groups not listed use `columns`.
- `flow_start`: optional frame id; the start page of the tap-through flow (Flow view and `/m/`). Falls back to the first frame when missing or unknown.
- `frames`: non-empty array. Each frame has `id`, `title`, `width`, `height`, `path`; optional `group` and `state` are shown under the title. In the tile view `group` also splits the board into sections: consecutive frames with the same `group` form one section with a title bar, starting on a new row, with its own columns and column widths (the widest frame per column within the section). Frames are never reordered, so keep the frames of a group next to each other; a group that appears again later is a separate section. Frames without `group` form sections without a title bar. When no frame has a `group`, the board is one grid, as before.
- `notes`: optional array of free-standing HTML blocks on the board, outside every frame (see Comments outside the phone: titles and notes). Each note has `id`, `path` (an `.html` file inside `frames/`), `x` and `y` (0–20000); optional `title`, `width` (40–4000, default 320) and `anchor` (a frame id: `x` and `y` are then measured from that frame's top-left corner, title included, instead of from the board's).
- Frame ids and element ids use letters, digits, underscores and hyphens; frame ids are unique in the project.
- Width and height are CSS px, 100–4000. `path` must be an `.html` file inside `frames/`.

## HTML content

A frame is a declarative HTML fragment loaded into the frame container. Mark elements that need stable review targets:

```html
<button data-ui-id="health-entry" data-ui-label="Health log entry">Health log</button>
```

The tool builds the host element id `<frame id>--<element id>` and comments use it. `screen` is reserved for the whole frame. Element ids must be unique inside a frame; different frames may reuse the same id because of the prefix. The whole frame is automatically commentable. Unmarked HTML/SVG elements get automatic targets from the server; the comment box lets you pick a child level or the parent. Automatic ids stay stable while the frame source is unchanged; when the source changes they are invalidated (old comments are kept and show "element removed"). For anything you need to track across revisions, write an explicit `data-ui-id`.

CSS must be scoped to the frame, for example `[data-frame-id="mobile"] .card`. This matters more since frames load lazily: a frame's fragment arrives only when it comes near the view, so unscoped CSS would restyle the board, and other frames, at an unpredictable moment. Do not override `body`, `button` or `:root` globally and do not reference elements by global ids. Scripts in injected fragments do not run, and neither do production app scripts, React apps or cross-origin iframes. Frame content is written by the project author; never import an untrusted third-party page as a frame.

Frames do not draw phone system UI (clock, battery, signal, notch, status bar, home indicator). The outer `.phone` element is just a size container.

Images use `/project/media/<file>`. Fragments may use the host variables `--bg`, `--fg`, `--card`, `--muted`, `--border`, `--primary`, or their own colours. The frame's `[data-frame-id]` scope covers the whole `<article>`, including the canvas title above the phone; redefining `--muted` etc. inside it affects only the frame, because the canvas title uses the dedicated `--canvas-fg` and `--canvas-muted`, which frame authors must not define.

## Comments outside the phone: titles, group bars and notes

Everything on the board can be commented on, not only what is inside a frame:

- The **title** and the **subtitle** (`group` / `state`) above every frame are targets automatically; there is nothing to write. Their ids are `<frame id>~title` and `<frame id>~subtitle` (a frame without `group` and `state` has no subtitle). The comment keeps the frame, and its stored `position` is relative to the frame.
- The **group title bar** of a section (see `group` above) is a target automatically too. A group has no id of its own, its name is the identifier: the target id is `group~<group>~title`, for example `group~Onboarding~title`. `~` and `%` in the name are written `%7E` and `%25`, so the name part never contains `~`. A group that comes back later is another section with its own bar, and its id has the number of the section: `group~Onboarding~2~title`, `group~Onboarding~3~title`. Frames without a group have no bar and so no target. Because the id contains the name, renaming a group (or moving frames so that sections change) makes the old comments say "element removed", like any removed element; they stay in the list. A comment on a group bar is filed like a comment on a note: frame "Canvas", empty `frame_id`, `position` relative to the board with `position_ref` `board`. The element label is `Group: <group>` (`分组：<group>` in Chinese).
- **Notes** are for text that belongs to no frame: a reading order, a remark between two screens, an annotation block. Declare them in `project.json` and write each one as a fragment in `frames/`, with the same `data-ui-id` / `data-ui-label` convention as a frame:

```json
"notes": [
  { "id": "reading-order", "title": "Reading notes", "path": "frames/note-reading-order.html", "x": 900, "y": 12, "width": 320 },
  { "id": "empty-state", "path": "frames/note-empty-state.html", "anchor": "home", "x": 0, "y": 780 }
]
```

```html
<h3 data-ui-id="heading" data-ui-label="Note heading">Reading order</h3>
<p data-ui-id="start">Start at the first screen.</p>
```

- The host element ids are `~note~<note id>` (the whole note) and `~note~<note id>~<element id>`. A `~` never occurs in frame or element ids, so these cannot collide with `<frame id>--<element id>`. Unmarked elements get automatic targets, as in a frame. Scope a note's CSS with `[data-note-id="<note id>"]`.
- A comment on a note has the frame "Canvas" (`frame`; `frame_id` is empty), so copy for AI and the exported JSON show `Canvas / <element>`. Its stored `position` is relative to the board, and `position_ref` says which reference applies (`board` for group bars and notes, `frame` for frame titles and subtitles). Comments inside a phone are stored exactly as before, without `position`.
- Notes are not part of the tile layout: they never move a frame and the layout does not avoid them, so pick `x` / `y` where no frame is (beside or below the grid), or use `anchor`. The board and the minimap grow to include them. Notes are hidden in the Flow view, absent from `/m/` and from the UI handoff export, and included in snapshots (they live in `frames/`).
- A note removed from `project.json` leaves its comments in place; they show "element removed", like any removed element.

## Tap-through flow: `data-goto`

Put `data-goto="<target frame id>"` next to `data-ui-id` on a button:

```html
<button data-ui-id="continue" data-ui-label="Continue" data-goto="today-actions">Continue</button>
```

- It is ignored in the tile view; it is read only by the Flow view and the phone page `/m/`, which share the same frame HTML.
- Flow view and phone page intercept clicks on `a`, `button`, `[role=button]` and anything with `data-goto`. If the clicked element or an ancestor has `data-goto` and the target frame exists, it jumps; any other intercepted element (including missing or empty targets) shows an "End of demo" hint for 1.5 s. Inputs, text selection and `label` are not intercepted; form submission is blocked.
- Back buttons also name a concrete frame id (no `back` keyword). The Flow view has "Back" (history stack) and "Back to start" (`flow_start`); the phone page uses the browser/system back.
- A wrong target is not an error; walk the flow in `/m/` to check it.

## Keep the scroll position between frames: `data-keep-scroll`

Normally a jump to another frame starts at the top of that frame. For several states of one page (a list and its "selected" variants, tabs, an expanded card) put the same group name on the scrolling element of each frame:

```html
<main class="content" data-keep-scroll="goal-list"> … </main>
```

- Scope: Flow view and phone page `/m/` (also "Back"). Ignored in the tile view.
- When a frame is shown, every `data-keep-scroll="<name>"` element in it takes the scroll position (`scrollTop` and `scrollLeft`) of the element with the same name in the frame just left. Names are matched exactly; a frame without the attribute, or with another name, starts at the top as before. An attribute without a value is the group named `""`.
- Put it on the element that scrolls (`overflow:auto`/`scroll`). On a non-scrolling element the nearest scrolling ancestor is used, at most the outer `.phone` (frames whose whole page scrolls).
- Only the frame being left hands over, so it is "the same place on the next screen", not a per-frame memory. "Back to start" and a reload carry nothing over. A shorter page is clamped to its own end.
- If the new frame cannot scroll that far yet (images, fonts or late layout), the position is applied again for up to 1.5 s, unless you scroll in the meantime. Give images fixed sizes or keep the states the same height for exact results.
- Use the same layout in the frames of a group (same header and padding), otherwise the same pixel offset shows different content.

## Phone preview `/m/`

- `GET /m/`: full-screen, read-only, one frame at a time (`/m` redirects). Frames are injected into `div.phone` (not an iframe), so scoped CSS keeps working. The design width (390) is scaled down on narrower screens; on screens ≤ 560 px wide the frame fills the width at 1×; wider screens (tablet, landscape) centre it at 390; height fills the screen; `viewport-fit=cover` and `env(safe-area-inset-*)` handle notched phones.
- Start frame: `?start=<frame id>` > `project.json.flow_start` > first frame (an invalid id falls back to the next level).
- `?rev=rXX` reads `snapshots/<rev>/` through `/api/snapshots/<rev>/…` (404 if missing). A faint "History rXX" label is shown. Without `rev` it shows the latest.
- Read-only: only GET requests; the server answers any POST/PUT/PATCH/DELETE on `/m` and below with 405. Paths below `/m/` other than `/m/` itself (including `..`, `%2e%2e`, encoded slashes) return 404. `/tool/` serves only `canvas.js` and `canvas.css`.
- No floating buttons; use the browser's refresh and back.
- The phone cannot open a loopback address. Restart the canvas with `--host <LAN_IP>` (a specific address on a trusted network; no authentication, see [DEPLOY.md](../DEPLOY.md)) and open it through the LAN address; the "Mobile preview" dialog shows a QR code and link.

## HTTP API (canvas server)

- `GET /api/project`: validated configuration. `GET /api/comments`: comments of the current revision.
- `GET /api/snapshots`: snapshot list (direct children of `snapshots/`, newest revision first): `{snapshots:[{rev,revision,name,created_at,frames,comments,valid,current}],current_revision}`.
- `GET /api/design`: `{markdown: "<DESIGN.md text>"}`, or `{markdown: null}` when the canvas has no `DESIGN.md`. Fixed file name (no path parameter); a symlink or non-regular file counts as missing, bytes that are not UTF-8 are replaced, and a file over 1 MB answers 413. `GET /api/snapshots/<rev>/design` is the same for a snapshot. Read-only: other methods are refused.
- `GET /api/snapshots/<rev>/project|comments|design|frames/<file>|media/<file>`: read-only view of a snapshot. `<rev>` must match `[A-Za-z0-9._-]+`, must not start with `.`, and must be a real non-symlink directory under `snapshots/`; file paths may not contain `..` or symlinks. Any POST/PUT/PATCH/DELETE on `/api/snapshots*` returns 405.
- `POST /api/comments`: submit a comment with `project_id`, `revision`, `client_id`, `target`, `text` (optional `excerpt`). The server validates the target and derives frame data from the configuration. `client_id` is the idempotency key for retries. Text is 1–4000 characters. Write endpoints require same origin.
- Responses: HTML, JS, CSS and JSON bodies of 512 bytes or more are gzip-compressed when the request's `Accept-Encoding` allows it (`Content-Encoding: gzip`, `Content-Length` of the compressed body, `Vary: Accept-Encoding`). Images, the export ZIP and `HEAD` replies are sent as they are. Every reply keeps `Cache-Control: no-store`.
- `GET /api/lang`, `POST /api/lang {"lang": "zh"|"en"|"auto"}`: UI language (see i18n.md).
- `GET /healthz`: `{service:"ui-canvas", id, display_id, name, port, pid, started_at, version, list_port}`; answered before `project.json` is read, so it works with a broken project, and not logged. `id` is the stored form (`"1"` or a legacy id). `display_id` is `"#1"` for a numbered canvas.

## HTTP API (list service)

`GET /`, `GET /api/canvases`, `GET /api/canvases/<id>` (with comment/snapshot/size statistics), `POST /api/canvases/<id>/start|stop`, `DELETE /api/canvases/<id>`, `GET /healthz` (`{service:"ui-canvas-list", pid, runtime, version, port, started_at}`). Writes accept same-origin requests only (Origin == Host). `<id>` is the stored form: a number (`1`) or a legacy `^[a-z0-9]{6}$`. `%231` is accepted as `#1`. The list page calls the API with the digits, never with a raw `#`, because a browser would treat `#` as the fragment and drop it. List records include `display_id` (`"#1"`).

Status: **running** = healthz says `ui-canvas` with the id of the directory; **stopped** = connection refused; **unresponsive** = timeout, non-JSON, HTTP error, id mismatch, or missing `canvas.json`.

## Process model

- Canvases are started by `new`/`start` (`subprocess.Popen`, own session, output to `logs/serve.log`) as the internal command `serve --canvas-dir <dir>`. At start-up the process requires the directory name to equal `<port>-<id>`; a port in use exits with code 98, on which `new`/`start` pick another port and rename the directory (up to 5 tries).
- Bind addresses: default `127.0.0.1` only. `--host 0.0.0.0` opens all interfaces; `--host auto` binds detected LAN/VPN addresses plus loopback; or give a comma-separated list. Loopback is always bound in addition to explicit addresses (the list service uses it for probes). Addresses that fail to bind are skipped and reported in `bind_errors`. The output `urls` lists every reachable URL and marks whether it is local-only.
- When bound to loopback only, requests whose `Host` header is not a loopback name are rejected with 403 (DNS-rebinding guard).
- Free ports: range 4100–4899 by default (`UI_CANVAS_PORT_RANGE=from-to`), excluding the list port. A port is taken if it is in any directory name under `canvases/` (including stopped canvases) or if probing it fails; allocation is serialised by `run/create.lock`, and the final arbiter is the `serve` bind.
- `ensure-list` holds `run/list.lock` so only one list service runs. When the list port is taken by something that is not this service, it only reports the error; it never kills a process or changes the port.
- `remove` moves the directory to `trash/` (page button and CLI `--yes` share the implementation). Only non-running canvases can be removed. `stop` checks the port owner's pid and that its command line contains `canvas.py`, `serve` and the directory name before sending SIGTERM (SIGKILL after 5 s).
- Background processes are not reaped when a chat or terminal session ends. After a reboot all canvases are stopped; start them from the list page or with `start --canvas <id>`.
