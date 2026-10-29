# -*- coding: utf-8 -*-
"""打包依赖完整性检查(不需要真跑 exe, 静态读 spec + 包目录)。

这次「检测一直未连接」的根因是 spec 漏收 comtypes.stream 与 UIA DLL,
属于打包配置错误, 功能代码完全正常。用静态检查把它固定成回归项。
"""
import sys, os, re
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(HERE, 'gui_batch.spec')

fails = []
def ck(n, c, e=''):
    print(('  [OK] ' if c else '  [FAIL] ') + n + (('  ' + str(e)) if e else ''))
    if not c: fails.append(n)

spec = open(SPEC, encoding='utf-8').read()
print('--- spec 静态检查 ---')

# 1. comtypes.stream 必须在 hiddenimports 里
ck("spec 含 'comtypes.stream'", 'comtypes.stream' in spec)
# 2. comtypes 其它关键子模块
for m in ('comtypes.client', 'comtypes.automation', 'comtypes.gen'):
    ck(f"spec 含 {m!r}", m in spec)
# 3. uiautomation 本体
ck("spec 含 'uiautomation'", 'uiautomation' in spec)
# 4. 排除了 win32com/pywin32(否则启动即崩)
for m in ('win32com', 'pythoncom', 'pywintypes'):
    ck(f'spec excludes 含 {m!r}', m in spec)
# 5. DLL 走 binaries 而不是 datas
ck('DLL 收在 binaries 参数里', re.search(r'binaries\s*=\s*_uia_binaries', spec) is not None)
ck('存在 _find_uiautomation 定位函数', '_find_uiautomation' in spec)
ck('目标路径保持 uiautomation/bin', "'uiautomation'" in spec and "'bin'" in spec)

print()
print('--- 本机 uiautomation 包完整性 ---')
uia_dir = None
try:
    import uiautomation as _u
    uia_dir = os.path.dirname(os.path.abspath(_u.__file__))
except Exception:
    # 源码环境没有就直接找常见位置
    for base in (os.environ.get('APPDATA'), os.environ.get('LOCALAPPDATA')):
        if not base:
            continue
        for sub in (('Python', 'Python310', 'site-packages', 'uiautomation'),
                    ('Python', 'Python310', 'lib', 'site-packages', 'uiautomation')):
            p = os.path.join(base, *sub)
            if os.path.isdir(p):
                uia_dir = p
                break
        if uia_dir:
            break

print('  uiautomation 目录:', uia_dir)
if uia_dir:
    ck('找到 uiautomation 包', True)
    bindir = os.path.join(uia_dir, 'bin')
    ck('存在 bin 目录', os.path.isdir(bindir), bindir)
    if os.path.isdir(bindir):
        dlls = [f for f in os.listdir(bindir) if f.lower().endswith('.dll')]
        ck('bin 内有两个 UIA DLL', len(dlls) >= 2, dlls)
        ck('含 X64 DLL', any('X64' in d for d in dlls), dlls)
        ck('含 X86 DLL', any('X86' in d for d in dlls), dlls)
else:
    # 本环境找不到包不代表打包有问题(spec 自己会定位), 不当作失败
    print('  (本环境看不到 uiautomation 包, 跳过包完整性检查)')

print()
print('--- comtypes 子模块可导入性 ---')
_checked = 0
for m in ('comtypes', 'comtypes.stream', 'comtypes.client', 'comtypes.automation'):
    try:
        __import__(m)
        ck(f'{m} 可导入', True)
        _checked += 1
    except Exception as e:
        if _checked == 0 and m == 'comtypes':
            print(f'  (本环境未安装 comtypes, 跳过导入检查)')
            break
        ck(f'{m} 可导入', False, f'{type(e).__name__}: {e}')
        _checked += 1

print()
print('--- 确认 spec 不再做全量 comtypes 枚举(会带进 win32com) ---')
ck('没有 _collect_comtypes_modules 全量枚举', '_collect_comtypes_modules' not in spec)

print()
if fails:
    print(f'FAILED {len(fails)}: ' + '; '.join(fails)); sys.exit(1)
print('ALL PASS')
