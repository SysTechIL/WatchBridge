"""Explicit clipboard editing, including Ctrl shortcuts on Hebrew Windows layouts."""
import sys
import tkinter as tk


def edit(widget, action):
    is_text = isinstance(widget, tk.Text)
    disabled = str(widget.cget('state')) in ('disabled', 'readonly')
    try:
        if action == 'select_all':
            if is_text:
                widget.tag_add('sel', '1.0', 'end-1c')
            else:
                widget.selection_range(0, 'end')
                widget.icursor('end')
            return 'break'
        if action in ('copy', 'cut'):
            try:
                if is_text:
                    start, end = 'sel.first', 'sel.last'
                    value = widget.get(start, end)
                else:
                    start, end = widget.index('sel.first'), widget.index('sel.last')
                    value = widget.get()[start:end]
            except tk.TclError:
                return 'break'
            if action == 'cut' and disabled:
                return 'break'
            widget.clipboard_clear()
            widget.clipboard_append(value)
            if action == 'cut':
                widget.delete(start, end)
        elif action == 'paste' and not disabled:
            try:
                value = widget.clipboard_get()
            except tk.TclError:
                return 'break'
            try:
                widget.delete('sel.first', 'sel.last')
            except tk.TclError:
                pass
            widget.insert('insert', value)
            if not is_text:
                widget.icursor('end')
    except tk.TclError:
        # Clipboard can be empty, unavailable or temporarily held by another app.
        pass
    return 'break'


def windows_modifiers():
    """Read physical modifier state when Tk omits Ctrl in a non-Latin layout."""
    try:
        import ctypes
        state = ctypes.windll.user32.GetKeyState
        return bool(state(0x11) & 0x8000), bool(state(0x12) & 0x8000)
    except (AttributeError, OSError):
        return False, False


def shortcut(event):
    ctrl, alt = bool(event.state & 0x4), bool(event.state & 0x8)
    if sys.platform == 'win32':
        physical_ctrl, physical_alt = windows_modifiers()
        ctrl = ctrl or physical_ctrl
        # Tk's extra modifier bits vary between Windows keyboard layouts.
        # Use the actual Windows Alt state rather than treating extra bits as Alt.
        alt = physical_alt
    if not ctrl or alt:
        return None
    key = str(event.keysym).lower()
    if sys.platform == 'win32':
        # Tk keysyms follow the active layout; Windows VK keycodes remain stable.
        key = {65:'a',67:'c',86:'v',88:'x'}.get(int(event.keycode), key)
    action = {'a':'select_all','c':'copy','v':'paste','x':'cut'}.get(key)
    return edit(event.widget, action) if action else None


def install_shortcuts(widget):
    """Put editing ahead of widget, virtual-event and ttk class bindings."""
    tag = 'WatchBridgeClipboard'
    root = widget.winfo_toplevel()
    if not getattr(root, '_watchbridge_clipboard_installed', False):
        root.bind_class(tag, '<KeyPress>', shortcut)
        # Explicit Latin shortcuts also handle Tk mapping a physical chord to a
        # virtual event instead of matching the generic KeyPress binding.
        for key, action in [('a','select_all'),('c','copy'),('v','paste'),('x','cut')]:
            for letter in (key, key.upper()):
                root.bind_class(tag, '<Control-KeyPress-' + letter + '>',
                                lambda e, a=action: edit(e.widget, a))
        for sequence, action in [('<Shift-Insert>','paste'),('<Control-Insert>','copy'),
                                  ('<Shift-Delete>','cut'),('<<Paste>>','paste'),
                                  ('<<Copy>>','copy'),('<<Cut>>','cut'),
                                  ('<<SelectAll>>','select_all')]:
            root.bind_class(tag, sequence, lambda e, a=action: edit(e.widget, a))
        root._watchbridge_clipboard_installed = True
    widget.bindtags((tag,) + tuple(t for t in widget.bindtags() if t != tag))


def install(widget):
    menu = tk.Menu(widget, tearoff=False, bg='#192339', fg='#edf2ff',
                   activebackground='#263e68', activeforeground='#ffffff')
    for label, action, accelerator in [('Cut','cut','Ctrl+X'), ('Copy','copy','Ctrl+C'),
                                        ('Paste','paste','Ctrl+V')]:
        menu.add_command(label=label, accelerator=accelerator,
                         command=lambda a=action: edit(widget, a))
    menu.add_separator()
    menu.add_command(label='Select All', accelerator='Ctrl+A', command=lambda: edit(widget, 'select_all'))

    def popup(event):
        widget.focus_set()
        readonly = str(widget.cget('state')) in ('disabled', 'readonly')
        menu.entryconfigure('Paste', state='disabled' if readonly else 'normal')
        menu.entryconfigure('Cut', state='disabled' if readonly else 'normal')
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return 'break'

    widget.bind('<Button-3>', popup, add='+')
    install_shortcuts(widget)
    return menu
