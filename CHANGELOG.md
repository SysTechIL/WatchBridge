# Changelog

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
