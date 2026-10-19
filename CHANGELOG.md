# Changelog

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
