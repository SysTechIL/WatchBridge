WATCHBRIDGE 1.1.0
Plex or Jellyfin watch history -> qBittorrent tags

GET STARTED
Open WatchBridge.exe, or use RUN.bat if you have the source package.
Open Connections, choose Plex or Jellyfin, and enter:
  For Plex:
    Plex server URL, such as http://localhost:32400
    Your personal Plex token
    Optional exact Plex profile name (blank means the token's account)
  For Jellyfin:
    Jellyfin server URL, such as http://localhost:8096
    Your exact Jellyfin user name
    An API key (Dashboard > API Keys, administrators only), or
    leave the API key blank and enter that user's password
  qBittorrent Web UI URL, such as http://localhost:8080
  qBittorrent Web UI username and password
  The existing tag to add, normally Watched
Enable the Web UI in qBittorrent and create your tag there first.

Click Test Connections, then Dry Run. Dry Run changes nothing.
Right-click connection/search fields for Paste, Copy, Cut and Select All.
Ctrl+V/C/X/A and Shift+Insert are supported, including Hebrew Windows layouts.
Review the video torrents in Scan & sync. Choose All ready torrents or
Selected ready torrents, then click Apply Tags. A fresh watch-state
scan and qBittorrent file check are performed before the tags are added.
Changes to connection settings require a new successful Dry Run.

IMPORT PREVIOUS SETTINGS
Connections > Import config.json reads the earlier script's settings into
memory. It does not copy that file into the application package. To remember
credentials, select Remember credentials, then Save Settings.

RESULTS
Ready: every supported, non-sample video file was matched and watched;
       the torrent and those video files are fully downloaded.
Tagged: the configured tag is already present.
Unwatched: at least one matched video is not marked watched on the media server.
Unmatched: at least one video path is absent from the media server.
Incomplete: all videos are watched, but the download is incomplete.
Error: an API request failed; resolve it and scan again before tagging.
Non-video torrents do not appear in the table or CSV reports. The count
excluded is shown after the scan. Already tagged non-video torrents are
also excluded.

FILES AND PATHS
The media server and qBittorrent must report identical Windows file paths.
A Jellyfin server in Docker or Linux reports paths such as /media/... that
will not match qBittorrent's Windows paths. The app uses
full paths, never fuzzy title matching. It does not read the media files.
Samples, subtitles, NFOs and images are ignored. Archives and ISO contents
are not inspected. Bonus video files absent from the media server block tagging.
Even deselected episode files in a season torrent must be watched. Multiple
media server episode records pointing to one file must all be marked watched.
Watching part of a video does not count as watched. Marking watched manually
in Plex or Jellyfin does count. Watching a different edition follows Plex's own watched
state for the matched library item.

CSV AND ACTIVITY
Export CSV saves ALL currently scanned video results, regardless of search
or status filters. Automatic reports are written after scans and tag updates.
Activity > Open Reports Folder opens them. Rows contain torrent names, hashes,
watch counts, errors and unmatched paths; never passwords, tokens or cookies.
Keep reports private if your filenames or paths are personal.

AUTOMATION AND STOP
Auto sync and apply tags is optional, disabled every time the app starts,
and runs only while this app is open. Choose the interval in Connections.
It applies to ALL ready torrents, regardless of table selection or filters.
Errors disable automatic runs. Stop disables auto sync and requests cancellation
after the current network request, which may take up to about 60 seconds.
Earlier tag additions remain. A new Dry Run is required after interruption.

CREDENTIALS
Settings: %LOCALAPPDATA%\WatchBridge\settings.json
Reports:  %LOCALAPPDATA%\WatchBridge\reports
Credentials are kept only in memory unless Remember credentials is enabled.
On Windows, remembered tokens and passwords are encrypted by Windows DPAPI
for the current Windows user. Non-secret connection settings are plain JSON.
Uncheck Remember credentials and Save Settings to remove the saved secrets.
The app does not use PLEX_TOKEN or QB_PASSWORD environment variables.
Personal Plex profile verification contacts plex.tv. Library data and torrent
operations go directly to the server URLs you enter. No analytics or telemetry
are implemented by this application. Plex, Jellyfin and qBittorrent run their own services.

FIND YOUR PLEX TOKEN
Sign in to Plex Web with the intended account, open a movie, choose
More (...) > Get Info > View XML, then find X-Plex-Token in the URL.
Official instructions:
https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/

SAFETY AND SHARING
The app only adds the configured tag. It never removes tags, deletes media
or torrents, pauses downloads, or changes watched state on the media server. If you
later mark a video unwatched, existing tags remain. Dry Run never adds tags.
When the app is stopped or an API call fails during tagging, some updates may
already have completed. Scan again to read the actual state before retrying.

Share the original source ZIP or dist\WatchBridge-Windows.zip from BUILD_EXE.bat.
Do not include imported configs, reports, or your personal application data.
Each recipient enters their own connection details. Source and EXE builds are
unsigned; there is no publisher certificate in this project.

REQUIREMENTS
Windows 10/11, accessible Plex or Jellyfin and qBittorrent Web APIs.
Source version: Python 3.10+ with tkinter and Internet for installing dependencies.
Built EXE: Python is bundled, and no separate Python installation is required.
qBittorrent legacy Ok. and newer empty HTTP 200/204 login replies are supported.
