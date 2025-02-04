# -*- coding: utf-8 -*-
import wx
import wx.adv
import os
import send2trash
import win32api
import win32con
import win32gui
import win32com.client
import win32com.shell.shell as shell
import win32com.shell.shellcon as shellcon
import time
import shutil
from collections import deque
from datetime import datetime
import pythoncom
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

pythoncom.CoInitialize()  # 添加在模块初始化处
class FileChangeHandler(FileSystemEventHandler):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        
    def on_created(self, event):
        wx.CallAfter(self.callback, "创建: " + event.src_path)
        
    def on_deleted(self, event):
        wx.CallAfter(self.callback, "删除: " + event.src_path)
        
    def on_modified(self, event):
        if not event.is_directory:
            wx.CallAfter(self.callback, "修改: " + event.src_path)
            
    def on_moved(self, event):
        wx.CallAfter(self.callback, f"移动: {event.src_path} -> {event.dest_path}")


class FileExplorerFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title="多标签文件浏览器", size=(1024, 768))
        
        # 初始化基本变量
        self.current_path = os.path.expanduser("~")
        self.history = deque(maxlen=10)
        self.clipboard = {"type": None, "paths": []}
        self.observer = Observer()
        self.closed_tabs = {"left": deque(maxlen=10), "right": deque(maxlen=10)}
        self._icon_cache = {}
        self.splitter_ratio = 0.5  # 保存分割比例
        
        # 设置窗口样式
        self.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW))
        
        # 创建主面板
        self.main_panel = wx.Panel(self)
        
        # 创建分割窗口
        self.splitter = wx.SplitterWindow(self.main_panel, style=wx.SP_3D | wx.SP_LIVE_UPDATE | wx.SP_PERMIT_UNSPLIT)
        
        # 创建左右两个标签页面板
        self.left_notebook = wx.Notebook(self.splitter)
        self.right_notebook = wx.Notebook(self.splitter)
        self.tabs = {"left": [], "right": []}
        
        # 设置分割窗口
        self.splitter.SplitVertically(self.left_notebook, self.right_notebook)
        
        # 绑定分割窗口事件
        self.splitter.Bind(wx.EVT_SPLITTER_SASH_POS_CHANGED, self.on_splitter_changed)
        self.splitter.Bind(wx.EVT_SPLITTER_SASH_POS_CHANGING, self.on_splitter_changing)
        
        # 主布局
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        main_sizer.Add(self.splitter, 1, wx.EXPAND)
        self.main_panel.SetSizer(main_sizer)
        
        # 加载系统图标
        self.load_system_icons()
        
        # 创建状态栏
        self.status_bar = self.CreateStatusBar(1)
        
        # 初始化菜单
        self.init_menu()
        
        # 绑定事件
        self.left_notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, lambda evt: self.on_tab_switch(evt, "left"))
        self.right_notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, lambda evt: self.on_tab_switch(evt, "right"))
        self.left_notebook.Bind(wx.EVT_LEFT_DCLICK, lambda evt: self.on_notebook_dclick(evt, "left"))
        self.right_notebook.Bind(wx.EVT_LEFT_DCLICK, lambda evt: self.on_notebook_dclick(evt, "right"))
        self.Bind(wx.EVT_SIZE, self.on_size)
        self.Bind(wx.EVT_CLOSE, self.OnClose)
        
        # 初始化标签页
        self.init_notebooks()
        
        # 调整大小和显示
        self.main_panel.Layout()
        self.Centre()
        
        # 设置初始分割位置为窗口宽度的一半
        wx.CallAfter(self.init_splitter_position)
        
        self.Show()
        
        # 开始监控文件系统变化
        self.start_watching(self.current_path)

    def init_splitter_position(self):
        """初始化分割窗口位置"""
        width = self.GetClientSize().GetWidth()
        self.splitter.SetSashPosition(int(width * self.splitter_ratio))
        self.splitter.SetMinimumPaneSize(200)
        self.splitter.SetSashGravity(0.5)

    def init_theme_menu(self):
        """初始化主题菜单"""
        menubar = wx.MenuBar()
        view_menu = wx.Menu()
        self.theme_items = {
            'light': view_menu.AppendRadioItem(wx.ID_ANY, "浅色主题"),
            'dark': view_menu.AppendRadioItem(wx.ID_ANY, "深色主题"),
            'system': view_menu.AppendRadioItem(wx.ID_ANY, "系统默认")
        }
        menubar.Append(view_menu, "&视图")
        self.SetMenuBar(menubar)
        
        # 绑定主题切换事件
        for item in self.theme_items.values():
            self.Bind(wx.EVT_MENU, self.on_change_theme, item)

    def get_selected_paths(self):
        """获取选中的文件路径列表"""
        selected_paths = []
        current_tab = self.get_current_tab()
        if not current_tab:
            return selected_paths
            
        list_ctrl = current_tab['list']
        item = -1
        while True:
            item = list_ctrl.GetNextItem(item, wx.LIST_NEXT_ALL, wx.LIST_STATE_SELECTED)
            if item == -1:
                break
            name = list_ctrl.GetItem(item, 1).GetText()
            path = os.path.join(current_tab['path'], name)
            selected_paths.append(path)
        return selected_paths

    def on_tab_switch(self, event, side):
        """切换标签页时更新监控路径"""
        current = self.get_current_tab(side)
        if current:
            self.start_watching(current['path'])
        event.Skip()

    def navigate_to(self, path, side=None):
        """导航到指定路径"""
        try:
            # 规范化路径
            path = os.path.normpath(path)
            
            # 检查路径是否存在且可访问
            if not os.path.exists(path):
                wx.MessageBox(f"路径不存在: {path}", "错误", wx.OK | wx.ICON_ERROR)
                return
                
            if not os.access(path, os.R_OK):
                wx.MessageBox(f"无法访问路径: {path}", "错误", wx.OK | wx.ICON_ERROR)
                return
            
            # 获取当前标签页
            if side is None:
                current_tab = self.get_current_tab()
            else:
                current_tab = self.get_current_tab(side)
                
            if not current_tab:
                return
                
            # 如果是相同路径，直接刷新
            if current_tab['path'] == path:
                self.refresh_file_list(current_tab)
                return
                
            # 更新路径
            current_tab['path'] = path
            current_tab['history'].append(path)
            
            # 更新标签页标题
            notebook = self.left_notebook if current_tab in self.tabs['left'] else self.right_notebook
            index = notebook.GetSelection()
            if index != -1:
                title = os.path.basename(path) or path
                notebook.SetPageText(index, title)
            
            # 更新路径输入框
            current_tab['path_ctrl'].SetValue(path)
            
            # 刷新文件列表
            self.refresh_file_list(current_tab)
            
            # 更新监控
            self.start_watching(path)
            
        except Exception as e:
            wx.LogError(f"导航失败: {str(e)}")

    def OnClose(self, event):
        """窗口关闭时清理资源"""
        if self.observer and self.observer.is_alive():
            self.observer.stop()
            self.observer.join()
        self.clear_icon_cache()
        self.Destroy()

    def init_notebooks(self):
        """初始化左右标签页"""
        # 创建左侧默认标签页
        self.add_tab(os.path.expanduser("~"), "left")
        # 创建左侧"+"标签页
        plus_panel = wx.Panel(self.left_notebook)
        self.left_notebook.AddPage(plus_panel, "+", False)
        
        # 创建右侧默认标签页
        self.add_tab(os.path.expanduser("~"), "right")
        # 创建右侧"+"标签页
        plus_panel = wx.Panel(self.right_notebook)
        self.right_notebook.AddPage(plus_panel, "+", False)

    def add_tab(self, initial_path, side="left"):
        """创建新标签页"""
        notebook = self.left_notebook if side == "left" else self.right_notebook
        
        # 创建标签页面板
        panel = wx.Panel(notebook)
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # 创建工具栏
        toolbar = wx.ToolBar(panel)
        # 添加工具栏按钮并设置提示
        back_tool = toolbar.AddTool(wx.ID_BACKWARD, "后退", 
            wx.ArtProvider.GetBitmap(wx.ART_GO_BACK, size=(16, 16)))
        forward_tool = toolbar.AddTool(wx.ID_FORWARD, "前进", 
            wx.ArtProvider.GetBitmap(wx.ART_GO_FORWARD, size=(16, 16)))
        up_tool = toolbar.AddTool(wx.ID_UP, "上级", 
            wx.ArtProvider.GetBitmap(wx.ART_GO_UP, size=(16, 16)))
        toolbar.AddSeparator()
        new_folder_tool = toolbar.AddTool(wx.ID_NEW, "新建文件夹", 
            wx.ArtProvider.GetBitmap(wx.ART_NEW_DIR, size=(16, 16)))
        refresh_tool = toolbar.AddTool(wx.ID_REFRESH, "刷新", 
            wx.ArtProvider.GetBitmap(wx.ART_REDO, size=(16, 16)))
        
        # 设置工具栏按钮提示
        toolbar.SetToolShortHelp(wx.ID_BACKWARD, "后退 (Alt+←)")
        toolbar.SetToolShortHelp(wx.ID_FORWARD, "前进 (Alt+→)")
        toolbar.SetToolShortHelp(wx.ID_UP, "上级目录 (Alt+↑)")
        toolbar.SetToolShortHelp(wx.ID_NEW, "新建文件夹 (Ctrl+N)")
        toolbar.SetToolShortHelp(wx.ID_REFRESH, "刷新 (F5)")
        
        toolbar.Realize()
        
        # 路径输入框
        path_ctrl = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        path_ctrl.SetValue(initial_path)
        
        # 创建图标列表
        icon_list = wx.ImageList(16, 16)
        
        # 文件列表
        file_list = wx.ListCtrl(panel, style=wx.LC_REPORT|wx.LC_SINGLE_SEL)
        file_list.SetImageList(icon_list, wx.IMAGE_LIST_SMALL)
        
        # 添加列
        file_list.InsertColumn(0, "", width=30)
        file_list.InsertColumn(1, "名称", width=200)
        file_list.InsertColumn(2, "大小", width=100)
        file_list.InsertColumn(3, "修改日期", width=150)
        
        # 布局
        sizer.Add(toolbar, 0, wx.EXPAND)
        sizer.Add(path_ctrl, 0, wx.EXPAND|wx.ALL, 5)
        sizer.Add(file_list, 1, wx.EXPAND|wx.ALL, 5)
        panel.SetSizer(sizer)
        
        # 绑定事件
        path_ctrl.Bind(wx.EVT_TEXT_ENTER, self.on_path_enter)
        file_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_item_activated)
        file_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_item_selected)
        file_list.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self.on_item_right_click)
        file_list.Bind(wx.EVT_SIZE, lambda evt: self.adjust_list_columns(file_list))
        toolbar.Bind(wx.EVT_TOOL, self.on_back, id=wx.ID_BACKWARD)
        toolbar.Bind(wx.EVT_TOOL, self.on_forward, id=wx.ID_FORWARD)
        toolbar.Bind(wx.EVT_TOOL, self.on_up, id=wx.ID_UP)
        toolbar.Bind(wx.EVT_TOOL, self.new_folder, id=wx.ID_NEW)
        toolbar.Bind(wx.EVT_TOOL, lambda evt: self.refresh_file_list(), id=wx.ID_REFRESH)
        
        # 记录标签页状态
        tab_data = {
            "panel": panel,
            "path": initial_path,
            "path_ctrl": path_ctrl,
            "list": file_list,
            "icon_list": icon_list,
            "history": deque([initial_path], maxlen=10)
        }
        
        # 如果是第一个标签页，直接添加
        if not self.tabs[side]:
            self.tabs[side].append(tab_data)
            notebook.InsertPage(0, panel, os.path.basename(initial_path) or initial_path, True)
        else:
            # 在"+"标签页之前插入新标签页
            self.tabs[side].append(tab_data)
            notebook.InsertPage(notebook.GetPageCount() - 1, panel, os.path.basename(initial_path) or initial_path, True)
        
        # 刷新文件列表
        self.refresh_file_list(tab_data)
        
        # 调整布局
        panel.Layout()

    def on_add_tab(self, event):
        """添加新标签页"""
        default_path = os.path.expanduser("~")
        self.add_tab(default_path)

    def on_close_tab(self, event):
        """关闭当前标签页"""
        current_tab = self.get_current_tab()
        if not current_tab:
            return
            
        # 获取当前标签页所在的notebook和索引
        if current_tab in self.tabs['left']:
            notebook = self.left_notebook
            side = 'left'
            index = self.tabs['left'].index(current_tab)
        else:
            notebook = self.right_notebook
            side = 'right'
            index = self.tabs['right'].index(current_tab)
            
        self.close_tab(index, side)

    def get_current_tab(self, side=None):
        """获取当前活动标签页数据"""
        if side is None:
            # 获取当前焦点所在的标签页
            focused = wx.Window.FindFocus()
            if focused:
                # 向上查找父窗口，直到找到标签页
                parent = focused.GetParent()
                while parent and parent != self.left_notebook and parent != self.right_notebook:
                    parent = parent.GetParent()
                if parent == self.left_notebook:
                    side = "left"
                elif parent == self.right_notebook:
                    side = "right"
                else:
                    # 如果找不到，默认使用左侧标签页
                    side = "left"
            else:
                side = "left"
        
        notebook = self.left_notebook if side == "left" else self.right_notebook
        current = notebook.GetSelection()
        if current != -1 and current < len(self.tabs[side]):
            return self.tabs[side][current]
        return None

    def init_menu(self):
        """初始化菜单栏"""
        menubar = wx.MenuBar()
        
        # 文件菜单
        file_menu = wx.Menu()
        file_menu.Append(wx.ID_NEW, "新建文件夹\tCtrl+N")
        file_menu.AppendSeparator()
        file_menu.Append(wx.ID_CLOSE, "关闭标签页\tCtrl+W")
        restore_tab_item = file_menu.Append(wx.ID_ANY, "恢复关闭的标签页\tCtrl+Shift+T")
        file_menu.AppendSeparator()
        file_menu.Append(wx.ID_EXIT, "退出\tAlt+F4")
        menubar.Append(file_menu, "文件(&F)")
        
        # 编辑菜单
        edit_menu = wx.Menu()
        edit_menu.Append(wx.ID_CUT, "剪切\tCtrl+X")
        edit_menu.Append(wx.ID_COPY, "复制\tCtrl+C")
        edit_menu.Append(wx.ID_PASTE, "粘贴\tCtrl+V")
        edit_menu.AppendSeparator()
        edit_menu.Append(wx.ID_DELETE, "删除\tDel")
        menubar.Append(edit_menu, "编辑(&E)")
        
        # 视图菜单
        view_menu = wx.Menu()
        view_menu.Append(wx.ID_REFRESH, "刷新\tF5")
        
        # 主题子菜单
        theme_menu = wx.Menu()
        self.theme_items = {
            'light': theme_menu.AppendRadioItem(wx.ID_ANY, "浅色主题"),
            'dark': theme_menu.AppendRadioItem(wx.ID_ANY, "深色主题"),
            'system': theme_menu.AppendRadioItem(wx.ID_ANY, "系统默认")
        }
        view_menu.AppendSubMenu(theme_menu, "主题")
        menubar.Append(view_menu, "视图(&V)")
        
        self.SetMenuBar(menubar)
        
        # 绑定菜单事件
        self.Bind(wx.EVT_MENU, self.new_folder, id=wx.ID_NEW)
        self.Bind(wx.EVT_MENU, self.on_close_tab, id=wx.ID_CLOSE)
        self.Bind(wx.EVT_MENU, lambda evt: self.Close(), id=wx.ID_EXIT)
        self.Bind(wx.EVT_MENU, self.on_cut, id=wx.ID_CUT)
        self.Bind(wx.EVT_MENU, self.on_copy, id=wx.ID_COPY)
        self.Bind(wx.EVT_MENU, self.on_paste, id=wx.ID_PASTE)
        self.Bind(wx.EVT_MENU, self.delete_items, id=wx.ID_DELETE)
        self.Bind(wx.EVT_MENU, lambda evt: self.refresh_file_list(), id=wx.ID_REFRESH)
        self.Bind(wx.EVT_MENU, self.restore_closed_tab, id=restore_tab_item.GetId())
        
        # 绑定主题切换事件
        for item in self.theme_items.values():
            self.Bind(wx.EVT_MENU, self.on_change_theme, id=item.GetId())
            
        # 设置默认主题
        self.theme_items['system'].Check(True)

    def refresh_all_tabs(self):
        """刷新所有标签页"""
        for side in self.tabs:
            for tab in self.tabs[side]:
                self.refresh_file_list(tab)
 
    def start_watching(self, path):
        """启动目录监控"""
        try:
            if self.observer and self.observer.is_alive():
                if self.watch_dog:
                    self.observer.unschedule(self.watch_dog)
                
            handler = FileChangeHandler(self.on_file_change)
            self.watch_dog = self.observer.schedule(handler, path, recursive=False)
            if not self.observer.is_alive():
                self.observer.start()
                
        except Exception as e:
            wx.LogError(f"监控启动失败: {str(e)}")

    def on_file_change(self, msg):
        """文件变化回调"""
        wx.CallAfter(self.status_bar.SetStatusText, msg, 0)
        wx.CallAfter(self.refresh_file_list)

    def sync_directory_changes(self):
        """监控目录变化并同步"""
        # 使用watchdog库实现文件系统监控
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
        
        class ChangeHandler(FileSystemEventHandler):
            def __init__(self, callback):
                self.callback = callback
                
            def on_modified(self, event):
                self.callback()
        
        self.observer = Observer()
        for side in self.tabs:
            for tab in self.tabs[side]:
                handler = ChangeHandler(lambda: wx.CallAfter(self.refresh_all_tabs))
                self.observer.schedule(handler, tab['path'], recursive=False)
        self.observer.start()

    def on_change_theme(self, event):
        """切换应用程序主题"""
        selected = next(k for k,v in self.theme_items.items() if v.IsChecked())
        self.apply_theme(selected)

    def apply_theme(self, theme_name):
        """应用主题配色方案"""
        themes = {
            'light': {
                'bg': wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW),
                'fg': wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT),
                'list_bg': wx.SystemSettings.GetColour(wx.SYS_COLOUR_LISTBOX),
                'list_fg': wx.SystemSettings.GetColour(wx.SYS_COLOUR_LISTBOXTEXT),
                'toolbar_bg': wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE),
                'textctrl_bg': wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW),
                'textctrl_fg': wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT),
                'notebook_bg': wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE),
                'notebook_fg': wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNTEXT)
            },
            'dark': {
                'bg': wx.Colour(53, 53, 53),
                'fg': wx.Colour(240, 240, 240),
                'list_bg': wx.Colour(30, 30, 30),
                'list_fg': wx.Colour(240, 240, 240),
                'toolbar_bg': wx.Colour(45, 45, 45),
                'textctrl_bg': wx.Colour(30, 30, 30),
                'textctrl_fg': wx.Colour(240, 240, 240),
                'notebook_bg': wx.Colour(45, 45, 45),
                'notebook_fg': wx.Colour(240, 240, 240)
            },
            'system': {
                'bg': wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW),
                'fg': wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT),
                'list_bg': wx.SystemSettings.GetColour(wx.SYS_COLOUR_LISTBOX),
                'list_fg': wx.SystemSettings.GetColour(wx.SYS_COLOUR_LISTBOXTEXT),
                'toolbar_bg': wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE),
                'textctrl_bg': wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW),
                'textctrl_fg': wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT),
                'notebook_bg': wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE),
                'notebook_fg': wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNTEXT)
            }
        }
        
        theme = themes.get(theme_name, themes['system'])
        
        # 设置主窗口颜色
        self.SetBackgroundColour(theme['bg'])
        self.SetForegroundColour(theme['fg'])
        
        # 设置面板颜色
        self.main_panel.SetBackgroundColour(theme['bg'])
        self.main_panel.SetForegroundColour(theme['fg'])
        
        # 设置标签页颜色
        for side in ['left', 'right']:
            notebook = self.left_notebook if side == 'left' else self.right_notebook
            notebook.SetBackgroundColour(theme['notebook_bg'])
            notebook.SetForegroundColour(theme['notebook_fg'])
            
            # 设置每个标签页的颜色
            for tab in self.tabs[side]:
                # 设置面板颜色
                tab['panel'].SetBackgroundColour(theme['bg'])
                tab['panel'].SetForegroundColour(theme['fg'])
                
                # 设置工具栏颜色
                toolbar = tab['panel'].GetChildren()[0]
                if isinstance(toolbar, wx.ToolBar):
                    toolbar.SetBackgroundColour(theme['toolbar_bg'])
                
                # 设置路径输入框颜色
                path_ctrl = tab['path_ctrl']
                path_ctrl.SetBackgroundColour(theme['textctrl_bg'])
                path_ctrl.SetForegroundColour(theme['textctrl_fg'])
                
                # 设置列表控件颜色
                list_ctrl = tab['list']
                list_ctrl.SetBackgroundColour(theme['list_bg'])
                list_ctrl.SetForegroundColour(theme['list_fg'])
                
                # 刷新控件
                tab['panel'].Refresh()
                path_ctrl.Refresh()
                list_ctrl.Refresh()
        
        # 刷新界面
        self.Refresh()
        self.Update()

    def init_ui(self):
        """初始化用户界面 - 已弃用，功能已移至add_tab方法"""
        pass

    def on_search(self, event):
        current_tab = self.get_current_tab()
        if not current_tab:
            return
        
        keyword = self.search_ctrl.GetValue().lower()
        list_ctrl = current_tab['list']
        
        for i in range(list_ctrl.GetItemCount()):
            name = list_ctrl.GetItemText(i, 1).lower()
            list_ctrl.SetItemState(i, wx.LIST_STATE_SELECTED if keyword in name else 0, wx.LIST_STATE_SELECTED)

    def new_folder(self, event):
        """创建新文件夹"""
        current_tab = self.get_current_tab()
        if not current_tab:
            return
            
        dlg = wx.TextEntryDialog(self, "请输入文件夹名称:", "新建文件夹")
        if dlg.ShowModal() == wx.ID_OK:
            name = dlg.GetValue()
            if not name:
                return
                
            path = os.path.join(current_tab['path'], name)
            try:
                os.makedirs(path, exist_ok=True)
                self.refresh_file_list(current_tab)
            except Exception as e:
                wx.MessageBox(f"创建文件夹失败: {str(e)}", "错误", wx.OK | wx.ICON_ERROR)
        dlg.Destroy()

    def load_system_icons(self):
        """加载系统图标"""
        try:
            # 获取系统图标
            self.folder_icon = self.get_file_icon(os.path.expanduser("~"), True)
            self.file_icon = self.get_file_icon("dummy.txt", False)
        except Exception as e:
            print(f"系统图标加载失败: {str(e)}")
            # 使用默认图标
            self.folder_icon = wx.ArtProvider.GetBitmap(wx.ART_FOLDER, wx.ART_OTHER, (16, 16))
            self.file_icon = wx.ArtProvider.GetBitmap(wx.ART_NORMAL_FILE, wx.ART_OTHER, (16, 16))

    def get_file_icon(self, path, is_folder=False):
        """获取文件或文件夹的系统图标"""
        try:
            # 从注册表获取图标
            if is_folder:
                key_path = "folder\\DefaultIcon"
            else:
                ext = os.path.splitext(path)[1].lower()
                key_path = f"{ext}\\DefaultIcon" if ext else "*\\DefaultIcon"
                
            try:
                key = win32api.RegOpenKey(win32con.HKEY_CLASSES_ROOT, key_path, 0, win32con.KEY_READ)
                icon_path, _ = win32api.RegQueryValueEx(key, "")
                win32api.RegCloseKey(key)
            except:
                # 如果没有DefaultIcon，尝试获取关联程序
                if not is_folder:
                    try:
                        ext = os.path.splitext(path)[1].lower()
                        key = win32api.RegOpenKey(win32con.HKEY_CLASSES_ROOT, ext, 0, win32con.KEY_READ)
                        file_type, _ = win32api.RegQueryValueEx(key, "")
                        win32api.RegCloseKey(key)
                        
                        key = win32api.RegOpenKey(win32con.HKEY_CLASSES_ROOT, f"{file_type}\\DefaultIcon", 0, win32con.KEY_READ)
                        icon_path, _ = win32api.RegQueryValueEx(key, "")
                        win32api.RegCloseKey(key)
                    except:
                        raise Exception("No icon found in registry")
                else:
                    raise Exception("No folder icon found in registry")
            
            # 解析图标路径
            if "," in icon_path:
                icon_path, icon_index = icon_path.rsplit(",", 1)
                icon_index = int(icon_index)
            else:
                icon_index = 0
            
            # 移除引号
            icon_path = icon_path.strip('"')
            
            # 展开环境变量
            icon_path = os.path.expandvars(icon_path)
            
            try:
                # 加载图标
                large, small = win32gui.ExtractIconEx(icon_path, icon_index)
                if small and len(small) > 0:
                    # 转换为wx.Bitmap
                    icon = wx.Icon()
                    icon.SetHandle(small[0])
                    bitmap = wx.Bitmap(icon)
                    
                    # 释放图标句柄
                    for handle in small:
                        if handle:
                            win32gui.DestroyIcon(handle)
                    for handle in large:
                        if handle:
                            win32gui.DestroyIcon(handle)
                            
                    return bitmap
            except Exception as e:
                print(f"加载图标失败: {str(e)}")
                
        except Exception as e:
            print(f"获取图标失败: {str(e)}")
        
        # 如果获取失败，返回默认图标
        return wx.ArtProvider.GetBitmap(
            wx.ART_FOLDER if is_folder else wx.ART_NORMAL_FILE,
            wx.ART_OTHER,
            (16, 16)
        )

    def get_file_type_icon(self, file_path):
        """获取文件类型的系统图标"""
        try:
            # 如果是目录，返回文件夹图标
            if os.path.isdir(file_path):
                return self.folder_icon
            
            # 从缓存获取图标
            ext = os.path.splitext(file_path)[1].lower()
            cache_key = ext if ext else os.path.basename(file_path).lower()
            
            if cache_key in self._icon_cache:
                return self._icon_cache[cache_key]
            
            # 从注册表获取图标
            try:
                # 获取文件类型关联的程序路径
                key_path = f"{ext}\\DefaultIcon" if ext else "*\\DefaultIcon"
                try:
                    key = win32api.RegOpenKey(win32con.HKEY_CLASSES_ROOT, key_path, 0, win32con.KEY_READ)
                    icon_path, _ = win32api.RegQueryValueEx(key, "")
                    win32api.RegCloseKey(key)
                except:
                    # 如果没有DefaultIcon，尝试获取关联程序
                    try:
                        key = win32api.RegOpenKey(win32con.HKEY_CLASSES_ROOT, ext, 0, win32con.KEY_READ)
                        file_type, _ = win32api.RegQueryValueEx(key, "")
                        win32api.RegCloseKey(key)
                        
                        key = win32api.RegOpenKey(win32con.HKEY_CLASSES_ROOT, f"{file_type}\\DefaultIcon", 0, win32con.KEY_READ)
                        icon_path, _ = win32api.RegQueryValueEx(key, "")
                        win32api.RegCloseKey(key)
                    except:
                        raise Exception("No icon found in registry")
                
                # 解析图标路径
                if "," in icon_path:
                    icon_path, icon_index = icon_path.rsplit(",", 1)
                    icon_index = int(icon_index)
                else:
                    icon_index = 0
                
                # 移除引号
                icon_path = icon_path.strip('"')
                
                # 展开环境变量
                icon_path = os.path.expandvars(icon_path)
                
                # 加载图标
                large, small = win32gui.ExtractIconEx(icon_path, icon_index)
                if small:
                    # 转换为wx.Bitmap
                    icon = wx.Icon()
                    icon.SetHandle(small[0])
                    bitmap = wx.Bitmap(icon)
                    
                    # 释放图标句柄
                    for handle in small:
                        win32gui.DestroyIcon(handle)
                    for handle in large:
                        win32gui.DestroyIcon(handle)
                        
                    # 缓存并返回图标
                    self._icon_cache[cache_key] = bitmap
                    return bitmap
                    
            except Exception as e:
                print(f"从注册表获取图标失败: {str(e)}")
            
            # 如果无法从注册表获取，使用默认图标
            default_icons = {
                '.txt': wx.ArtProvider.GetBitmap(wx.ART_NORMAL_FILE, size=(16, 16)),
                '.doc': wx.ArtProvider.GetBitmap(wx.ART_NORMAL_FILE, size=(16, 16)),
                '.docx': wx.ArtProvider.GetBitmap(wx.ART_NORMAL_FILE, size=(16, 16)),
                '.xls': wx.ArtProvider.GetBitmap(wx.ART_NORMAL_FILE, size=(16, 16)),
                '.xlsx': wx.ArtProvider.GetBitmap(wx.ART_NORMAL_FILE, size=(16, 16)),
                '.pdf': wx.ArtProvider.GetBitmap(wx.ART_NORMAL_FILE, size=(16, 16)),
                '.jpg': wx.ArtProvider.GetBitmap(wx.ART_NORMAL_FILE, size=(16, 16)),
                '.jpeg': wx.ArtProvider.GetBitmap(wx.ART_NORMAL_FILE, size=(16, 16)),
                '.png': wx.ArtProvider.GetBitmap(wx.ART_NORMAL_FILE, size=(16, 16)),
                '.gif': wx.ArtProvider.GetBitmap(wx.ART_NORMAL_FILE, size=(16, 16)),
                '.exe': wx.ArtProvider.GetBitmap(wx.ART_EXECUTABLE_FILE, size=(16, 16)),
                '.dll': wx.ArtProvider.GetBitmap(wx.ART_NORMAL_FILE, size=(16, 16)),
            }
            default_icon = default_icons.get(ext, self.file_icon)
            self._icon_cache[cache_key] = default_icon
            return default_icon
                
        except Exception as e:
            print(f"获取文件类型图标失败: {str(e)}")
            return self.file_icon

    def refresh_file_list(self, tab=None):
        """刷新指定标签页或当前标签页的文件列表"""
        if tab is None:
            tab = self.get_current_tab()
        if not tab:
            return
            
        list_ctrl = tab['list']
        icon_list = tab['icon_list']
        current_path = tab['path']
        path_ctrl = tab['path_ctrl']
        
        # 保存当前滚动位置和选中项
        top_item = list_ctrl.GetTopItem()
        selected_items = []
        item = -1
        while True:
            item = list_ctrl.GetNextItem(item, wx.LIST_NEXT_ALL, wx.LIST_STATE_SELECTED)
            if item == -1:
                break
            selected_items.append(list_ctrl.GetItem(item, 1).GetText())
        
        # 更新路径显示
        path_ctrl.SetValue(current_path)
        
        # 清空列表
        list_ctrl.DeleteAllItems()
        icon_list.RemoveAll()
        
        try:
            items = []
            # 添加上级目录项
            parent = os.path.dirname(current_path)
            if parent and parent != current_path:
                items.append(("..", True, 0, "", parent))
            
            # 获取目录内容
            for item in os.listdir(current_path):
                full_path = os.path.join(current_path, item)
                is_dir = os.path.isdir(full_path)
                try:
                    size = os.path.getsize(full_path) if not is_dir else 0
                    mtime = os.path.getmtime(full_path)
                    modified = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
                    items.append((item, is_dir, size, modified, full_path))
                except OSError:
                    continue
            
            # 排序：文件夹优先，然后按名称排序
            items.sort(key=lambda x: (not x[1], x[0].lower()))
            
            # 添加到列表
            for idx, (name, is_dir, size, modified, full_path) in enumerate(items):
                if name == "..":
                    icon = wx.ArtProvider.GetBitmap(wx.ART_GO_UP, wx.ART_OTHER, (16, 16))
                else:
                    icon = self.folder_icon if is_dir else self.get_file_type_icon(full_path)
                
                icon_idx = icon_list.Add(icon)
                list_ctrl.InsertItem(idx, "")
                list_ctrl.SetItemImage(idx, icon_idx)
                list_ctrl.SetItem(idx, 1, name)
                list_ctrl.SetItem(idx, 2, self.format_size(size) if not is_dir and name != ".." else "")
                list_ctrl.SetItem(idx, 3, modified if name != ".." else "")
                
                # 恢复选中状态
                if name in selected_items:
                    list_ctrl.SetItemState(idx, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
            
            # 恢复滚动位置
            if top_item >= 0 and top_item < list_ctrl.GetItemCount():
                list_ctrl.EnsureVisible(top_item)
            
            # 更新状态栏
            total_items = len(items) - (1 if items and items[0][0] == ".." else 0)
            folders = sum(1 for item in items if item[1] and item[0] != "..")
            files = total_items - folders
            self.status_bar.SetStatusText(f"文件夹: {folders}, 文件: {files}", 0)
            
        except Exception as e:
            wx.LogError(f"无法访问目录 {current_path}：{str(e)}")
            
        # 调整列宽
        self.adjust_list_columns(list_ctrl)
    
    def format_size(self, size):
        """将文件大小转换为人类可读的格式"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                if unit == 'B':
                    return f"{int(size)} {unit}"
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} PB"
    
    # 其余方法实现（new_folder, delete_items等）...
    
    def on_context_menu(self, event):
        """显示上下文菜单"""
        current_tab = self.get_current_tab()
        if not current_tab:
            return
            
        # 创建菜单
        menu = wx.Menu()
        menu.Append(wx.ID_NEW, "新建文件夹\tCtrl+N")
        menu.AppendSeparator()
        menu.Append(wx.ID_CUT, "剪切\tCtrl+X")
        menu.Append(wx.ID_COPY, "复制\tCtrl+C")
        menu.Append(wx.ID_PASTE, "粘贴\tCtrl+V")
        menu.AppendSeparator()
        menu.Append(wx.ID_DELETE, "删除\tDel")
        
        # 绑定事件
        menu.Bind(wx.EVT_MENU, self.new_folder, id=wx.ID_NEW)
        menu.Bind(wx.EVT_MENU, self.on_copy, id=wx.ID_COPY)
        menu.Bind(wx.EVT_MENU, self.on_paste, id=wx.ID_PASTE)
        menu.Bind(wx.EVT_MENU, self.delete_items, id=wx.ID_DELETE)
        
        # 显示菜单
        self.PopupMenu(menu)
        menu.Destroy()

    def on_size(self, event):
        """处理窗口大小变化事件"""
        if self.main_panel:
            size = self.GetClientSize()
            self.main_panel.SetSize(size)
            
            # 根据保存的比例设置分割位置
            window_width = self.splitter.GetSize().GetWidth()
            new_pos = int(window_width * self.splitter_ratio)
            
            # 确保不超出最小/最大限制
            min_pos = 200
            max_pos = window_width - 200
            new_pos = max(min_pos, min(new_pos, max_pos))
            
            self.splitter.SetSashPosition(new_pos)
            
            self.main_panel.Layout()
            # 调整当前标签页的列宽
            for side in ['left', 'right']:
                for tab in self.tabs[side]:
                    self.adjust_list_columns(tab['list'])
        event.Skip()

    def on_copy(self, event):
        selected = self.get_selected_paths()
        if selected:
            self.clipboard = {"type": "copy", "paths": selected}
            self.status_bar.SetStatusText(f"已复制 {len(selected)} 项", 0)

    def on_paste(self, event):
        """粘贴文件"""
        if not self.clipboard:
            return
            
        current_tab = self.get_current_tab()
        if not current_tab:
            return
            
        dest = current_tab['path']
        try:
            for src in self.clipboard["paths"]:
                if self.clipboard["type"] == "copy":
                    shutil.copy2(src, dest)
                else:  # 剪切操作
                    shutil.move(src, dest)
            self.refresh_file_list()
        except Exception as e:
            wx.LogError(f"操作失败：{str(e)}")

    def on_forward(self, event):
        """前进到下一个目录"""
        current_tab = self.get_current_tab()
        if not current_tab:
            return
            
        history = current_tab['history']
        if len(history) > 1:
            current_path = history[-1]
            next_path = history[0]  # 获取最早的路径
            if os.path.exists(next_path) and next_path != current_path:
                history.rotate(-1)  # 循环移动历史记录
                self.navigate_to(next_path)

    def on_item_activated(self, event):
        """处理项目双击事件"""
        try:
            current_tab = self.get_current_tab()
            if not current_tab:
                return
                
            list_ctrl = current_tab['list']
            
            # 获取选中项
            if isinstance(event, wx.ListEvent):
                index = event.GetIndex()
            else:
                index = list_ctrl.GetFirstSelected()
                
            if index == -1:
                return
                
            name = list_ctrl.GetItem(index, 1).GetText()
            path = os.path.join(current_tab['path'], name)
            
            if name == "..":
                # 导航到上级目录
                parent = os.path.dirname(current_tab['path'])
                if parent and parent != current_tab['path']:
                    self.navigate_to(parent)
            elif os.path.isdir(path):
                # 导航到子目录
                self.navigate_to(path)
            else:
                # 打开文件
                try:
                    os.startfile(path)
                except Exception as e:
                    # 尝试使用默认应用打开
                    try:
                        import subprocess
                        subprocess.run(['start', '', path], shell=True, check=True)
                    except Exception as sub_e:
                        wx.MessageBox(f"无法打开文件: {str(e)}\n{str(sub_e)}", "错误", wx.OK | wx.ICON_ERROR)
                        
        except Exception as e:
            wx.LogError(f"处理双击事件失败: {str(e)}")

    def preview_image(self, path):
        """图片预览窗口"""
        preview_win = wx.Frame(self, title="图片预览 - " + os.path.basename(path))
        img = wx.Image(path, wx.BITMAP_TYPE_ANY)
        img = img.Scale(800, 600, wx.IMAGE_QUALITY_HIGH)
        wx.StaticBitmap(preview_win, bitmap=wx.Bitmap(img)).SetFocus()
        preview_win.Show()

    def preview_text(self, path):
        """文本预览窗口"""
        preview_win = wx.Frame(self, title="文本预览 - " + os.path.basename(path))
        text_ctrl = wx.TextCtrl(preview_win, style=wx.TE_MULTILINE|wx.TE_READONLY)
        with open(path, 'r', encoding='utf-8') as f:
            text_ctrl.SetValue(f.read())
        preview_win.Show()

    def on_up(self, event):
        """导航到上级目录"""
        current_tab = self.get_current_tab()
        if not current_tab:
            return
            
        parent = os.path.dirname(current_tab['path'])
        if parent and parent != current_tab['path']:
            self.navigate_to(parent)

    def on_back(self, event):
        """导航到历史记录中的上一个目录"""
        current_tab = self.get_current_tab()
        if not current_tab or len(current_tab['history']) <= 1:
            return
            
        current_tab['history'].pop()  # 移除当前路径
        prev_path = current_tab['history'].pop()
        self.navigate_to(prev_path)

    def delete_items(self, event):
        """删除选中的项目"""
        paths = self.get_selected_paths()
        if not paths:
            return
            
        count = len(paths)
        msg = f"确定要删除选中的 {count} 个项目吗？\n这些项目将被移动到回收站。"
        dlg = wx.MessageDialog(self, msg, "确认删除",
                             wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)
                             
        if dlg.ShowModal() == wx.ID_YES:
            for path in paths:
                try:
                    send2trash.send2trash(path)
                except Exception as e:
                    wx.MessageBox(f"删除失败: {str(e)}", "错误", wx.OK | wx.ICON_ERROR)
                    break
            self.refresh_file_list()
        dlg.Destroy()

    def on_path_enter(self, event):
        """处理路径输入框回车事件"""
        try:
            current_tab = self.get_current_tab()
            if not current_tab:
                return
                
            path = current_tab['path_ctrl'].GetValue().strip()
            
            # 处理环境变量
            path = os.path.expandvars(path)
            # 处理用户目录
            path = os.path.expanduser(path)
            
            # 如果是相对路径，转换为绝对路径
            if not os.path.isabs(path):
                path = os.path.join(current_tab['path'], path)
            
            # 规范化路径
            path = os.path.normpath(path)
            
            if os.path.exists(path):
                self.navigate_to(path)
            else:
                wx.MessageBox("路径不存在", "错误", wx.OK | wx.ICON_ERROR)
                current_tab['path_ctrl'].SetValue(current_tab['path'])
                
        except Exception as e:
            wx.LogError(f"处理路径输入失败: {str(e)}")
            if current_tab:
                current_tab['path_ctrl'].SetValue(current_tab['path'])

    def adjust_list_columns(self, list_ctrl):
        """调整列表列宽以适应窗口大小"""
        if not list_ctrl:
            return
            
        try:
            width = list_ctrl.GetClientSize().width
            if width <= 0:
                return
                
            # 预留滚动条宽度
            scrollbar_width = wx.SystemSettings.GetMetric(wx.SYS_VSCROLL_X)
            width = max(0, width - scrollbar_width)
            
            # 设置列宽
            list_ctrl.SetColumnWidth(0, 30)  # 图标列
            name_width = int(width * 0.4)
            size_width = int(width * 0.2)
            date_width = width - name_width - size_width - 30 - scrollbar_width
            
            list_ctrl.SetColumnWidth(1, max(50, name_width))  # 名称列
            list_ctrl.SetColumnWidth(2, max(50, size_width))  # 大小列
            list_ctrl.SetColumnWidth(3, max(50, date_width))  # 日期列
            
        except Exception as e:
            wx.LogError(f"调整列宽失败：{str(e)}")

    def on_item_right_click(self, event):
        """处理文件项右键点击事件"""
        if wx.GetKeyState(wx.WXK_CONTROL):  # Ctrl+右键
            self.show_system_menu(event)
        else:
            self.show_custom_menu(event)

    def show_system_menu(self, event):
        """显示系统右键菜单"""
        try:
            paths = self.get_selected_paths()
            if not paths:
                return
                
            # 获取Shell接口
            pythoncom.CoInitialize()  # 初始化COM
            try:
                shell_app = win32com.client.Dispatch("Shell.Application")
                
                # 获取父文件夹和选中项
                parent_folder = shell_app.NameSpace(os.path.dirname(paths[0]))
                if not parent_folder:
                    return
                    
                # 获取选中项
                items = []
                for path in paths:
                    item = parent_folder.ParseName(os.path.basename(path))
                    if item:
                        items.append(item)
                
                if not items:
                    return
                    
                # 获取上下文菜单
                verbs = items[0].Verbs()
                if not verbs:
                    return
                    
                # 创建菜单
                menu = wx.Menu()
                verb_map = {}  # 用于存储菜单项ID和动作的映射
                
                # 添加常用菜单项
                for i in range(verbs.Count):
                    verb = verbs.Item(i)
                    if verb:
                        name = verb.Name
                        if name:
                            # 过滤掉不需要的菜单项
                            if "pin" in name.lower() or "快速访问" in name:
                                continue
                            id = wx.NewId()
                            menu.Append(id, name)
                            verb_map[id] = verb
                
                # 显示菜单
                if menu.GetMenuItemCount() > 0:
                    def on_menu(evt):
                        try:
                            verb = verb_map.get(evt.GetId())
                            if verb:
                                verb.DoIt()
                        except Exception as e:
                            print(f"执行菜单命令失败: {str(e)}")
                    
                    for id in verb_map:
                        menu.Bind(wx.EVT_MENU, on_menu, id=id)
                    
                    if event.GetEventObject():
                        event.GetEventObject().PopupMenu(menu)
                menu.Destroy()
                
            finally:
                pythoncom.CoUninitialize()  # 清理COM
                
        except Exception as e:
            print(f"显示系统菜单失败: {str(e)}")
            self.show_custom_menu(event)

    def show_custom_menu(self, event):
        """显示自定义右键菜单"""
        menu = wx.Menu()
        
        # 获取选中的路径
        paths = self.get_selected_paths()
        current_tab = self.get_current_tab()
        
        # 添加菜单项
        open_item = menu.Append(wx.ID_OPEN, "打开(&O)\tEnter")
        menu.AppendSeparator()
        
        cut_item = menu.Append(wx.ID_CUT, "剪切(&T)\tCtrl+X")
        copy_item = menu.Append(wx.ID_COPY, "复制(&C)\tCtrl+C")
        paste_item = menu.Append(wx.ID_PASTE, "粘贴(&P)\tCtrl+V")
        menu.AppendSeparator()
        
        rename_item = menu.Append(wx.ID_ANY, "重命名(&M)\tF2")
        delete_item = menu.Append(wx.ID_DELETE, "删除(&D)\tDelete")
        menu.AppendSeparator()
        
        refresh_item = menu.Append(wx.ID_REFRESH, "刷新(&R)\tF5")
        properties_item = menu.Append(wx.ID_PROPERTIES, "属性(&A)\tAlt+Enter")
        
        # 设置菜单项状态
        paste_item.Enable(bool(self.clipboard["paths"]))
        for item in [cut_item, copy_item, rename_item, delete_item, properties_item]:
            item.Enable(bool(paths))
        
        # 绑定事件处理器
        menu.Bind(wx.EVT_MENU, self.on_item_activated, open_item)
        menu.Bind(wx.EVT_MENU, self.on_cut, cut_item)
        menu.Bind(wx.EVT_MENU, self.on_copy, copy_item)
        menu.Bind(wx.EVT_MENU, self.on_paste, paste_item)
        menu.Bind(wx.EVT_MENU, self.on_rename, rename_item)
        menu.Bind(wx.EVT_MENU, self.delete_items, delete_item)
        menu.Bind(wx.EVT_MENU, lambda evt: self.refresh_file_list(), refresh_item)
        menu.Bind(wx.EVT_MENU, self.show_properties, properties_item)
        
        # 显示菜单
        if event.GetEventObject():
            event.GetEventObject().PopupMenu(menu)
        menu.Destroy()

    def on_rename(self, event):
        """重命名文件或文件夹"""
        paths = self.get_selected_paths()
        if not paths:
            return
            
        path = paths[0]  # 只重命名第一个选中项
        old_name = os.path.basename(path)
        
        dlg = wx.TextEntryDialog(self, "请输入新名称:", "重命名", old_name)
        if dlg.ShowModal() == wx.ID_OK:
            new_name = dlg.GetValue()
            if new_name and new_name != old_name:
                try:
                    new_path = os.path.join(os.path.dirname(path), new_name)
                    os.rename(path, new_path)
                    self.refresh_file_list()
                except Exception as e:
                    wx.MessageBox(f"重命名失败: {str(e)}", "错误", wx.OK | wx.ICON_ERROR)
        dlg.Destroy()

    def show_properties(self, event):
        """显示文件属性"""
        paths = self.get_selected_paths()
        if not paths:
            return
            
        try:
            shell.ShellExecuteEx(
                fMask=shellcon.SEE_MASK_NOCLOSEPROCESS | shellcon.SEE_MASK_INVOKEIDLIST,
                lpVerb="properties",
                lpFile=paths[0],
                nShow=win32con.SW_SHOW
            )
        except Exception as e:
            wx.MessageBox(f"无法显示属性: {str(e)}", "错误", wx.OK | wx.ICON_ERROR)

    def on_item_selected(self, event):
        """处理文件项选中事件"""
        paths = self.get_selected_paths()
        if not paths:
            self.status_bar.SetStatusText("")
            return
            
        try:
            total_size = 0
            for path in paths:
                if os.path.isfile(path):
                    total_size += os.path.getsize(path)
            
            if len(paths) == 1:
                path = paths[0]
                if os.path.isfile(path):
                    self.status_bar.SetStatusText(f"文件大小: {self.format_size(total_size)}")
                else:
                    items = os.listdir(path)
                    files = sum(1 for item in items if os.path.isfile(os.path.join(path, item)))
                    folders = sum(1 for item in items if os.path.isdir(os.path.join(path, item)))
                    self.status_bar.SetStatusText(f"包含: {folders} 个文件夹, {files} 个文件")
            else:
                self.status_bar.SetStatusText(f"选中: {len(paths)} 项, 总大小: {self.format_size(total_size)}")
                
        except Exception as e:
            self.status_bar.SetStatusText(f"错误: {str(e)}")

    def on_notebook_dclick(self, event, side):
        """处理标签栏空白处双击事件"""
        notebook = self.left_notebook if side == "left" else self.right_notebook
        pos = event.GetPosition()
        
        # 获取点击的标签页索引
        tab_hit = notebook.HitTest(pos)
        if tab_hit[0] != wx.NOT_FOUND:
            # 如果点击的是"+"标签页
            if notebook.GetPageText(tab_hit[0]) == "+":
                # 获取当前活动标签页的路径
                current_tab = self.get_current_tab(side)
                path = current_tab['path'] if current_tab else os.path.expanduser("~")
                self.add_tab(path, side)
            elif tab_hit[0] < len(self.tabs[side]):  # 不是"+"标签页
                self.close_tab(tab_hit[0], side)
        else:
            # 点击在标签区域外，创建新标签
            current_tab = self.get_current_tab(side)
            path = current_tab['path'] if current_tab else os.path.expanduser("~")
            self.add_tab(path, side)
        
        event.Skip()

    def on_tab_dclick(self, event, side):
        """处理标签页双击事件"""
        notebook = self.left_notebook if side == "left" else self.right_notebook
        pos = event.GetPosition()
        
        # 获取点击的标签页索引
        tab_hit = notebook.HitTest(pos)
        if tab_hit[0] != wx.NOT_FOUND:
            if tab_hit[0] == notebook.GetPageCount() - 1:
                # 点击"+"标签，创建新标签
                self.add_tab(os.path.expanduser("~"), side)
            else:
                # 关闭标签页
                self.close_tab(tab_hit[0], side)
        
        event.Skip()

    def close_tab(self, index, side):
        """关闭指定标签页"""
        notebook = self.left_notebook if side == "left" else self.right_notebook
        
        # 不允许关闭最后一个标签页
        if len(self.tabs[side]) <= 1:
            return
            
        # 不允许关闭"+"标签页
        if notebook.GetPageText(index) == "+":
            return
            
        # 保存标签页数据用于恢复
        tab_data = self.tabs[side][index].copy()
        self.closed_tabs[side].append(tab_data)
        
        # 如果没有其他标签页，选中"+"标签页
        if notebook.GetPageCount() == 1:
            notebook.SetSelection(0)
        
        # 删除标签页
        notebook.DeletePage(index)
        del self.tabs[side][index]
        
        # 更新监控
        current_tab = self.get_current_tab(side)
        if current_tab:
            self.start_watching(current_tab['path'])

    def on_cut(self, event):
        """剪切文件"""
        selected = self.get_selected_paths()
        if selected:
            self.clipboard = {"type": "cut", "paths": selected}
            self.status_bar.SetStatusText(f"已剪切 {len(selected)} 项", 0)

    def on_splitter_changed(self, event):
        """分割条位置改变后的处理"""
        # 更新分割比例
        window_width = self.splitter.GetSize().GetWidth()
        if window_width > 0:
            self.splitter_ratio = self.splitter.GetSashPosition() / window_width
        
        # 调整列表控件列宽
        for side in ['left', 'right']:
            for tab in self.tabs[side]:
                self.adjust_list_columns(tab['list'])
        event.Skip()

    def on_splitter_changing(self, event):
        """分割条正在移动时的处理"""
        # 获取窗口大小
        width = self.splitter.GetSize().GetWidth()
        # 限制最小和最大位置
        min_pos = 200
        max_pos = width - 200
        if event.GetSashPosition() < min_pos:
            event.SetSashPosition(min_pos)
        elif event.GetSashPosition() > max_pos:
            event.SetSashPosition(max_pos)
        event.Skip()

    def restore_closed_tab(self, event):
        """恢复最近关闭的标签页"""
        # 获取当前焦点所在的一侧
        focused = wx.Window.FindFocus()
        side = "left"
        if focused:
            parent = focused.GetParent()
            while parent and parent != self.left_notebook and parent != self.right_notebook:
                parent = parent.GetParent()
            if parent == self.right_notebook:
                side = "right"
        
        # 检查是否有已关闭的标签页
        if self.closed_tabs[side]:
            tab_data = self.closed_tabs[side].pop()
            self.add_tab(tab_data['path'], side)

    def clear_icon_cache(self):
        """清理图标缓存"""
        self._icon_cache.clear()

if __name__ == "__main__":
    app = wx.App()
    frame = FileExplorerFrame()
    frame.Show()
    app.MainLoop()