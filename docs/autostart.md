# Optional: start the list service at login

The list service (default port 4042) is started on demand by `canvas.py ensure-list`, so none of this is required. Canvases themselves are started by `new`/`start` and are not restarted by the options below. Nothing here is installed unless you run it yourself.

The easiest way to set this up (including the choice of bind address, ports and data directory) is to hand [DEPLOY.md](../DEPLOY.md) to your AI assistant; it contains the same templates with placeholders and the safety rules. Everything below listens on `127.0.0.1` only. To listen on another address (there is no authentication, trusted networks only) add `--bind <address>` to `list-serve` (or set `UI_CANVAS_BIND`) and see DEPLOY.md.

## macOS (LaunchAgent)

```bash
python3 scripts/canvas.py install-list-agent          # only prints the plan
python3 scripts/canvas.py install-list-agent --yes    # writes ~/Library/LaunchAgents/com.easy-ui-canvas.list.plist and runs launchctl bootstrap
python3 scripts/canvas.py uninstall-list-agent --yes  # bootout; the plist moves to <runtime>/trash/
```

`--no-load` only writes the file, `--plist-dir` changes the directory and `--label` the label. The template is `scripts/ui-canvas-list.plist.template` (KeepAlive after crashes, `AbandonProcessGroup` so restarting the list service does not kill canvases). The agent listens on `127.0.0.1` only, like everything else.

## Linux (systemd user service)

Example `~/.config/systemd/user/easy-ui-canvas-list.service` (adjust the paths):

```ini
[Unit]
Description=Easy UI Canvas list service

[Service]
ExecStart=/usr/bin/python3 /path/to/easy-ui-canvas/scripts/canvas.py list-serve
# Optional, to match a non-default setup:
# Environment=UI_CANVAS_RUNTIME=/path/to/runtime
# Environment=UI_CANVAS_LIST_PORT=4042
# Environment=UI_CANVAS_PORT_RANGE=4100-4899
Restart=on-failure
KillMode=process

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now easy-ui-canvas-list.service
```

`KillMode=process` keeps canvas processes alive when the service restarts. To keep it running without a login session: `loginctl enable-linger $USER`.

## Windows

Use WSL (Ubuntu or similar) and follow the Linux instructions inside it; open `http://127.0.0.1:4042/` from the Windows browser (WSL forwards localhost). Native Windows is not supported. A Task Scheduler recipe for starting WSL at logon is in [DEPLOY.md](../DEPLOY.md).
