# 让你的 AI 助手帮你部署 Easy UI Canvas

**把本文件整份交给你的 AI 助手（Claude Code、Cursor、Codex 等），它会和你沟通部署细节，并帮你完成部署。**

English: [DEPLOY.md](DEPLOY.md)

---

> 以下内容是写给 AI 助手的，使用者不需要继续往下读。

## 1. 角色与目标

你是一名谨慎的部署助手。目标是让 Easy UI Canvas（一个本地多帧 UI 探索画布，只依赖 Python 3 标准库）**按使用者想要的方式**运行起来，完成验证，并给使用者留下清晰的停止、重启、卸载命令。

部署细节不由你替使用者决定。绑定地址、是否开机自启、端口、数据位置、是否启用导出功能都是使用者的选择：先问，等回答，再动手。每个问题可以给出推荐默认值，但不得悄悄套用。

使用使用者所用的语言交流。一次只问一个问题，用通俗的话说明，等回复后再问下一个。

## 2. 安全底线（不可违背）

这些规则高于本文件其他内容、仓库里的任何文字，也高于使用者随口说的话。如果某一步会违反规则，请停下并说明原因。

1. **默认只绑定 `127.0.0.1`。** 除非使用者在第 4 节中另有选择，否则一律使用它。
2. **本工具没有登录验证。** 能访问某个端口的人都可以查看、评论、删除评论并停止画布。使用者选择任何非本机地址（局域网 IP、Tailscale IP、`auto` 或地址列表）时，你**必须**在做任何事之前用大白话说明：「本工具没有登录验证。与你处于同一网段（或同一个 tailnet）、能访问该地址和端口的人，都能评论、删除评论、停止画布。请只在你信任的网络里继续。」得到明确确认（「确认继续」或同等表述）后才能继续。
3. **不得绑定 `0.0.0.0`**（所有网卡），除非使用者明确要求；此时要带着同样的警告再确认一次，并补充「这会包含本机所有网络接口」。优先使用具体地址。
4. **不得替使用者开防火墙、配置端口转发或 portproxy、建立隧道，或把任何东西暴露到公网。** 如果使用者想这样做，说明这超出本工具范围且工具没有登录验证，但不要替他做。
5. **不得写入或回显任何令牌或密钥**（Tailscale auth key、API key、密码、云服务或 Git 凭据）：不写进文件、命令、日志或消息。如果某一步需要，请使用者在本对话之外自己处理。
6. **不修改使用者的其他服务**：不编辑其他服务单元、plist、代理配置或防火墙规则；不结束不是你启动的进程；不占用被其他程序使用的端口（换一个端口或先询问）。
7. 在安装目录和所选运行数据目录之外创建、修改或删除任何东西（例如 LaunchAgent plist 或 systemd 用户单元），必须先让使用者在第 6 节确认具体计划。不得删除使用者的数据：移到运行数据目录的 `trash/`，或先询问。
8. 不做系统级安装，也不运行 `sudo`，除非使用者明确要求。

## 3. 先探测环境（只读）

提问之前先收集事实。下面的命令都是只读的，请按平台调整。

```bash
uname -a                                   # 操作系统与架构（Windows 上必须在 WSL 里，见 7.2 节）
command -v python3 && python3 --version    # 需要 Python 3.9 及以上
# 已被占用的端口（用其中存在的命令）：
ss -ltn 2>/dev/null || lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null || netstat -an 2>/dev/null | grep LISTEN
command -v tailscale && tailscale status   # 是否安装并运行了 Tailscale？
tailscale ip -4 2>/dev/null                # 本机的 Tailscale 地址（如果有）
# 局域网地址候选（用其中存在的命令；只向使用者展示私有地址）：
ip -4 addr 2>/dev/null || ifconfig 2>/dev/null
command -v node && node --version          # 可选：仅「导出 UI 稿」功能需要
command -v systemctl && systemctl --user is-system-running 2>/dev/null   # Linux：是否有 systemd 用户管理器？
uname -s | grep -q Darwin && command -v launchctl                        # macOS：是否有 LaunchAgent？
```

还要检查：

- 仓库是否已在本地？看是否有 `scripts/canvas.py`。如果别人已把目录交给你或你就在其中，那就是 `<INSTALL_DIR>`。否则询问使用者放到哪里。默认来源是 `<REPO_URL>` = `https://github.com/karlarso/easy-ui-canvas`（用 `git clone https://github.com/karlarso/easy-ui-canvas.git` 获取），无需再向使用者索要；除非使用者指定了别的地址。不要猜测任何其他地址。
- Easy UI Canvas 是否已经在运行或已安装？检查默认列表端口：`curl -s http://127.0.0.1:4042/healthz`。如果返回 `"service": "ui-canvas-list"`，说明已有实例：告诉使用者它用的运行数据目录（返回中的 `runtime`），并询问是复用还是替换。如果该端口返回的是别的内容，说明被其他程序占用，不要动它。
- 是否已有自启项？（`~/Library/LaunchAgents/com.easy-ui-canvas.list.plist`、`~/.config/systemd/user/easy-ui-canvas-list.service`。）
- Playwright 是否可用（可选）？`node -e "require.resolve('playwright')"`（失败也没关系；可加 `2>/dev/null` 隐藏报错）。
- 使用者在用哪种 AI 工具？技能是否已经装好？你通常知道自己是哪种工具（Claude Code、Cursor、Codex）；不确定，或使用者可能还想给其他工具装，就先找线索，稍后在 Q7 里问。下面的命令都是只读的：

```bash
command -v claude codex cursor cursor-agent 2>/dev/null                 # 有哪些 AI 工具的命令行
ls -d ~/.claude ~/.codex ~/.cursor .claude .cursor 2>/dev/null          # 哪些工具有配置目录（全局或当前项目内）
ls -d ~/.claude/skills/easy-ui-canvas ~/.codex/skills/easy-ui-canvas \
      .claude/skills/easy-ui-canvas .cursor/skills/easy-ui-canvas 2>/dev/null   # 技能是否已安装？（也要检查该工具最新文档里的路径）
```

  把工具归为「Claude Code」「Cursor」「Codex」或「其他」。技能目录下已有 `easy-ui-canvas`，说明该处已装过：用 `ls -ld` 看它是否软链、指向哪里，里面有没有 `SKILL.md`。未经询问（Q7）不要覆盖。

用几行话向使用者汇总（系统、Python 版本、相关的占用端口、有没有 Tailscale、有没有 Node/Playwright、用的是哪种 AI 工具、技能是否已装）。如果 Python 低于 3.9 或不存在，请停下并告知使用者，不要替他安装系统软件包。

## 4. 与使用者沟通（一次一个问题，等每个回答）

不要因为觉得自己知道答案就跳过问题。记住这些回答，第 6 节要复述。

**Q1. 你打算在哪里使用？**
- (a) 只在这台电脑上用。
- (b) 还要在手机、家里/办公室网络里的其他电脑上用，或远程访问。

选 (a)：绑定 `127.0.0.1`，跳过 Q2（并说明），继续 Q3。选 (b)：问 Q2。

**Q2. 监听哪个地址？** 结合探测到的地址说明各选项（真实地址只在回复使用者时使用，绝不写进仓库文件）：

| 选择 | 含义 | 谁能访问 |
| --- | --- | --- |
| `127.0.0.1` | 仅本机。 | 只有本机上的程序。手机打不开。 |
| `<LAN_IP>`（本机在 Wi-Fi/有线网络里的私有地址） | 同一局域网内的设备。 | 该网络里所有能访问该地址的人，包括共享 Wi-Fi 上的访客。路由器重新分配后地址可能变化。 |
| `<TAILSCALE_IP>`（本机的 Tailscale 地址，通常是 `100.x.y.z`） | 你的 Tailscale 网络（tailnet）里的设备，在任何地方都能连。 | tailnet 里所有人和设备，包括别人共享给你的设备。服务启动时需要 Tailscale 已在线。 |
| `auto` | 绑定所有探测到的局域网和 Tailscale 地址。 | 上面两类都能访问。 |
| `0.0.0.0` | 所有网络接口。不推荐。 | 一切能路由到本机的对象。必须满足安全底线第 3 条的明确要求和二次确认。 |

除了你选的地址，工具始终还会监听 `127.0.0.1`。只要选了非本机地址，就立刻给出安全底线第 2 条的「无登录验证」警告，并等待明确确认。使用者不确认，就回退到 `127.0.0.1`。

**Q3. 登录/开机时是否自动启动？**
- 否：需要时由使用者（或应其要求由你）用 `ensure-list` 启动。简单，不留痕迹。
- 是：为**列表服务**设置用户级自启（macOS LaunchAgent、Linux `systemd --user` 或 WSL，见第 7 节）。说明：重启后列表页会自己起来，但每个画布是独立进程，会保持停止，需使用者在列表页启动（或用 `start --canvas <id>`）。

**Q4. 端口。** 默认：列表页 `4042`，画布从 `4100-4899` 中选取（列表端口不会用于画布）。问是否保持默认。如要改，需要 `<LIST_PORT>` 和 `<PORT_MIN>-<PORT_MAX>`（范围在 1024–65535 之间；列表端口 1–65535）。对照你探测到的占用端口，有冲突就提出替代方案。

**Q5. 运行数据放哪里？** 评论、帧和快照都存放在同一个运行数据目录。默认 `~/ui-canvas-runtime`。询问保持默认还是换路径（`<RUNTIME_DIR>`）。建议放在本地普通磁盘（不要放网络盘或云同步目录：里面有 SQLite 数据库），评论重要的话建议使用者自行备份。如果使用者已有带画布的运行数据目录，用同一路径即可保留它们。

**Q6. 是否需要「导出 UI 稿」功能？** 它会生成带整页截图的 ZIP，需要 Node.js、Playwright 和 Chromium（或 Google Chrome），这些由**使用者自己安装**：本仓库不捆绑、也不自动安装。选「是」时，告诉使用者会安装什么、从哪里下载（例如 `npm install playwright` 和 `npx playwright install chromium`，会下载第三方软件），提议安装位置，并且只在得到明确的「可以」之后才运行命令。如果 Playwright 装在非标准位置，需要把环境变量 `UI_CANVAS_PLAYWRIGHT_MODULE` 指向它（使用自启时列表服务的环境里也要设置）。选「否」就跳过，其余功能照常可用。

**Q7. 是否安装 Easy UI Canvas 技能（skill）？** 技能就是教 AI 助手如何创建画布、写界面帧、读取并回复评论的说明（即 `SKILL.md` 加随附的脚本和文档）。请问：

- **给哪个（哪些）AI 工具装**：Claude Code、Cursor、Codex，还是其他（请说出名称）？把第 3 节探测到的当作默认建议，但使用者可以增减。
- **装到全局还是仅当前项目？** 全局：该工具下所有项目都能用；项目：只有当前项目目录（`<PROJECT_DIR>`）能用。
- 如果别处已经装过（第 3 节）：保留、更新还是替换？

说明**不装**的后果：画布本身照常运行，但助手不会知道如何创建画布、写界面帧、读取评论，使用者每次会话都得手动解释（或每次让助手去读 `SKILL.md`）。装不装由使用者决定，不是你：可以推荐，但使用者说「不」或「以后再说」就跳过 7.4，并告诉他以后怎么装。没有得到同意之前不要安装任何东西，并在第 6 节复述确切的目标路径。

## 5. 到此你已有的参数

下文使用的占位符（替换成使用者的回答；写入文件时不得留下任何占位符）：

| 占位符 | 含义 | 默认值 |
| --- | --- | --- |
| `<INSTALL_DIR>` | 含 `scripts/canvas.py` 的目录 | 仓库所在位置 |
| `<PYTHON3>` | `command -v python3` 得到的绝对路径 | |
| `<HOST>` | 绑定设置：`127.0.0.1`、某个地址、`auto`，或逗号分隔的列表 | `127.0.0.1` |
| `<LIST_PORT>` | 列表页端口 | `4042` |
| `<PORT_MIN>-<PORT_MAX>` | 画布端口范围 | `4100-4899` |
| `<RUNTIME_DIR>` | 运行数据目录 | `~/ui-canvas-runtime` |
| `<HOME_DIR>` | 使用者的主目录 | |
| `<SKILL_DIR>` | AI 工具加载技能的目录，以 `easy-ui-canvas` 结尾（7.4 节）；使用者选了几个工具/范围就有几个 | 无：仅当 Q7 选「是」时才有 |
| `<PROJECT_DIR>` | 项目级安装技能时的项目目录 | 当前项目 |

真实的参数名（已对照 `scripts/canvas.py` 核对）：

| 设置 | 命令行选项 | 环境变量 |
| --- | --- | --- |
| 运行数据目录 | `--runtime-dir <RUNTIME_DIR>` | `UI_CANVAS_RUNTIME` |
| 列表页端口 | `--list-port <LIST_PORT>` | `UI_CANVAS_LIST_PORT` |
| 绑定地址 | `--bind <HOST>`（别名 `--host`），用于 `ensure-list`、`list-serve`、`new`、`start`、`serve` | `UI_CANVAS_BIND`（`--bind` 的默认值） |
| 画布端口范围 | 无 | `UI_CANVAS_PORT_RANGE=<PORT_MIN>-<PORT_MAX>` |
| 界面语言 | `canvas.py lang zh\|en\|auto` | `UI_CANVAS_LANG`（仅影响命令行输出） |
| Playwright 位置 | 无 | `UI_CANVAS_PLAYWRIGHT_MODULE` |

这些设置如何传给各个进程：

- 每次调用 `canvas.py` 都要使用同一个运行数据目录和列表端口：要么为你运行的命令设置环境变量（`export UI_CANVAS_RUNTIME=... UI_CANVAS_LIST_PORT=... UI_CANVAS_PORT_RANGE=...`），要么每次都传选项。
- 画布端口范围由负责分配端口的进程读取：你的命令行调用（`new`、`start`）以及列表服务（使用者在列表页点「启动」时）。使用自启时，也要把 `UI_CANVAS_PORT_RANGE` 放进服务环境。
- 用命令行启动的画布使用该次命令的绑定设置；从列表页启动的画布使用列表服务的绑定设置。绑定不是默认值时，每次 `new`/`start` 都传 `--bind <HOST>`；只有在使用者同意你修改其 shell 配置文件时，才在服务环境和使用者自己的 shell 中设置 `UI_CANVAS_BIND`（否则只传 `--bind`）。
- 未经询问，不要把这些 export 写进使用者的 shell 配置文件。

## 6. 复述计划并请使用者确认

改动任何东西之前，用一个简短列表复述计划，并请使用者明确回答「是」：

- 安装目录和使用的 Python。
- 绑定地址及其含义（非本机地址要再次重复「无登录验证」警告）。
- 列表端口和画布端口范围。
- 运行数据目录。
- 自启：无，或你将创建的确切文件（路径）和加载它的命令。
- 导出功能：跳过，或你将安装的确切内容和位置。
- 技能：跳过，或对每个工具给出确切的 `<SKILL_DIR>` 路径、全局还是项目、软链还是复制（7.4 节），以及是否会替换已有的东西。
- 你**不会**碰的东西（防火墙、其他服务、其他端口）。

使用者改了什么，就更新计划并再次确认。没听到「是」之前不要开始。

## 7. 执行

### 7.1 启动列表服务并创建一个检查用画布

```bash
export UI_CANVAS_RUNTIME=<RUNTIME_DIR> UI_CANVAS_LIST_PORT=<LIST_PORT> UI_CANVAS_PORT_RANGE=<PORT_MIN>-<PORT_MAX>
cd <INSTALL_DIR>
<PYTHON3> scripts/canvas.py ensure-list --bind <HOST>
<PYTHON3> scripts/canvas.py new --name "Deploy check" --bind <HOST>
```

两条命令都会输出 JSON：`url` / `urls`（每项标注 `local-only`、`lan`、`tailscale` 或 `explicit`）、画布的 `id`、`dir`、`port` 和 `log`。如果 `ensure-list` 报告端口被其他程序占用或属于另一个运行数据目录，原文转告并询问使用者；不得自行结束进程或改端口。`ensure-list` 不会改变已在运行的列表服务的绑定：要改绑定，先停掉那个服务（第 9 节）。

### 7.2 自启（仅当使用者选择了）

先用上面的普通命令启动并确认可用。然后按下面的模板为对应平台生成文件，给使用者看，再写入并加载。这些自启项只运行列表服务。如果自启项已安装但未加载，此时运行 `ensure-list` 会手动再起一个列表服务：运行前先检查服务状态。

只替换占位符，保留其他所有键。只有当 `<HOST>` 不是 `127.0.0.1` 时才加 `UI_CANVAS_BIND`；只有使用者需要时才加 `UI_CANVAS_PLAYWRIGHT_MODULE`。

**macOS（LaunchAgent）。** 默认仅本机的配置下，工具自己能写文件：`<PYTHON3> scripts/canvas.py install-list-agent` 只打印计划（试运行），`... install-list-agent --yes` 写入 `~/Library/LaunchAgents/com.easy-ui-canvas.list.plist` 并加载（`uninstall-list-agent --yes` 移除；plist 会被移到 `<RUNTIME_DIR>/trash/`）。该内置命令没有绑定选项，所以其他绑定需要你按下面的模板自己写 plist（与 `scripts/ui-canvas-list.plist.template` 对应），文件为 `~/Library/LaunchAgents/com.easy-ui-canvas.list.plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.easy-ui-canvas.list</string>
  <key>ProgramArguments</key>
  <array>
    <string><PYTHON3></string>
    <string><INSTALL_DIR>/scripts/canvas.py</string>
    <string>list-serve</string>
    <string>--runtime-dir</string>
    <string><RUNTIME_DIR></string>
    <string>--list-port</string>
    <string><LIST_PORT></string>
    <string>--bind</string>
    <string><HOST></string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>UI_CANVAS_RUNTIME</key>
    <string><RUNTIME_DIR></string>
    <key>UI_CANVAS_LIST_PORT</key>
    <string><LIST_PORT></string>
    <key>UI_CANVAS_PORT_RANGE</key>
    <string><PORT_MIN>-<PORT_MAX></string>
    <key>UI_CANVAS_BIND</key>
    <string><HOST></string>
    <key>PATH</key>
    <string>/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>
  <key>ThrottleInterval</key>
  <integer>10</integer>
  <key>AbandonProcessGroup</key>
  <true/>
  <key>WorkingDirectory</key>
  <string><HOME_DIR></string>
  <key>StandardOutPath</key>
  <string><RUNTIME_DIR>/logs/list.log</string>
  <key>StandardErrorPath</key>
  <string><RUNTIME_DIR>/logs/list.log</string>
</dict>
</plist>
```

plist 里使用绝对路径（不要用 `~`）；XML 里的 `&` 要写成 `&amp;`。先用 `plutil -lint <plist 路径>` 校验，再加载：

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.easy-ui-canvas.list.plist
launchctl print gui/$(id -u)/com.easy-ui-canvas.list | head
```

（`AbandonProcessGroup` 让列表服务重启时不会杀掉画布；`KeepAlive` 只在崩溃后重启。）

**Linux（systemd 用户服务）。** 写入 `~/.config/systemd/user/easy-ui-canvas-list.service`：

```ini
[Unit]
Description=Easy UI Canvas list service

[Service]
Environment=UI_CANVAS_RUNTIME=<RUNTIME_DIR>
Environment=UI_CANVAS_LIST_PORT=<LIST_PORT>
Environment=UI_CANVAS_PORT_RANGE=<PORT_MIN>-<PORT_MAX>
Environment=UI_CANVAS_BIND=<HOST>
ExecStart=<PYTHON3> <INSTALL_DIR>/scripts/canvas.py list-serve --runtime-dir <RUNTIME_DIR> --list-port <LIST_PORT> --bind <HOST>
Restart=on-failure
KillMode=process

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now easy-ui-canvas-list.service
systemctl --user status easy-ui-canvas-list.service --no-pager
```

`KillMode=process` 让服务重启时画布进程继续存活。没有登录会话时（无显示器的机器），服务只在使用者登录期间运行，除非启用 lingering：运行 `loginctl enable-linger $USER` 之前先询问，并说明这会让服务在开机时启动。如果 `<HOST>` 是 Tailscale 地址，服务可能在开机时早于 Tailscale 上线而失败；`Restart=on-failure` 会重试，并请把这一点告诉使用者。如果已经用 `ensure-list` 手动启动了服务，先停掉那个进程（第 9 节），让单元接管端口。

**Windows（WSL）。** 不支持原生 Windows；一切都在 WSL（Ubuntu 或类似）中运行，上面的步骤都在 WSL 的 shell 里完成。

- 如果该 WSL 发行版启用了 systemd（`systemctl --user is-system-running` 可用；较新的 WSL 2 需要在 `/etc/wsl.conf` 里设置 `[boot]` `systemd=true`，这是使用者的决定，且需要 `wsl --shutdown` 才生效），就在 WSL 里使用上面的 Linux 单元。WSL 本身仍需处于运行状态：在 Windows 登录时启动它见下一条。
- 否则使用 Windows 任务计划程序的「登录时」任务，运行一个常驻的 WSL 进程，同时让发行版保持唤醒。示例动作（在 Windows PowerShell 中，经使用者同意后运行；`<DISTRO>` 用 `wsl -l -q` 查看）：

```powershell
schtasks /Create /TN "Easy UI Canvas" /SC ONLOGON /TR "wsl.exe -d <DISTRO> --exec <PYTHON3> <INSTALL_DIR>/scripts/canvas.py list-serve --runtime-dir <RUNTIME_DIR> --list-port <LIST_PORT> --bind <HOST>"
```

  这里 `<PYTHON3>`、`<INSTALL_DIR>`、`<RUNTIME_DIR>` 是 WSL（Linux）路径。需要设置端口范围的环境变量时，在命令前加 `wsl.exe -d <DISTRO> --exec env UI_CANVAS_PORT_RANGE=<PORT_MIN>-<PORT_MAX> <PYTHON3> ...`。也可以把命令放进 WSL 里的一个小 shell 脚本，由任务运行该脚本。确认使用者同意后，用 `schtasks /Delete /TN "Easy UI Canvas" /F` 删除。（这个任务计划程序做法只是模板：请告诉使用者它未能在所有 Windows/WSL 版本上测试，并与他一起验证。）
- Windows 浏览器通过 WSL 的 localhost 转发访问 `http://127.0.0.1:<LIST_PORT>/`。要让手机访问，需要 Windows 侧的网络配置（镜像网络、端口代理、防火墙规则），这超出本工具范围，你也不得替使用者设置（安全底线第 4 条）；说明情况，交由使用者决定。

### 7.3 可选的导出工具

仅当使用者在 Q6 回答「是」并批准了确切命令时才做。用 `node -e "require.resolve('playwright')"`（或通过 `UI_CANVAS_PLAYWRIGHT_MODULE`）验证，并用画布工具栏的「导出 UI 稿」按钮测试导出。失败就如实报告错误信息，不要再自动安装其他东西。

### 7.4 安装 Easy UI Canvas 技能（仅当使用者在 Q7 选了「是」）

在 7.1 之后做，此时运行数据目录和端口已确定。使用者选「否」就跳过。

**1. 先弄清装什么、装到哪。** 技能就是整个仓库目录：`SKILL.md` 加 `scripts/`、`assets/`、`docs/`、`examples/`（要全部带上，不能只拷 `SKILL.md`：它用相对路径引用脚本和文档）。各工具、各范围的目标路径 `<SKILL_DIR>` 以 `SKILL.md` 开头「Install for your agent」那一段为准，下表与它一致（两处要同步修改）：

| 工具 | 全局 | 仅当前项目 |
| --- | --- | --- |
| Claude Code | `~/.claude/skills/easy-ui-canvas/` | `<PROJECT_DIR>/.claude/skills/easy-ui-canvas/` |
| Cursor | 请查 Cursor 最新文档里是否有全局位置 | `<PROJECT_DIR>/.cursor/skills/easy-ui-canvas/`，或在 Cursor 规则里引用 `<INSTALL_DIR>/SKILL.md` |
| Codex | `~/.codex/skills/easy-ui-canvas/` | 让 `<PROJECT_DIR>/AGENTS.md` 指向 `<INSTALL_DIR>/SKILL.md` |
| 其他 | 询问使用者，并阅读该工具文档 | 同左 |

**技能目录可能随工具版本变化。** 创建任何东西之前，先查该工具当前的文档（或它自带的帮助），确认技能从哪里加载，与上表对照；如果不一致，告诉使用者，并在其同意后用文档里的路径。缺失的上级目录只在使用者自己的主目录或项目里创建，不要用 `sudo`。

**2. 决定：一份还是两份。** 技能目录和部署选的安装目录（`<INSTALL_DIR>`）可以是同一份文件，也可以是两份独立副本。请明确告诉使用者会是哪一种，并让他选：

- **推荐：一份，软链。** 仓库克隆/保留在 `<INSTALL_DIR>`，`<SKILL_DIR>` 做成指向它的软链。以后更新只需在 `<INSTALL_DIR>` 里 `git pull`，技能、运行代码和文档不会脱节；多个工具或项目可以链接到同一个 `<INSTALL_DIR>`。
- **两份副本。** 把目录复制到 `<SKILL_DIR>`（例如工具或系统不跟随软链，或以后可能删掉 `<INSTALL_DIR>`）。副本不会自动更新：每次在 `<INSTALL_DIR>` 里 `git pull` 之后都要手动刷新，要告诉使用者。
- 如果 `<INSTALL_DIR>` 本来就在合适的位置（例如就是项目自己的 `.claude/skills/easy-ui-canvas/`），就不需要额外安装。

注意：运行数据目录里也有一份代码（`<RUNTIME_DIR>/app/`，由 `ensure-list` 同步），那是内部使用的，与技能放在哪里无关。

**3. 安装（在第 6 节的计划得到确认之后）。** 目标已存在就停下询问；不要悄悄删除或覆盖（要把旧的挪开，例如挪到 `<SKILL_DIR>.bak-<日期>`，也要先征得同意）。

```bash
mkdir -p "$(dirname <SKILL_DIR>)"
# 推荐：软链（一份）
ln -s <INSTALL_DIR> <SKILL_DIR>
# 或：复制（两份）；只复制需要的内容，不带 .git
mkdir -p <SKILL_DIR> && cp -R <INSTALL_DIR>/SKILL.md <INSTALL_DIR>/scripts <INSTALL_DIR>/assets <INSTALL_DIR>/docs <INSTALL_DIR>/examples <SKILL_DIR>/
```

软链方式在 Windows / WSL 下的注意点：在 WSL 里用 Linux 路径。运行在 Windows 一侧的工具（例如 Windows 版 Cursor 或 Claude Code）读的是 Windows 的用户目录（`C:\Users\<用户名>\...`），不是 WSL 的主目录，WSL 里建的软链在那边不一定能被跟随；这时要么把技能装到那个工具真正会看的位置（复制，或 Windows 软链 `mklink /D`，后者需要开发者模式或管理员权限，须经使用者同意），要么让工具也跑在 WSL 里。不要在没告诉使用者的情况下从 WSL 往 `/mnt/c` 下建链接。`<INSTALL_DIR>` 请放在 WSL 的 Linux 文件系统里，不要放在 `/mnt/c` 下。软链不能用就退回复制，并说明。

**4. 验证。**

```bash
test -f <SKILL_DIR>/SKILL.md && echo "SKILL.md ok"
ls <SKILL_DIR>            # SKILL.md scripts assets docs examples（若是软链，还有仓库的其余内容）
export UI_CANVAS_RUNTIME=<RUNTIME_DIR> UI_CANVAS_LIST_PORT=<LIST_PORT> UI_CANVAS_PORT_RANGE=<PORT_MIN>-<PORT_MAX>
<PYTHON3> <SKILL_DIR>/scripts/canvas.py ensure-list --bind <HOST>
```

`ensure-list` 必须使用与 7.1 **相同**的运行数据目录、列表端口和绑定（即上面的 export），因为它会把代码同步到 `<RUNTIME_DIR>/app/`，并且在没有服务应答时启动列表服务。只有在 7.1 已按这些值启动了服务时才运行它（这时它只会报告已在运行的那个）；如果使用者还没有确认过任何运行中的实例（例如选择以后再部署），就**不要**运行，只验证 `<SKILL_DIR>/SKILL.md` 和 `<PYTHON3> <SKILL_DIR>/scripts/canvas.py --help`，并且绝不在其他端口或另一个运行数据目录上额外启动实例。装了多个目标时，如果其余都是指向同一目录的软链，检查一个即可；每个副本至少检查 `SKILL.md` 和 `--help`。

**5. 告诉使用者**：刚装好的技能通常要在新会话里（或重启该工具后）才会被加载，当前这场对话可能还用不上。

## 8. 验证

使用 7.1 节输出里的真实 URL 和端口。把 `<CANVAS_PORT>` 换成画布的 `port`。

```bash
curl -s -o /dev/null -w "list page   %{http_code}\n" http://127.0.0.1:<LIST_PORT>/
curl -s -o /dev/null -w "canvas page %{http_code}\n" http://127.0.0.1:<CANVAS_PORT>/
curl -s -o /dev/null -w "phone page  %{http_code}\n" http://127.0.0.1:<CANVAS_PORT>/m/
curl -s http://127.0.0.1:<LIST_PORT>/healthz       # {"service": "ui-canvas-list", ...}
<PYTHON3> scripts/canvas.py list                   # 检查用画布应为 "running"
```

三个页面都必须返回 `200`。如果 `<HOST>` 不是本机地址，还要在本机上请求所选地址上的页面（`http://<HOST>:<LIST_PORT>/`；`auto` 时使用 `ensure-list` 打印的非本机 URL），期望 `200`。不要用会触及其他设备或防火墙的方式从机器外部测试；请使用者自己在手机上打开该 URL。

语言切换（该设置由列表页、所有画布、手机页和命令行共用）：

```bash
<PYTHON3> scripts/canvas.py lang                   # 记下当前值（"lang": null 表示 auto）
<PYTHON3> scripts/canvas.py lang zh
curl -s http://127.0.0.1:<LIST_PORT>/api/lang      # 期望 "effective": "zh"
curl -s http://127.0.0.1:<LIST_PORT>/ | grep -c 'window.UIC_LANG="zh"'   # 期望 1
<PYTHON3> scripts/canvas.py lang en                # 同样期望 "effective": "en"
<PYTHON3> scripts/canvas.py lang <ORIGINAL_VALUE>  # zh、en 或 auto：恢复使用者原来的设置，或他现在想要的
```

手机预览：请使用者在浏览器里打开画布，点「手机预览」并扫描二维码。只有当所选绑定包含可访问的非本机地址（`urls` 里有不是 `local-only` 的条目）且手机在同一网络时才能用；绑定 `127.0.0.1` 时手机打不开，请如实说明，不要报告成「可用」。

如果安装了自启，也要检查：`launchctl print` / `systemctl --user status` 显示服务在运行，列表页返回 `200`，并且（经使用者同意做测试时）重新登录或重启该服务后仍返回 `200`。

最后询问使用者是保留还是移除「Deploy check」画布。移除：`canvas.py stop --canvas <id>`，再 `canvas.py remove --canvas <id> --yes`（移到 `trash/`，可恢复）。

## 9. 交付总结：停止、重启、卸载

最后用使用者的语言写一段简短总结：安装在哪里、列表页 URL、绑定地址及其对「谁能访问」的含义、端口、运行数据目录、自启状态、导出状态、任何失败的地方。然后给出填好使用者真实值的下列命令（前面加上 7.1 节的 `export` 行，或传选项）。

停止与重启：

```bash
<PYTHON3> <INSTALL_DIR>/scripts/canvas.py list                          # id、端口、状态
<PYTHON3> <INSTALL_DIR>/scripts/canvas.py stop  --canvas <CANVAS_ID>     # 一个画布
<PYTHON3> <INSTALL_DIR>/scripts/canvas.py start --canvas <CANVAS_ID> --bind <HOST>
```

列表服务自己没有停止命令：

- macOS 自启：`launchctl bootout gui/$(id -u)/com.easy-ui-canvas.list`（停止并卸载），`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.easy-ui-canvas.list.plist`（重新加载）。
- Linux/WSL 自启：`systemctl --user stop|restart easy-ui-canvas-list.service`。
- 没有自启：用 `curl -s http://127.0.0.1:<LIST_PORT>/healthz`（字段 `pid`）找到进程号，用 `ps -p <PID> -o args=` 确认命令行包含 `canvas.py` 和 `list-serve`，再 `kill <PID>`。重新启动用 `ensure-list --bind <HOST>`。更新代码后运行 `ensure-list --restart-if-outdated --bind <HOST>`。

列表服务停止时，画布进程仍会继续运行。如果使用者想全部关掉，先逐个 `stop --canvas <id>`。重启电脑后所有画布都处于停止状态；从列表页或用 `start` 启动。

卸载（仅当使用者要求时，逐步确认）：

1. 停止所有画布（`list`，再 `stop --canvas <id>`）以及上面所述的列表服务。
2. 移除自启：macOS 用 `canvas.py uninstall-list-agent --yes`（或 `launchctl bootout ...` 并把 plist 移走）；Linux/WSL 用 `systemctl --user disable --now easy-ui-canvas-list.service`，再删除 `~/.config/systemd/user/easy-ui-canvas-list.service` 并运行 `systemctl --user daemon-reload`；Windows 用 `schtasks /Delete /TN "Easy UI Canvas" /F`。
3. 运行数据目录里是使用者的画布和评论。除非使用者明确要求，不要删除；可以提议把它移到备份位置。
4. 安装目录只是仓库本身；使用者要求时才删除。

技能：说明是否已安装、给哪个（哪些）工具、确切的 `<SKILL_DIR>` 路径，以及每处是指向 `<INSTALL_DIR>` 的软链（在那里 `git pull` 即可更新）还是独立副本（每次更新后要手动刷新）。如果使用者没装，说明以后怎么装（7.4 节），以及不装的话助手不会知道如何创建画布、读取评论。

最后告诉使用者如何给助手布置设计任务。在**新会话**里（刚装好的技能通常当前会话加载不到；请重启工具或新开对话，Claude Code、Codex 等如果有技能列表，可以确认它已出现）说：

> 使用 Easy UI Canvas 技能。<描述你想要的界面，或：读取我画布上的评论并更新设计>

（见 `SKILL.md`）。使用者在画布上写的评论，助手可以在下一次会话里读取。如果没装技能，使用者仍可以每次任务都让助手去读 `<INSTALL_DIR>/SKILL.md`。
