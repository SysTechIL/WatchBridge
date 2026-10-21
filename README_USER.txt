WATCHBRIDGE 1.2.0
Plex or Jellyfin watch history -> qBittorrent tags

GET STARTED
Open WatchBridge.exe, or use RUN.bat if you have the source package.
For the command line use WatchBridgeCLI.exe, or WatchBridgeCLI.bat from source.
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

BACKGROUND SCHEDULE (WINDOW CLOSED)
Open Schedule, choose When, then click Save Schedule:
  Every X minutes     every 1 minute to 31 days
  Daily at set times  one or more 24-hour times, e.g. 03:00, 15:30
  Weekly on set days  chosen days at chosen times
  At Windows sign-in  once each time you sign in
  Real time           listens for Plex or Jellyfin playback and watched-state
                      events, waits a few seconds, then syncs; an optional
                      full check runs every N minutes in case of a missed event
Interval, daily and weekly can also run at sign-in. Off removes the schedule.
WatchBridge registers one task for your Windows account in Windows Task
Scheduler. Runs happen while you are signed in to Windows. No administrator
rights, Windows service or stored Windows password are used.
Background runs need Remember credentials. Saving the schedule also saves your
connection settings. Each run scans, then tags ALL ready torrents only when the
scan has no errors. Runs never overlap, including with the window. After the
chosen number of consecutive failures (5 by default, 0 = never) background
runs pause until you click Resume. Run Now starts a run immediately.
Plex real-time events need a token from the server owner. Jellyfin events use
the user's password or an API key. Without events, the full check still runs.
Log: %LOCALAPPDATA%\WatchBridge\logs\watchbridge.log (Open Log).
To stop everything: choose Off and Save Schedule, or WatchBridgeCLI schedule off.
If you move or update WatchBridge in another folder, open Schedule and click
Save Schedule again so the task points to the new location.

COMMAND LINE
Every option in the window is available from WatchBridgeCLI. Examples:
  WatchBridgeCLI test
  WatchBridgeCLI scan --status ready,unmatched --details
  WatchBridgeCLI scan --csv C:\Reports\watched.csv --json
  WatchBridgeCLI apply                      all ready torrents
  WatchBridgeCLI apply --name "Show" --hash HASH   selected ready torrents
  WatchBridgeCLI sync                       scan, then tag all ready torrents
  WatchBridgeCLI auto --interval 15         auto sync until Ctrl+C
  WatchBridgeCLI config show | set | import config.json | clear-credentials | path
  WatchBridgeCLI schedule set interval --every 30m --at-logon
  WatchBridgeCLI schedule set daily --at 03:00,15:30
  WatchBridgeCLI schedule set weekly --days sun-thu --at 22:30
  WatchBridgeCLI schedule set logon
  WatchBridgeCLI schedule set realtime --delay 30 --fallback 60
  WatchBridgeCLI schedule show | run | resume | off
  WatchBridgeCLI agent --status | --run-now | --stop
  WatchBridgeCLI reports --open | --list 10
  WatchBridgeCLI logs --tail 40 | --follow | --open
  WatchBridgeCLI guide | gui | --version
Connection options apply to one run unless --save is added: --server,
--plex-url, --plex-token, --plex-profile, --jf-url, --jf-user, --jf-api-key,
--jf-password, --qb-url, --qb-user, --qb-password, --tag, --config FILE.
Pass "-" as a secret to be prompted, or set WATCHBRIDGE_PLEX_TOKEN,
WATCHBRIDGE_JF_API_KEY, WATCHBRIDGE_JF_PASSWORD or WATCHBRIDGE_QB_PASSWORD
so secrets do not appear in the process list.
Exit codes: 0 ok, 1 failed or scan errors, 2 invalid input, 3 another run in
progress, 4 background runs paused, 130 stopped.

CREDENTIALS
Settings: %LOCALAPPDATA%\WatchBridge\settings.json
Reports:  %LOCALAPPDATA%\WatchBridge\reports
Logs:     %LOCALAPPDATA%\WatchBridge\logs
Credentials are kept only in memory unless Remember credentials is enabled.
On Windows, remembered tokens and passwords are encrypted by Windows DPAPI
for the current Windows user. Non-secret connection settings are plain JSON.
Uncheck Remember credentials and Save Settings to remove the saved secrets.
The window does not read environment variables. Only the command line reads
the WATCHBRIDGE_* variables listed above, and only when you set them.
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
Do not include imported configs, reports, logs, or your personal application data.
Each recipient enters their own connection details. Source and EXE builds are
unsigned; there is no publisher certificate in this project.

REQUIREMENTS
Windows 10/11, accessible Plex or Jellyfin and qBittorrent Web APIs.
Source version: Python 3.10+ with tkinter and Internet for installing dependencies.
Built EXE: Python is bundled, and no separate Python installation is required.
qBittorrent legacy Ok. and newer empty HTTP 200/204 login replies are supported.
