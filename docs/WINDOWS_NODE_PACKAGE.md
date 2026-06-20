# Windows Node Package

FSYS can package the Storage Node as a portable Windows folder. This is not a Windows Service yet.

## Build

From the repository root:

```powershell
.\scripts\build_windows_node.ps1
```

The script uses PyInstaller in `onedir` mode and creates:

```text
dist/FSYSNode/
```

## Package Contents

Expected files and folders:

```text
FSYS Node.exe
fsys-node.exe
start_node.bat
check_status.bat
.env.example
README_NODE_WINDOWS.md
data/
shared_space/
thumbnails/
logs/
```

## First Run Setup

On first run, if `.env` is missing, the node creates a safe default `.env`.
It uses localhost Master defaults and common local folders such as Videos and Downloads when they exist.

Use `FSYS Node.exe` -> `Setup / Reconfigure` when you need to change network or library settings.

The wizard asks for:

- Master URL or comma-separated `MASTER_URLS`
- Node port
- Shared Space directory
- Storage size such as `20GB` or `1TB`
- Local Libraries, one path per line
- Node token

When saved, the wizard writes `.env`. If `.env` already exists, it creates `.env.backup` first.

Edit `.env` in `dist/FSYSNode`:

- `MASTER_URLS`: comma-separated Master URLs. Put LAN/Tailscale/local fallbacks in order.
- `LOCAL_LIBRARY_DIRS`: comma-separated folders the node is allowed to browse.
- `NODE_ID=auto`: creates a stable `data/node_identity.json`.
- `NODE_HOST=auto`: advertises the detected local IP.

You can still edit `.env` manually later.

## Setup Commands

Run setup again:

```text
fsys-node.exe --setup
```

Reset config:

```text
fsys-node.exe --reset-config
```

Reset moves `.env` to `.env.old`, then starts the setup wizard.

## Run

Double-click:

```text
FSYS Node.exe
```

The control window can start, stop, restart, open Dashboard, open local status, open logs, and run setup.

Fallback:

```text
start_node.bat
```

The fallback console window stays open so startup errors are visible.

## Check Status

Run:

```text
check_status.bat
```

It calls:

```text
http://127.0.0.1:5001/api/status
```

Look for `node_id`, `node_host`, `master_urls`, `active_master_url`, and `registration`.

## Firewall

If other devices need to stream or browse from this node, allow inbound TCP on port `5001` in Windows Defender Firewall.

Windows may show a firewall prompt on first run. Allow private-network access if the node should be reachable from devices on the same LAN.

## Notes

- Keep runtime folders out of Git.
- `shared_space/` is for managed CACHED files.
- `LOCAL_LIBRARY_DIRS` exposes only the folders you choose.
- `logs/node.log` is the first place to check startup and registration issues.
- Windows Service, auto update, and signed installer are deferred.
