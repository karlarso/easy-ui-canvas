# Unreleased

## 简体中文

从流程视图切到平铺视图时，平铺会把流程里当前这一帧放到视口正中，缩放保持不变。在流程里翻页时不会提前改平铺的位置；回到平铺之后再拖动画布，也不会被拉回那一帧。流程里没有当前帧时，平铺停在原来的位置。从平铺进入流程仍从浏览入口开始。

画布可以改显示名称。列表每行有「改名」；画布页顶栏标题可以点，标题旁也有铅笔。两次都会同时写入 `canvas.json` 的 `name` 和 `project.json` 的 `name`。目录名、端口、画布编号、项目 id、版本号都不变，也不会写快照。名称会去掉首尾空白，不能为空，最长 100 个字符。

画布列表在窄屏（宽度不超过 700px）改成一张卡片一个画布：标题、状态、编号和端口。大按钮是「手机预览」（运行中打开 `/m/`，否则不可点），至少 44px 高。打开（运行中）、启动（已停止）、停止（运行中或无响应）、改名和移除都在「更多」里；移除仍在分隔线下面，并且仍要确认。语言选择单独一行，不再和标题挤在一起；页脚的安全说明默认收起。更宽的屏幕仍是原来的表格，手机预览仍是单独的按钮。改名仍走 `POST /api/canvases/<id>/rename`，同时写入两份 JSON。

手机预览页（`/m/`）每次打开或刷新都从浏览入口开始：地址里的 `?start=`（指向已有帧时），否则 `project.json` 的 `flow_start`，否则第一帧。刷新不会回到刷新前那一屏，地址栏里的帧哈希也会被去掉。画布里的流程视图不变，刷新仍停在地址栏哈希对应的那一帧。

打开中的画布会把评论写在它加载时的版本上。之后 agent 提高了 `project.revision`，这个标签页仍能新增、修改、删除评论，不会因为版本不一致被拒绝，也不会被自动刷新成新版本。这些评论记在浏览器打开的那个版本下。只看当前版本的 `comments` 会漏掉它们；输出里的 `other_revisions` 表示还有别的版本，需要加 `--all`。

升级到编号画布之后，不要再用旧版 skill 操作同一个 runtime。旧版的 `dir_ports` 看不到编号目录，给新画布选端口时可能选到已经被占用的端口。

## English

Switching from Flow to Tile centres the frame that was open in Flow and keeps the zoom. Moving between frames while Flow is still open leaves the tile camera where it was. After the switch, panning the tile view stays where you leave it. With no current Flow frame, the tile camera stays put. Opening Flow from Tile still starts at the browse entry.

A canvas display name can be changed. Each list row has Rename, and the canvas page title can be clicked or edited from the pencil beside it. Both writes update `canvas.json` `name` and `project.json` `name` together. The directory, port, canvas id, project id and revision stay the same, and no snapshot is written. The name is trimmed, must not be empty, and is at most 100 characters.

On a narrow screen (700px and below) the canvas list is one card per canvas: title, status, id and port. The large control is Mobile preview (it opens `/m/` while the canvas is running, and is inactive otherwise) and is at least 44px tall. Open (when running), Start (when stopped), Stop (when running or unresponsive), Rename and Remove sit in More; Remove stays under a separator and still asks for confirmation. The language control is on its own row, clear of the title, and the security note in the footer stays collapsed. Wider screens keep the table, and Mobile preview stays its own control there. Rename still calls `POST /api/canvases/<id>/rename`, which writes both JSON files.

The phone preview (`/m/`) opens on the browse entry on every load and refresh: `?start=` when it names a frame, otherwise `flow_start` in `project.json`, otherwise the first frame. A refresh does not return to the screen that was open before it, and a frame hash in the address bar is removed. The in-canvas Flow view is unchanged: a refresh there still stays on the frame in the address-bar hash.

An open canvas saves comments on the revision it loaded. After an agent bumps `project.revision`, that tab can still create, edit and delete comments: the server accepts the revision the browser sends and does not reload the board onto the new revision. Those comments stay on the open revision. `comments` without `--all` lists only the live revision; `other_revisions` in that output means other revisions still have feedback.

After upgrading to numbered canvases, do not keep using an older copy of this skill against the same runtime. The old `dir_ports` does not see numbered directories, so it can hand a new canvas a port that is already taken.
