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

from engine import SyncEngine, Cancelled, clean_url, public_error, write_report, report_name
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
        self.title('WatchBridge | Plex to qBittorrent')
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
        self.current_profile = tk.StringVar(value='No Plex profile connected')
        self.phase = tk.StringVar(value='Connect your accounts, then start a dry run.')
        self.connection_state = tk.StringVar(value='NOT CONNECTED')
        self.footer_text = tk.StringVar(value='No changes made. Non-video torrents are excluded.')
        self._style()
        self._layout()
        self.search.trace_add('write', lambda *_: self.refresh_table())
        self.filter.trace_add('write', lambda *_: self.refresh_table())
        for key, var in self.vars.items():
            if key not in ('remember', 'interval'):
                var.trace_add('write', lambda *_: self.refresh_actions())
        self.protocol('WM_DELETE_WINDOW', self.on_close)
        self.after(80, self.drain)
        self.after(1000, self.auto_tick)
        if self.error_on_load:
            self.after(300, lambda: messagebox.showwarning('Settings', self.error_on_load))
        self.show_page('Connections' if not values.get('plex_token') else 'Scan & sync')

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
        self.label(sidebar, 'Plex to qBittorrent', 10, MUTED, PANEL).pack(anchor='w', padx=25, pady=(4, 32))
        self.nav = {}
        self.pages = {}
        for name in ('Scan & sync', 'Connections', 'Activity', 'Help'):
            b = self.button(sidebar, name, lambda n=name: self.show_page(n), color=PANEL, anchor='w')
            b.pack(fill='x', padx=12, pady=3)
            self.nav[name] = b
        bottom = tk.Frame(sidebar, bg=PANEL)
        bottom.pack(side='bottom', fill='x', padx=24, pady=25)
        self.label(bottom, 'ADD TAGS ONLY', 9, TEAL, PANEL, True).pack(anchor='w')
        self.label(bottom, 'Your media stays where it is.\nNo deletion. No tag removal.', 9,
                   MUTED, PANEL, justify='left').pack(anchor='w', pady=(8, 14))
        self.label(bottom, 'v1.0.2  /  Windows', 9, MUTED, PANEL).pack(anchor='w')
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
        self._activity(self.pages['Activity'])
        self._help(self.pages['Help'])

    def show_page(self, name):
        for page in self.pages.values():
            page.pack_forget()
        self.pages[name].pack(fill='both', expand=True)
        self.page_title.configure(text=name)
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
        for i, (title, subtitle, fields) in enumerate([
            ('Plex', 'Read watch history for one profile', [
                ('Server URL', 'plex_url', False), ('Personal token', 'plex_token', True),
                ('Profile name (optional)', 'plex_user', False)]),
            ('qBittorrent', 'Add the tag to matching video torrents', [
                ('Web UI URL', 'qb_url', False), ('Web UI username', 'qb_username', False),
                ('Web UI password', 'qb_password', True), ('Existing tag', 'tag', False)])]):
            card = tk.Frame(columns, bg=PANEL, padx=20, pady=18)
            card.grid(row=0, column=i, sticky='nsew', padx=(0 if i==0 else 14, 0))
            columns.columnconfigure(i, weight=1, uniform='connections')
            self.label(card, title, 17, TEXT, PANEL, True).pack(anchor='w')
            self.label(card, subtitle, 9, MUTED, PANEL).pack(anchor='w', pady=(4, 18))
            for label, key, secret in fields:
                self.label(card, label, 10, MUTED, PANEL).pack(anchor='w', pady=(0, 5))
                entry = ttk.Entry(card, textvariable=self.vars[key], show='*' if secret else '')
                entry.pack(fill='x', pady=(0, 12))
                install_edit_menu(entry)
                self.inputs.append(entry)
                if secret:
                    self.secret_entries.append(entry)
            if i==0:
                self.label(card, 'Leave profile blank to use the token owner.\nEnter an exact name to verify or switch profiles.',
                           9, MUTED, PANEL, justify='left').pack(anchor='w', pady=(0, 8))
                self.button(card, 'How to find my token', lambda: webbrowser.open(
                    'https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/')).pack(anchor='w')
        options = tk.Frame(parent, bg=PANEL, padx=18, pady=12)
        options.pack(fill='x', pady=(16, 0))
        ttk.Checkbutton(options, text='Show token and password', variable=self.show_secrets,
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
        self.label(parent, 'Settings are saved per user. The app folder contains no personal configuration.', 9, MUTED).pack(anchor='w', pady=(14, 0))

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
        body = (
            '1  CONNECT\nEnter your Plex URL and personal token, then your qBittorrent Web UI details. '
            'Create your chosen tag in qBittorrent before testing the connection.\n\n'
            '2  DRY RUN\nReads your watched state and compares full file paths. No tags are changed. '
            'Review Ready, Unwatched and Unmatched rows. Non-video torrents are excluded.\n\n'
            '3  APPLY TAGS\nChoose all ready torrents or selected ready torrents. The app rechecks '
            'your Plex watched state and qBittorrent file paths, then adds and verifies the tag.\n\n'
            'HOW MATCHING WORKS\nA movie or single episode must be marked watched in Plex. '
            'Season and series packs require every video file in that torrent to be watched. '
            'All episode records sharing the same file must be watched. Partial viewing is not enough.\n\n'
            'PATHS AND FILES\nPlex and qBittorrent must report identical Windows paths. Samples, subtitles '
            'and NFO files are ignored. RAR and ISO contents are not inspected. Bonus videos absent from '
            'Plex prevent the torrent from being marked ready. Downloads must be complete.\n\n'
            'YOUR DATA\nNo files or torrents are deleted, and tags are never removed. The app does not '
            'change Plex watched state. A later change to unwatched will not remove an existing tag. '
            'Credentials are optional to remember and are encrypted with Windows DPAPI for your account. '
            'Plex profile verification requires access to plex.tv.\n\n'
            'AUTOMATION\nAuto sync is off at startup. When enabled, each interval performs a dry scan and '
            'then applies tags to all ready torrents. It only runs while this app is open. '
            'Errors disable auto sync. Stop interrupts after the current network request finishes.\n\n'
            'SHARING\nShare only the source ZIP or the built application folder. Do not include your '
            'personal settings, imported config.json, reports or screenshots. Recipients enter their own details.')
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

    def config(self):
        values = {k: v.get() for k, v in self.vars.items()}
        values['plex_url'] = clean_url(values['plex_url'])
        values['qb_url'] = clean_url(values['qb_url'])
        values['tag'] = values['tag'].strip()
        if not values['plex_token'].strip():
            raise ValueError('Enter your Plex token in Connections.')
        if not values['tag'] or ',' in values['tag']:
            raise ValueError('Use one existing tag without commas.')
        return values

    def same_config(self):
        try:
            current = self.config()
        except ValueError:
            return False
        return self.scan_config is not None and all(current[k] == self.scan_config[k]
            for k in current if k not in ('remember', 'interval'))

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
                if key not in ('remember', 'interval') and isinstance(data.get(key), str):
                    self.vars[key].set(data[key])
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
                    self.current_profile.set('Plex profile: ' + data)
                    self.connection_state.set('CONNECTED')
                elif kind == 'phase':
                    self.phase.set(data)
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


if __name__ == '__main__':
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
