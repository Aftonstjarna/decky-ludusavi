# Savehaven backend and web interface

## Origin

Forked from [GedasFX/decky-ludusavi](https://github.com/GedasFX/decky-ludusavi) at `dad36ecf98fb2d41bb838f358d5e4c1ea5641094`. The original BSD-3-Clause license and copyright notices remain in LICENSE. The Steam lifecycle registration and Python Ludusavi adapter are adapted from upstream, not independent replacements.

## Run locally

```sh
python3 ~/.dev/decky-ludusavi/run_savehaven.py
```

Open http://127.0.0.1:8765. Stop the old standalone Savehaven demo before starting this server. The service is shared by the standalone launcher and Decky backend; do not run both on port 8765.

The existing `~/SaveDemo` repository, `~/SaveDemoSources` originals, and `~/SaveDemoMirror` are reused. The intended production root remains `~/Saves`, marked with `.savehaven.json`, but this development build deliberately cannot enroll real save paths.

## How jobs are triggered

The fork retains `SteamClient.GameSessions.RegisterForAppLifetimeNotifications`:

- Start: record the running app; do not invoke Ludusavi or hash saves.
- Exit: map Steam App ID to an installation, then queue that installation.
- Before invoking Ludusavi: apply explicit exceptions, curated inclusion, then installed-copy Steam Cloud coverage. Excluded and unknown-coverage installations do not launch a scan.
- Run Ludusavi's JSON preview only for the eligible installation, check that files have settled, preserve a pre-move backup, move into the central repository, and link the original directory back.
- Mirror only the affected game. Previous mirror contents remain in `versions/`.

The worker blocks on an empty queue. There is no background scan timer, startup scan, or idle file hashing. Duplicate exits are suppressed; jobs are serialized and overlapping updates request one follow-up job. Jobs for running games are deferred until an exit event. Queued jobs are in-memory; after a crash, use the explicit scan button or another game-exit event.

Web edits/restores enqueue the affected sample. Simulated saves do not enqueue a scan until **Exit**. Rules are persisted without triggering a scan. Pausing disables automatic processing; an explicit manual scan can run while paused. Unknown App IDs are shown for review and never guessed into another game's save paths.

## Try the sandbox

1. Open **Automation**.
2. Press **Start**, **Save**, then **Exit** on a sample installation.
3. Confirm that only that installation is processed. Working Steam Cloud samples stay excluded unless explicitly included.
4. Use **Sandbox files** for editing curated sample JSON and restoring versions.
5. Export a backup ZIP, including checksums and historical backups.

Map an App ID under an installation to route incoming hooks to that sandbox sample. These mappings do not enable management of that app's real saves. Cloud statuses are explicit test metadata; the fork does not yet verify live Steam Cloud coverage. The web page does not poll while idle; click **Refresh status** after external Steam events. It fetches metadata briefly while a queued web action completes.

The separate sample **Save library** remains illustrative and browser-local. Actual sandbox rules and App ID mappings are controlled on **Automation**, stored in `~/SaveDemo/.automation.json`.

## Decky build

```sh
corepack pnpm install --frozen-lockfile
corepack pnpm build
```

A distributable must include `main.py`, `plugin.json`, `package.json`, `dist/index.js`, `py_modules/`, `web/`, and LICENSE. The plugin is named **Savehaven Ludusavi**, leaving the upstream plugin distinguishable. Stop the standalone server before loading it. The Decky backend serves the same local web interface and owns the queue; no separate web service is required.

This repository does not overwrite an installed plugin. Actual lifecycle delivery needs validation inside the user's Steam/Decky session after installation. Avoid enabling two backup plugins for the same installations during that validation.

## API and checks

The local-only `/api/hooks` POST endpoint accepts `{"appId":"123","event":"start"}` or `exit`, with optional `name`. Like other mutations, it requires JSON, the local Origin/Host, and the session `X-Savehaven-Token` returned by `/api/automation`. Decky calls the same backend hook directly through its RPC.

```sh
PYTHONPATH=py_modules python3 -m unittest discover -s tests -p 'test_*.py'
node tests/test-policy.mjs
```

The test suite covers actual sandbox Ludusavi previews, migration and link recovery, mirror history, ZIP integrity, stale edits, unsafe paths, idle/start behavior, targeted exit jobs, cloud exclusions, duplicate exits, pause behavior, and unmapped/running games.

## Remaining production work

Live installation discovery and verified per-installation Steam Cloud coverage, production path enrollment, cross-filesystem migration, Syncthing integration, and production retention settings are not enabled. The sandbox uses directory symlinks; it does not use fragile individual-file hard links. Mirroring is local and does not protect against loss of the computer. Existing historical backups remain available even after an installation is excluded.
