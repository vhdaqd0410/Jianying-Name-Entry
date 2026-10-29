# -*- mode: python ; coding: utf-8 -*-
# 海外人名条批量生成 · v2.0.0 · onefile 单文件打包配置
#
# 打包时必须处理的一个坑(不处理会表现为「能启动剪映, 但检测一直未连接 / 批量替换失效」):
#   uiautomation 的 COM 调用链依赖 comtypes 的子模块(尤其 comtypes.stream),
#   PyInstaller 不会自动全收。漏收时每次 UIA 调用都抛
#   ModuleNotFoundError: No module named 'comtypes.stream',
#   于是永远找不到剪映窗口 —— 而「启动剪映」只用 subprocess, 所以看起来是好的。
#
# 另外 uiautomation 自带两个原生 DLL(UIAutomationClient_VC140_X64/X86.dll),
# 运行时按 os.path.dirname(__file__)/bin 查找, 需随包放到 uiautomation/bin/。
#
# 注意: 不要用「全量枚举 comtypes 子模块」的写法 —— 会连带引入 win32com,
#       而 PyInstaller 的 pyi_rth_win32comgenpy 钩子会因缺 pythoncom 而启动即崩。
import os
import sys


def _find_uiautomation():
    """定位 uiautomation 包目录(源码/虚拟环境/系统用户目录/沙箱影子目录都试)"""
    cands = []
    try:
        import uiautomation as _u
        cands.append(os.path.dirname(os.path.abspath(_u.__file__)))
    except Exception:
        pass
    for base in (os.environ.get('APPDATA'), os.environ.get('LOCALAPPDATA')):
        if base:
            cands.append(os.path.join(base, 'Python', 'Python310', 'site-packages', 'uiautomation'))
            cands.append(os.path.join(base, 'Python', 'Python310', 'lib', 'site-packages', 'uiautomation'))
    # 沙箱影子目录(打包在沙箱里跑时依赖装在这里)
    for shadow in (r'C:\Users\Admin\.hanako\.ephemeral\win32-sandbox-env\AppData\Roaming\Python\Python310\site-packages',):
        cands.append(os.path.join(shadow, 'uiautomation'))
    cands.append(os.path.join(sys.prefix, 'Lib', 'site-packages', 'uiautomation'))
    for c in cands:
        if c and os.path.isdir(os.path.join(c, 'bin')):
            return c
    return None


_uia = _find_uiautomation()
_uia_binaries = []
if _uia:
    for fn in os.listdir(os.path.join(_uia, 'bin')):
        src = os.path.join(_uia, 'bin', fn)
        if os.path.isfile(src) and fn.lower().endswith('.dll'):
            # 目标保持 uiautomation/bin/xxx.dll —— uiautomation 按包内相对路径找
            _uia_binaries.append((src, os.path.join('uiautomation', 'bin')))
    print('[spec] uiautomation:', _uia)
    print('[spec] DLL:', [os.path.basename(b[0]) for b in _uia_binaries])
else:
    print('[spec] !! 未找到 uiautomation/bin, 打出的 exe 将无法连接剪映')

# uiautomation 实际会用到的 comtypes 子模块(关键是 stream)
_comtypes_mods = [
    'comtypes',
    'comtypes.stream',
    'comtypes.client',
    'comtypes.automation',
    'comtypes.typeinfo',
    'comtypes.gen',
    'comtypes._post_coinit',
]
print('[spec] comtypes 子模块:', _comtypes_mods)

name = '海外人名条批量生成'

a = Analysis(
    ['gui_batch.pyw'],
    pathex=['.'],
    binaries=_uia_binaries,
    datas=[('icon.ico', '.')],
    hiddenimports=_comtypes_mods + [
        'uiautomation', 'uiautomation.uiautomation', 'uiautomation.version',
        'src.pyJianYingDraft.jianying_controller', 'src.pyJianYingDraft.exceptions',
    ],
    hookspath=[],
    runtime_hooks=[],
    # 排除 win32com/pywin32: 一旦被带进来, PyInstaller 的 win32com 钩子会因缺 pythoncom 崩
    excludes=['numpy', 'pandas', 'matplotlib', 'PIL',
              'win32com', 'pythoncom', 'pywintypes'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon='icon.ico',
    version='version_info.txt',
    disable_windowed_traceback=False,
)
