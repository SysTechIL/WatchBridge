from pathlib import Path
import sys
import tkinter as tk
import types
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import clipboard_actions as clipboard


class Entry:
    def __init__(self, value='', clip='', selection=None, state='normal'):
        self.value, self.clip, self.selection, self.state = value,clip,selection,state
        self.cursor=len(value)
    def cget(self,name):return self.state
    def get(self):return self.value
    def index(self,index):
        if not self.selection:raise tk.TclError('No selection')
        return self.selection[0 if index=='sel.first' else 1]
    def delete(self,start,end):
        if isinstance(start,str):start,end=self.index(start),self.index(end)
        self.value=self.value[:start]+self.value[end:];self.cursor=start;self.selection=None
    def insert(self,index,value):
        self.value=self.value[:self.cursor]+value+self.value[self.cursor:];self.cursor+=len(value)
    def icursor(self,index):self.cursor=len(self.value)
    def selection_range(self,start,end):self.selection=(0,len(self.value))
    def clipboard_get(self):return self.clip
    def clipboard_clear(self):self.clip=''
    def clipboard_append(self,value):self.clip+=value


class ClipboardTests(unittest.TestCase):
    def test_paste_replaces_selection_once(self):
        e=Entry('old value',clip='new',selection=(0,9))
        self.assertEqual(clipboard.edit(e,'paste'),'break');self.assertEqual(e.value,'new')
    def test_hebrew_windows_shortcut(self):
        e=Entry(clip='pasted')
        event=types.SimpleNamespace(widget=e,state=4,keycode=86,keysym='hebrew_waw')
        with patch.object(clipboard.sys,'platform','win32'):
            self.assertEqual(clipboard.shortcut(event),'break')
        self.assertEqual(e.value,'pasted')
    def test_disabled_does_not_paste(self):
        e=Entry('keep',clip='replace',state='disabled')
        clipboard.edit(e,'paste');self.assertEqual(e.value,'keep')
    def test_copy_cut_select_all(self):
        e=Entry('abcd',selection=(1,3))
        clipboard.edit(e,'copy');self.assertEqual(e.clip,'bc');self.assertEqual(e.value,'abcd')
        clipboard.edit(e,'cut');self.assertEqual(e.value,'ad')
        clipboard.edit(e,'select_all');self.assertEqual(e.selection,(0,2))
    def test_altgr_does_not_trigger_shortcut(self):
        e=Entry(clip='paste')
        event=types.SimpleNamespace(widget=e,state=4|8,keycode=86,keysym='v')
        # AltGr is reported by Windows as Ctrl+Alt held together.
        with patch.object(clipboard,'windows_modifiers',return_value=(True,True)):
            self.assertIsNone(clipboard.shortcut(event));self.assertEqual(e.value,'')
    def test_no_selection_copy_is_safe(self):
        e=Entry('text',clip='keep')
        clipboard.edit(e,'copy');self.assertEqual(e.clip,'keep')
    def test_windows_physical_control_fallback(self):
        e=Entry('abc')
        event=types.SimpleNamespace(widget=e,state=0,keycode=65,keysym='hebrew_shin')
        with patch.object(clipboard.sys,'platform','win32'),patch.object(clipboard,'windows_modifiers',return_value=(True,False)):
            self.assertEqual(clipboard.shortcut(event),'break')
        self.assertEqual(e.selection,(0,3))
    def test_windows_altgr_not_captured(self):
        e=Entry(clip='keep')
        event=types.SimpleNamespace(widget=e,state=4,keycode=86,keysym='v')
        with patch.object(clipboard.sys,'platform','win32'),patch.object(clipboard,'windows_modifiers',return_value=(True,True)):
            self.assertIsNone(clipboard.shortcut(event))
        self.assertEqual(e.value,'')
    def test_shortcuts_precede_widget_class(self):
        class Root:
            def __init__(self):self.bindings={}
            def bind_class(self,tag,sequence,fn):self.bindings[(tag,sequence)]=fn
        class Field(Entry):
            def __init__(self,root):super().__init__('old',clip='new');self.root=root;self.tags=('entry','TEntry','root','all')
            def winfo_toplevel(self):return self.root
            def bindtags(self,tags=None):
                if tags is not None:self.tags=tags
                return self.tags
        root=Root();field=Field(root);clipboard.install_shortcuts(field)
        self.assertEqual(field.tags[0],'WatchBridgeClipboard')
        self.assertEqual(field.tags[1:],('entry','TEntry','root','all'))
        event=types.SimpleNamespace(widget=field)
        root.bindings[('WatchBridgeClipboard','<Control-KeyPress-a>')](event)
        self.assertEqual(field.selection,(0,3))
        root.bindings[('WatchBridgeClipboard','<Control-KeyPress-v>')](event)
        self.assertEqual(field.value,'new')
        clipboard.install_shortcuts(field)
        self.assertEqual(field.tags.count('WatchBridgeClipboard'),1)


if __name__=='__main__':unittest.main()
