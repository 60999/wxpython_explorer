# wx_explorer
 基于wxpython的文件浏览器，为测试AI生成项目

# 多标签文件浏览器 v0.1

一个基于 wxPython 的多标签文件浏览器，提供类似 Windows 资源管理器的功能。

## 功能特点

- 多标签页浏览：支持同时打开多个目录标签页
- 文件操作：
  - 复制/剪切/粘贴文件
  - 新建文件夹
  - 删除文件(移至回收站)
- 导航功能：
  - 前进/后退/向上导航
  - 地址栏直接输入路径
  - 双击打开文件/文件夹
- 实时监控：自动检测并显示当前目录的文件变化
- 文件信息显示：
  - 文件名
  - 文件大小
  - 修改时间
- 界面功能：
  - 可调整列宽
  - 状态栏显示文件统计信息
  - 右键菜单支持

## 操作说明

1. 基本操作
   - 新建标签页：点击标签栏上的 "+" 按钮
   - 关闭标签页：Ctrl+W 或菜单栏 "文件->关闭标签页"
   - 切换标签页：点击对应标签

2. 文件操作
   - 新建文件夹：Ctrl+N 或工具栏按钮
   - 复制：Ctrl+C
   - 粘贴：Ctrl+V
   - 删除：Delete 键(删除到回收站)

3. 导航操作
   - 后退：工具栏后退按钮
   - 前进：工具栏前进按钮
   - 上级目录：工具栏向上按钮
   - 直接导航：在地址栏输入路径并回车
   - 打开文件/文件夹：双击项目

## 运行环境要求

- Windows 11 x64 操作系统
- Python 3.8+
- wxPython 4.1+

## 安装步骤

1. 创建并激活 conda 环境:


```bash
conda create -n wx_explorer python=3.10 -y
conda activate wx_explorer
```

2. 安装依赖:

```bash
pip install -r requirements.txt
```

或使用 conda:  

```bash
conda env create -f environment.yml
```

3. 运行程序:

```bash
python wx_explorer.py
```


## 依赖说明

主要依赖库:
- wxPython: GUI 框架
- pywin32: Windows API 调用
- send2trash: 回收站支持
- watchdog: 文件系统监控
