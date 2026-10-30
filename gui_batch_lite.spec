# -*- mode: python ; coding: utf-8 -*-
# 海外人名条批量生成 · 精简版 · onefile 单文件打包配置
#
# 与完整版共用同一份 gui_batch.pyw，只靠打包时打入 lite.txt 标记切换为精简版：
#   - 只输出到输出目录，不做自动归档（不匹配剧名、不剪切到项目文件夹）
#   - 配置目录隔离到 %APPDATA%\JianyingNameEntryLite
#
# 打包依赖的两个坑（与完整版相同，漏了会导致检测一直未连接）：
#   1) comtypes 子模块(尤其 comtypes.stream)必须显式写进 hiddenimports
#   2) uiautomation 自带的 UIAutomationClient_VC140_X64/X86.dll 要收进 binaries
import os
import sys


def _find_uiautomation():
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
            _uia_binaries.append((src, os.path.join('uiautomation', 'bin')))
    print('[spec-lite] uiautomation:', _uia)
    print('[spec-lite] DLL:', [os.path.basename(b[0]) for b in _uia_binaries])
else:
    print('[spec-lite] !! 未找到 uiautomation/bin')

if not os.path.isfile('lite.txt'):
    raise SystemExit('[spec-lite] 缺少 lite.txt 标记文件，无法打出精简版')

_comtypes_mods = [
    'comtypes',
    'comtypes.stream',
    'comtypes.client',
    'comtypes.automation',
    'comtypes.typeinfo',
    'comtypes.gen',
    'comtypes._post_coinit',
]

name = '海外人名条批量生成-精简版'

a = Analysis(
    ['gui_batch.pyw'],
    pathex=['.'],
    binaries=_uia_binaries,
    # lite.txt 打进 _MEIPASS，程序启动即可判定为精简版
    datas=[('icon.ico', '.'), ('lite.txt', '.')],
    hiddenimports=_comtypes_mods + [
        'uiautomation', 'uiautomation.uiautomation', 'uiautomation.version',
        'src.pyJianYingDraft.jianying_controller', 'src.pyJianYingDraft.exceptions',
    ],
    hookspath=[],
    runtime_hooks=[],
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
