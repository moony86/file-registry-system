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

## Configure

On first run, if `.env` is missing, the node copies `.env.example` to `.env` and keeps running.

Edit `.env` in `dist/FSYSNode`:

- `MASTER_URLS`: comma-separated Master URLs. Put LAN/Tailscale/local fallbacks in order.
- `LOCAL_LIBRARY_DIRS`: comma-separated folders the node is allowed to browse.
- `NODE_ID=auto`: creates a stable `data/node_identity.json`.
- `NODE_HOST=auto`: advertises the detected local IP.

## Run

Double-click:

```text
start_node.bat
```

The window stays open so startup errors are visible.

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

## Notes

- Keep runtime folders out of Git.
- `shared_space/` is for managed CACHED files.
- `LOCAL_LIBRARY_DIRS` exposes only the folders you choose.
- Windows Service, setup wizard, auto update, and signed installer are deferred.
