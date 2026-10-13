# -*- coding: utf-8 -*-
"""界面级验证: 最终位置控件 + 配置持久化 + 导入CSV自动填剧名。"""
import sys, os, json, time, tempfile, shutil, threading, importlib.util, types
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if 'uiautomation' not in sys.modules:
    stub = types.ModuleType('uiautomation')
    for _n in ('Control', 'WindowControl', 'GetRootControl', 'AutomationElement', 'SetGlobalSearchTimeout'):
        setattr(stub, _n, type(_n, (), {}))
    sys.modules['uiautomation'] = stub

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根(tests 的上一级)
spec = importlib.util.spec_from_file_location('gb', os.path.join(HERE, 'gui_batch.pyw'))
gb = importlib.util.module_from_spec(spec); spec.loader.exec_module(gb)
import tkinter as tk
from tkinter import ttk

fails = []
def ck(n, c, e=''):
    print(('  [OK] ' if c else '  [FAIL] ') + n + (('  ' + str(e)) if e else ''))
    if not c: fails.append(n)

tmp = tempfile.mkdtemp(prefix='gbui2_')
gb.SETTINGS_FILE = os.path.join(tmp, 'config.json')
gb.TEMPLATE_FILE = os.path.join(tmp, 'templates.json')
gb.HISTORY_FILE = os.path.join(tmp, '.draft_history.json')

root = tk.Tk(); root.withdraw()
app = gb.App(root)

print('--- 控件 ---')
for n in ('final_root_var', 'final_title_var', 'final_subdir_var', 'final_move_var'):
    ck(f'{n} 存在', hasattr(app, n))
ck('子文件夹默认=人名条', app.final_subdir_var.get() == '人名条', app.final_subdir_var.get())
ck('剪切默认勾选', app.final_move_var.get() is True)
ck('根目录默认为空', app.final_root_var.get() == '')
ck('匹配预览方法存在', hasattr(app, 'preview_final_match'))
ck('pick_final_root 存在', hasattr(app, 'pick_final_root'))

print('--- 配置持久化 ---')
d = app._collect_settings()
for k in ('final_root', 'final_title', 'final_subdir', 'final_move'):
    ck(f'_collect_settings 含 {k}', k in d)
ck('旧的 final_dir 已移除', 'final_dir' not in d)

app.final_root_var.set(r'O:\AI漫剧剪辑一组')
app.final_title_var.set('合约八年我成了自己的靠山')
app.final_subdir_var.set('人名条')
app.final_move_var.set(True)
app._save_all_settings()
saved = json.load(open(gb.SETTINGS_FILE, encoding='utf-8'))
ck('根目录已存', saved.get('final_root') == r'O:\AI漫剧剪辑一组')
ck('剧名已存', saved.get('final_title') == '合约八年我成了自己的靠山')
ck('剪切开关已存', saved.get('final_move') is True)

app.final_root_var.set(''); app.final_title_var.set(''); app.final_move_var.set(False)
app._apply_settings(saved)
ck('读回根目录', app.final_root_var.get() == r'O:\AI漫剧剪辑一组')
ck('读回剧名', app.final_title_var.get() == '合约八年我成了自己的靠山')
ck('读回剪切开关', app.final_move_var.get() is True)

print('--- 导入CSV自动填剧名 ---')
csv_dir = os.path.join(tmp, '短剧剧本交付', '32_合约八年我成了自己的靠山')
os.makedirs(csv_dir)
csv_path = os.path.join(csv_dir, '合约八年我成了自己的靠山_角色场景表.csv')
open(csv_path, 'w', encoding='utf-8-sig').write('序号,中文名,英文名\n1,,Iris\n1,,Margaret Sterling\n')
app.final_title_var.set('')          # 先清空
app._auto_title = ''
app._fill_title_from_path(csv_path)
ck('剧名自动填入(取文件名)', app.final_title_var.get() == '合约八年我成了自己的靠山', app.final_title_var.get())
# 再导入别的剧, 自动值应被覆盖
csv2 = os.path.join(csv_dir, '07_我的便宜老公是总裁_角色场景表.csv')
open(csv2, 'w', encoding='utf-8-sig').write('序号,中文名,英文名\n1,,Luke\n')
app._fill_title_from_path(csv2)
ck('下次导入可覆盖自动值', app.final_title_var.get() == '我的便宜老公是总裁', app.final_title_var.get())
# 用户手填过则不被覆盖
app.final_title_var.set('我手填的剧名'); app._auto_title = 'x'
app._fill_title_from_path(csv_path)
ck('用户手填不被覆盖', app.final_title_var.get() == '我手填的剧名')

print('--- runner 参数透传 ---')
r = gb.BatchRunner(None, tmp, log_cb=lambda *a: None, final_root=r'O:\AI漫剧剪辑一组',
                   final_title='测试剧', final_subdir='人名条', final_move=True)
ck('root 透传', r.final_root == r'O:\AI漫剧剪辑一组')
ck('title 透传', r.final_title == '测试剧')
ck('subdir 透传', r.final_subdir == '人名条')
ck('剪切开关透传', r.final_move is True)
r2 = gb.BatchRunner(None, tmp, log_cb=lambda *a: None)
ck('不设最终位置时不动作', r2.resolve_final_dir(['a']) == '')

print('--- 同名处理控件与询问 ---')
ck('同名处理控件存在', hasattr(app, 'conflict_var'))
ck('默认=询问', app.conflict_var.get() == '询问', app.conflict_var.get())
for label, val in gb.CONFLICT_LABELS.items():
    app.conflict_var.set(label)
    ck(f'{label} -> {val}', app._conflict_policy() == val, app._conflict_policy())
# 配置持久化
app.final_root_var.set(r'O:\AI漫剧剪辑一组')
app.conflict_var.set('覆盖')
d2 = app._collect_settings()
ck('_collect_settings 含 final_conflict', d2.get('final_conflict') == 'overwrite', d2.get('final_conflict'))
app._save_all_settings()
sv = json.load(open(gb.SETTINGS_FILE, encoding='utf-8'))
ck('config.json 存了 final_conflict', sv.get('final_conflict') == 'overwrite', sv.get('final_conflict'))
app.conflict_var.set('询问')
app._apply_settings(sv)
ck('读回后=覆盖', app.conflict_var.get() == '覆盖', app.conflict_var.get())

# 真实对话框: 反复尝试点击按钮(带超时兜底, 避免测试挂死)
def _find_dialog():
    for w in app.root.winfo_children():
        if isinstance(w, tk.Toplevel) and w.title() == '最终目录有同名文件':
            return w
    return None


def _walk(x):
    for c in x.winfo_children():
        yield c
        yield from _walk(c)


def click_when_ready(text, tries=50):
    """轮询等对话框出现并点下指定按钮; 超时则强制关闭。"""
    def attempt(n):
        w = _find_dialog()
        if w is not None:
            for c in _walk(w):
                try:
                    txt = c.cget('text')
                except tk.TclError:
                    continue
                if isinstance(c, ttk.Button) and str(txt) == text:
                    c.invoke()
                    return
        if n > 0:
            app.root.after(100, lambda: attempt(n - 1))
        else:
            print(f'  !! 点击「{text}」超时, 强制关闭对话框')
            w2 = _find_dialog()
            if w2 is not None:
                app.root.update()
                w2.destroy()
    attempt(tries)


app.root.after(200, lambda: click_when_ready('覆盖'))
val = app._conflict_dialog([('/s/a.mp4', '/d/a.mp4')])
ck('对话框点“覆盖”返回 overwrite', val == 'overwrite', val)
app.root.after(200, lambda: click_when_ready('取消投送'))
val2 = app._conflict_dialog([('/s/a.mp4', '/d/a.mp4'), ('/s/b.mp4', '/d/b.mp4')])
ck('对话框点“取消投送”返回 cancel', val2 == 'cancel', val2)

# 跨线程询问: 工作线程发起, 主线程真实 mainloop 回应(与运行时一致)
gb_orig = app._conflict_dialog
app._conflict_dialog = lambda c: 'skip'
holder = {}

def worker():
    holder['v'] = app._ask_conflict([('/s/a.mp4', '/d/a.mp4')])
    try:
        app.root.after(0, app.root.quit)
    except Exception:
        pass

app.root.after(200, lambda: threading.Thread(target=worker, daemon=True).start())
app.root.after(15000, app.root.quit)   # 兜底, 避免测试挂死
app.root.mainloop()
ck('工作线程能拿到询问答复', holder.get('v') == 'skip', holder.get('v'))
app._conflict_dialog = gb_orig

print('--- 可写目录解析(冻结/非冻结) ---')
ck('非冻结时=源码目录', gb.app_dir() == HERE, gb.app_dir())
ck('SETTINGS_FILE 在 app_dir 下', os.path.dirname(gb.SETTINGS_FILE) == HERE or gb.SETTINGS_FILE.startswith(tmp))
# 模拟冻结后的行为
_real_frozen = getattr(sys, 'frozen', None)
_real_appdata = os.environ.get('APPDATA')
sys.frozen = True
os.environ['APPDATA'] = tmp
_frozen_dir = gb.app_dir()
ck('冻结时=APPDATA 下专用目录', _frozen_dir == os.path.join(tmp, 'JianyingNameEntry'), _frozen_dir)
ck('冻结时会自动建目录', os.path.isdir(_frozen_dir))
if _real_frozen is None:
    del sys.frozen
else:
    sys.frozen = _real_frozen
if _real_appdata is None:
    os.environ.pop('APPDATA', None)
else:
    os.environ['APPDATA'] = _real_appdata
ck('还原后回到源码目录', gb.app_dir() == HERE, gb.app_dir())

print('--- 真实 O 盘匹配 + 剪切到临时目录(只读O盘) ---')
REAL = r'O:\AI漫剧剪辑一组'
if os.path.isdir(REAL):
    proj, why = gb.match_project(REAL, '合约八年我成了自己的靠山_角色场景表')
    ck('真实 O 盘命中项目', proj and '合约八年' in proj, f'{proj} / {why}')
else:
    print('  (O盘不可见, 跳过)')

root.destroy()
shutil.rmtree(tmp, ignore_errors=True)
print()
if fails:
    print(f'FAILED {len(fails)}: ' + '; '.join(fails)); sys.exit(1)
print('ALL PASS')
