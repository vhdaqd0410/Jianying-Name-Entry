# -*- coding: utf-8 -*-
"""v1.9.0: 归档规则默认展开 + 导入后自动匹配预览 + 成功倒计时/失败重试。"""
import sys, os, time, json, tempfile, shutil, importlib.util, types
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

TMP = tempfile.mkdtemp(prefix='v190_')
gb.SETTINGS_FILE = os.path.join(TMP, 'config.json')
gb.TEMPLATE_FILE = os.path.join(TMP, 'templates.json')
gb.HISTORY_FILE = os.path.join(TMP, '.draft_history.json')

# 造最终位置根目录 + 项目
FINAL = os.path.join(TMP, 'AI漫剧剪辑一组')
os.makedirs(FINAL)
PROJ = os.path.join(FINAL, 'H0242-11947《我的便宜老公是总裁》')
os.makedirs(os.path.join(PROJ, '人名条'))
open(os.path.join(PROJ, '人名条', 'Luke.mp4'), 'wb').write(b'x')

# 造剧本目录
D = os.path.join(TMP, '短剧剧本交付')
os.makedirs(os.path.join(D, '35_我的便宜老公是总裁'))
CAP = os.path.join(D, '35_我的便宜老公是总裁', '我的便宜老公是总裁_角色场景表.csv')
open(CAP, 'w', encoding='utf-8-sig').write('序号,中文名,英文名\n1,,Luke\n2,,Emily\n')
# 一个匹配不上的（文件名与项目名无关）
os.makedirs(os.path.join(D, '99_无关剧名'))
BAD = os.path.join(D, '99_无关剧名', '完全对不上的名字_角色场景表.csv')
open(BAD, 'w', encoding='utf-8-sig').write('序号,中文名,英文名\n1,,Zoe\n')

def new_app():
    r = tk.Tk(); r.withdraw()
    a = gb.App(r)
    return r, a

def find_dialog(app, title='匹配预览'):
    for w in app.root.winfo_children():
        if isinstance(w, tk.Toplevel) and w.title() == title:
            return w
    return None

def pump(root, seconds=0.5):
    t0 = time.time()
    while time.time() - t0 < seconds:
        try:
            root.update()
        except Exception:
            return
        time.sleep(0.03)

def labels_in(w):
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

def buttons_in(w, only_visible=False):
    out = []
    def walk(x):
        for c in x.winfo_children():
            try:
                if isinstance(c, ttk.Button):
                    if not only_visible or c.winfo_ismapped():
                        out.append(c)
            except Exception:
                pass
            walk(c)
    walk(w)
    return out

def entries_in(w):
    out = []
    def walk(x):
        for c in x.winfo_children():
            try:
                if isinstance(c, ttk.Entry):
                    out.append(c)
            except Exception:
                pass
            walk(c)
    walk(w)
    return out

# ================= 1. 归档规则默认展开 =================
print('--- 归档规则默认展开 ---')
r1, app1 = new_app()
r1.deiconify(); pump(r1, 0.5)

def find_card(x, title):
    for c in x.winfo_children():
        try:
            if isinstance(c, ttk.Labelframe) and str(c.cget('text')) == title:
                return c
        except Exception:
            pass
        rr = find_card(c, title)
        if rr:
            return rr
    return None

card3 = find_card(r1, '输出与归档')
ck('找到 输出与归档', card3 is not None)
if card3:
    h_with_secB = card3.winfo_reqheight()
    # 收起"归档规则"应该变矮 -> 证明它默认是展开的
    fbs = []
    def walkf(x):
        for c in x.winfo_children():
            try:
                if isinstance(c, ttk.Button) and str(c.cget('style')) == 'Fold.TButton':
                    fbs.append(c); continue
            except Exception:
                pass
            walkf(c)
    walkf(card3)
    ck('卡片内 3 个折叠分组', len(fbs) == 3, len(fbs))
    if len(fbs) >= 2:
        fbs[1].invoke(); pump(r1, 0.2)     # 点"归档规则"
        h_after = card3.winfo_reqheight()
        ck('点归档规则后收起(说明默认展开)', h_after < h_with_secB, f'{h_with_secB} -> {h_after}')
        fbs[1].invoke(); pump(r1, 0.2)
        ck('再点恢复', card3.winfo_reqheight() == h_with_secB)
r1.destroy()

# ================= 2. 匹配成功: 自动弹窗 + 倒计时关闭 =================
print('--- 匹配成功: 自动弹窗 + 3秒倒计时 ---')
r2, app2 = new_app()
r2.deiconify()
app2.final_root_var.set(FINAL)
app2._fill_title_from_path(CAP)
app2._set_names(['Luke', 'Emily'])
app2.final_title_var.set('我的便宜老公是总裁')
app2._auto_title = '我的便宜老公是总裁'
pump(r2, 0.3)

app2._run_match_preview_async()
# 等弹出
dlg = None
for _ in range(40):
    pump(r2, 0.1)
    dlg = find_dialog(app2)
    if dlg:
        break
ck('导入后自动弹出匹配预览', dlg is not None)
if dlg:
    pump(r2, 0.3)
    labs = labels_in(dlg)
    ck('弹窗显示匹配成功', any('匹配成功' in t for t in labs), labs[:6])
    ck('显示了项目文件夹名', any('我的便宜老公是总裁' in t for t in labs), labs[:6])
    btns = buttons_in(dlg, only_visible=True)
    ck('成功态只有确定按钮(没有检测)', not any('检测' in str(b.cget('text')) for b in btns),
       [str(b.cget('text')) for b in btns])
    ck('按钮带倒计时', any('确定 (' in str(b.cget('text')) for b in btns),
       [str(b.cget('text')) for b in btns])
    # 成功态剧名输入区应隐藏
    ck('成功态隐藏剧名输入区', len([e for e in entries_in(dlg) if e.winfo_ismapped()]) == 0)
    # 等 3 秒多, 应该自动关闭
    pump(r2, 4.2)
    ck('3 秒后自动关闭', find_dialog(app2) is None)
r2.destroy()

# ================= 3. 匹配失败: 输入框 + 检测 + 重试成功 =================
print('--- 匹配失败: 可改剧名重试 ---')
r3, app3 = new_app()
r3.deiconify()
app3.final_root_var.set(FINAL)
app3.final_title_var.set('完全对不上的名字')
app3._auto_title = '完全对不上的名字'
app3._set_names(['Zoe'])
pump(r3, 0.3)

app3._run_match_preview_async()
dlg = None
for _ in range(40):
    pump(r3, 0.1)
    dlg = find_dialog(app3)
    if dlg:
        break
ck('失败时也弹窗', dlg is not None)
if dlg:
    pump(r3, 0.3)
    labs = labels_in(dlg)
    ck('提示未匹配到', any('未匹配' in t for t in labs), labs[:6])
    ens = entries_in(dlg)
    ck('失败态提供剧名输入框', len([e for e in ens if e.winfo_ismapped()]) >= 1, len(ens))
    btns = buttons_in(dlg, only_visible=True)
    btn_texts = [str(b.cget('text')) for b in btns]
    ck('失败态有检测按钮', any('检测' in t for t in btn_texts), btn_texts)
    ck('失败态不显示倒计时确定', not any('确定' in t for t in btn_texts), btn_texts)

    # 输入正确剧名后点检测
    if ens:
        ens[0].delete(0, 'end')
        ens[0].insert(0, '我的便宜老公是总裁')
        pump(r3, 0.2)
        for b in buttons_in(dlg, only_visible=True):
            if '检测' in str(b.cget('text')):
                b.invoke()
                break
        pump(r3, 0.4)
        labs2 = labels_in(dlg)
        ck('检测后转为匹配成功', any('匹配成功' in t for t in labs2), labs2[:6])
        ck('剧名已回写到界面', app3.final_title_var.get() == '我的便宜老公是总裁',
           app3.final_title_var.get())
        btns2 = buttons_in(dlg, only_visible=True)
        ck('转成功态后有倒计时确定', any('确定 (' in str(b.cget('text')) for b in btns2),
           [str(b.cget('text')) for b in btns2])
        ck('转成功态后隐藏输入区',
           len([e for e in entries_in(dlg) if e.winfo_ismapped()]) == 0)
        pump(r3, 4.2)
        ck('重试成功后也自动关闭', find_dialog(app3) is None)
r3.destroy()

# ================= 4. 未设最终位置根目录: 不弹 =================
print('--- 未设根目录时不弹 ---')
r4, app4 = new_app()
r4.deiconify()
app4.final_root_var.set('')
pump(r4, 0.3)
app4._run_match_preview_async()
pump(r4, 0.6)
ck('未设根目录不弹窗', find_dialog(app4) is None)
r4.destroy()

# ================= 5. 检测空剧名应拒绝 =================
print('--- 空剧名检测 ---')
r5, app5 = new_app()
r5.deiconify()
app5.final_root_var.set(FINAL)
app5.final_title_var.set('对不上的名字')
app5._set_names(['Zoe'])
pump(r5, 0.3)
app5._run_match_preview_async()
dlg = None
for _ in range(40):
    pump(r5, 0.1)
    dlg = find_dialog(app5)
    if dlg:
        break
if dlg:
    pump(r5, 0.3)
    ens = entries_in(dlg)
    if ens:
        ens[0].delete(0, 'end')
        for b in buttons_in(dlg, only_visible=True):
            if '检测' in str(b.cget('text')):
                b.invoke(); break
        pump(r5, 0.3)
        labs = labels_in(dlg)
        ck('空剧名给出提示且不误判成功', any('不能为空' in t for t in labs), labs[:6])
        ck('仍是失败态(有输入框)', len(entries_in(dlg)) >= 1)
    try:
        dlg.destroy()
    except Exception:
        pass
r5.destroy()

shutil.rmtree(TMP, ignore_errors=True)
print()
if fails:
    print(f'FAILED {len(fails)}: ' + '; '.join(fails)); sys.exit(1)
print('ALL PASS')
