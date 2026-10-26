# Unreleased

## 简体中文

画布列表在窄屏（宽度不超过 700px）改成一张卡片一个画布：标题、状态、编号和端口。主按钮是「打开」或「启动」（无响应时是「停止」），至少 44px 高。手机预览、停止和移除收在「更多」里，移除仍要确认。语言选择单独一行，不再和标题挤在一起；页脚的安全说明默认收起。更宽的屏幕仍是原来的表格。重命名仍用浏览器的 prompt，只改 `canvas.json` 里的名称，不改目录，也不重启正在运行的画布。

手机预览页（`/m/`）每次打开或刷新都从浏览入口开始：地址里的 `?start=`（指向已有帧时），否则 `project.json` 的 `flow_start`，否则第一帧。刷新不会回到刷新前那一屏，地址栏里的帧哈希也会被去掉。画布里的流程视图不变，刷新仍停在地址栏哈希对应的那一帧。

打开中的画布会把评论写在它加载时的版本上。之后 agent 提高了 `project.revision`，这个标签页仍能新增、修改、删除评论，不会因为版本不一致被拒绝，也不会被自动刷新成新版本。这些评论记在浏览器打开的那个版本下。只看当前版本的 `comments` 会漏掉它们；输出里的 `other_revisions` 表示还有别的版本，需要加 `--all`。

升级到编号画布之后，不要再用旧版 skill 操作同一个 runtime。旧版的 `dir_ports` 看不到编号目录，给新画布选端口时可能选到已经被占用的端口。

## English

On a narrow screen (700px and below) the canvas list is one card per canvas: title, status, id and port. The main button is Open or Start (Stop when the canvas is unresponsive) and is at least 44px tall. Mobile preview, Stop and Remove sit behind More; Remove still asks for confirmation. The language control is on its own row, clear of the title, and the security note in the footer stays collapsed. Wider screens keep the table. Rename still uses the browser prompt and only writes the name in `canvas.json`; the directory and a running process stay as they are.

The phone preview (`/m/`) opens on the browse entry on every load and refresh: `?start=` when it names a frame, otherwise `flow_start` in `project.json`, otherwise the first frame. A refresh does not return to the screen that was open before it, and a frame hash in the address bar is removed. The in-canvas Flow view is unchanged: a refresh there still stays on the frame in the address-bar hash.

An open canvas saves comments on the revision it loaded. After an agent bumps `project.revision`, that tab can still create, edit and delete comments: the server accepts the revision the browser sends and does not reload the board onto the new revision. Those comments stay on the open revision. `comments` without `--all` lists only the live revision; `other_revisions` in that output means other revisions still have feedback.

After upgrading to numbered canvases, do not keep using an older copy of this skill against the same runtime. The old `dir_ports` does not see numbered directories, so it can hand a new canvas a port that is already taken.
