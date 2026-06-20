# FSYS Node Runtime

## Run From Python

From the repository root:

```powershell
cd storage-node
python app.py
```

Put the node `.env` file in `storage-node/.env` when running from source. Start with `storage-node/.env.example` and adjust paths/ports.

## Future EXE Runs

When packaged as an exe later, keep `.env` next to the executable or in the working directory used to launch it. Runtime folders should stay outside Git and should not be bundled as source files.

## Node Identity

With `NODE_ID=auto`, the node creates `storage-node/data/node_identity.json` on first start. This file stores the stable `node_id`. Do not edit it casually.

If the local IP changes, `generated_host` may update, but `node_id` must stay the same.

If `node_identity.json` is corrupted, startup fails with a clear error. Fix the JSON manually, or delete it only if you intentionally want a new node identity.

## Master Fallback

Use `MASTER_URLS` as a comma-separated list:

```env
MASTER_URLS=http://lan-master:5123,http://tailscale-master:5123,http://localhost:5000
```

The node tries URLs in order. Once one succeeds, later requests start from that active master URL. Check `/api/status` to see `active_master_url`.

## Location Types

`LOCAL`: Original user file already on the node. FSYS registers it but does not copy, trash, or delete it.

`CACHED`: Managed Shared Space copy created by upload/cache. Delete moves it to trash; restore moves it back.

`HOT`: Future trusted/server storage promotion. Not implemented in v0.8.0.

## Check Master Connectivity

Open:

```text
http://127.0.0.1:5001/api/status
```

Confirm:

- `node_id`
- `master_urls`
- `active_master_url`
- `registration.registered`
- `shared_space_used_bytes`

If Master is down, the node should keep running and keep retrying registration in the background.

## If IP Changes

Keep `NODE_HOST=auto` unless you need a fixed advertised host. Restart the node and check `/api/status`; `node_host` should reflect the new detected host while `node_id` stays unchanged.
