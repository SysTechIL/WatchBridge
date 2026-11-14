# Changelog

## 1.3.0

- Saved settings that cannot be read in full are no longer replaced by defaults. The window and
  the command line keep every setting that can be read; the command line refuses to save over the
  file until you choose `--remember` or `--no-remember`, and each save keeps the previous file as
  `settings.bak`.
- Real time: an event that arrives while another run is busy is retried, also when the full check
  is set to 0.
- Automatic reports are pruned: the newest 100 are kept by default. Change it in Activity or with
  `config set --keep-reports N` (0 keeps all).
- Save Settings no longer saves unsaved Schedule changes, so the saved schedule always matches
  Task Scheduler. A schedule change that Task Scheduler refuses no longer changes the settings.
- Jellyfin uses a separate device id per computer, Windows user and role, so a sync no longer ends
  the real-time listener's login, and password logins are logged out after each run.
- qBittorrent sessions are logged out after each run.
- Sorting by Watched orders by the share of files watched instead of alphabetically.
- The progress bar advances for every torrent while tagging, including skipped ones.
- `config set` reports an invalid number instead of crashing.
- Task Scheduler status shows correctly on non-English Windows.
- Security: tokens for real-time events are sent in a header instead of the address when the
  server accepts it; a warning appears when credentials would cross the network over plain
  `http://`; CSV reports also neutralize cells starting with Tab or a carriage return; secrets typed
  on the command line print a warning; remembered credentials use extra DPAPI entropy (credentials
  saved by earlier versions are still read).
- New: a trusted certificate file for https servers with a self-signed certificate
  (Connections, or `--ca-file`). It is added to the standard certificate list.

## 1.2.0

- Add a Schedule page to run in the background with the window closed: every X minutes, daily or
  weekly at set times, at Windows sign-in, or in real time. It optionally also runs at sign-in.
- Scheduling uses one Windows Task Scheduler task per Windows user. It needs no administrator
  rights, Windows service or stored Windows password, so DPAPI credentials keep working.
- Real-time mode listens for Plex notifications and Jellyfin WebSocket events (playback stopped,
  watched state changed). It syncs after a short delay, with an optional full check as a fallback.
- Background runs tag only after an error-free scan, never overlap with each other or the window,
  are logged to `%LOCALAPPDATA%\WatchBridge\logs`, and pause after repeated failures until resumed.
- Add a full command line, `WatchBridgeCLI`, with every window option: test, scan/dry-run with
  filters, JSON and CSV, apply all or selected torrents, sync, auto, config, schedule, agent,
  reports and logs. Secrets can be prompted for or read from `WATCHBRIDGE_*` variables.
- Move the in-window auto sync from Connections to the Schedule page ("While this window is open"),
  so all timing options are in one place.
- The build now produces `WatchBridgeCLI.exe` beside `WatchBridge.exe`.
- New dependency: `websocket-client`.
- Replace documentation screenshots with demo data, and add Schedule screenshots.
- Fix the AltGr clipboard test so that it no longer depends on the physical keyboard state.

## 1.1.0

- Add Jellyfin as an alternative to Plex. Choose the media server in Connections.
- Jellyfin connects with an API key and an exact user name, or with that user's password.
- Read Jellyfin played state and file paths for movies and episodes, including every version of an item.
- Remember the Jellyfin API key and password with Windows DPAPI, like the Plex token.
- Existing Plex settings keep working; Plex remains the default.

## 1.0.2

- Handle clipboard shortcuts before ttk and widget bindings.
- Add explicit Ctrl+A/C/V/X and virtual Select All bindings.
- Read physical Windows modifier state as a fallback for non-Latin layouts.
- Keep the right-click editing menu from 1.0.1.

## 1.0.1

- Fix clipboard shortcuts in connection and search fields, including Hebrew Windows keyboard layouts.
- Add right-click Cut, Copy, Paste and Select All menus.
- Support Shift+Insert, Ctrl+Insert and Shift+Delete editing shortcuts.
- Add Hebrew and English repository documentation.

## 1.0.0

- Initial English Windows desktop interface for Plex to qBittorrent watched tagging.
- Dry Run, Apply Tags, CSV export, video-only results and per-user encrypted settings.
