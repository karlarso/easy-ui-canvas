# Easy UI Canvas

作者：karlarso · Apache-2.0

[English](README.md) | 简体中文

> **要部署？把 [DEPLOY.zh-CN.md](DEPLOY.zh-CN.md) 交给你的 AI 助手。**

## 一键部署

把下面这句话交给你的 AI 助手（Claude Code、Cursor、Codex 等）。它会读取 [DEPLOY.zh-CN.md](DEPLOY.zh-CN.md)，就绑定地址、是否开机自启、端口、数据位置、是否导出等细节向你逐项确认，并在你确认计划后才部署。

```text
读取 https://raw.githubusercontent.com/karlarso/easy-ui-canvas/main/DEPLOY.zh-CN.md ，并按它部署 Easy UI Canvas。改动任何东西之前，先问我绑定地址和是否开机自启。
```

默认只在本机使用（`127.0.0.1`）；助手在向你的网络开放任何访问之前必须先提醒你，因为本工具没有登录验证。English: [DEPLOY.md](DEPLOY.md)。

## 简介

一个本地运行的 **UI 设计探索画布**：把多个 HTML 界面（帧）并排放在可缩放、可拖动的画布上，按元素评论，在手机上点着走流程，并让 AI 编程助手在下一次会话里读取并回复评论。它只依赖 Python 3 标准库，既可作为智能体技能（Claude Code、Cursor、Codex）使用，也可以当普通命令行工具用。

## 使用示例

Easy UI Canvas 运行起来、助手也装好了技能（见上文）之后，你可以直接用大白话让它出设计稿。下面是三个典型场景，每个都有可直接复制的一句话和常见的后续步骤。三个场景里，助手都会把帧写成 HTML 片段，给你可能要讨论的元素加上稳定的 `data-ui-id` 和 `data-ui-label`，并告诉你画布的地址。

### 1. 设计一套 App 组件库

适用于想把按钮、输入框、卡片、导航并排看，并且同时看浅色和深色。

```text
使用 Easy UI Canvas 技能。为一个手机 App 新建名为「App 组件库」的画布。每类组件做一个帧（按钮、输入框、卡片、导航栏和标签栏），每类各做浅色和深色两个版本：把组件类别写在帧的 group，把「light」或「dark」写在帧的 state。在帧里展示按下、禁用、报错等状态，并给每个组件加稳定的 data-ui-id 和 data-ui-label，方便我评论。不要画手机状态栏。
```

后续：打开画布，点选元素写评论（「按钮圆角太大」「深色下卡片需要描边」），然后对助手说：「读取组件库画布上的评论，按评论修改各帧，并逐条回复。」它会运行 `canvas.py comments --canvas <id>`，较大改动前先做快照，修改各帧，用 `canvas.py reply ... --status changed` 记录每条改动，你再回来看。

### 2. 优化线上已有页面

适用于页面已经存在，想把「现状」和「优化版」并排对照。

```text
使用 Easy UI Canvas 技能。我要优化的页面是：<页面地址>（如果你自己打不开，我会改为提供截图或保存下来的 HTML）。请手动把现状复刻成一个标题为「现状」的帧（state：current），保留结构和文案；再在它旁边做一个「优化版」帧（state：proposed），解决我下面列出的问题，并在两个帧里给对应元素使用相同的 data-ui-id，方便评论对应起来。问题：<你和用户不满意的地方>。
```

助手只能使用它真正能访问到的内容：它能打开的公开页面，或你提供的截图、HTML 文件。它不会替你登录任何站点，也不会照搬别人网站的脚本（帧是静态 HTML/CSS，脚本不会运行）。后续：在「优化版」帧上对喜欢或不喜欢的差异写评论，然后让助手读取评论、调整该帧（会先给旧版本做快照）并回复。

### 3. 根据新功能需求设计新界面

适用于手上有 PRD 或一句话需求，想要一个能在手机上点着试的原型。

```text
使用 Easy UI Canvas 技能。需求：<粘贴 PRD 或一句话需求>。把主流程的各个界面做成独立的帧（入口、各个步骤、成功页、主要的出错情况），按步骤给每个帧命名，并在每个按钮（包括返回按钮）上加 data-goto 把它们串起来，让流程可以点击。设置起始帧。然后告诉我画布地址和怎么打开手机预览。
```

后续：在画布里打开「流程」视图，或点「手机预览」扫二维码，在手机上走一遍流程（手机必须能访问画布地址，这需要非本机的绑定，见 [DEPLOY.zh-CN.md](DEPLOY.zh-CN.md)）。在流程让人困惑的地方写评论，再让助手读取评论，修改界面或界面之间的跳转。

## 截图

以下均为真实运行实例的截图，使用仓库自带的示例项目（三个界面的 App 设计）。截图中的画布界面为英文；切换语言后工具栏和提示会变成中文。

**画布列表页**：每个画布是一个独立的小服务，列表页负责启动、停止和移除。

![画布列表页，含一个英文示例和一个中文示例](docs/images/list-page.png)

**画布平铺视图**：App 主界面、详情页、设置页并排展示。

![画布页：主界面、详情页、设置页三帧](docs/images/canvas-app-home.png)

**添加评论**：打开评论模式，点中某个元素（高亮）后写下意见。

![评论模式：选中主按钮并弹出评论框](docs/images/canvas-add-comment.png)

**评论面板**：所有意见集中在一处，可标记状态、复制给 AI。

![右侧评论面板，含两条评论](docs/images/canvas-comments-panel.png)

**手机预览**：扫码即可在手机上打开只读预览页。

![手机预览弹窗：二维码和预览链接](docs/images/canvas-qr.png)

## 功能

- **多帧画布**：平铺视图，支持缩放、平移、小地图和适合窗口；帧是你或智能体编写的普通 HTML/CSS 片段。
- **元素评论**：点选任意元素（或整帧）写意见，标记为待处理 / 已修改 / 需讨论，可「复制给 AI」，也可在命令行回复。
- **流程视图与手机预览**：给按钮加 `data-goto`，原型可在画布内和手机上的 `/m/` 页面点着走（带二维码）。
- **快照**：保留旧版本及其评论，只读回看。
- **多个画布，一个列表页**：每个画布是一个独立的小服务，列表页负责启动、停止和移除。
- **UI 稿交接导出**：一个 ZIP，含离线页面、截图、资源和 `HANDOFF.md`（需要可选的外部工具，见下）。
- **中英文界面**，在列表页切换；服务器错误信息和命令行输出同样支持。
- **无需构建、不依赖 CDN、不需要第三方 Python 包。**

## 快速开始

要求：Python 3.9 及以上；macOS 或 Linux（Windows 请使用 WSL）。

```bash
git clone <repo-url> easy-ui-canvas
cd easy-ui-canvas
python3 scripts/canvas.py ensure-list                  # 在 http://127.0.0.1:4042/ 启动列表服务
python3 scripts/canvas.py new --name "我的第一个画布"    # 用示例创建画布并启动
```

打开 `new` 输出的 `url`（或在列表页点选画布）。把画布目录（输出里的 `dir`）中的示例帧（`frames/*.html`、`project.json`）换成你自己的设计，刷新页面即可。格式见 [docs/project-format.md](docs/project-format.md)（英文）。

常用命令：

```bash
python3 scripts/canvas.py list                          # 画布、端口和状态
python3 scripts/canvas.py stop   --canvas <id>
python3 scripts/canvas.py start  --canvas <id>
python3 scripts/canvas.py comments --canvas <id>        # 读取评论
python3 scripts/canvas.py reply  --canvas <id> --comment-id <cid> --status changed --text "已修改"
python3 scripts/canvas.py snapshot --canvas <id>        # 改版前先保留当前版本
python3 scripts/canvas.py lang zh                       # 或 en / auto
```

画布数据保存在 `~/ui-canvas-runtime/`（可用 `UI_CANVAS_RUNTIME` 修改）。移除画布只是把它移入该目录下的 `trash/`。

### 作为智能体技能使用

[SKILL.md](SKILL.md) 告诉智能体如何操作本工具。**Claude Code**：把本目录复制到 `~/.claude/skills/easy-ui-canvas/`。**Cursor**：复制到 `.cursor/skills/easy-ui-canvas/`，或在规则里引用 `SKILL.md`。**Codex**：复制到 `~/.codex/skills/easy-ui-canvas/`，或让 `AGENTS.md` 指向 `SKILL.md`。（技能目录以各工具的最新文档为准。）

## 依赖

- **运行时只需要 Python 3 标准库**，无需 `pip install`。
- **「导出 UI 稿」（可选）** 需要整页截图，因此需要你自行安装 Node.js、[Playwright](https://playwright.dev/) 以及 Chromium 或 Google Chrome（例如 `npm install playwright`、`npx playwright install chromium`）。它们是可选的外部工具，不随本仓库分发，也不会被自动安装。找不到 Playwright 时可设置 `UI_CANVAS_PLAYWRIGHT_MODULE`。不用导出时无需这些。
- **测试**只用标准库和 Node.js；浏览器冒烟测试和二维码交叉验证另用其文件头注明的可选包，缺少时会自动跳过。

## 平台

支持 macOS 和 Linux；Windows 请使用 WSL。开机自启是可选项，见 [DEPLOY.zh-CN.md](DEPLOY.zh-CN.md)（交给 AI 助手的部署指南）和 [docs/autostart.md](docs/autostart.md)（macOS LaunchAgent、Linux systemd、WSL）。

## 安全

**没有任何鉴权。** 能访问端口的人都可以查看并修改你的画布和评论。

- 默认所有服务只监听 `127.0.0.1`，并拒绝 `Host` 头不是回环地址的请求（防 DNS 重绑定）。写接口只接受同源请求。
- 要让其他设备（例如同一 Wi-Fi 下的手机）访问，必须显式指定：`--host 0.0.0.0`、`--host <地址>`、`--host auto`（检测到的局域网/VPN 地址）或环境变量 `UI_CANVAS_BIND`。请只在可信网络中这样做。命令输出会标明每个 URL 是否仅限本机。
- 帧 HTML 由你或智能体编写；不要把不可信的第三方页面当作帧导入（片段里的脚本不会执行，但 CSS 和标记会生效）。

## 语言

在列表页选定语言之前，界面跟随浏览器语言（`zh*` 为中文，其余为英文）；选择会保存在服务端，所以所有画布、手机预览和命令行保持一致。详见 [docs/i18n.md](docs/i18n.md)。

## 测试

```bash
sh tests/run_all.sh
```

依次运行：i18n 一致性检查、端到端服务测试（临时运行目录和空闲端口）、快照接口测试、滚轮路由测试，以及（装有可选包时）二维码交叉验证和无头浏览器冒烟测试。见 [tests/README.md](tests/README.md)。

## 目录结构

```text
scripts/canvas.py        命令行与服务（Python 标准库）
scripts/export_ui.py, export-ui.cjs   UI 稿交接导出
assets/                  前端（canvas.html/js/css、list.html、mobile.html、i18n.js、i18n.json）
examples/en, examples/zh 示例项目
docs/                    格式、行为、i18n、自启动
DEPLOY.md, DEPLOY.zh-CN.md   交给 AI 助手的部署指南
tests/                   测试
SKILL.md                 智能体说明
```

## 许可证

Copyright 2026 karlarso, licensed under Apache-2.0, third-party notice see NOTICE（版权所有 2026 karlarso，采用 Apache-2.0 许可，第三方声明见 NOTICE）。详见 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)。

第三方说明：`assets/canvas.js` 中的二维码编码器改编自 Project Nayuki 的 QR Code generator（MIT 许可），详见 [NOTICE](NOTICE)。
