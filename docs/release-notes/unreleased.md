# Unreleased

## 简体中文

导出 UI 稿的响应头 `X-UI-Frame-Count` 是这次 ZIP 里的帧数，和包内 `project.json`、交接说明里的页面表、以及 `m/index.html` 的画面数相同。带 `rev` 时这个数来自该快照的同一次导出。不带 `rev` 时仍是实时画布，计数也来自这次导出。

点「导出 UI 稿」会先弹出版本列表。每次打开都重新读取，最新版本（实时画布）排在第一并默认选中，不是正在看的历史版本，也不是上次的选择。确认后下载所选版本；取消或 Esc 不下载，也不改变当前画布。历史版本只读那份快照里的帧、`flow_start` 和当时的 `media/`。快照里没有的图片不会改用现在的文件补上。不带 `rev` 的 `GET /api/export-ui` 仍导出实时画布。

导出的 ZIP 在 `index.html` 上增加手机预览入口，打开包内的 `m/index.html`。入口文字、预览页标题和提示跟导出时的界面语言走：中文是「手机预览」，英文是 Mobile preview。不看画布名称。语言来源和画布页面一样，先是这次请求的 `X-UIC-Lang`，否则已保存的语言，否则浏览器语言；都不是中文时用英文。起点和画布 `/m/` 相同：`?start=` 指向已有帧时用它，否则 `project.json` 的 `flow_start`，否则第一帧。画面里的 `data-goto` 可以点，浏览器返回也沿这条路径回去。没有 `data-goto` 的按钮只提示到此为止，不会登录或保存。图片用包内相对路径。解压后用浏览器直接打开，或放在静态网站的子路径下，都不需要原来的画布服务。

「手机预览」里的地址选择不再用系统下拉菜单。点一下展开，点一行就收起；Esc 或点菜单外面只关掉菜单。字体、圆角、边框和选中底色跟这个弹窗一致，选中项不是系统蓝底。地址、默认当前页面、二维码和复制没有改。

画布工具栏「手机预览」仍是原来的弹窗。打开时重新读取这块画布实际在听的地址。默认选中、排在第一位的是当前页面的地址（协议、主机、端口不变，路径仍是 `/m/`，历史版本带 `?rev=`）。局域网或 Tailscale 地址不会抢这个默认项；当前若是 localhost 或回环地址，也不会被换成别的地址，弹窗会说明手机打不开它，有其他地址时可以在同一个弹窗里切换。切换后二维码、链接文字和「复制预览链接」是同一个地址。`0.0.0.0` 和 `::` 只表示监听范围，不会变成二维码。只监听到一个可分享地址时不显示选择器。列不出来时仍保留当前页面的链接，并说明其他地址没列出来。服务在某个地址上监听，并不表示手机一定能打开它。

列表页可以写一段附加说明（Markdown），按钮在「给 Agent」旁边。文字保存在运行目录的 `AGENT.custom.md`，升级 `app/` 或执行 ensure-list 都不会删掉它。`GET /agent.md` 和 `GET /agent`（中文和英文）会在内置说明之后加上同一段文字，标题固定为 `## Additional instructions`。文件不存在，或去掉空白后为空，就不加这一节。超过 64 KiB 会拒绝（413）。保存和列表上的其他写操作一样，只接受同源请求。这是整份列表共用的一段，不是某一块画布的 `DESIGN.md`。编辑用 `GET` / `POST /api/agent-custom`（`{"markdown":"..."}`）。

添加评论的框里，元素说明旁边有「复制元素地址」。点一下把当前画布、正在看的版本和这个元素的评论目标 id 复制到剪贴板，按钮会短暂变成「已复制」，并弹出提示。评论框不关闭，已写的意见还在，也不会因此保存评论。复制出来的文字是：

```
UI Canvas 元素地址
画布：<画布源站>/（canvas id: #12）
版本：v3
画面：home（Home）
元素：继续
元素 ID：home--continue
```

画布那一行和「复制画面引用」相同。版本是这个标签页加载时的 `project.revision`（评论记在这个版本上），不是最新快照，也不是之后才提高的版本号。元素 ID 就是评论的 `target`（`<帧 id>--<data-ui-id>`、整帧 `<帧 id>--screen`、`<帧 id>~title`、`<帧 id>~subtitle`、`group~<分组>~title`、`~note~<批注 id>`）。分组标题条和批注块没有帧，画面那一行是「画面：画布」。换了元素层级再复制，用的是当前选中的那一层。`/m/` 没有这个按钮。

`/agent.md` 写明：历史版本（`GET /api/snapshots`）只列出 `snapshots/` 下的目录。只提高 `project.revision` 不会产生历史记录。同一版本已有的快照不会被覆盖；没有快照的中间版本之后无法恢复。要出现在历史版本里的改动，先对当前版本执行 `snapshot`，再提高 `revision`。

「历史版本」菜单第一项是「回到最新版本」。正在看快照时，点它或横幅上的同名按钮会立刻回到可编辑的实时画布：只读横幅消失，地址里的 `?rev=` 去掉，不再弹出确认。已经在最新版本上时，这一项标成当前，点它只关闭菜单。目录名与当前版本号相同的快照仍标成只读快照（版本号碰巧相同）；点那一行仍打开快照，不会回到实时画布。

查看历史版本时，横幅上有「复制此版本链接」。复制出的地址是当前画布源站加上 `?rev=<快照 id>`（和「历史版本」菜单、`/m/?rev=` 用的是同一个 `snapshots/` 目录名）。在新标签页打开会停在这个历史版本，只读，不会改成当前的 `project.revision`。正在看流程视图时，链接还会带上 `#view=flow&frame=<帧 id>&rev=<同一 id>`。回到最新版本后，地址里的 `rev` 会去掉。快照 id 无效或读不到时，仍打开当前版本。手机预览 `/m/?rev=` 本来就会打开对应快照，这次没有改它。

列表说明更正两处。`new` 从 `--from` 复制 `project.json`、`DESIGN.md`（若有）、`README.md`（若有）、`frames/` 和 `media/`，不复制 `pages/`、`previews/`、`index.html` 或 `HANDOFF.md`。`GET <canvas-origin>/api/design` 返回 `{"markdown":"..."}` 或 `{"markdown":null}`（依赖可读的 `project.json`；过大为 413）。

`/agent.md` 里的 `DESIGN.md` 改为画布级设计说明：给人只读，也给后续 Agent 接手。新建画布时尽量写一份；意图变了再改，只改某一帧外观不必动。写目标、关键流程、约束、未决问题；文案和布局细节放在 `frames/` 与评论。

仓库根目录增加短的 `AGENTS.md`：日常使用指向正在运行列表的 `<列表源站>/agent.md`，部署看 `DEPLOY.md`。

使用 skill 已停用。`SKILL.md` 已删除。部署不再询问是否安装它，也不再把仓库复制或链接到工具的 skill 目录。原先「已有部署上只安装 skill」一节改为拒绝安装，并指向 `<列表源站>/agent.md`。已经装过的副本不要再用来操作这个实例；正在运行的列表说明才是依据。日常使用就是抓取那个页面。部署只看 `DEPLOY.md` / `DEPLOY.zh-CN.md`。

列表页有「给 Agent」入口，打开 `/agent`。同一份说明的纯 Markdown 在 `/agent.md`（`?lang=zh` 或 `?lang=en` 可指定这一次的语言），助手可以用 curl 读取。地址相对于列表源站，列表以 `--bind auto` 启动时 Tailscale 和局域网都适用。部署说明仍是 `DEPLOY.md`。窄屏卡片不变：手机预览仍是大按钮，打开、启动、停止、改名和移除仍在「更多」里。改名仍通过 `rename_canvas` 同时写入 `canvas.json` 和 `project.json`。

从流程视图切到平铺视图时，平铺会把流程里当前这一帧放到视口正中，缩放保持不变。在流程里翻页时不会提前改平铺的位置；回到平铺之后再拖动画布，也不会被拉回那一帧。流程里没有当前帧时，平铺停在原来的位置。从平铺进入流程仍从浏览入口开始。

画布可以改显示名称。列表每行有「改名」；画布页顶栏标题可以点，标题旁也有铅笔。两次都会同时写入 `canvas.json` 的 `name` 和 `project.json` 的 `name`。目录名、端口、画布编号、项目 id、版本号都不变，也不会写快照。名称会去掉首尾空白，不能为空，最长 100 个字符。

画布列表在窄屏（宽度不超过 700px）改成一张卡片一个画布：标题、状态、编号和端口。大按钮是「手机预览」（运行中打开 `/m/`，否则不可点），至少 44px 高。打开（运行中）、启动（已停止）、停止（运行中或无响应）、改名和移除都在「更多」里；移除仍在分隔线下面，并且仍要确认。语言选择单独一行，不再和标题挤在一起；页脚的安全说明默认收起。更宽的屏幕仍是原来的表格，手机预览仍是单独的按钮。改名仍走 `POST /api/canvases/<id>/rename`，同时写入两份 JSON。

手机预览页（`/m/`）每次打开或刷新都从浏览入口开始：地址里的 `?start=`（指向已有帧时），否则 `project.json` 的 `flow_start`，否则第一帧。刷新不会回到刷新前那一屏，地址栏里的帧哈希也会被去掉。画布里的流程视图不变，刷新仍停在地址栏哈希对应的那一帧。

打开中的画布会把评论写在它加载时的版本上。之后 agent 提高了 `project.revision`，这个标签页仍能新增、修改、删除评论，不会因为版本不一致被拒绝，也不会被自动刷新成新版本。这些评论记在浏览器打开的那个版本下。只看当前版本的 `comments` 会漏掉它们；输出里的 `other_revisions` 表示还有别的版本，需要加 `--all`。

升级到编号画布之后，不要再用已经装上的旧副本操作同一个 runtime。旧版的 `dir_ports` 看不到编号目录，给新画布选端口时可能选到已经被占用的端口。

## English

`X-UI-Frame-Count` on an Export UI response is the number of frames in that ZIP. It matches `project.json`, the page table in the handoff, and the screens in `m/index.html`. With `rev`, the number comes from that snapshot's export. With no `rev`, the export is still the live canvas, and the count comes from that same export.

Export UI handoff first opens a version list. Each time it opens, the list is read again and the latest version (the live canvas) is first and selected. That is not the history version on screen and not the previous choice. Confirm downloads the selected version. Cancel or Esc does not download and does not change the canvas. A history version uses only the frames, `flow_start`, and `media/` stored in that snapshot. A media file that is not in the snapshot is not filled in from the live canvas. `GET /api/export-ui` without `rev` still exports the live canvas.

The exported ZIP adds a phone-preview link on `index.html`, opening `m/index.html` inside the package. The link, the preview title and the prompts follow the language of that export: 手机预览 in Chinese, Mobile preview in English. The canvas name is not used. The language is the same as the canvas page: `X-UIC-Lang` on this request, otherwise the stored language, otherwise the browser language, and English when that is not Chinese. It starts where canvas `/m/` starts: `?start=` when that frame exists, otherwise `flow_start` in `project.json`, otherwise the first frame. `data-goto` links work, and the browser Back button walks that same path. A button without `data-goto` only says the demo ends; it does not sign in or save. Images use paths inside the package. Opening the unzipped files, or hosting the folder on a static site under a subpath, does not need the canvas server.

The address control in Mobile preview is no longer the system dropdown. Click it to open a menu, choose a row and the menu closes; Esc or a click outside the menu closes only the menu. Type, radius, border and the selected row use the same look as the dialog, without the system blue highlight. The addresses, the current-page default, the QR code and copy are unchanged.

Toolbar “Mobile preview” stays in its existing dialog. Opening it re-reads the addresses this canvas process is actually listening on. The default, listed first, is the address of the page you have open (same scheme, host and port; path `/m/`, plus `?rev=` on a history version). A LAN or Tailscale address does not take that default. A localhost or loopback address is not replaced either; the dialog says a phone cannot open it, and you can switch in the same dialog when another address exists. The QR code, the link text and “Copy preview link” always use the address that is selected. `0.0.0.0` and `::` describe the listen scope and are never the QR link. A single shareable address hides the selector. If the lookup fails, the dialog keeps this page’s link and says the other addresses could not be listed. An address the service is listening on is not a check that a phone can open it.

The list page can store one Markdown note, additional instructions for this list. The button sits next to For agents. The text is saved as `AGENT.custom.md` in the runtime directory, so an app upgrade or ensure-list does not remove it. `GET /agent.md` and `GET /agent` (Chinese and English) append that same text after the built-in guide, under the heading `## Additional instructions`. A missing file, or one that is empty after trimming, does not add the section. More than 64 KiB is rejected (413). Saving uses the same same-origin rule as the other list writes. The note is list-wide, separate from a canvas `DESIGN.md`. The editor uses `GET` / `POST /api/agent-custom` (`{"markdown":"..."}`).

The add-comment box has "Copy element address" next to the element context. It copies this canvas, the revision on screen and the element's comment target to the clipboard, briefly labels the button "Copied", and shows a toast. The box stays open, the draft stays, and no comment is saved. The copied text is:

```
UI Canvas element address
Canvas: <canvas-origin>/ (canvas id: #12)
Revision: v3
Frame: home (Home)
Element: Continue
Element ID: home--continue
```

The canvas line matches "Copy frame reference". Revision is the `project.revision` this tab loaded (where its comments are stored), not the newest snapshot and not a revision bumped after the tab opened. Element ID is the comment `target` (`<frame id>--<data-ui-id>`, `<frame id>--screen` for the whole frame, `<frame id>~title`, `<frame id>~subtitle`, `group~<group>~title`, `~note~<note id>`). A group bar or a note has no frame, so that line is "Frame: Canvas". Copying again after a layer change uses the layer now selected. `/m/` does not have this button.

The agent guide (`/agent.md`) now states that History (`GET /api/snapshots`) lists only directories under `snapshots/`. Raising `project.revision` alone does not create a History entry. An existing snapshot for that revision is never overwritten, and an intermediate revision with no snapshot cannot be recovered later. Before a revision bump that should appear in History, snapshot the current revision, then raise `revision`.

The History menu’s first item is “Back to latest”. While a snapshot is open, that item and the banner button of the same name return immediately to the editable live canvas: the read-only banner goes away and `?rev=` is removed, with no confirmation. On the live canvas the item is marked current and choosing it only closes the menu. A snapshot whose directory name matches the live revision is tagged as a read-only snapshot with that same revision number; choosing the row still opens the snapshot.

While a history version is open, the banner has “Copy link to this version”. The copied URL is this canvas origin plus `?rev=<snapshot id>` (the same `snapshots/` directory name the History menu and `/m/?rev=` already use). Opening it in a new tab stays on that snapshot, read-only, and does not move to the live `project.revision`. In the Flow view the link also includes `#view=flow&frame=<frame id>&rev=<same id>`. Leaving history removes `rev` from the address. An unknown or unreadable id still opens the current version. The phone preview `/m/?rev=` already opened that snapshot; this change does not alter it.

The list guide corrects two points. `new` copies `project.json`, `DESIGN.md` (if present), `README.md` (if present), `frames/` and `media/` from `--from`, and does not copy `pages/`, `previews/`, `index.html` or `HANDOFF.md`. `GET <canvas-origin>/api/design` returns `{"markdown":"..."}` or `{"markdown":null}` (depends on a readable `project.json`; 413 if too large).

The agent guide (`/agent.md`) now describes `DESIGN.md` as a canvas-level brief: read-only for people, and context for later Agents. Prefer writing one when creating a canvas; update it when the intent changes, not for a one-frame visual tweak. Goals, key flows, constraints and open questions—not the full copy and layout (`frames/` and comments).

A short root `AGENTS.md` points everyday use at the running list's `<list-origin>/agent.md` and deploy at `DEPLOY.md`.

The usage skill is retired. `SKILL.md` is removed. Deploy no longer asks to install it, and it no longer copies or links the repository into a tool skill directory. The old skill-only install section now refuses that install and points at `<list-origin>/agent.md`. An assistant that already has a copy installed should stop using it; the guide on the running list is the source of truth. Everyday use is to fetch that page. Deploy stays `DEPLOY.md`.

The list page has a For agents entry, which opens `/agent`. The same guide is plain Markdown at `/agent.md` (`?lang=en` or `?lang=zh` selects the language for that request) so an assistant can fetch it with curl. Paths are relative to the list origin, so Tailscale and LAN both work when the list was started with `--bind auto`. The narrow list cards are unchanged: Mobile preview stays the large control, and Open, Start, Stop, Rename and Remove stay in More. Rename still goes through `rename_canvas` and writes both `canvas.json` and `project.json`.

Switching from Flow to Tile centres the frame that was open in Flow and keeps the zoom. Moving between frames while Flow is still open leaves the tile camera where it was. After the switch, panning the tile view stays where you leave it. With no current Flow frame, the tile camera stays put. Opening Flow from Tile still starts at the browse entry.

A canvas display name can be changed. Each list row has Rename, and the canvas page title can be clicked or edited from the pencil beside it. Both writes update `canvas.json` `name` and `project.json` `name` together. The directory, port, canvas id, project id and revision stay the same, and no snapshot is written. The name is trimmed, must not be empty, and is at most 100 characters.

On a narrow screen (700px and below) the canvas list is one card per canvas: title, status, id and port. The large control is Mobile preview (it opens `/m/` while the canvas is running, and is inactive otherwise) and is at least 44px tall. Open (when running), Start (when stopped), Stop (when running or unresponsive), Rename and Remove sit in More; Remove stays under a separator and still asks for confirmation. The language control is on its own row, clear of the title, and the security note in the footer stays collapsed. Wider screens keep the table, and Mobile preview stays its own control there. Rename still calls `POST /api/canvases/<id>/rename`, which writes both JSON files.

The phone preview (`/m/`) opens on the browse entry on every load and refresh: `?start=` when it names a frame, otherwise `flow_start` in `project.json`, otherwise the first frame. A refresh does not return to the screen that was open before it, and a frame hash in the address bar is removed. The in-canvas Flow view is unchanged: a refresh there still stays on the frame in the address-bar hash.

An open canvas saves comments on the revision it loaded. After an agent bumps `project.revision`, that tab can still create, edit and delete comments: the server accepts the revision the browser sends and does not reload the board onto the new revision. Those comments stay on the open revision. `comments` without `--all` lists only the live revision; `other_revisions` in that output means other revisions still have feedback.

After upgrading to numbered canvases, do not keep using an older installed copy against the same runtime. The old `dir_ports` does not see numbered directories, so it can hand a new canvas a port that is already taken.
