# Easy UI Canvas

作者：karlarso · Apache-2.0

[English](README.md) | 简体中文

> **⚠️ 无登录验证：仅限本机或可信网络使用。**

> **要部署？把 [DEPLOY.zh-CN.md](DEPLOY.zh-CN.md) 交给你的 AI 助手。**

## 🚀 一键部署

用哪一句？Easy UI Canvas 还没装到这台机器上，用第一句。已经在运行（列表页开着，画布也在），只想让一个新的助手（另一个 AI 工具，或新开的会话）装上 skill、接着用现有实例，用第二句。

**还没安装。** 把下面这句话交给你的 AI 助手（Claude Code、Cursor、Codex 等）。它会读取 [DEPLOY.zh-CN.md](DEPLOY.zh-CN.md)，就绑定地址、是否开机自启、端口、数据位置、是否导出等细节向你逐项确认，并在你确认计划后才部署。它还会询问是否给你的 AI 工具安装 Easy UI Canvas skill（以及装在哪里），你同意后一并安装。

```text
读取 https://raw.githubusercontent.com/karlarso/easy-ui-canvas/main/DEPLOY.zh-CN.md ，并按它部署 Easy UI Canvas。改动任何东西之前，先问我绑定地址和是否开机自启。
```

默认只在本机使用（`127.0.0.1`）；助手在向你的网络开放任何访问之前必须先提醒你，因为本工具没有登录验证。English: [DEPLOY.md](DEPLOY.md)。

**已经在运行：只安装 skill。** 把下面这句话交给新的助手。它会读取 [SKILL.md](SKILL.md) 和 [DEPLOY.zh-CN.md 的「已有部署上只安装 skill」](DEPLOY.zh-CN.md#skill-only-install)，问你这个工具的 skill 装在哪里、怎么装，装好后找到正在运行的实例，确认能访问，再告诉你可以使用了。绑定地址、开机自启、端口、数据位置和已有画布都保持原样。English: [DEPLOY.md](DEPLOY.md#skill-only-install)。

```text
Easy UI Canvas 已经部署好并在运行。不要重新部署，也不要改绑定地址、开机自启、端口或数据位置，不要停止或移除任何画布。
请读取 https://raw.githubusercontent.com/karlarso/easy-ui-canvas/main/SKILL.md 和 https://raw.githubusercontent.com/karlarso/easy-ui-canvas/main/DEPLOY.zh-CN.md 里的「已有部署上只安装 skill」一节，并且只按那一节做。
先问我这个 AI 工具的 skill 要装到哪里、怎么装，装好后找到正在运行的实例，确认你能访问它，然后告诉我可以开始了。
```

## 🎨 简介

一个本地运行的 **UI 设计探索画布**：把多个 HTML 界面（帧）并排放在可缩放、可拖动的画布上，按元素评论，在手机上点着走流程，并让 AI 编程助手在下一次会话里读取并回复评论。它只依赖 Python 3 标准库，既可作为 agent skill（Claude Code、Cursor、Codex）使用，也可以当普通命令行工具用。

## ✨ 为什么用它

- 🔌 **不绑定任何一家 AI。** 任何能读文件、能运行命令的 AI 编程工具（Claude Code、Cursor、Codex 等）都能用，换工具、换模型不用换画布。
- 🏠 **无账号、无 token，数据都在自己机器上。** 只用 Python 标准库，无云服务、无构建步骤；一句话就能让 AI 帮你部署。共享范围完全由你控制；本工具没有登录验证，共享请只在可信网络内进行（见下文「安全」一节）。
- ⚡ **反馈快而精确。** 评论直接锚定到具体元素，AI 一读就知道你指的是哪里；部署完成后，从提需求、出界面到逐元素反馈，整个循环很顺畅。
- 🧱 **设计稿就是真实的 HTML/CSS，不是图片。** 可以直接复用成代码，没有“设计转开发”这一步。

## 💬 使用示例

Easy UI Canvas 运行起来、助手也装好了 skill（见上文「一键部署」一节）之后，一句话就够了：怎么建画布或接着改已有的画布、写帧、让元素可评论、把界面串起来、把地址交给你，这些 skill 都已经知道。五个典型场景：

### 1. 设计一套 App 组件库

```text
用 Easy UI Canvas 帮我设计一套记账 APP 的组件库：
按钮、输入框、卡片、列表项。
```

> 后续：AI 会给你一个画布链接，你在上面点选元素写评论，AI 读取评论后继续修改。

### 2. 改进自己项目里的某个页面

把占位符换成你自己仓库里的页面（比如 pricing 页面）。

```text
用 Easy UI Canvas 把我这个仓库里的 <某个页面，如 pricing 页面>
现状画下来，再给我两个改进版本放在旁边对比。
```

> 后续：AI 会给你一个画布链接，你在上面点选元素写评论，AI 读取评论后继续修改。

### 3. 设计新功能

```text
用 Easy UI Canvas 设计“团队共享相册”功能的界面，
包含创建相册、邀请成员、浏览三个页面。
```

> 后续：AI 会给你一个画布链接，你在上面点选元素写评论，AI 读取评论后继续修改。

### 4. 接着改已有画布

说出画布的名字，或把画布链接交给助手。

```text
用 Easy UI Canvas 接手我已有的画布 <画布名字或链接>，
先读里面的帧和评论，再在这块画布上继续改。
```

> 后续：AI 会找到这块画布（有多块对得上时会先问你），读它的帧和评论（含状态），在同一块画布上继续改。如果画布停着，会先启动它，然后把链接给你。

### 5. 从导出的 UI 稿接着设计

把「导出 UI 稿」得到的 ZIP（离线页面、截图、资源和 `HANDOFF.md`）交给助手。助手会先解压，再用导出的帧新建画布；没有一步导入的命令。

```text
用 Easy UI Canvas 从我导出的这份 UI 稿 ZIP
<ZIP 的路径> 新建一块画布，并在上面继续设计。
```

> 后续：AI 会解压 ZIP，阅读 `HANDOFF.md`，用导出的帧和 `project.json` 新建一块画布，然后把链接给你。ZIP 里没有评论，新画布也不会有。

其余细节（帧结构、元素 id、点击跳转、手机预览、如何回复评论）都由 skill 处理，见 [SKILL.md](SKILL.md)。手机预览要求手机能访问画布地址，这需要非本机的绑定（见 [DEPLOY.zh-CN.md](DEPLOY.zh-CN.md)）。

## 🖼️ 截图

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

## 🧩 功能

- 🗂️ **多帧画布**：平铺视图，支持缩放、平移、小地图和适合窗口；帧是你或 agent 编写的普通 HTML/CSS 片段。
- 💬 **元素评论**：点选任意元素（或整个 frame、frame 的标题和副标题、分组标题栏，以及画布上独立的批注块 note）写意见，标记为待处理 / 已修改 / 需讨论，可「复制给 AI」，也可在命令行回复。
- 📱 **流程视图与手机预览**：给按钮加 `data-goto`，原型可在画布内和手机上的 `/m/` 页面点着走（带二维码）。画布内的流程视图里也能开启评论模式，对当前这一帧点选元素写意见（评论模式下点击只选元素、不跳转）；`/m/` 仍是只读预览。同一页面的多个状态 frame 里，给滚动容器加相同的 `data-keep-scroll="组名"`，跳转时就保留滚动位置。
- 📝 **设计说明**：在 `project.json` 旁放一个 `DESIGN.md`，工具栏的「设计说明」按钮即可只读查看（历史版本也会显示当时快照里的那份）。
- 🕘 **快照**：保留旧版本及其评论，只读回看。
- 📋 **多个画布，一个列表页**：每个画布是一个独立的小服务，列表页负责启动、停止和移除。
- 📤 **UI 稿交接导出**：一个 ZIP，含离线页面、截图、资源和 `HANDOFF.md`（需要可选的外部工具，见下）。
- 🌐 **中英文界面**，在列表页切换；服务器错误信息和命令行输出同样支持。
- 🪶 **无需构建、不依赖 CDN、不需要第三方 Python 包。**
- 📁 **纯文件，可放进 git**：画布就是目录里的普通文件（HTML、JSON、资源），可以直接放进 git 仓库。
- 📄 **开源**：Apache-2.0。

评论不限于界面内部：frame 的标题和副标题、分组（group）的标题栏开箱即可点选；画布（board）上独立的批注块 note（在 `project.json` 的 `notes` 里声明，每块一个 HTML 片段）可以放在任意位置，对批注块和分组标题栏的评论都归在「画布」这个 frame 名下。详见 [docs/project-format.md](docs/project-format.md)（英文）。

## 🛠️ 手动安装（不用 AI 部署时）

<details>
<summary>展开手动安装步骤</summary>

要求：Python 3.9 及以上；macOS 或 Linux（Windows 请使用 WSL）。

```bash
git clone https://github.com/karlarso/easy-ui-canvas.git easy-ui-canvas
cd easy-ui-canvas
python3 scripts/canvas.py ensure-list                  # 在 http://127.0.0.1:4042/ 启动列表服务
python3 scripts/canvas.py new --name "我的第一个画布"    # 用示例创建画布并启动
```

项目格式见 [docs/project-format.md](docs/project-format.md)（英文）。

</details>

## 📦 依赖

- **运行时只需要 Python 3 标准库**，无需 `pip install`。
- **「导出 UI 稿」（可选）** 需要整页截图，因此需要你自行安装 Node.js、[Playwright](https://playwright.dev/) 以及 Chromium 或 Google Chrome（例如 `npm install playwright`、`npx playwright install chromium`）。它们是可选的外部工具，不随本仓库分发，也不会被自动安装。找不到 Playwright 时可设置 `UI_CANVAS_PLAYWRIGHT_MODULE`。不用导出时无需这些。
- **测试**只用标准库和 Node.js；浏览器冒烟测试和二维码交叉验证另用其文件头注明的可选包，缺少时会自动跳过。

## 💻 平台

支持 macOS 和 Linux；Windows 请使用 WSL。开机自启是可选项，见 [DEPLOY.zh-CN.md](DEPLOY.zh-CN.md)（交给 AI 助手的部署指南）和 [docs/autostart.md](docs/autostart.md)（macOS LaunchAgent、Linux systemd、WSL）。

## 🔒 安全

**没有任何登录验证。** 能访问端口的人都可以查看并修改你的画布和评论。

- 默认所有服务只监听 `127.0.0.1`，并拒绝 `Host` 头不是回环地址的请求（防 DNS 重绑定）。写接口只接受同源请求。
- 要让其他设备（例如同一 Wi-Fi 下的手机）访问，必须显式指定：`--host 0.0.0.0`、`--host <地址>`、`--host auto`（检测到的局域网/VPN 地址）或环境变量 `UI_CANVAS_BIND`。请只在可信网络中这样做。命令输出会标明每个 URL 是否仅限本机。
- 帧的 HTML 由你或 agent 编写；不要把不可信的第三方页面当作帧导入（片段里的脚本不会执行，但 CSS 和标记会生效）。

## 🌐 语言

在列表页选定语言之前，界面跟随浏览器语言（`zh*` 为中文，其余为英文）；选择会保存在服务端，所以所有画布、手机预览和命令行保持一致。详见 [docs/i18n.md](docs/i18n.md)。

## 📁 目录结构

```text
scripts/canvas.py        命令行与服务（Python 标准库）
scripts/export_ui.py, export-ui.cjs   UI 稿交接导出
assets/                  前端（canvas.html/js/css、list.html、mobile.html、i18n.js、i18n.json）
examples/en, examples/zh 示例项目
docs/                    格式、行为、i18n、自启动
DEPLOY.md, DEPLOY.zh-CN.md   交给 AI 助手的部署指南
tests/                   测试
SKILL.md                 agent 说明
```

运行测试请见 [CONTRIBUTING.md](CONTRIBUTING.md) 中的 [Running the tests](CONTRIBUTING.md#running-the-tests)。

## 📄 许可证

版权所有 2026 karlarso，采用 Apache-2.0 许可，第三方声明见 [NOTICE](NOTICE)。完整条款见 [LICENSE](LICENSE)。

第三方说明：`assets/canvas.js` 中的二维码编码器改编自 Project Nayuki 的 QR Code generator（MIT 许可），详见 [NOTICE](NOTICE)。
