# -*- coding: utf-8 -*-
import wx
import wx.adv
import os
import send2trash
import win32api
import win32con
import win32gui
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
        self.watch_dog = None
        
        # 设置窗口样式
        self.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW))
        
        # 创建主面板
        self.main_panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        self.main_panel.SetSizer(main_sizer)
        
        # 创建带标签页的面板
        self.notebook = wx.Notebook(self.main_panel)
        self.tabs = []  # 存储各标签页状态
        
        # 加载系统图标
        self.load_system_icons()
        
        # 创建状态栏
        self.status_bar = self.CreateStatusBar(2)
        self.status_bar.SetStatusWidths([-3, -1])
        
        # 初始化菜单
        self.init_menu()
        
        # 添加新建标签按钮
        button_panel = wx.Panel(self.main_panel)
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.add_tab_button = wx.Button(button_panel, label="+", size=(20, 20))
        button_sizer.Add(self.add_tab_button, 0, wx.ALIGN_CENTER_VERTICAL|wx.RIGHT, 5)
        button_panel.SetSizer(button_sizer)
        
        # 主布局
        main_sizer.Add(button_panel, 0, wx.EXPAND|wx.ALL, 2)
        main_sizer.Add(self.notebook, 1, wx.EXPAND|wx.ALL, 5)
        
        # 绑定事件
        self.add_tab_button.Bind(wx.EVT_BUTTON, self.on_add_tab)
        self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.on_tab_switch)
        self.Bind(wx.EVT_SIZE, self.on_size)
        self.Bind(wx.EVT_CLOSE, self.OnClose)
        
        # 初始化第一个标签
        self.add_tab(self.current_path)
        
        # 调整大小和显示
        self.main_panel.Layout()
        self.Centre()
        self.Show()
        
        # 开始监控文件系统变化
        self.start_watching(self.current_path)

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

    def on_tab_switch(self, event):
        """切换标签页时更新监控路径"""
        current = self.get_current_tab()
        if current:
            self.start_watching(current['path'])
        event.Skip()

    def navigate_to(self, path):
        """导航到指定路径"""
        if not os.path.exists(path):
            wx.MessageBox(f"路径不存在: {path}", "错误", wx.OK | wx.ICON_ERROR)
            return
            
        current_tab = self.get_current_tab()
        if not current_tab:
            return
            
        current_tab['path'] = path
        current_tab['history'].append(path)
        self.notebook.SetPageText(self.notebook.GetSelection(), os.path.basename(path) or path)
        
        # 刷新文件列表
        self.refresh_file_list(current_tab)
        
        # 更新监控
        self.start_watching(path)

    def OnClose(self, event):
        """窗口关闭时停止监控线程"""
        if self.observer and self.observer.is_alive():
            self.observer.stop()
            self.observer.join()
        self.Destroy()

    def add_tab(self, initial_path):
        """创建新标签页"""
        # 创建标签页面板
        panel = wx.Panel(self.notebook)
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # 创建工具栏
        toolbar = wx.ToolBar(panel)
        toolbar.AddTool(wx.ID_BACKWARD, "后退", wx.ArtProvider.GetBitmap(wx.ART_GO_BACK, size=(16, 16)))
        toolbar.AddTool(wx.ID_FORWARD, "前进", wx.ArtProvider.GetBitmap(wx.ART_GO_FORWARD, size=(16, 16)))
        toolbar.AddTool(wx.ID_UP, "上级", wx.ArtProvider.GetBitmap(wx.ART_GO_UP, size=(16, 16)))
        toolbar.AddSeparator()
        toolbar.AddTool(wx.ID_NEW, "新建文件夹", wx.ArtProvider.GetBitmap(wx.ART_NEW_DIR, size=(16, 16)))
        toolbar.AddTool(wx.ID_REFRESH, "刷新", wx.ArtProvider.GetBitmap(wx.ART_REDO, size=(16, 16)))
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
        self.tabs.append(tab_data)
        
        # 添加标签页
        self.notebook.AddPage(panel, os.path.basename(initial_path) or initial_path, True)
        
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
        current = self.notebook.GetSelection()
        if current != -1 and len(self.tabs) > 1:  # 保留至少一个标签页
            self.notebook.DeletePage(current)
            del self.tabs[current]
            # 更新当前标签页的监控
            current_tab = self.get_current_tab()
            if current_tab:
                self.start_watching(current_tab['path'])

    def get_current_tab(self):
        """获取当前活动标签页数据"""
        current = self.notebook.GetSelection()
        if current != -1 and current < len(self.tabs):
            return self.tabs[current]
        return None

    def init_menu(self):
        """初始化菜单栏"""
        menubar = wx.MenuBar()
        
        # 文件菜单
        file_menu = wx.Menu()
        file_menu.Append(wx.ID_NEW, "新建文件夹\tCtrl+N")
        file_menu.AppendSeparator()
        file_menu.Append(wx.ID_CLOSE, "关闭标签页\tCtrl+W")
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
        menubar.Append(view_menu, "视图(&V)")
        
        self.SetMenuBar(menubar)
        
        # 绑定菜单事件
        self.Bind(wx.EVT_MENU, self.new_folder, id=wx.ID_NEW)
        self.Bind(wx.EVT_MENU, self.on_close_tab, id=wx.ID_CLOSE)
        self.Bind(wx.EVT_MENU, lambda evt: self.Close(), id=wx.ID_EXIT)
        self.Bind(wx.EVT_MENU, self.on_copy, id=wx.ID_COPY)
        self.Bind(wx.EVT_MENU, self.on_paste, id=wx.ID_PASTE)
        self.Bind(wx.EVT_MENU, self.delete_items, id=wx.ID_DELETE)
        self.Bind(wx.EVT_MENU, lambda evt: self.refresh_file_list(), id=wx.ID_REFRESH)

    def refresh_all_tabs(self):
        """刷新所有标签页"""
        for tab in self.tabs:
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
        for tab in self.tabs:
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
            'light': (wx.SYS_COLOUR_WINDOW, wx.SYS_COLOUR_WINDOWTEXT),
            'dark': (wx.Colour(53,53,53), wx.Colour(240,240,240)),
            'system': (wx.SYS_COLOUR_WINDOW, wx.SYS_COLOUR_WINDOWTEXT)
        }
        bg, fg = themes[theme_name]
        self.SetBackgroundColour(wx.SystemSettings.GetColour(bg))
        self.SetForegroundColour(wx.SystemSettings.GetColour(fg))
        self.Refresh()

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
            self.folder_icon = wx.ArtProvider.GetBitmap(wx.ART_FOLDER, wx.ART_OTHER, (16, 16))
            self.file_icon = wx.ArtProvider.GetBitmap(wx.ART_NORMAL_FILE, wx.ART_OTHER, (16, 16))
        except Exception as e:
            print(f"系统图标加载失败: {str(e)}")
            # 使用默认图标
            self.folder_icon = wx.ArtProvider.GetBitmap(wx.ART_FOLDER, wx.ART_OTHER, (16, 16))
            self.file_icon = wx.ArtProvider.GetBitmap(wx.ART_NORMAL_FILE, wx.ART_OTHER, (16, 16))

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
        
        # 更新路径显示
        path_ctrl.SetValue(current_path)
        
        # 清空列表
        list_ctrl.DeleteAllItems()
        icon_list.RemoveAll()
        
        try:
            items = []
            for item in os.listdir(current_path):
                full_path = os.path.join(current_path, item)
                is_dir = os.path.isdir(full_path)
                try:
                    size = os.path.getsize(full_path) if not is_dir else 0
                    mtime = os.path.getmtime(full_path)
                    modified = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
                    items.append((item, is_dir, size, modified))
                except OSError:
                    continue
            
            items.sort(key=lambda x: (not x[1], x[0].lower()))  # 文件夹优先，然后按名称排序
            
            for idx, (name, is_dir, size, modified) in enumerate(items):
                icon = self.folder_icon if is_dir else self.file_icon
                icon_idx = icon_list.Add(icon)
                list_ctrl.InsertItem(idx, "")
                list_ctrl.SetItemImage(idx, icon_idx)
                list_ctrl.SetItem(idx, 1, name)
                list_ctrl.SetItem(idx, 2, self.format_size(size) if not is_dir else "")
                list_ctrl.SetItem(idx, 3, modified)
                
            # 更新状态栏
            total_items = len(items)
            folders = sum(1 for item in items if item[1])
            files = total_items - folders
            self.status_bar.SetStatusText(f"文件夹: {folders}, 文件: {files}", 1)
            
        except Exception as e:
            wx.LogError(f"无法访问目录 {current_path}：{str(e)}")
    
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
            self.main_panel.SetSize(self.GetClientSize())
            self.main_panel.Layout()
            # 调整当前标签页的列宽
            current_tab = self.get_current_tab()
            if current_tab:
                self.adjust_list_columns(current_tab['list'])
        event.Skip()

    def on_copy(self, event):
        selected = self.get_selected_paths()
        if selected:
            self.clipboard = {"type": "copy", "paths": selected}
            self.status_bar.SetStatusText(f"已复制 {len(selected)} 项", 1)

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
        current_tab = self.get_current_tab()
        if not current_tab:
            return
            
        list_ctrl = current_tab['list']
        index = event.GetIndex()
        name = list_ctrl.GetItem(index, 1).GetText()
        path = os.path.join(current_tab['path'], name)
        
        if os.path.isdir(path):
            self.navigate_to(path)
        else:
            try:
                os.startfile(path)
            except Exception as e:
                wx.MessageBox(f"无法打开文件: {str(e)}", "错误", wx.OK | wx.ICON_ERROR)

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
        current_tab = self.get_current_tab()
        if not current_tab:
            return
            
        path = current_tab['path_ctrl'].GetValue()
        if os.path.exists(path):
            self.navigate_to(path)
        else:
            wx.MessageBox("路径不存在", "错误", wx.OK | wx.ICON_ERROR)
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
            list_ctrl.SetColumnWidth(1, int(width * 0.4))  # 名称列
            list_ctrl.SetColumnWidth(2, int(width * 0.2))  # 大小列
            list_ctrl.SetColumnWidth(3, int(width * 0.4) - scrollbar_width)  # 日期列
        except Exception as e:
            wx.LogError(f"调整列宽失败：{str(e)}")

if __name__ == "__main__":
    app = wx.App()
    frame = FileExplorerFrame()
    frame.Show()
    app.MainLoop()