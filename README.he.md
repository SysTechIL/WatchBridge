<div dir="rtl" align="right">

# WatchBridge

עברית | [English](README.md)

אפליקציית Windows עם ממשק באנגלית ושורת פקודה, שמסנכרנת מצב צפייה מפרופיל Plex אחד או ממשתמש
Jellyfin אחד לתגיות ב-qBittorrent. ההתאמה מתבצעת לפי הנתיב המלא של קובצי הווידיאו.
אפשר להריץ אותה ידנית, לפי תזמון ברקע או בזמן אמת.

## צילומי מסך

כל צילומי המסך מציגים נתוני דוגמה.

### סריקה, תוצאות וסינון

![מסך הסריקה עם טורנטים לדוגמה](docs/images/scan-and-sync.png)

### תזמון ברקע

| כל X דקות | זמן אמת |
| --- | --- |
| ![עמוד התזמון עם ריצה כל 30 דקות ובכניסה ל-Windows](docs/images/schedule.png) | ![עמוד התזמון במצב זמן אמת](docs/images/schedule-realtime.png) |

### חיבורים: Plex או Jellyfin

| Plex | Jellyfin |
| --- | --- |
| ![עמוד החיבורים כאשר Plex נבחר](docs/images/connections-plex.png) | ![עמוד החיבורים כאשר Jellyfin נבחר](docs/images/connections-jellyfin.png) |

<details>
<summary>יומן פעילות ועזרה</summary>

### יומן פעילות ודוחות

![יומן הפעילות של האפליקציה](docs/images/activity.png)

### עזרה וכללי התאמה

![מסך העזרה באנגלית](docs/images/help.png)

</details>

## יכולות

- **סריקה יבשה (Dry Run):** בדיקת התוצאות ללא שינוי בתגיות.
- **הוספת תגיות (Apply Tags):** הוספת תג לכל הטורנטים המוכנים או לפריטים נבחרים בלבד.
- **ייצוא ל-CSV (Export CSV):** שמירת התוצאות, מספר הקבצים שנצפו ונתיבים שלא הותאמו.
- חיפוש, סינון, התקדמות, יומן פעילות ועצירה.
- תמיכה בסרטים, בפרקים בודדים ובחבילות של עונות וסדרות.
- תמיכה ב-Plex או ב-Jellyfin כשרת המדיה, לבחירה בעמוד Connections.
- אימות פרופיל Plex או משתמש Jellyfin ובדיקת החיבורים לשני השירותים.
- שמירת סודות אופציונלית בהצפנת Windows DPAPI.
- ייבוא הגדרות מהסקריפט הקודם וסנכרון אוטומטי כשהאפליקציה פתוחה.
- **תזמון ברקע** כשהחלון סגור: כל X דקות, כל יום או בימים נבחרים בשעות קבועות, בכניסה ל-Windows,
  או **בזמן אמת** לפי אירועי צפייה מ-Plex או מ-Jellyfin.
- **שורת פקודה מלאה** (`WatchBridgeCLI`) עם כל האפשרויות של החלון, לסקריפטים ולמסוף.
- הדבקה והעתקה מתפריט לחיצה ימנית וקיצורי מקשים, כולל פריסת מקלדת עברית ב-Windows.

האפליקציה מוסיפה תגיות בלבד. היא לא מוחקת קבצים או טורנטים, לא עוצרת הורדות,
לא מסירה תגיות ולא משנה מצב צפייה ב-Plex. טורנטים ללא וידיאו מוחרגים מהתוצאות.

## דרישות

- מערכת הפעלה: Windows 10 או Windows 11.
- שרת Plex או Jellyfin נגיש וחשבון עם גישה לספריות.
- qBittorrent עם ממשק Web UI פעיל והתג המבוקש שכבר קיים, למשל `Watched`.
- נתיבי Windows זהים כפי שהם מופיעים בשרת המדיה וב-qBittorrent.
- להפעלה מקוד ולבניית EXE: Python 3.10 ומעלה, עם tkinter ו-Python Launcher.

## התקנה והפעלה

1. הורד דרך **Code > Download ZIP** וחלץ לתיקייה חדשה.
2. התקן Python 3.10 ומעלה, כולל Python Launcher.
3. הפעל את **`RUN.bat`**. בפעם הראשונה יותקנו התלויות בסביבה נפרדת.
4. בעמוד **Connections** בחר **Plex** או **Jellyfin** והזן את כתובות השרתים ופרטי החיבור.
5. לחץ **Test Connections**, ולאחר מכן **Dry Run** בעמוד **Scan & sync**.
6. בדוק את התוצאות והפעל **Apply Tags** להוספת התגיות.

כתובות לדוגמה כאשר השירותים מותקנים במחשב המקומי:

<div dir="ltr" align="left">

```text
Plex:        http://localhost:32400
Jellyfin:    http://localhost:8096
qBittorrent: http://localhost:8080
```

</div>

אם השירותים מותקנים במחשב אחר, החלף את `localhost` בשם או בכתובת שלו.
פרטי החיבור ל-qBittorrent הם של ממשק ה-Web UI.
למציאת טוקן Plex השתמש ב[הוראות הרשמיות](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/).

אפשר להשאיר **Profile name** ריק לשימוש בחשבון שאליו שייך הטוקן, או להזין
שם פרופיל מדויק לאימות או מעבר אליו. מצבי הצפייה של משתמשים אחרים לא משולבים.
אימות הפרופיל דורש גישה ל-`plex.tv`.

### Jellyfin

הזן את כתובת השרת ואת שם המשתמש המדויק ב-Jellyfin, ואז אחת משתי האפשרויות:

- **API key**: מנהל השרת יוצר מפתח ב-**Dashboard > API Keys**.
- אם אין מפתח, השאר את השדה ריק והזן את **הסיסמה** של אותו משתמש.

נקרא רק מצב הצפייה של המשתמש שנבחר. ב-Jellyfin פריט נחשב נצפה (Played) לאחר
צפייה כמעט עד הסוף או לאחר סימון ידני.

Jellyfin שרץ ב-Docker או ב-Linux מדווח בדרך כלל נתיבים כמו `/media/movies/...`.
נתיבים כאלה לא יתאימו לנתיבי Windows ב-qBittorrent, וכל הסרטונים יופיעו כ-Unmatched.
שני השירותים חייבים לדווח את אותם נתיבי Windows.

אם השתמשת בסקריפט הקודם, בחר **Connections > Import config.json** וטען את
קובץ ההגדרות הקיים שלך. לא מצורף למאגר קובץ עם פרטים אישיים.

## פירוש התוצאות

| מצב | משמעות |
| --- | --- |
| Ready | כל קובצי הווידיאו הותאמו לתוכן שנצפה וההורדה הושלמה. |
| Tagged | התג המבוקש כבר קיים בטורנט. |
| Unwatched | לפחות קובץ אחד הותאם ל-Plex ואינו מסומן כנצפה. |
| Unmatched | לפחות נתיב וידיאו אחד לא נמצא בשרת המדיה. |
| Incomplete | התוכן נצפה, אך ההורדה טרם הושלמה. |
| Error | קריאת API נכשלה. יש לפתור את התקלה ולסרוק שוב לפני הוספת תגיות. |

**סריקה יבשה (Dry Run) לא מוסיפה תגיות.** Apply Tags קורא מחדש את מצב הצפייה ואת נתיבי הקבצים
לפני ההוספה. לאחר שינוי הגדרות החיבור נדרשת סריקה חדשה.
להוספה לפריטים מסוימים, בחר שורות בעזרת Ctrl או Shift ובחר
**Selected ready torrents** במקום **All ready torrents**.

## כללי ההתאמה

- נדרשת התאמה לפי נתיב מלא, ללא ניחוש על בסיס שמות דומים.
- סרט או פרק בודד צריכים להיות מסומנים כנצפו בפרופיל או במשתמש שנבחר.
- חבילת עונה או סדרה תסומן רק לאחר צפייה בכל קובצי הווידיאו הרלוונטיים שבה.
- אם קובץ מייצג כמה פרקים ב-Plex, כל רשומות הפרקים צריכות להיות מסומנות כנצפו.
- Sample, כתוביות, תמונות ו-NFO לא נחשבים לווידיאו. תוכן RAR ו-ISO אינו נבדק.
- סרטוני בונוס או קבצים שלא נמצאו ב-Plex מונעים את סימון הטורנט.
- גם פרקים שלא נבחרו להורדה נחשבים כחלק מחבילת הטורנט.
- צפייה חלקית אינה מספיקה. סימון ידני כנצפה ב-Plex נחשב כנצפה.
- התג אינו מוסר אם התוכן מסומן בהמשך כלא נצפה.

## דוחות ואוטומציה

**ייצוא ל-CSV (Export CSV)** כולל את כל תוצאות הווידיאו, ללא קשר לסינון הנוכחי בטבלה.
דוחות אוטומטיים נשמרים לאחר סריקות ועדכוני תגיות. אפשר לפתוח אותם דרך
**Activity > Open Reports Folder**.

בתחתית עמוד **Schedule**, בחלק **While this window is open**, אפשר להפעיל
**Auto sync and apply tags every** ולבחור מרווח זמן. זה עובד רק כשהחלון פתוח, ולא דורש לזכור סיסמאות.
האפשרות כבויה בכל הפעלה מחדש. הריצה האוטומטית מטפלת בכל הטורנטים המוכנים,
ללא קשר לבחירה בטבלה, ומפסיקה במקרה של שגיאות. עצירה נכנסת לתוקף לאחר בקשת
הרשת הנוכחית. תגיות שכבר נוספו נשארות ואפשר לבדוק אותן בסריקה נוספת.

## תזמון ברקע

עמוד **Schedule** מריץ את WatchBridge כשהחלון סגור, כל עוד אתה מחובר ל-Windows.
האפליקציה רושמת משימה אחת עבור משתמש ה-Windows שלך ב-Task Scheduler (מתזמן המשימות של Windows).
לא נדרשות הרשאות מנהל, Windows Service או שמירת סיסמת Windows.

| מצב | מתי רץ |
| --- | --- |
| Every X minutes | כל דקה עד 31 יום, למשל כל 30 דקות. |
| Daily at set times | בשעה אחת או יותר בכל יום, למשל `03:00, 15:30`. |
| Weekly on set days | בימים ובשעות שנבחרו, למשל א'-ה' ב-22:30. |
| At Windows sign-in | פעם אחת בכל כניסה ל-Windows. |
| Real time | מאזין לאירועים מ-Plex או מ-Jellyfin ומסנכרן זמן קצר אחרי סיום צפייה או שינוי מצב צפייה. |

במצבים Every X minutes, Daily ו-Weekly אפשר לסמן ריצה נוספת בכל כניסה ל-Windows.
מצב Real time מתחיל בכניסה ל-Windows. הוא ממתין כמה שניות אחרי האירוע האחרון (30 כברירת מחדל),
ומריץ גם בדיקה מלאה כל N דקות, למקרה שאירוע הוחמץ. ב-Plex האירועים דורשים טוקן של בעל השרת.
ב-Jellyfin האירועים מתקבלים עם הסיסמה או ה-API key של המשתמש. אם האירועים לא זמינים, הבדיקה המלאה ממשיכה לרוץ.

כל ריצה ברקע סורקת קודם. היא מוסיפה תגיות לכל הטורנטים המוכנים רק אם בסריקה לא היו שגיאות.
ריצות לא חופפות, גם לא לפעולה בחלון. אחרי מספר כישלונות ברצף (5 כברירת מחדל) הריצות ברקע
נעצרות עד שלוחצים **Resume**. ריצה ברקע דורשת **Remember credentials**.
**Run Now** מפעיל ריצה מיד, ו-**Open Log** פותח את יומן הפעילות ברקע.
אם מעבירים את WatchBridge לתיקייה אחרת, יש ללחוץ שוב **Save Schedule**.

## שורת פקודה

כל אפשרות שקיימת בחלון זמינה גם ב-`WatchBridgeCLI.exe`, או ב-`WatchBridgeCLI.bat` בחבילת הקוד.
לפרטים: `WatchBridgeCLI --help` או `WatchBridgeCLI <command> --help`.

<div dir="ltr" align="left">

```text
WatchBridgeCLI test                                    Test Connections
WatchBridgeCLI scan [--status ready,unmatched] [--search TEXT] [--details] [--json] [--csv FILE]
WatchBridgeCLI apply [--name TEXT] [--hash HASH]       Apply Tags (all ready, or a selection)
WatchBridgeCLI sync                                    Scan, then tag all ready torrents
WatchBridgeCLI auto --interval 15                      Auto sync while the command runs
WatchBridgeCLI config show | set | import FILE | clear-credentials | path
WatchBridgeCLI schedule set interval --every 30m --at-logon
WatchBridgeCLI schedule set daily --at 03:00,15:30
WatchBridgeCLI schedule set weekly --days sun-thu --at 22:30
WatchBridgeCLI schedule set logon
WatchBridgeCLI schedule set realtime --delay 30 --fallback 60
WatchBridgeCLI schedule show | run | resume | off
WatchBridgeCLI agent [--status | --run-now | --stop]   Real-time agent
WatchBridgeCLI reports [--open] [--list N]
WatchBridgeCLI logs [--tail N] [--follow] [--open]
WatchBridgeCLI guide | gui | --version
```

</div>

פרמטרי החיבור גוברים על ההגדרות השמורות בריצה אחת: `--server plex|jellyfin`, `--plex-url`,
`--plex-token`, `--plex-profile`, `--jf-url`, `--jf-user`, `--jf-api-key`, `--jf-password`,
`--qb-url`, `--qb-user`, `--qb-password`, `--tag` ו-`--config FILE`. לשמירה הוסף `--save`,
יחד עם `--remember` או `--no-remember`. בסודות אפשר להעביר `-` כדי לקבל בקשה להקלדה, או להגדיר
`WATCHBRIDGE_PLEX_TOKEN`, `WATCHBRIDGE_JF_API_KEY`, `WATCHBRIDGE_JF_PASSWORD` או `WATCHBRIDGE_QB_PASSWORD`.
כך הסודות לא מופיעים ברשימת התהליכים.

קודי יציאה: `0` הצלחה, `1` כישלון או שגיאות בסריקה, `2` קלט לא תקין, `3` ריצה אחרת פעילה,
`4` הריצות ברקע מושהות, `130` נעצר.

## בניית EXE לשיתוף

במחשב Windows הפעל:

<div dir="ltr" align="left">

```text
BUILD_EXE.bat
```

</div>

בסיום ייווצר:

<div dir="ltr" align="left">

```text
dist/WatchBridge-Windows.zip
```

</div>

שתף את ה-ZIP הזה. הוא כולל `WatchBridge.exe` עצמאי (החלון והריצות ברקע), `WatchBridgeCLI.exe`
(שורת הפקודה) והוראות באנגלית, והמקבלים
לא יצטרכו להתקין Python. כל משתמש מזין את פרטי החיבור שלו.
המאגר מכיל קוד מקור, ללא EXE שכבר נבנה. הבנייה מתבצעת ב-Windows והקובץ אינו חתום.

## פרטיות ושמירת הגדרות

הנתונים האישיים נשמרים מחוץ לתיקיית התוכנה:

<div dir="ltr" align="left">

```text
%LOCALAPPDATA%\WatchBridge\settings.json
%LOCALAPPDATA%\WatchBridge\reports\
%LOCALAPPDATA%\WatchBridge\logs\
%LOCALAPPDATA%\WatchBridge\schedule-state.json
```

</div>

הטוקן והסיסמה נשמרים בזיכרון בלבד, אלא אם סומנה **Remember credentials**.
בשמירה נעשה שימוש ב-Windows DPAPI עבור המשתמש הנוכחי. יתר הגדרות החיבור הן
JSON רגיל. להסרת הסודות השמורים, בטל את האפשרות ולחץ Save Settings.
אין באפליקציה מנגנון טלמטריה.

אל תעלה למאגר `config.json` אישי, הגדרות, דוחות או צילומי מסך עם מידע פרטי.
קובץ `.gitignore` מחריג הגדרות אישיות, דוחות, מטמון, סביבות Python ותוצרי בנייה.

## פיתוח ובדיקות

<div dir="ltr" align="left">

```powershell
py -3 -m pip install -r requirements.txt
py -3 -m unittest discover -s tests -v
py -3 watchbridge.py
```

</div>

80 בדיקות הלוגיקה משתמשות בנתוני API ובשדות קלט מדומים. הן מכסות התאמת נתיבים, חבילות
עונות, פרקים באותו קובץ, עימוד תוצאות, פרופילים, התחברות ל-Jellyfin ול-qBittorrent, עצירה וסינון דוחות.
נבדקים גם קיצורי ההדבקה בפריסת מקלדת עברית. בדיקת שמירת הסודות משתמשת בהצפנה מדומה.
בנוסף נבדקים פענוח התזמון, קובץ ה-XML ל-Task Scheduler, נעילת הריצה, השהיה וחידוש אחרי כישלונות,
טיפול באירועי זמן אמת, לולאת הסוכן וכל פקודות שורת הפקודה. מראה החלון ואירועי Plex אמיתיים
דורשים בדיקה במחשב Windows מול שרתים אמיתיים.

הוראות נוספות באנגלית: [README_USER.txt](README_USER.txt).

## רישיון

[MIT](LICENSE). זהו פרויקט עצמאי שאינו קשור רשמית ל-Plex, ל-Jellyfin או ל-qBittorrent.

</div>
