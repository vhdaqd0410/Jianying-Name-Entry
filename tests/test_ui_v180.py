# -*- coding: utf-8 -*-
"""新界面验证: 能否构建 / 底部控制区是否永远可见 / 折叠是否生效 / 几何是否溢出。"""
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

TMP = tempfile.mkdtemp(prefix='ui_new_')
gb.SETTINGS_FILE = os.path.join(TMP, 'config.json')
gb.TEMPLATE_FILE = os.path.join(TMP, 'templates.json')
gb.HISTORY_FILE = os.path.join(TMP, '.draft_history.json')

print('--- DPI 感知函数 ---')
print('  enable_dpi_awareness 存在:', hasattr(gb, 'enable_dpi_awareness'))
print('  get_dpi_scale 存在:', hasattr(gb, 'get_dpi_scale'))

root = tk.Tk(); root.withdraw()
app = gb.App(root)
root.deiconify()
for _ in range(14):
    root.update(); time.sleep(0.04)
print(f'  窗口尺寸: {root.winfo_width()}x{root.winfo_height()}')

print('--- 关键控件是否可见(默认尺寸) ---')
def vis(label, w):
    try:
        m = w.winfo_ismapped()
        h = w.winfo_height()
        ok = bool(m) and h > 5
        ck(f'{label} 可见', ok, f'mapped={m} h={h}')
    except Exception as e:
        ck(f'{label} 可见', False, e)

for lab, w in (('开始批量', app.start_btn), ('干跑预览', app.preview_btn),
               ('停止', app.stop_btn), ('暂停', app.pause_btn), ('重跑失败', app.rerun_btn),
               ('进度条', app.pbar), ('名字框', app.name_box), ('日志框', app.log_box),
               ('断点续跑勾选', None)):
    if w is not None:
        vis(lab, w)

print('--- 小窗口(最小尺寸)下控制区仍可见 ---')
root.geometry('860x640')
for _ in range(14):
    root.update(); time.sleep(0.04)
for lab, w in (('开始批量', app.start_btn), ('进度条', app.pbar)):
    vis(f'小窗·{lab}', w)

print('--- 滚轮/滚动区存在 ---')
canvases = []
def walk(x):
    for c in x.winfo_children():
        if isinstance(c, tk.Canvas):
            canvases.append(c)
        walk(c)
walk(root)
scroll_canvas = None
for c in canvases:
    try:
        if c.cget('yscrollcommand'):
            scroll_canvas = c
            break
    except Exception:
        pass
ck('存在滚动画布', scroll_canvas is not None)
if scroll_canvas:
    inner_h = scroll_canvas.bbox('all')[3] if scroll_canvas.bbox('all') else 0
    ck('滚动区已设 scrollregion', bool(scroll_canvas.cget('scrollregion')) or inner_h > 0,
       scroll_canvas.cget('scrollregion'))

print('--- 折叠分组 ---')
# 找卡片③里的 Fold.TButton
folds = []
def walk2(x):
    for c in x.winfo_children():
        try:
            if isinstance(c, ttk.Button) and str(c.cget('style')) == 'Fold.TButton':
                folds.append(c)
        except Exception:
            pass
        walk2(c)
walk2(root)
ck('有折叠按钮', len(folds) >= 2, f'找到 {len(folds)} 个')

# 卡片标题
titles = []
def walk3(x):
    for c in x.winfo_children():
        try:
            if isinstance(c, ttk.Labelframe):
                titles.append(str(c.cget('text')))
        except Exception:
            pass
        walk3(c)
walk3(root)
print('  卡片标题:', titles)
ck('卡片③更名为 输出与归档', '输出与归档' in titles, titles)
ck('无旧 Card.TLabelframe 残留', not any('Card.' in str(t) for t in titles))

main = root.winfo_children()[0]

print('--- 折叠交互 ---')
def find_card(x, title):
    for c in x.winfo_children():
        try:
            if isinstance(c, ttk.Labelframe) and str(c.cget('text')) == title:
                return c
        except Exception:
            pass
        r = find_card(c, title)
        if r:
            return r
    return None


def fold_buttons_of(card):
    """按出现顺序返回该卡片内的折叠按钮"""
    out = []
    def w(x):
        for c in x.winfo_children():
            try:
                if isinstance(c, ttk.Button) and str(c.cget('style')) == 'Fold.TButton':
                    out.append(c)
                    continue
            except Exception:
                pass
            w(c)
    w(card)
    return out

card3 = find_card(root, '输出与归档')
ck('找到 输出与归档 卡片', card3 is not None)
if card3:
    fbs = fold_buttons_of(card3)
    ck('卡片内有 3 个折叠分组(保存位置/归档规则/高级选项)', len(fbs) == 3, len(fbs))
    # 分组1 默认展开 -> 点它应收起
    h0 = card3.winfo_reqheight()
    fbs[0].invoke(); root.update(); time.sleep(0.08)
    h1 = card3.winfo_reqheight()
    ck('收起“保存位置”后变矮', h1 < h0, f'{h0} -> {h1}')
    # 再点恢复
    fbs[0].invoke(); root.update(); time.sleep(0.08)
    h2 = card3.winfo_reqheight()
    ck('再点恢复原高', h2 == h0, f'{h2} vs {h0}')
    # 分组2(归档规则) v1.9.0 起默认展开 -> 点它应收起
    fbs[1].invoke(); root.update(); time.sleep(0.08)
    h3 = card3.winfo_reqheight()
    ck('“归档规则”默认展开(点后变矮)', h3 < h0, f'{h0} -> {h3}')
    fbs[1].invoke(); root.update(); time.sleep(0.08)
    ck('再点恢复', card3.winfo_reqheight() == h0, card3.winfo_reqheight())

print('--- 窄栏宽度分配 ---')
# 按内容识别: 含日志框的帧 = 日志区
def frame_with(widget):
    p = widget
    while p is not None:
        if isinstance(p, ttk.Frame) and p.master is main:
            return p
        p = p.master if hasattr(p, 'master') else None
    return None

log_frame = frame_with(app.log_box)
left_frame = frame_with(app.name_box)
ck('识别出日志区与操作区', log_frame is not None and left_frame is not None
   and log_frame is not left_frame)
if log_frame and left_frame:
    print(f'  日志区 宽={log_frame.winfo_width()} req={log_frame.winfo_reqwidth()}')
    print(f'  操作区 宽={left_frame.winfo_width()} req={left_frame.winfo_reqwidth()}')
    ck('日志区拿到自己的请求宽度(未被挤扁)',
       log_frame.winfo_width() >= log_frame.winfo_reqwidth() - 2,
       f'{log_frame.winfo_width()} vs {log_frame.winfo_reqwidth()}')
    # 关键回归点: 卡片区宽度不该被某个长标题撑爆(修前那个 484px 的长标题)
    inner_w = None
    for c in canvases:
        try:
            if c.cget('yscrollcommand'):
                bbox = c.bbox('all')
                inner_w = (bbox[2] - bbox[0]) if bbox else None
                break
        except Exception:
            pass
    print(f'  卡片区内容宽={inner_w}')
    ck('卡片区宽度合理(<520, 不再被长标题撑爆)', inner_w is not None and inner_w < 520, inner_w)
    ck('底部控制区不超窗口宽', left_frame.winfo_reqwidth() <= root.winfo_width(),
       f'{left_frame.winfo_reqwidth()} vs {root.winfo_width()}')

root.destroy()
shutil.rmtree(TMP, ignore_errors=True)
print()
if fails:
    print(f'FAILED {len(fails)}: ' + '; '.join(fails)); sys.exit(1)
print('ALL PASS')
