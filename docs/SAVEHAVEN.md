# Savehaven: Ludusavi + centralization + Syncthing

Live mode uses the installed Ludusavi executable and its normal configuration in `~/.config/ludusavi`. Ludusavi owns discovery, manifests, cloud filtering, custom games, backup formats, retention and restores. The web interface is a thin adapter to these operations. The parent Decky game picker, alias controls and restore modal are retained.

## Plugin lifecycle

The plugin creates `LiveService` from `_main()` when `~/Saves/.savehaven.json` has `kind: savehaven-live`. The web listener and event worker run inside Decky's plugin process. `_unload()` stops the listener, cancels an active Ludusavi command, drains queued work and joins the worker. All Python modules, the Decky bundle and web assets are included in the installation ZIP. Syncthing XML parsing uses the host `/usr/bin/python3` via the bundled short-lived helper because Decky's frozen runtime omits that standard-library module. There is no standalone systemd service. `run_savehaven.py` is only a development launcher and must not run beside the installed plugin.

## Real saves

`~/Saves` keeps its existing curated layout and Syncthing folder registration. The marker identifies the repository. This machine uses `/var/mnt/8TB-HDD/SavehavenMirror/ludusavi` for native Ludusavi backups, with five full versions. The prior `~/ludusavi-backup` archive remains untouched. The original configuration is saved at `~/.local/state/savehaven/activation-original-config.yaml`.

Centralization is the added operation: after a successful native backup, complete save-only directories may be copied into `~/Saves/Managed/`, verified by SHA-256, and linked back to the original path. Mixed directories, nested symlinks, shared/hard-linked files, duplicate discoveries and changed files are skipped or rejected. Each original directory remains beside the old path as `.savehaven-before-*`; journals in `~/.local/state/savehaven/moves` record recovery paths. Do not delete these originals until recovery has been verified. Restore redirects are written to Ludusavi's own configuration.

Default filtering excludes Steam Cloud games. Named CLI commands bypass Ludusavi's automatic selection, so hook-triggered requests check the same native config and manifest first. Separate custom-game entries represent curated saves, non-Steam copies and explicit exceptions. Unknown titles are not automatically migrated. Add a specific save folder and Steam shortcut App ID through Custom games when needed.

Syncthing status is read through its existing local API; keys remain on the host. Savehaven neither creates device pairings nor duplicates the sync loop. Remote changes do not trigger extra scans. Hooks back up only the exiting game; full discovery runs only when Preview is requested. Syncthing conflict copies are preserved.

Restore uses Ludusavi and first writes a recovery backup to a separate native backup destination. ZIP exports use Ludusavi's ZIP format, bundled with its mapping metadata for portability. Logs, host-specific mappings and migration journals are outside the synced repository.

## Development

Run `PYTHONPATH=py_modules python3 -m unittest discover -s tests -p 'test_*.py'`, `node tests/test-policy.mjs`, and `corepack pnpm build`. Tests include actual Ludusavi binary backup/restore/export and plugin web-server lifecycle using temporary directories. The old SaveDemo fixtures remain available with the development launcher; real mode never creates synthetic saves.
