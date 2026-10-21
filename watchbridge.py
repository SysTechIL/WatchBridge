"""WatchBridge desktop application. Run with Python 3.10+ on Windows."""
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import webbrowser

from engine import SyncEngine, Cancelled, __version__, checked_config, public_error, write_report, report_name
import agent
from helptext import GUIDE
import runtime
import scheduler
import settings as storage
from clipboard_actions import install as install_edit_menu

BG = '#0b1020'
PANEL = '#121a2c'
CARD = '#192339'
TEXT = '#edf2ff'
MUTED = '#9eacc5'
BLUE = '#4f8cff'
TEAL = '#4dd4b0'
ORANGE = '#f5ae52'
RED = '#ff7c8b'
STATUS = {'READY': 'Ready', 'TAGGED': 'Tagged', 'UNWATCHED': 'Unwatched',
          'UNMATCHED': 'Unmatched', 'INCOMPLETE': 'Incomplete', 'ERROR': 'Error'}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('WatchBridge | Plex or Jellyfin to qBittorrent')
        icon = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'assets' / 'watchbridge.ico'
        if sys.platform == 'win32' and icon.exists():
            self.iconbitmap(str(icon))
        self.geometry('1320x880')
        self.minsize(1120, 760)
        self.configure(bg=BG)
        self.events = queue.Queue()
        self.cancel_event = threading.Event()
        self.busy = False
        self.rows = {}
        self.scan_config = None
        self.scan_complete = False
        self.excluded = 0
        self.last_report = None
        self.next_auto = None
        self.closing = False
        self.error_on_load = None
        try:
            values = storage.load()
        except Exception:
            values = dict(storage.DEFAULTS)
            self.error_on_load = 'Saved settings could not be unlocked. Enter your connection details again.'
        self.vars = {k: tk.BooleanVar(value=v) if isinstance(v, bool) else tk.StringVar(value=v)
                     for k, v in values.items()}
        self.search = tk.StringVar()
        self.filter = tk.StringVar(value='All video')
        self.scope = tk.StringVar(value='All ready torrents')
        self.auto = tk.BooleanVar(value=False)
        self.show_secrets = tk.BooleanVar(value=False)
        self.current_profile = tk.StringVar(value='No media server profile connected')
        self.phase = tk.StringVar(value='Connect your accounts, then start a dry run.')
        self.connection_state = tk.StringVar(value='NOT CONNECTED')
        self.footer_text = tk.StringVar(value='No changes made. Non-video torrents are excluded.')
        self._style()
        self._layout()
        self.search.trace_add('write', lambda *_: self.refresh_table())
        self.filter.trace_add('write', lambda *_: self.refresh_table())
        for key, var in self.vars.items():
            if key not in storage.LOCAL_KEYS:
                var.trace_add('write', lambda *_: self.refresh_actions())
        self.protocol('WM_DELETE_WINDOW', self.on_close)
        self.after(80, self.drain)
        self.after(1000, self.auto_tick)
        self.after(1500, self.schedule_tick)
        if self.error_on_load:
            self.after(300, lambda: messagebox.showwarning('Settings', self.error_on_load))
        configured = (values.get('jf_user') and (values.get('jf_api_key') or values.get('jf_password'))
                      if values.get('media_server') == 'jellyfin' else values.get('plex_token'))
        self.show_page('Scan & sync' if configured else 'Connections')

    def _style(self):
        self.option_add('*Font', ('Segoe UI', 10))
        self.option_add('*TCombobox*Listbox.background', CARD)
        self.option_add('*TCombobox*Listbox.foreground', TEXT)
        s = ttk.Style(self)
        s.theme_use('clam')
        s.configure('TFrame', background=BG)
        s.configure('Card.TFrame', background=PANEL)
        s.configure('TLabel', background=BG, foreground=TEXT)
        s.configure('TEntry', fieldbackground=CARD, foreground=TEXT, bordercolor='#2b3954',
                    insertcolor=TEXT, padding=9, lightcolor=CARD, darkcolor=CARD)
        s.map('TEntry', fieldbackground=[('disabled', PANEL)], foreground=[('disabled', MUTED)])
        s.configure('TCombobox', fieldbackground=CARD, background=CARD, foreground=TEXT,
                    arrowcolor=MUTED, padding=8, bordercolor='#2b3954')
        s.map('TCombobox', fieldbackground=[('readonly', CARD)], foreground=[('readonly', TEXT)])
        s.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                    rowheight=35, borderwidth=0, font=('Segoe UI', 10))
        s.configure('Treeview.Heading', background=CARD, foreground=MUTED,
                    padding=10, borderwidth=0, font=('Segoe UI', 9, 'bold'))
        s.map('Treeview', background=[('selected', '#263e68')], foreground=[('selected', '#ffffff')])
        s.map('Treeview.Heading', background=[('active', '#26344c')])
        s.configure('Horizontal.TProgressbar', background=BLUE, troughcolor=CARD,
                    borderwidth=0, lightcolor=BLUE, darkcolor=BLUE)
        s.configure('Vertical.TScrollbar', background=CARD, troughcolor=PANEL,
                    borderwidth=0, arrowcolor=MUTED)
        s.configure('TCheckbutton', background=PANEL, foreground=TEXT, padding=4)
        s.map('TCheckbutton', background=[('active', PANEL)])
        s.configure('TRadiobutton', background=PANEL, foreground=TEXT, padding=4,
                    indicatorbackground=CARD, indicatorforeground=BLUE, upperbordercolor=MUTED, lowerbordercolor=MUTED)
        s.map('TRadiobutton', background=[('active', PANEL)], indicatorbackground=[('pressed', CARD)])

    def label(self, parent, text='', size=10, color=TEXT, bg=BG, bold=False, **kw):
        return tk.Label(parent, text=text, bg=bg, fg=color,
                        font=('Segoe UI', size, 'bold' if bold else 'normal'), **kw)

    def button(self, parent, text, command, color=CARD, fg=TEXT, **kw):
        return tk.Button(parent, text=text, command=command, bg=color, fg=fg,
            activebackground=color, activeforeground=fg, disabledforeground='#63708a',
            relief='flat', borderwidth=0, padx=16, pady=10, cursor='hand2',
            font=('Segoe UI', 10, 'bold'), **kw)

    def _layout(self):
        sidebar = tk.Frame(self, bg=PANEL, width=220)
        sidebar.pack(side='left', fill='y')
        sidebar.pack_propagate(False)
        self.label(sidebar, 'W', 28, TEAL, PANEL, True).pack(anchor='w', padx=25, pady=(28, 0))
        self.label(sidebar, 'WatchBridge', 20, TEXT, PANEL, True).pack(anchor='w', padx=25)
        self.label(sidebar, 'Plex / Jellyfin to qBittorrent', 10, MUTED, PANEL).pack(anchor='w', padx=25, pady=(4, 32))
        self.nav = {}
        self.pages = {}
        for name in ('Scan & sync', 'Connections', 'Schedule', 'Activity', 'Help'):
            b = self.button(sidebar, name, lambda n=name: self.show_page(n), color=PANEL, anchor='w')
            b.pack(fill='x', padx=12, pady=3)
            self.nav[name] = b
        bottom = tk.Frame(sidebar, bg=PANEL)
        bottom.pack(side='bottom', fill='x', padx=24, pady=25)
        self.label(bottom, 'ADD TAGS ONLY', 9, TEAL, PANEL, True).pack(anchor='w')
        self.label(bottom, 'Your media stays where it is.\nNo deletion. No tag removal.', 9,
                   MUTED, PANEL, justify='left').pack(anchor='w', pady=(8, 14))
        self.label(bottom, 'v' + __version__ + '  /  Windows', 9, MUTED, PANEL).pack(anchor='w')
        outer = tk.Frame(self, bg=BG)
        outer.pack(side='left', fill='both', expand=True, padx=28, pady=24)
        top = tk.Frame(outer, bg=BG)
        top.pack(fill='x', pady=(0, 20))
        self.page_title = self.label(top, 'Scan & sync', 23, bold=True)
        self.page_title.pack(side='left')
        self.label(top, size=9, color=TEAL, textvariable=self.connection_state).pack(side='right')
        self.container = tk.Frame(outer, bg=BG)
        self.container.pack(fill='both', expand=True)
        for name in self.nav:
            self.pages[name] = tk.Frame(self.container, bg=BG)
        self._dashboard(self.pages['Scan & sync'])
        self._connections(self.pages['Connections'])
        self._schedule(self.pages['Schedule'])
        self._activity(self.pages['Activity'])
        self._help(self.pages['Help'])

    def show_page(self, name):
        for page in self.pages.values():
            page.pack_forget()
        self.pages[name].pack(fill='both', expand=True)
        self.page_title.configure(text=name)
        self.current_page = name
        if name == 'Schedule':
            self.refresh_schedule_status()
        for key, button in self.nav.items():
            button.configure(bg='#243451' if key == name else PANEL,
                             fg=TEXT if key == name else MUTED)

    def _dashboard(self, parent):
        self.label(parent, 'Turn your watch history into organized torrents.', 11, MUTED).pack(anchor='w')
        self.label(parent, size=10, color=TEAL, textvariable=self.current_profile).pack(anchor='w', pady=(6, 18))
        metrics = tk.Frame(parent, bg=BG)
        metrics.pack(fill='x', pady=(0, 18))
        self.metrics = {}
        for i, (key, name, color) in enumerate([('READY', 'Ready to tag', TEAL),
                ('TAGGED', 'Already tagged', BLUE), ('UNMATCHED', 'Unmatched paths', ORANGE),
                ('UNWATCHED', 'Not fully watched', MUTED)]):
            card = tk.Frame(metrics, bg=PANEL, padx=18, pady=12)
            card.grid(row=0, column=i, sticky='nsew', padx=(0 if i==0 else 10, 0))
            metrics.columnconfigure(i, weight=1)
            value = tk.StringVar(value='0')
            self.metrics[key] = value
            self.label(card, size=25, color=color, bg=PANEL, bold=True, textvariable=value).pack(anchor='w')
            self.label(card, name, 9, MUTED, PANEL).pack(anchor='w', pady=(3, 0))
        controls = tk.Frame(parent, bg=BG)
        controls.pack(fill='x', pady=(0, 12))
        self.scan_button = self.button(controls, 'Dry Run', lambda: self.start('scan'), BLUE)
        self.scan_button.pack(side='left')
        self.apply_button = self.button(controls, 'Apply Tags', lambda: self.start('apply'), ORANGE, BG, state='disabled')
        self.apply_button.pack(side='left', padx=8)
        self.cancel_button = self.button(controls, 'Stop', self.stop, state='disabled')
        self.cancel_button.pack(side='left')
        self.export_button = self.button(controls, 'Export CSV', self.export_csv, state='disabled')
        self.export_button.pack(side='right')
        scope_bar = tk.Frame(parent, bg=BG)
        scope_bar.pack(fill='x', pady=(0, 14))
        self.label(scope_bar, 'Apply to:', 9, MUTED).pack(side='left', padx=(0, 8))
        ttk.Combobox(scope_bar, textvariable=self.scope, values=['All ready torrents', 'Selected ready torrents'],
                     state='readonly', width=24).pack(side='left')
        self.label(scope_bar, 'Dry Run never changes tags.', 9, MUTED).pack(side='right')
        tools = tk.Frame(parent, bg=BG)
        tools.pack(fill='x', pady=(0, 10))
        search_entry = ttk.Entry(tools, textvariable=self.search)
        search_entry.pack(side='left', fill='x', expand=True)
        install_edit_menu(search_entry)
        self.label(tools, ' Search   ', 9, MUTED).pack(side='left')
        ttk.Combobox(tools, textvariable=self.filter, values=['All video']+list(STATUS.values()),
                     state='readonly', width=16).pack(side='right')
        table_frame = tk.Frame(parent, bg=PANEL)
        table_frame.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(table_frame, columns=('status', 'name', 'watched'), show='headings', selectmode='extended')
        self.tree.heading('status', text='STATUS', command=lambda: self.sort_table('status'))
        self.tree.heading('name', text='TORRENT', command=lambda: self.sort_table('torrent'))
        self.tree.heading('watched', text='WATCHED', command=lambda: self.sort_table('watched_files'))
        self.tree.column('status', width=118, minwidth=100, stretch=False)
        self.tree.column('name', width=580, minwidth=280)
        self.tree.column('watched', width=90, minwidth=85, stretch=False, anchor='center')
        scroll = ttk.Scrollbar(table_frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)
        for status, color in [('READY', TEAL), ('TAGGED', BLUE), ('UNMATCHED', ORANGE), ('ERROR', RED)]:
            self.tree.tag_configure(status, foreground=color)
        self.tree.bind('<<TreeviewSelect>>', self.show_details)
        self.label(parent, 'FILE DETAILS', 9, MUTED, bold=True).pack(anchor='w', pady=(12, 5))
        self.details = tk.Text(parent, height=3, bg=PANEL, fg=MUTED, relief='flat', padx=12, pady=8,
                               wrap='word', font=('Segoe UI', 9), state='disabled')
        self.details.pack(fill='x')
        install_edit_menu(self.details)
        self.set_text(self.details, 'Select a torrent to inspect unmatched paths or its watch count.')
        self.label(parent, size=10, color=TEXT, textvariable=self.phase).pack(anchor='w', pady=(14, 7))
        self.progress = ttk.Progressbar(parent, mode='determinate', maximum=100)
        self.progress.pack(fill='x')
        self.label(parent, size=9, color=MUTED, textvariable=self.footer_text).pack(anchor='w', pady=(7, 0))

    def _connections(self, parent):
        self.label(parent, 'Use your own accounts. Each person connects to their own servers.', 11, MUTED).pack(anchor='w', pady=(0, 18))
        columns = tk.Frame(parent, bg=BG)
        columns.pack(fill='x')
        self.inputs = []
        self.secret_entries = []

        def fields(card, items):
            for label, key, secret in items:
                self.label(card, label, 10, MUTED, PANEL).pack(anchor='w', pady=(0, 5))
                entry = ttk.Entry(card, textvariable=self.vars[key], show='*' if secret else '')
                entry.pack(fill='x', pady=(0, 12))
                install_edit_menu(entry)
                self.inputs.append(entry)
                if secret:
                    self.secret_entries.append(entry)

        media = tk.Frame(columns, bg=PANEL, padx=20, pady=18)
        media.grid(row=0, column=0, sticky='nsew')
        heading = tk.Frame(media, bg=PANEL)
        heading.pack(fill='x')
        self.label(heading, 'Media server', 17, TEXT, PANEL, True).pack(side='left')
        for text, value in (('Jellyfin', 'jellyfin'), ('Plex', 'plex')):
            radio = ttk.Radiobutton(heading, text=text, value=value, variable=self.vars['media_server'],
                                    command=self.show_media_fields)
            radio.pack(side='right', padx=(12, 0))
            self.inputs.append(radio)
        self.label(media, 'Read watch history for one profile or user', 9, MUTED, PANEL).pack(anchor='w', pady=(4, 18))
        self.plex_fields = tk.Frame(media, bg=PANEL)
        fields(self.plex_fields, [('Server URL', 'plex_url', False), ('Personal token', 'plex_token', True),
                                  ('Profile name (optional)', 'plex_user', False)])
        self.label(self.plex_fields, 'Leave profile blank to use the token owner.\nEnter an exact name to verify or switch profiles.',
                   9, MUTED, PANEL, justify='left').pack(anchor='w', pady=(0, 8))
        self.button(self.plex_fields, 'How to find my token', lambda: webbrowser.open(
            'https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/')).pack(anchor='w')
        self.jf_fields = tk.Frame(media, bg=PANEL)
        fields(self.jf_fields, [('Server URL', 'jf_url', False), ('User name', 'jf_user', False),
                                ('API key', 'jf_api_key', True), ('Password (only without API key)', 'jf_password', True)])
        self.label(self.jf_fields, 'Admins create API keys in Dashboard > API Keys. Other users enter a password.',
                   9, MUTED, PANEL, justify='left').pack(anchor='w')
        self.show_media_fields()

        qb = tk.Frame(columns, bg=PANEL, padx=20, pady=18)
        qb.grid(row=0, column=1, sticky='nsew', padx=(14, 0))
        for i in (0, 1):
            columns.columnconfigure(i, weight=1, uniform='connections')
        self.label(qb, 'qBittorrent', 17, TEXT, PANEL, True).pack(anchor='w')
        self.label(qb, 'Add the tag to matching video torrents', 9, MUTED, PANEL).pack(anchor='w', pady=(4, 18))
        fields(qb, [('Web UI URL', 'qb_url', False), ('Web UI username', 'qb_username', False),
                    ('Web UI password', 'qb_password', True), ('Existing tag', 'tag', False)])
        options = tk.Frame(parent, bg=PANEL, padx=18, pady=12)
        options.pack(fill='x', pady=(16, 0))
        ttk.Checkbutton(options, text='Show tokens and passwords', variable=self.show_secrets,
            command=lambda: [entry.configure(show='' if self.show_secrets.get() else '*') for entry in self.secret_entries]).pack(anchor='w')
        self.remember_check = ttk.Checkbutton(options, text='Remember credentials on this Windows account (encrypted)', variable=self.vars['remember'])
        self.remember_check.pack(anchor='w', pady=(5, 0))
        if sys.platform != 'win32':
            self.vars['remember'].set(False)
            self.remember_check.configure(state='disabled')
        actions = tk.Frame(parent, bg=BG)
        actions.pack(fill='x', pady=16)
        self.test_button = self.button(actions, 'Test Connections', lambda: self.start('test'), BLUE)
        self.test_button.pack(side='left')
        self.save_button = self.button(actions, 'Save Settings', self.save_settings)
        self.save_button.pack(side='left', padx=8)
        self.import_button = self.button(actions, 'Import config.json', self.import_settings)
        self.import_button.pack(side='left')
        auto_frame = tk.Frame(parent, bg=PANEL, padx=18, pady=14)
        auto_frame.pack(fill='x')
        ttk.Checkbutton(auto_frame, text='Auto sync and apply tags while this app is open', variable=self.auto,
                         command=self.auto_changed).pack(anchor='w')
        row = tk.Frame(auto_frame, bg=PANEL)
        row.pack(fill='x', pady=(10, 0))
        self.label(row, 'Run every', 10, MUTED, PANEL).pack(side='left')
        ttk.Combobox(row, textvariable=self.vars['interval'], state='readonly',
                     values=['5', '10', '15', '30', '60'], width=5).pack(side='left', padx=10)
        self.label(row, 'minutes. Each run checks watched state before adding tags.', 9, MUTED, PANEL).pack(side='left')
        self.label(parent, 'Settings are saved per user. The app folder contains no personal configuration. '
                   'To run with this window closed, use Schedule.', 9, MUTED).pack(anchor='w', pady=(14, 0))

    def _schedule(self, parent):
        self.label(parent, 'Run WatchBridge in the background with this window closed, while you are signed in to Windows.',
                   11, MUTED).pack(anchor='w', pady=(0, 18))
        card = tk.Frame(parent, bg=PANEL, padx=20, pady=18)
        card.pack(fill='x')
        self.label(card, 'Background schedule', 17, TEXT, PANEL, True).pack(anchor='w')
        self.label(card, 'Each run scans, then adds the tag to all ready torrents only when the scan has no errors. '
                   'Uses Windows Task Scheduler; no administrator rights or Windows service.',
                   9, MUTED, PANEL).pack(anchor='w', pady=(4, 16))
        self.schedule_mode = tk.StringVar(value=scheduler.MODES.get(self.vars['schedule_mode'].get(), 'Off'))
        self.day_vars = {}
        try:
            days = scheduler.parse_days(self.vars['schedule_days'].get())
        except ValueError:
            days = list(scheduler.DAYS)
        self.schedule_rows = {}
        # Rows for the chosen mode are shown inside this frame, above the summary line.
        fields = tk.Frame(card, bg=PANEL)

        def row(key, text):
            frame = tk.Frame(card if key == 'mode' else fields, bg=PANEL)
            self.label(frame, text, 10, MUTED, PANEL, width=16, anchor='w').pack(side='left')
            self.schedule_rows[key] = frame
            return frame

        def entry(parent, var, width):
            widget = ttk.Entry(parent, textvariable=var, width=width)
            widget.pack(side='left')
            install_edit_menu(widget)

        mode_row = row('mode', 'When')
        mode_row.pack(fill='x', pady=(0, 10))
        ttk.Combobox(mode_row, textvariable=self.schedule_mode, values=list(scheduler.MODES.values()),
                     state='readonly', width=24).pack(side='left')
        fields.pack(fill='x')
        every = row('interval', 'Run every')
        ttk.Combobox(every, textvariable=self.vars['schedule_every'], width=8,
                     values=['5', '10', '15', '30', '60', '120', '360', '720', '1440']).pack(side='left')
        self.label(every, '  minutes. Any value from 1 minute to 31 days (44640).', 9, MUTED, PANEL).pack(side='left')
        week = row('days', 'On days')
        for day in scheduler.DAYS:
            self.day_vars[day] = tk.BooleanVar(value=day in days)
            ttk.Checkbutton(week, text=day, variable=self.day_vars[day]).pack(side='left', padx=(0, 6))
        times = row('times', 'At')
        entry(times, self.vars['schedule_times'], 22)
        self.label(times, '  24-hour times, comma-separated, e.g. 03:00, 15:30', 9, MUTED, PANEL).pack(side='left')
        delay = row('delay', 'Wait after event')
        ttk.Combobox(delay, textvariable=self.vars['realtime_delay'], width=8,
                     values=['10', '30', '60', '120', '300']).pack(side='left')
        self.label(delay, '  seconds after playback stops or watched state changes on the media server.',
                   9, MUTED, PANEL).pack(side='left')
        fallback = row('fallback', 'Full check every')
        ttk.Combobox(fallback, textvariable=self.vars['realtime_fallback'], width=8,
                     values=['0', '15', '30', '60', '120', '360', '1440']).pack(side='left')
        self.label(fallback, '  minutes, in case an event is missed. 0 = events only.', 9, MUTED, PANEL).pack(side='left')
        logon = row('logon', '')
        ttk.Checkbutton(logon, text='Also run when I sign in to Windows', variable=self.vars['schedule_at_logon']).pack(side='left')
        failures = row('failures', 'Pause after')
        ttk.Combobox(failures, textvariable=self.vars['max_failures'], width=8,
                     values=['0', '1', '3', '5', '10']).pack(side='left')
        self.label(failures, '  consecutive failed runs. 0 = never pause.', 9, MUTED, PANEL).pack(side='left')
        self.schedule_summary = tk.StringVar()
        self.label(card, size=10, color=TEAL, bg=PANEL, textvariable=self.schedule_summary,
                   justify='left', wraplength=900).pack(anchor='w', pady=(6, 0))
        self.schedule_note = self.label(card, 'Real time needs a Plex token from the server owner, or a Jellyfin user '
                                        'password or API key. If events are unavailable, the full check still runs.',
                                        9, MUTED, PANEL, justify='left')
        self.schedule_mode.trace_add('write', lambda *_: self.show_schedule_fields())
        for var in (self.vars['schedule_every'], self.vars['schedule_times'], self.vars['realtime_delay'],
                    self.vars['realtime_fallback'], self.vars['schedule_at_logon'], *self.day_vars.values()):
            var.trace_add('write', lambda *_: self.update_schedule_summary())
        actions = tk.Frame(parent, bg=BG)
        actions.pack(fill='x', pady=16)
        self.schedule_button = self.button(actions, 'Save Schedule', self.save_schedule, BLUE)
        self.schedule_button.pack(side='left')
        self.button(actions, 'Run Now', self.schedule_run_now).pack(side='left', padx=8)
        self.button(actions, 'Resume', self.schedule_resume).pack(side='left')
        self.button(actions, 'Open Log', self.open_logs).pack(side='right')
        self.button(actions, 'Refresh', self.refresh_schedule_status).pack(side='right', padx=8)
        status = tk.Frame(parent, bg=PANEL, padx=18, pady=14)
        status.pack(fill='x')
        self.label(status, 'STATUS', 9, MUTED, PANEL, True).pack(anchor='w', pady=(0, 6))
        self.schedule_status = tk.StringVar(value='Reading Task Scheduler...')
        tk.Label(status, textvariable=self.schedule_status, bg=PANEL, fg=TEXT, justify='left', anchor='w',
                 font=('Consolas', 10), wraplength=1000).pack(anchor='w')
        self.label(parent, 'Saving the schedule also saves your connection settings, which must be remembered. '
                   'Command line: WatchBridgeCLI schedule set interval --every 30m  |  schedule show  |  schedule off',
                   9, MUTED, wraplength=1000, justify='left').pack(anchor='w', pady=(14, 0))
        self.schedule_refreshing = False
        self.show_schedule_fields()

    def schedule_mode_key(self):
        return next((k for k, v in scheduler.MODES.items() if v == self.schedule_mode.get()), 'off')

    def show_schedule_fields(self):
        mode = self.schedule_mode_key()
        visible = {'off': [], 'interval': ['interval', 'logon', 'failures'], 'daily': ['times', 'logon', 'failures'],
                   'weekly': ['days', 'times', 'logon', 'failures'], 'logon': ['failures'],
                   'realtime': ['delay', 'fallback', 'failures']}[mode]
        for key, frame in self.schedule_rows.items():
            if key != 'mode':
                frame.pack_forget()
        self.schedule_note.pack_forget()
        for key in visible:
            self.schedule_rows[key].pack(fill='x', pady=(0, 10))
        if mode == 'realtime':
            self.schedule_note.pack(anchor='w', pady=(4, 0))
        self.update_schedule_summary()

    def schedule_values(self):
        values = {k: v.get() for k, v in self.vars.items()}
        values['schedule_mode'] = self.schedule_mode_key()
        days = [d for d in scheduler.DAYS if self.day_vars[d].get()]
        values['schedule_days'] = ','.join(days) if days or values['schedule_mode'] == 'weekly' else 'all'
        return values

    def update_schedule_summary(self):
        if hasattr(self, 'schedule_note'):
            try:
                self.schedule_summary.set(scheduler.describe(self.schedule_values()))
            except ValueError as exc:
                self.schedule_summary.set(str(exc))

    def save_schedule(self):
        values = self.schedule_values()
        if values['schedule_mode'] != 'off' and not values.get('remember'):
            if not messagebox.askyesno('Remember credentials', 'Background runs need your connection credentials '
                    'while this window is closed. Remember them, encrypted for this Windows user?'):
                return
            values['remember'] = True
            self.vars['remember'].set(True)
        self.schedule_button.configure(state='disabled')
        self.schedule_status.set('Saving schedule...')

        def worker():
            try:
                self.events.put(('schedule_saved', (agent.configure(values), values)))
            except ValueError as exc:
                self.events.put(('schedule_error', str(exc)))
            except Exception as exc:
                self.events.put(('schedule_error', public_error(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def schedule_run_now(self):
        try:
            self.append_log(agent.run_now())
            self.after(2000, self.refresh_schedule_status)
        except (ValueError, RuntimeError) as exc:
            messagebox.showinfo('Schedule', str(exc))

    def schedule_resume(self):
        runtime.resume()
        self.append_log('Background runs resumed.')
        self.refresh_schedule_status()

    def refresh_schedule_status(self):
        if not hasattr(self, 'schedule_status') or self.schedule_refreshing:
            return
        self.schedule_refreshing = True
        values = {k: v.get() for k, v in self.vars.items()}

        def worker():
            try:
                text = '\n'.join(agent.status_lines(agent.status(values)))
            except Exception as exc:
                text = public_error(exc)
            self.events.put(('schedule_status', text))
        threading.Thread(target=worker, daemon=True).start()

    def schedule_tick(self):
        if getattr(self, 'current_page', None) == 'Schedule':
            self.refresh_schedule_status()
        self.after(15000, self.schedule_tick)

    def open_logs(self):
        folder = runtime.LOG_FILE.parent
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == 'win32':
            os.startfile(str(folder))
        else:
            webbrowser.open(folder.as_uri())

    def _activity(self, parent):
        bar = tk.Frame(parent, bg=BG)
        bar.pack(fill='x', pady=(0, 14))
        self.label(bar, 'Connection checks, scan progress and verified tag changes.', 10, MUTED).pack(side='left')
        self.button(bar, 'Open Reports Folder', self.open_reports).pack(side='right')
        self.log = tk.Text(parent, bg=PANEL, fg=MUTED, relief='flat', padx=16, pady=15,
                           font=('Consolas', 10), wrap='word', state='disabled')
        self.log.pack(fill='both', expand=True)
        install_edit_menu(self.log)
        self.append_log('Welcome to WatchBridge. Dry Run reads data; Apply Tags adds tags.')

    def _help(self, parent):
        body = GUIDE
        text = tk.Text(parent, bg=PANEL, fg=TEXT, relief='flat', padx=24, pady=20,
                       font=('Segoe UI', 11), wrap='word')
        text.pack(fill='both', expand=True)
        text.insert('1.0', body)
        text.configure(state='disabled')
        install_edit_menu(text)

    @staticmethod
    def set_text(widget, value):
        widget.configure(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('1.0', value)
        widget.configure(state='disabled')

    def append_log(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', time.strftime('%H:%M:%S') + '  ' + str(text) + '\n')
        # Keep memory use bounded on long-running auto sync sessions.
        if int(self.log.index('end-1c').split('.')[0]) > 4000:
            self.log.delete('1.0', '501.0')
        self.log.see('end')
        self.log.configure(state='disabled')

    def show_media_fields(self):
        jellyfin = self.vars['media_server'].get() == 'jellyfin'
        (self.plex_fields if jellyfin else self.jf_fields).pack_forget()
        (self.jf_fields if jellyfin else self.plex_fields).pack(fill='x')

    def config(self):
        return checked_config({k: v.get() for k, v in self.vars.items()})

    def same_config(self):
        try:
            current = self.config()
        except ValueError:
            return False
        return self.scan_config is not None and all(current[k] == self.scan_config[k]
            for k in current if k not in storage.LOCAL_KEYS)

    def refresh_actions(self):
        if not hasattr(self, 'apply_button'):
            return
        ready = sum(r['status']=='READY' for r in self.rows.values())
        errors = any(r['status']=='ERROR' for r in self.rows.values())
        can_apply = not self.busy and self.scan_complete and self.same_config() and ready and not errors
        self.apply_button.configure(state='normal' if can_apply else 'disabled', text='Apply Tags' + (f' ({ready})' if ready else ''))
        self.export_button.configure(state='normal' if self.rows and not self.busy else 'disabled')

    def set_busy(self, busy):
        self.busy = busy
        for widget in (self.scan_button, self.test_button, self.save_button, self.import_button, *self.inputs):
            widget.configure(state='disabled' if busy else 'normal')
        self.cancel_button.configure(state='normal' if busy else 'disabled')
        self.refresh_actions()

    def save_settings(self):
        try:
            storage.save(self.config())
            self.append_log('Settings saved for this Windows user.')
            messagebox.showinfo('Settings saved', 'Connection settings saved. Credentials are remembered only if selected.')
        except Exception as exc:
            messagebox.showerror('Settings', public_error(exc))

    def import_settings(self):
        filename = filedialog.askopenfilename(title='Import previous configuration', filetypes=[('JSON settings', '*.json')])
        if not filename:
            return
        try:
            data = json.loads(Path(filename).read_text(encoding='utf-8-sig'))
            if not isinstance(data, dict):
                raise ValueError('The settings file must contain a JSON object.')
            for key in self.vars:
                if key not in storage.LOCAL_KEYS and isinstance(data.get(key), str):
                    if key == 'media_server' and data[key] not in ('plex', 'jellyfin'):
                        continue
                    self.vars[key].set(data[key])
            self.show_media_fields()
            self.append_log('Imported connection details into memory. Save Settings to remember them.')
            self.connection_state.set('NOT CONNECTED')
        except Exception:
            messagebox.showerror('Import', 'Could not read this JSON settings file.')

    def start(self, mode):
        if self.busy:
            return
        try:
            cfg = self.config()
        except ValueError as exc:
            messagebox.showerror('Connections', str(exc))
            self.show_page('Connections')
            return
        selected_rows = []
        if mode == 'apply':
            if not self.scan_complete or not self.same_config() or any(r['status']=='ERROR' for r in self.rows.values()):
                messagebox.showinfo('Dry Run required', 'Run a successful dry scan using these connection settings first.')
                return
            if self.scope.get() == 'Selected ready torrents':
                selected_rows = [self.rows[h] for h in self.tree.selection() if self.rows[h]['status']=='READY']
            else:
                selected_rows = [r for r in self.rows.values() if r['status']=='READY']
            if not selected_rows:
                messagebox.showinfo('Nothing to tag', 'No ready torrents were selected for tagging.')
                return
        lock = None
        if mode != 'test':
            # One run at a time across this window, scheduled runs and the real-time agent.
            lock = runtime.RunLock()
            if not lock.acquire():
                text = 'A scheduled or real-time run is in progress. Try again in a minute.'
                if mode == 'auto':
                    self.append_log('Auto sync skipped: ' + text)
                    self.next_auto = time.monotonic() + int(self.vars['interval'].get())*60
                else:
                    messagebox.showinfo('Busy', text)
                return
        if mode in ('scan', 'auto'):
            self.rows.clear()
            self.scan_complete = False
            self.scan_config = cfg.copy()
            self.excluded = 0
            self.refresh_table()
            self.update_metrics()
        self.cancel_event = threading.Event()
        self.set_busy(True)
        self.progress.configure(mode='indeterminate')
        self.progress.start(12)
        self.phase.set({'test':'Testing connections...', 'scan':'Starting Dry Run...',
                        'apply':'Rechecking watched state before tagging...', 'auto':'Auto sync: scanning...'}[mode])
        self.append_log(self.phase.get())
        if mode != 'test':
            self.show_page('Scan & sync')

        def worker():
            engine = SyncEngine(cfg, lambda kind, data: self.events.put((kind, data)), self.cancel_event)
            try:
                if mode == 'test':
                    engine.connect()
                    result = {'mode':mode}
                elif mode == 'apply':
                    # Copies keep all mutation of displayed rows on the GUI thread.
                    added = engine.apply([dict(r) for r in selected_rows])
                    result = {'mode':mode, 'added':added}
                else:
                    rows, excluded = engine.scan()
                    added = 0
                    if mode == 'auto' and not any(r['status']=='ERROR' for r in rows):
                        added = engine.apply(rows)
                    result = {'mode':mode, 'rows':rows, 'excluded':excluded, 'added':added}
                self.events.put(('done', result))
            except Cancelled:
                self.events.put(('cancelled', mode))
            except Exception as exc:
                self.events.put(('failure', public_error(exc)))
            finally:
                engine.close()
                if lock:
                    lock.release()
        threading.Thread(target=worker, daemon=True).start()

    def stop(self):
        self.cancel_event.set()
        self.auto.set(False)
        self.next_auto = None
        self.phase.set('Stopping after the current request. Earlier tag additions are kept.')
        self.cancel_button.configure(state='disabled')

    def drain(self):
        dirty = False
        try:
            for _ in range(200):
                kind, data = self.events.get_nowait()
                if kind == 'log':
                    self.append_log(data)
                elif kind == 'profile':
                    self.current_profile.set(('Jellyfin user: ' if self.vars['media_server'].get() == 'jellyfin'
                                              else 'Plex profile: ') + data)
                    self.connection_state.set('CONNECTED')
                elif kind == 'phase':
                    self.phase.set(data)
                elif kind == 'schedule_status':
                    self.schedule_refreshing = False
                    self.schedule_status.set(data)
                elif kind == 'schedule_saved':
                    text, values = data
                    for key in scheduler.normalize(values):
                        self.vars[key].set(values[key])
                    self.schedule_button.configure(state='normal')
                    self.append_log('Schedule saved: ' + text)
                    self.refresh_schedule_status()
                elif kind == 'schedule_error':
                    self.schedule_button.configure(state='normal')
                    self.schedule_refreshing = False
                    self.refresh_schedule_status()
                    messagebox.showerror('Schedule', data)
                elif kind == 'progress':
                    self.progress.stop()
                    self.progress.configure(mode='determinate', value=100*data[0]/max(data[1], 1))
                    self.phase.set(f'Checked {data[0]:,} / {data[1]:,} torrents')
                elif kind in ('row', 'updated'):
                    self.rows[data['hash']] = data
                    self.upsert_row(data)
                    dirty = True
                elif kind == 'done':
                    self.finish(data)
                    dirty = True
                elif kind in ('failure', 'cancelled'):
                    self.progress.stop()
                    self.set_busy(False)
                    self.scan_complete = False
                    self.auto.set(False)
                    self.next_auto = None
                    text = data if kind == 'failure' else 'Stopped. Partial results are available; scan again before tagging.'
                    self.phase.set(text)
                    self.append_log(text)
                    self.save_report()
                    if kind == 'failure':
                        self.connection_state.set('CHECK CONNECTIONS')
                        messagebox.showerror('Operation stopped', text)
                    if self.closing:
                        self.destroy()
                        return
        except queue.Empty:
            pass
        if dirty:
            self.update_metrics()
            self.refresh_actions()
        self.after(80, self.drain)

    def finish(self, result):
        self.progress.stop()
        self.progress.configure(mode='determinate', value=100)
        self.set_busy(False)
        mode = result['mode']
        if mode in ('scan', 'auto'):
            self.rows = {r['hash']:r for r in result['rows']}
            self.excluded = result['excluded']
            self.scan_complete = not any(r['status']=='ERROR' for r in self.rows.values())
            self.refresh_table()
        if mode == 'test':
            text = 'Both connections verified. Start a Dry Run to find watched torrents.'
        elif mode == 'scan':
            text = 'Dry Run complete. No tags changed.'
        else:
            text = f"Finished. Verified {result['added']:,} tag additions."
        self.phase.set(text)
        self.append_log(text)
        if mode != 'test':
            self.save_report()
        if any(r['status']=='ERROR' for r in self.rows.values()) and mode != 'test':
            self.auto.set(False)
            self.next_auto = None
        self.footer_text.set(f'{len(self.rows):,} video torrents shown. {self.excluded:,} non-video torrents excluded.')
        if self.auto.get():
            self.next_auto = time.monotonic() + int(self.vars['interval'].get())*60
        if self.closing:
            self.destroy()

    def matches_filter(self, row):
        term = self.search.get().casefold().strip()
        return (self.filter.get() == 'All video' or STATUS.get(row['status']) == self.filter.get()) and (
            not term or term in (row['torrent'] + ' ' + row.get('unmatched_paths', '')).casefold())

    def upsert_row(self, row):
        h = row['hash']
        if not self.matches_filter(row):
            if self.tree.exists(h):
                self.tree.delete(h)
            return
        count = f"{row['watched_files']} / {row['video_files']}" if row['video_files'] != '' else '?'
        args = {'values':(STATUS.get(row['status'], row['status']), row['torrent'], count), 'tags':(row['status'],)}
        if self.tree.exists(h):
            self.tree.item(h, **args)
        else:
            self.tree.insert('', 'end', iid=h, **args)

    def refresh_table(self):
        if not hasattr(self, 'tree'):
            return
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for row in self.rows.values():
            self.upsert_row(row)
        self.tree.selection_set([h for h in selected if self.tree.exists(h)])

    def sort_table(self, key):
        reverse = getattr(self, 'sort_key', None) == key and not getattr(self, 'sort_reverse', False)
        self.sort_key, self.sort_reverse = key, reverse
        items = sorted(self.rows.items(), key=lambda x: str(x[1].get(key, '')).casefold(), reverse=reverse)
        self.rows = dict(items)
        self.refresh_table()

    def update_metrics(self):
        for key, var in self.metrics.items():
            var.set(format(sum(r['status']==key for r in self.rows.values()), ','))

    def show_details(self, _event=None):
        selection = self.tree.selection()
        if not selection:
            return
        row = self.rows[selection[0]]
        detail = row['torrent'] + '\n'
        detail += ('Unmatched paths:\n' + row['unmatched_paths'].replace(' | ', '\n')) if row['unmatched_paths'] else (
            row.get('error') or f"{row['watched_files']} of {row['video_files']} video files marked watched.")
        if len(selection)>1:
            detail += f'\n{len(selection)} rows selected. Use Selected ready torrents to apply only to this selection.'
        self.set_text(self.details, detail)

    def save_report(self):
        if not self.rows:
            return
        try:
            self.last_report = storage.APP_DIR / 'reports' / report_name()
            write_report(self.last_report, self.rows.values())
            self.append_log('CSV report saved in your reports folder.')
        except Exception:
            self.append_log('Could not save the automatic report. Use Export CSV to choose another folder.')

    def export_csv(self):
        filename = filedialog.asksaveasfilename(title='Export all video results', defaultextension='.csv',
            initialfile=report_name(), filetypes=[('CSV report', '*.csv')])
        if filename:
            try:
                write_report(filename, self.rows.values())
                self.append_log('Exported all video results to CSV. Search filters do not remove rows from exports.')
                messagebox.showinfo('Export complete', 'CSV report saved. It contains all video results, including unmatched paths.')
            except Exception:
                messagebox.showerror('Export', 'Could not save the report. Choose a writable folder.')

    def open_reports(self):
        folder = storage.APP_DIR / 'reports'
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == 'win32':
            os.startfile(str(folder))
        else:
            webbrowser.open(folder.as_uri())

    def auto_changed(self):
        self.next_auto = time.monotonic()+int(self.vars['interval'].get())*60 if self.auto.get() else None
        self.append_log('Auto sync enabled: future runs will add tags.' if self.auto.get() else 'Auto sync disabled.')

    def auto_tick(self):
        if self.auto.get() and self.next_auto is not None and time.monotonic() >= self.next_auto and not self.busy:
            self.next_auto = time.monotonic()+int(self.vars['interval'].get())*60
            self.start('auto')
        self.after(1000, self.auto_tick)

    def on_close(self):
        if self.busy:
            if not messagebox.askyesno('Stop and close', 'Stop this operation and close after the current request? Tags already added will remain.'):
                return
            self.closing = True
            self.stop()
        else:
            self.destroy()


def start_gui():
    try:
        if sys.platform == 'win32':
            import ctypes
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                pass
        App().mainloop()
    except Exception as exc:
        # Do not write traceback files containing personal connection information.
        try:
            messagebox.showerror('WatchBridge', 'The application could not start. '\
                'Use RUN.bat to install dependencies, then try again.\n' + type(exc).__name__)
        except Exception:
            pass
        raise SystemExit(1)
    return 0


if __name__ == '__main__':
    if len(sys.argv) > 1:
        # Command-line and Task Scheduler runs; see cli.py or run with --help.
        import cli
        sys.exit(cli.main(sys.argv[1:]))
    start_gui()
