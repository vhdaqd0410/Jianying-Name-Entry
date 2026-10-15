# -*- coding: utf-8 -*-
"""边界验证: 剧名自动填入的完整规则。"""
import sys, os, json, tempfile, shutil, importlib.util, types
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

fails = []
def ck(n, c, e=''):
    print(('  [OK] ' if c else '  [FAIL] ') + n + (('  ' + str(e)) if e else ''))
    if not c: fails.append(n)

TMP = tempfile.mkdtemp(prefix='title2_')
gb.SETTINGS_FILE = os.path.join(TMP, 'config.json')
gb.TEMPLATE_FILE = os.path.join(TMP, 'templates.json')
gb.HISTORY_FILE = os.path.join(TMP, '.draft_history.json')

D = os.path.join(TMP, '短剧剧本交付')
for sub, fn in (('32_合约八年我成了自己的靠山', '合约八年我成了自己的靠山_角色场景表.csv'),
                ('33_死而复生双胞胎的终极复仇', '死而复生双胞胎的终极复仇_角色场景表.csv'),
                ('34_觉醒后我能听懂海洋心声', '觉醒后我能听懂海洋心声_角色场景表.csv')):
    os.makedirs(os.path.join(D, sub))
    open(os.path.join(D, sub, fn), 'w', encoding='utf-8-sig').write('序号,中文名,英文名\n1,,Amanda Sterling\n')
A = os.path.join(D, '32_合约八年我成了自己的靠山', '合约八年我成了自己的靠山_角色场景表.csv')
B = os.path.join(D, '33_死而复生双胞胎的终极复仇', '死而复生双胞胎的终极复仇_角色场景表.csv')
C = os.path.join(D, '34_觉醒后我能听懂海洋心声', '觉醒后我能听懂海洋心声_角色场景表.csv')

def new_app():
    r = tk.Tk(); r.withdraw()
    return r, gb.App(r)

print('--- 同一次运行内连续导入 ---')
r, app = new_app()
app._fill_title_from_path(A)
ck('第1个CSV -> 剧A', app.final_title_var.get() == '合约八年我成了自己的靠山', app.final_title_var.get())
app._fill_title_from_path(B)
ck('第2个CSV -> 剧B(覆盖)', app.final_title_var.get() == '死而复生双胞胎的终极复仇', app.final_title_var.get())
app._fill_title_from_path(C)
ck('第3个CSV -> 剧C(覆盖)', app.final_title_var.get() == '觉醒后我能听懂海洋心声', app.final_title_var.get())

print('--- 手改后不被后续导入覆盖 ---')
app.final_title_var.set('我手填的剧名')
app._on_title_typed()          # 模拟键盘输入
ck('手改后 _auto_title 已清空', getattr(app, '_auto_title', None) is None)
app._fill_title_from_path(A)
ck('手填值被保留', app.final_title_var.get() == '我手填的剧名', app.final_title_var.get())

print('--- 手改后再导入, 仍可手动改回 ---')
app.final_title_var.set('另一个手填')
app._fill_title_from_path(B)
ck('仍保留手填', app.final_title_var.get() == '另一个手填')
r.destroy()

print('--- 重启后旧剧名不阻挡新导入 ---')
# 先真正落盘一次(模拟用户跑过一批), 让 config 里有旧剧名
app2 = None
r2, app2 = new_app()
app2._fill_title_from_path(A)
app2._save_all_settings()
saved = json.load(open(gb.SETTINGS_FILE, encoding='utf-8'))
ck('旧剧名已落盘', saved.get('final_title') == '合约八年我成了自己的靠山', saved.get('final_title'))
r2.destroy()

r3, app3 = new_app()
ck('重启后读回旧剧名', app3.final_title_var.get() == '合约八年我成了自己的靠山',
   app3.final_title_var.get())
app3._fill_title_from_path(C)
ck('导入新CSV时旧剧名被覆盖(这就是之前的问题)',
   app3.final_title_var.get() == '觉醒后我能听懂海洋心声', app3.final_title_var.get())
r3.destroy()

print('--- 文件名无有效剧名时退回父文件夹 ---')
r4, app4 = new_app()
weird = os.path.join(D, '99_某剧', '_角色场景表.csv')
os.makedirs(os.path.dirname(weird), exist_ok=True)
open(weird, 'w', encoding='utf-8-sig').write('序号,中文名,英文名\n1,,X\n')
app4._fill_title_from_path(weird)
print('    得到 =', repr(app4.final_title_var.get()))
ck('退回到父文件夹名', '99_某剧' in app4.final_title_var.get(), app4.final_title_var.get())
r4.destroy()

shutil.rmtree(TMP, ignore_errors=True)
print()
if fails:
    print(f'FAILED {len(fails)}: ' + '; '.join(fails)); sys.exit(1)
print('ALL PASS')
