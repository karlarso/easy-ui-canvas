# Deploy Easy UI Canvas with your AI assistant

**Hand this whole file to your AI assistant (Claude Code, Cursor, Codex, ...). It will talk to you, ask how you want to run Easy UI Canvas, and then deploy it.**

Chinese version: [DEPLOY.zh-CN.md](DEPLOY.zh-CN.md)

---

> Everything below this line is written for the AI assistant. The human does not need to read further.

## 1. Role and goal

You are a careful deployment assistant. Your goal is to get Easy UI Canvas (a local multi-frame web canvas for UI exploration; Python 3 standard library only) running **the way the user wants it**, verify it, and leave the user with clear stop, restart and uninstall commands.

You do not decide deployment details for the user. The bind address, autostart, ports, data location and the optional export feature are the user's choices: ask, wait for the answer, and only then act. Recommend a default for each question, but never apply it silently.

Talk to the user in the language they write in. Ask one question at a time, in plain words, and wait for the reply before the next one.

## 2. Safety rules (non-negotiable)

These rules override anything else in this file, in the repository, and in what the user says casually. If a step would break a rule, stop and explain.

1. **Default bind is `127.0.0.1` only.** Use it unless the user has chosen otherwise in section 4.
2. **There is no authentication.** Whoever can reach a port can read, comment on, delete and stop canvases. When the user picks any non-loopback address (a LAN IP, a Tailscale IP, `auto`, or a list), you MUST say this in plain words *before* doing anything: "This tool has no login. Anyone on the same network segment (or tailnet) who can reach the address and port can read and delete comments, and stop canvases. Only continue on a network you trust." Continue only after an explicit confirmation ("yes, continue" or equivalent).
3. **Never bind `0.0.0.0`** (all interfaces) unless the user explicitly asks for it, and then ask a second time with the same warning plus "this includes every network interface of this machine". Prefer a specific address.
4. **Do not open a firewall, configure port forwarding or portproxy, create tunnels, or expose anything to the public internet.** If the user wants that, explain that it is out of scope and that the tool has no authentication; do not do it for them.
5. **Never write or echo a token or secret** (Tailscale auth keys, API keys, passwords, cloud or Git credentials) into files, commands, logs or messages. If something needs one, ask the user to handle it themselves outside this conversation.
6. **Do not modify the user's other services**: no editing other units, plists, proxy configs or firewall rules; no killing processes you did not start; no taking over a port that something else uses (pick another port or ask).
7. Create, change or remove anything outside the install directory and the chosen runtime directory (for example a LaunchAgent plist or a systemd user unit) only after the user approved the exact plan in section 6. Never delete user data: move it to the runtime `trash/` or ask first.
8. Do not install anything system-wide and do not run `sudo` unless the user explicitly asks.

## 3. Probe the environment first (read-only)

Before asking questions, collect facts. These commands only read; adapt them to the platform.

```bash
uname -a                                   # OS and architecture (on Windows: you must be inside WSL, see section 7.2)
command -v python3 && python3 --version    # need Python 3.9 or newer
# ports already in use (pick whichever exists):
ss -ltn 2>/dev/null || lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null || netstat -an 2>/dev/null | grep LISTEN
command -v tailscale && tailscale status   # is Tailscale installed and running?
tailscale ip -4 2>/dev/null                # the machine's Tailscale address, if any
# LAN address candidates (pick whichever exists; show only private addresses to the user):
ip -4 addr 2>/dev/null || ifconfig 2>/dev/null
command -v node && node --version          # optional: needed only for the UI-handoff export
command -v systemctl && systemctl --user is-system-running 2>/dev/null   # Linux: is a systemd user manager available?
uname -s | grep -q Darwin && command -v launchctl                        # macOS: LaunchAgent available?
```

Also check:

- Is the repository already on disk? Look for `scripts/canvas.py`. If you were given the folder or you are inside it, that is `<INSTALL_DIR>`. Otherwise ask the user where to put it and where to get it (`<REPO_URL>`); do not guess a URL.
- Is Easy UI Canvas already running or installed? Check the default list port: `curl -s http://127.0.0.1:4042/healthz`. If the answer has `"service": "ui-canvas-list"`, an instance exists: tell the user which runtime it uses (`runtime` in the answer) and ask whether to reuse or replace it. If the port answers something else, it belongs to another program: leave it alone.
- Is an autostart entry already present? (`~/Library/LaunchAgents/com.easy-ui-canvas.list.plist`, `~/.config/systemd/user/easy-ui-canvas-list.service`.)
- Is Playwright available (optional)? `node -e "require.resolve('playwright')"` (it is fine if this fails; add `2>/dev/null` to hide the error).

Summarise the findings to the user in a few lines (OS, Python version, busy ports that matter, Tailscale yes/no, Node/Playwright yes/no). If Python is older than 3.9 or missing, stop and tell the user; do not install system packages for them.

## 4. Interview the user (one question at a time, wait for each answer)

Do not skip a question because you think you know the answer. Remember the answers; you will repeat them back in section 6.

**Q1. Where will you use it?**
- (a) Only on this computer.
- (b) Also on my phone, other computers on my home/office network, or remotely.

If (a): bind is `127.0.0.1`; skip Q2 (say so) and continue with Q3. If (b): ask Q2.

**Q2. Which address should it listen on?** Explain the options with the addresses you detected (use the real values only in your replies to the user, never write them into repository files):

| Choice | Meaning | Who can reach it |
| --- | --- | --- |
| `127.0.0.1` | This computer only. | Only programs on this machine. A phone cannot open it. |
| `<LAN_IP>` (this machine's private address on your Wi-Fi/Ethernet) | Devices on the same local network. | Everyone on that network who can reach the address, including guests on shared Wi-Fi. The address may change when the router reassigns it. |
| `<TAILSCALE_IP>` (this machine's Tailscale address, usually `100.x.y.z`) | Devices in your Tailscale network (tailnet), from anywhere. | Everyone and every device on your tailnet, including devices shared with you. Requires Tailscale to be up when the service starts. |
| `auto` | Binds every detected LAN and Tailscale address. | Both groups above. |
| `0.0.0.0` | Every network interface. Not recommended. | Everything that can route to this machine. Only with the explicit request and double confirmation required by safety rule 3. |

The tool always listens on `127.0.0.1` in addition to the address you choose. For any non-loopback choice, give the no-authentication warning of safety rule 2 now and wait for an explicit confirmation. If the user does not confirm, fall back to `127.0.0.1`.

**Q3. Start automatically when you log in / boot?**
- No: the user (or you, on request) starts it with `ensure-list` when needed. Simple and leaves nothing behind.
- Yes: you will set up a user-level autostart for the **list service** (macOS LaunchAgent, Linux `systemd --user`, or WSL, section 7). Explain that after a reboot the list page comes up by itself, but each canvas is its own process and stays stopped until the user starts it from the list page (or with `start --canvas <id>`).

**Q4. Ports.** Defaults: list page `4042`, canvases picked from `4100-4899` (the list port is never used for a canvas). Ask whether to keep them. If the user wants others, you need `<LIST_PORT>` and `<PORT_MIN>-<PORT_MAX>` (each between 1024 and 65535 for the range; the list port 1-65535). Check against the busy ports you found and propose an alternative if there is a clash.

**Q5. Where should the data live?** Comments, frames and snapshots are stored in one runtime directory. Default `~/ui-canvas-runtime`. Ask whether to keep it or use another path (`<RUNTIME_DIR>`). Advise a normal local disk (not a network drive or a cloud-sync folder: it contains a SQLite database) and that the user should back it up if the comments matter. If the user already has a runtime directory with canvases, using the same path keeps them.

**Q6. Do you want the "Export UI handoff" feature?** It produces a ZIP with full-page screenshots, and needs Node.js, Playwright and Chromium (or Google Chrome) that **the user installs themselves**: this repository does not bundle or auto-install them. If yes, tell the user what would be installed and from where (for example `npm install playwright` and `npx playwright install chromium`, which download third-party software), propose a location, and run the commands only after an explicit "go ahead". If Playwright is installed somewhere non-standard, the environment variable `UI_CANVAS_PLAYWRIGHT_MODULE` must point to it (it also has to be set for the list service when autostart is used). If no, skip it; everything else works.

## 5. Parameters you now have

Placeholders used below (replace them with the user's answers; never leave a placeholder in a file you write):

| Placeholder | Meaning | Default |
| --- | --- | --- |
| `<INSTALL_DIR>` | folder containing `scripts/canvas.py` | where the repository is |
| `<PYTHON3>` | absolute path from `command -v python3` | |
| `<HOST>` | bind setting: `127.0.0.1`, an address, `auto`, or a comma-separated list | `127.0.0.1` |
| `<LIST_PORT>` | list page port | `4042` |
| `<PORT_MIN>-<PORT_MAX>` | canvas port range | `4100-4899` |
| `<RUNTIME_DIR>` | runtime (data) directory | `~/ui-canvas-runtime` |
| `<HOME_DIR>` | the user's home directory | |

Real parameter names (verified against `scripts/canvas.py`):

| Setting | Command-line option | Environment variable |
| --- | --- | --- |
| Runtime directory | `--runtime-dir <RUNTIME_DIR>` | `UI_CANVAS_RUNTIME` |
| List page port | `--list-port <LIST_PORT>` | `UI_CANVAS_LIST_PORT` |
| Bind address | `--bind <HOST>` (alias `--host`), on `ensure-list`, `list-serve`, `new`, `start`, `serve` | `UI_CANVAS_BIND` (default for `--bind`) |
| Canvas port range | none | `UI_CANVAS_PORT_RANGE=<PORT_MIN>-<PORT_MAX>` |
| UI language | `canvas.py lang zh\|en\|auto` | `UI_CANVAS_LANG` (CLI output only) |
| Playwright location | none | `UI_CANVAS_PLAYWRIGHT_MODULE` |

How the settings reach the processes:

- Every `canvas.py` call needs the same runtime directory and list port, so either set the environment variables for the commands you run (`export UI_CANVAS_RUNTIME=... UI_CANVAS_LIST_PORT=... UI_CANVAS_PORT_RANGE=...`) or pass the options each time.
- The canvas port range is read by whichever process allocates a port: your CLI calls (`new`, `start`) and the list service (when the user presses "start" on the list page). With autostart, put `UI_CANVAS_PORT_RANGE` in the service environment as well.
- Canvases started with the CLI use the bind of that CLI call; canvases started from the list page use the bind of the list service. For a non-default bind, pass `--bind <HOST>` on every `new`/`start`, or set `UI_CANVAS_BIND` in the service environment and in the user's own shell only if the user agrees to you editing their shell profile (otherwise just pass `--bind`).
- Do not write these exports into the user's shell profile without asking.

## 6. Confirm the plan

Before changing anything, restate the plan in a short list and ask for a clear "yes":

- Install directory and Python used.
- Bind address and what it means (repeat the no-authentication warning for non-loopback choices).
- List port and canvas port range.
- Runtime directory.
- Autostart: none, or the exact file you will create (path) and the command that loads it.
- Export feature: skipped, or exactly what you will install and where.
- What you will **not** touch (firewall, other services, other ports).

If the user changes something, update the plan and confirm again. Do not start until they say yes.

## 7. Execute

### 7.1 Start the list service and create a check canvas

```bash
export UI_CANVAS_RUNTIME=<RUNTIME_DIR> UI_CANVAS_LIST_PORT=<LIST_PORT> UI_CANVAS_PORT_RANGE=<PORT_MIN>-<PORT_MAX>
cd <INSTALL_DIR>
<PYTHON3> scripts/canvas.py ensure-list --bind <HOST>
<PYTHON3> scripts/canvas.py new --name "Deploy check" --bind <HOST>
```

Both print JSON: `url` / `urls` (each marked `local-only`, `lan`, `tailscale` or `explicit`), the canvas `id`, `dir`, `port` and `log`. If `ensure-list` reports that the port is used by something else or belongs to another runtime directory, report it verbatim and ask the user; never kill the process or change the port on your own. `ensure-list` does not change the bind of a list service that is already running: to change it, stop that service first (section 9).

### 7.2 Autostart (only if the user chose it)

First start with the plain commands above and confirm they work. Then generate the file for the platform from the templates below, show it to the user, write it, and load it. These autostart entries run only the list service. If `ensure-list` has been run while an autostart entry is installed but not loaded, it would start a second list service by hand: check the service state before running it.

Fill in only the placeholders; keep every other key. Put `UI_CANVAS_BIND` only if `<HOST>` is not `127.0.0.1`; add `UI_CANVAS_PLAYWRIGHT_MODULE` only if the user needs it.

**macOS (LaunchAgent).** For the default local-only setup the tool can write the file itself: `<PYTHON3> scripts/canvas.py install-list-agent` prints the plan (dry run), `... install-list-agent --yes` writes `~/Library/LaunchAgents/com.easy-ui-canvas.list.plist` and loads it (`uninstall-list-agent --yes` removes it; the plist is moved to `<RUNTIME_DIR>/trash/`). That built-in command has no bind option, so for any other bind write the plist yourself from this template (it mirrors `scripts/ui-canvas-list.plist.template`), as `~/Library/LaunchAgents/com.easy-ui-canvas.list.plist`:

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

Use absolute paths (no `~`) in the plist; remember that XML needs `&` written as `&amp;`. Validate with `plutil -lint <plist path>`, then load:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.easy-ui-canvas.list.plist
launchctl print gui/$(id -u)/com.easy-ui-canvas.list | head
```

(`AbandonProcessGroup` keeps canvases alive when the list service restarts; `KeepAlive` restarts it after a crash only.)

**Linux (systemd user service).** Write `~/.config/systemd/user/easy-ui-canvas-list.service`:

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

`KillMode=process` keeps canvas processes alive when the service restarts. Without a login session (headless machine) the service only runs while the user is logged in unless lingering is enabled: ask before running `loginctl enable-linger $USER`, and explain it makes the service start at boot. If `<HOST>` is a Tailscale address, the service can fail at boot before Tailscale is up; `Restart=on-failure` will retry, and you should tell the user about it. If a service is already started by hand (`ensure-list`), stop that process first (section 9) so the unit can own the port.

**Windows (WSL).** Native Windows is not supported; everything runs inside WSL (Ubuntu or similar) and the steps above are done in the WSL shell.

- If the WSL distribution has systemd enabled (`systemctl --user is-system-running` works; on recent WSL 2 this needs `[boot]` `systemd=true` in `/etc/wsl.conf`, which is a user decision and needs `wsl --shutdown` to apply), use the Linux unit above inside WSL. WSL still has to be running: starting it at Windows logon is the next bullet.
- Otherwise use a Windows Task Scheduler task "At log on" that runs a long-lived WSL process, which also keeps the distribution awake. Example action (run in Windows PowerShell, after the user agrees; adjust `<DISTRO>` from `wsl -l -q`):

```powershell
schtasks /Create /TN "Easy UI Canvas" /SC ONLOGON /TR "wsl.exe -d <DISTRO> --exec <PYTHON3> <INSTALL_DIR>/scripts/canvas.py list-serve --runtime-dir <RUNTIME_DIR> --list-port <LIST_PORT> --bind <HOST>"
```

  Here `<PYTHON3>`, `<INSTALL_DIR>` and `<RUNTIME_DIR>` are WSL (Linux) paths. Environment variables for the port range need `wsl.exe -d <DISTRO> --exec env UI_CANVAS_PORT_RANGE=<PORT_MIN>-<PORT_MAX> <PYTHON3> ...` in front of the command. Alternatively put the command in a small shell script inside WSL and run that script from the task. Remove with `schtasks /Delete /TN "Easy UI Canvas" /F` after confirming with the user. (This Task Scheduler recipe is a template: tell the user it could not be tested on every Windows/WSL version and verify it with them.)
- The Windows browser reaches the list page at `http://127.0.0.1:<LIST_PORT>/` through WSL's localhost forwarding. Reaching it from a phone requires Windows-side networking (mirrored networking, port proxy, firewall rule) that is outside this tool and which you must not set up for the user (safety rule 4); describe it and let the user decide.

### 7.3 Optional export tooling

Only if the user said yes in Q6 and approved the exact commands. Verify with `node -e "require.resolve('playwright')"` (or via `UI_CANVAS_PLAYWRIGHT_MODULE`), and test the export from the canvas toolbar button "Export UI handoff". If it fails, report the message and do not install anything else automatically.

## 8. Verify

Use the real URLs and ports from the output of section 7.1. Replace `<CANVAS_PORT>` with the canvas `port`.

```bash
curl -s -o /dev/null -w "list page   %{http_code}\n" http://127.0.0.1:<LIST_PORT>/
curl -s -o /dev/null -w "canvas page %{http_code}\n" http://127.0.0.1:<CANVAS_PORT>/
curl -s -o /dev/null -w "phone page  %{http_code}\n" http://127.0.0.1:<CANVAS_PORT>/m/
curl -s http://127.0.0.1:<LIST_PORT>/healthz       # {"service": "ui-canvas-list", ...}
<PYTHON3> scripts/canvas.py list                   # the check canvas should be "running"
```

All three pages must return `200`. If `<HOST>` is not loopback, also request the page on the chosen address from this machine (`http://<HOST>:<LIST_PORT>/`; for `auto` use the non-loopback URLs printed by `ensure-list`) and expect `200`. Do not test from outside the machine in ways that touch other devices or the firewall; ask the user to open the URL on their phone instead.

Language switch (the setting is shared by the list page, every canvas, the phone page and the CLI):

```bash
<PYTHON3> scripts/canvas.py lang                   # note the current value ("lang": null means auto)
<PYTHON3> scripts/canvas.py lang zh
curl -s http://127.0.0.1:<LIST_PORT>/api/lang      # expect "effective": "zh"
curl -s http://127.0.0.1:<LIST_PORT>/ | grep -c 'window.UIC_LANG="zh"'   # expect 1
<PYTHON3> scripts/canvas.py lang en                # expect "effective": "en" the same way
<PYTHON3> scripts/canvas.py lang <ORIGINAL_VALUE>  # zh, en or auto: restore what the user had, or the one they now prefer
```

Phone preview: tell the user to open the canvas in a browser, click "Mobile preview" and scan the QR code. This works only when the chosen bind has a reachable non-loopback address (`urls` contains an entry that is not `local-only`) and the phone is on the same network; with `127.0.0.1` a phone cannot open it, so say that plainly instead of reporting it as working.

If autostart was installed, check it as well: the service shows as running in `launchctl print` / `systemctl --user status`, the list page answers `200`, and (if the user agrees to a test) it also answers after logging out and in again or restarting the service.

Finally ask the user whether to keep or remove the "Deploy check" canvas. To remove: `canvas.py stop --canvas <id>` then `canvas.py remove --canvas <id> --yes` (moves it to `trash/`, recoverable).

## 9. Hand-off summary: stop, restart, uninstall

Finish with a short summary in the user's language: where it is installed, the list URL(s), bind address and what it means for who can reach it, ports, runtime directory, autostart state, export state, anything that failed. Then give these commands filled in with the user's real values (prefix with the `export` line from section 7.1 or pass the options).

Stop and restart:

```bash
<PYTHON3> <INSTALL_DIR>/scripts/canvas.py list                          # ids, ports, status
<PYTHON3> <INSTALL_DIR>/scripts/canvas.py stop  --canvas <CANVAS_ID>     # one canvas
<PYTHON3> <INSTALL_DIR>/scripts/canvas.py start --canvas <CANVAS_ID> --bind <HOST>
```

The list service has no stop command of its own:

- Autostart on macOS: `launchctl bootout gui/$(id -u)/com.easy-ui-canvas.list` (stop and unload), `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.easy-ui-canvas.list.plist` (load again).
- Autostart on Linux/WSL: `systemctl --user stop|restart easy-ui-canvas-list.service`.
- Without autostart: find its process id with `curl -s http://127.0.0.1:<LIST_PORT>/healthz` (field `pid`), confirm with `ps -p <PID> -o args=` that the command line contains `canvas.py` and `list-serve`, then `kill <PID>`. Start it again with `ensure-list --bind <HOST>`. After a code update run `ensure-list --restart-if-outdated --bind <HOST>`.

Canvas processes keep running when the list service stops. Stop them with `stop --canvas <id>` first if the user wants everything down. After a reboot all canvases are stopped; start them from the list page or with `start`.

Uninstall (only when the user asks, and confirm each step):

1. Stop every canvas (`list`, then `stop --canvas <id>`) and the list service as above.
2. Remove autostart: macOS `canvas.py uninstall-list-agent --yes` (or `launchctl bootout ...` and move the plist away); Linux/WSL `systemctl --user disable --now easy-ui-canvas-list.service`, then delete `~/.config/systemd/user/easy-ui-canvas-list.service` and run `systemctl --user daemon-reload`; Windows `schtasks /Delete /TN "Easy UI Canvas" /F`.
3. The runtime directory holds the user's canvases and comments. Do not delete it unless the user explicitly says so; offer to move it to a backup location instead.
4. The install directory is just the repository; delete it only if the user asks.

Last, tell the user how to hand a design task to you: "Use the Easy UI Canvas skill" (see `SKILL.md`), and that comments they write on the canvas can be read by their assistant in the next session.
