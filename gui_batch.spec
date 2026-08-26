# -*- mode: python ; coding: utf-8 -*-
# 海外人名条批量生成 · 1.0 稳定版 打包配置
import os

name = '海外人名条批量生成'

a = Analysis(
    ['gui_batch.pyw'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=['uiautomation', 'comtypes'],
    hookspath=[],
    runtime_hooks=[],
    excludes=['numpy', 'pandas', 'matplotlib', 'PIL'],
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
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    version='version_info.txt',
    disable_windowed_traceback=False,
)
