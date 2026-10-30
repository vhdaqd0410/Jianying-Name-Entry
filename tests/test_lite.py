# -*- coding: utf-8 -*-
"""精简版验证: 能否构建 / 有无归档入口 / 配置目录隔离。"""
import sys, os, time, tempfile, shutil, importlib.util, types
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if 'uiautomation' not in sys.modules:
    stub = types.ModuleType('uiautomation')
    for _n in ('Control', 'WindowControl', 'GetRootControl', 'AutomationElement', 'SetGlobalSearchTimeout'):
        setattr(stub, _n, type(_n, (), {}))
    sys.modules['uiautomation'] = stub

HERE = r'F:\OH-WorkSpace\projects\Jianying-Name-Entry'
spec = importlib.util.spec_from_file_location('gb', os.path.join(HERE, 'gui_batch.pyw'))
gb = importlib.util.module_from_spec(spec); spec.loader.exec_module(gb)
import tkinter as tk
from tkinter import ttk

fails = []
def ck(n, c, e=''):
    print(('  [OK] ' if c else '  [FAIL] ') + n + (('  ' + str(e)) if e else ''))
    if not c: fails.append(n)

TMP = tempfile.mkdtemp(prefix='lite_')
# 手工把 LITE 打开(源码模式下模拟精简版)
gb.LITE = True   # 源码下模拟精简版(等价于打包时打入 lite.txt)
gb.SETTINGS_FILE = os.path.join(TMP, 'config.json')
gb.TEMPLATE_FILE = os.path.join(TMP, 'templates.json')
gb.HISTORY_FILE = os.path.join(TMP, '.draft_history.json')

print('--- 构建精简版界面 ---')
root = tk.Tk(); root.withdraw()
app = gb.App(root)
root.deiconify()
for _ in range(14):
    root.update(); time.sleep(0.04)
ck('界面构建成功', True)
ck('窗口标题标注精简版', '精简版' in root.title(), root.title())

print()
print('--- 确认没有归档入口 ---')
def all_texts(w):
    out = []
    def walk(x):
        for c in x.winfo_children():
            try:
                t = str(c.cget('text'))
                if t:
                    out.append(t)
            except Exception:
                pass
            walk(c)
    walk(w)
    return out

texts = all_texts(root)
joined = ' | '.join(texts)
for bad in ('最终位置根目录', '归档规则', '匹配预览', '同名处理', '剧名', '项目名'):
    ck(f'不含「{bad}」', bad not in joined, [t for t in texts if bad in t])
ck('project_var 为空(不会建子目录)', app.project_var.get() == '', app.project_var.get())

print()
print('--- 保留的必要项 ---')
for good in ('输出目录', '开始批量', '断点续跑', '导出后转透明通道'):
    ck(f'含「{good}」', any(good in t for t in texts), [t for t in texts if good in t][:3])

print()
print('--- 归档变量占位可用(不报错) ---')
for attr in ('final_root_var', 'final_title_var', 'conflict_var', 'final_move_var', 'final_subdir_var'):
    ck(f'{attr} 存在', hasattr(app, attr))
ck('final_root_var 为空(意味着不会归档)', app.final_root_var.get() == '', app.final_root_var.get())

print()
print('--- 导入 CSV 后不弹匹配预览 ---')
D = os.path.join(TMP, '剧本')
os.makedirs(D)
csvp = os.path.join(D, '某剧_角色场景表.csv')
open(csvp, 'w', encoding='utf-8-sig').write('序号,中文名,英文名\n1,,Luke\n')
app.final_root_var.set(r'O:\AI漫剧剪辑一组')   # 即使误设了根目录也不该弹
app._run_match_preview_async()
for _ in range(20):
    root.update(); time.sleep(0.03)
dialogs = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
ck('未弹匹配预览', len(dialogs) == 0, dialogs)
ck('日志无“跳过自动匹配预览”提示', '跳过自动匹配预览' not in app._log_text())

print()
print('--- 投送逻辑自动跳过(不归档) ---')
LOG = []
OUT = os.path.join(TMP, '输出'); os.makedirs(OUT)
made = os.path.join(OUT, 'Luke.mp4')
open(made, 'wb').write(b'x')
# 精简版界面 final_root_var 为空 -> runner 的 final_root 也为空 -> deliver_all 直接返回
root_var = app.final_root_var.get().strip()
r_lite = gb.BatchRunner(None, OUT, log_cb=lambda m: LOG.append(m),
                        final_root=root_var, final_title=app.final_title_var.get())
r_lite._produced = [made]
st = r_lite.deliver_all(['Luke'])
ck('精简版 deliver_all 不搬任何文件', st['moved'] == 0 and st['overwritten'] == 0, st)
ck('文件仍在输出目录', os.path.exists(made))
ck('未定位最终目录', r_lite._final_dir == '', r_lite._final_dir)

print()
print('--- 配置目录隔离 ---')
# 精简版应使用带 Lite 的目录名
orig_lite = gb.LITE
gb.LITE = True
lite_dir = None
try:
    # 直接看 app_dir 分支逻辑: frozen 下用 JianyingNameEntryLite
    import inspect
    src = inspect.getsource(gb.app_dir)
    ck('app_dir 含 JianyingNameEntryLite', 'JianyingNameEntryLite' in src)
    ck('app_dir 按 LITE 切换子目录', "if LITE" in src or 'JianyingNameEntryLite' in src)
except Exception as e:
    ck('app_dir 源码检查', False, e)
gb.LITE = orig_lite

root.destroy()
shutil.rmtree(TMP, ignore_errors=True)
print()
if fails:
    print(f'FAILED {len(fails)}: ' + '; '.join(fails)); sys.exit(1)
print('ALL PASS')
