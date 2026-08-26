# -*- mode: python ; coding: utf-8 -*-
# 海外人名条批量生成 · v1.0.5 · onefile 单文件打包配置(嵌入 icon.ico)
import os

name = '海外人名条批量生成'

a = Analysis(
    ['gui_batch.pyw'],
    pathex=['.'],
    binaries=[],
    datas=[('icon.ico', '.')],
    hiddenimports=['uiautomation', 'comtypes', 'src.pyJianYingDraft.jianying_controller'],
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
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon='icon.ico',
    version='version_info.txt',
    disable_windowed_traceback=False,
)
