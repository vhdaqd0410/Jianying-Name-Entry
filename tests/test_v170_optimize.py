# -*- coding: utf-8 -*-
"""v1.7.0 六项优化验证: 断点续跑 / 空格热键 / 重跑不丢名单 / 窗口尺寸 / 日志 / 线程堆积。"""
import sys, os, time, tempfile, shutil, importlib.util, types, threading, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if 'uiautomation' not in sys.modules:
    stub = types.ModuleType('uiautomation')
    for _n in ('Control', 'WindowControl', 'GetRootControl', 'AutomationElement', 'SetGlobalSearchTimeout'):
        setattr(stub, _n, type(_n, (), {}))
    sys.modules['uiautomation'] = stub

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location('gb', os.path.join(HERE, 'gui_batch.pyw'))
gb = importlib.util.module_from_spec(spec); spec.loader.exec_module(gb)
import tkinter as tk
from tkinter import ttk

fails = []
def ck(n, c, e=''):
    print(('  [OK] ' if c else '  [FAIL] ') + n + (('  ' + str(e)) if e else ''))
    if not c: fails.append(n)

TMP = tempfile.mkdtemp(prefix='v170_')
OUT = os.path.join(TMP, '输出'); os.makedirs(OUT)
FIN = os.path.join(TMP, '最终')
PROJ = os.path.join(FIN, '731-11926-（海外）《合约八年，我成了自己的靠山》')
TARGET = os.path.join(PROJ, '人名条'); os.makedirs(TARGET)
TITLE = '合约八年我成了自己的靠山'

LOG = []
def mk(**kw):
    kw.setdefault('log_cb', lambda m: LOG.append(m))
    kw.setdefault('final_root', FIN)
    kw.setdefault('final_title', TITLE)
    kw.setdefault('conflict_policy', 'rename')
    return gb.BatchRunner(None, OUT, **kw)

# ================= 1. 断点续跑 =================
print('--- 断点续跑 ---')
class R(gb.BatchRunner):
    """记录真正处理了哪些名字"""
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw); self.processed = []
    def process_one(self, name, before_set):
        self.processed.append(name)
        p = os.path.join(self._outdir_actual, name + '.mp4')
        open(p, 'wb').write(b'D' + name.encode())
        self._produced.append(p)
        return True

# 第一次: 全量 3 个
r1 = R(None, OUT, log_cb=lambda m: LOG.append(m), final_root=FIN, final_title=TITLE,
       conflict_policy='rename', resume=True)
res1 = r1.run(['Adam', 'Ben', 'Cara'])
ck('首轮处理了全部 3 个', r1.processed == ['Adam', 'Ben', 'Cara'], r1.processed)
ck('首轮全部投送', all(os.path.exists(os.path.join(TARGET, n + '.mp4')) for n in ['Adam', 'Ben', 'Cara']))
ck('首轮无跳过', r1._skipped == [], r1._skipped)

# 第二次: 中断后重跑, 已投送的 3 个应被跳过; 只新增 Dan
LOG.clear()
r2 = R(None, OUT, log_cb=lambda m: LOG.append(m), final_root=FIN, final_title=TITLE,
       conflict_policy='rename', resume=True)
res2 = r2.run(['Adam', 'Ben', 'Cara', 'Dan'])
ck('续跑只处理新增的 Dan', r2.processed == ['Dan'], r2.processed)
ck('续跑跳过了 3 个', sorted(r2._skipped) == ['Adam', 'Ben', 'Cara'], r2._skipped)
ck('跳过的按成功计入结果', all(res2.get(n) for n in ['Adam', 'Ben', 'Cara']))
ck('日志说明跳过', any('断点续跑' in m and '跳过' in m for m in LOG), [m for m in LOG if '续跑' in m])
ck('Dan 已投送', os.path.exists(os.path.join(TARGET, 'Dan.mp4')))
ck('未产生重复文件', not any('(1)' in f for f in os.listdir(TARGET)), os.listdir(TARGET))

# 第三次: 全部已完成 -> 一条都不导
LOG.clear()
r3 = R(None, OUT, log_cb=lambda m: LOG.append(m), final_root=FIN, final_title=TITLE,
       conflict_policy='rename', resume=True)
res3 = r3.run(['Adam', 'Ben', 'Cara', 'Dan'])
ck('全完成时零导出', r3.processed == [], r3.processed)
ck('日志提示全部已完成', any('全部已完成' in m for m in LOG), [m for m in LOG if '完成' in m])

# 关掉续跑 -> 应重新全跑
r4 = R(None, OUT, log_cb=lambda m: LOG.append(m), final_root=FIN, final_title=TITLE,
       conflict_policy='rename', resume=False)
r4.run(['Adam', 'Ben'])
ck('关掉续跑则重新导出', r4.processed == ['Adam', 'Ben'], r4.processed)

print('--- 续跑识别 (1) 后缀与 mov ---')
# 目标目录里有 Cara(1).mp4 形式, 也应归到 Cara
open(os.path.join(TARGET, 'Zed(1).mp4'), 'wb').write(b'x')
open(os.path.join(TARGET, 'Yan_透明.mov'), 'wb').write(b'x')
open(os.path.join(TARGET, 'Wes.mp4'), 'wb').write(b'x')
r5 = mk(resume=True)
r5._outdir_actual = OUT
r5.resolve_final_dir(['Zed', 'Yan', 'Wes'])
dn = r5._produced_names()
ck('识别 姓名(1).mp4 -> 姓名', 'Zed' in dn, sorted(dn))
ck('_透明.mov 归到本体名 Yan', 'Yan' in dn, sorted(dn))
ck('不产生 姓名_透明 这种假名字', 'Yan_透明' not in dn, sorted(dn))
ck('普通成片名正常', 'Wes' in dn, sorted(dn))

print('--- 输出目录里的残留也算已完成 ---')
open(os.path.join(OUT, 'Left.mp4'), 'wb').write(b'x')   # 上次未投送完的
r6 = mk(resume=True)
r6._outdir_actual = OUT
dn6 = r6._produced_names()
ck('扫到输出目录残留', 'Left' in dn6, sorted(dn6))

# ================= 2. 空格热键（不依赖按键模拟: 直接验守卫逻辑） =================
print('--- 空格热键守卫逻辑 ---')
root_t = tk.Tk(); root_t.withdraw()
gb.SETTINGS_FILE = os.path.join(TMP, 'config.json')
gb.TEMPLATE_FILE = os.path.join(TMP, 'templates.json')
gb.HISTORY_FILE = os.path.join(TMP, '.draft_history.json')
app = gb.App(root_t)
root_t.deiconify(); root_t.update()

ck('root 上保留 <space> 全局绑定', bool(root_t.bind('<space>')))

calls = []
app.toggle_pause = lambda: calls.append(1)

# 焦点在文本控件 -> 必须让路(不 pause, 不 break)
app.name_box.focus_force(); root_t.update()
ck('识别到焦点在名字框', app._focus_is_text())
for running in (False, True):
    app._running = running
    app.pause_btn.config(state='normal')
    calls.clear()
    ret = app._hotkey_toggle_pause()
    ck(f'焦点在名字框(running={running}) 不触发暂停', not calls, calls)
    ck(f'焦点在名字框(running={running}) 返回 None 让空格输入', ret is None, ret)

# 焦点不在文本控件 -> 运行中才拦键
root_t.focus_force(); root_t.update()
ck('焦点不在文本控件时判定为非文本', not app._focus_is_text())
app._running = True
app.pause_btn.config(state='normal')
calls.clear()
ret = app._hotkey_toggle_pause()
ck('焦点在窗口+运行中 -> 触发暂停并拦键', bool(calls) and ret == 'break', (calls, ret))

# 未运行时不吞键
calls.clear()
app._running = False
ret = app._hotkey_toggle_pause()
ck('未运行时不触发暂停', not calls)
ck('未运行时不拦键(空格不被吞)', ret is None, ret)

# 运行中但暂停按钮禁用 -> 不拦键(用 instate 判断, 不再用 cget)
app._running = True
app.pause_btn.config(state='disabled'); root_t.update()
calls.clear()
ret = app._hotkey_toggle_pause()
ck('暂停按钮禁用时不拦键', ret is None and not calls, (calls, ret))
ck('instate 能识别 disabled', app.pause_btn.instate(['disabled']))
app.pause_btn.config(state='normal')

# ================= 3. 重跑不丢名单 =================
print('--- 重跑失败不覆盖名字列表 ---')
full = ['Alpha', 'Beta', 'Gamma']
app._set_names(full)
app._running = False
started = {}
app._start_run = lambda names, outdir: started.update(names=list(names))
app._last_fail_names = ['Beta']
app.rerun_failed()
ck('重跑的是失败名单', started.get('names') == ['Beta'], started)
ck('界面名单保持全量', app._get_names() == full, app._get_names())

# ================= 4. 窗口尺寸记忆 =================
print('--- 窗口尺寸记忆 ---')
root_t.geometry('1100x880'); root_t.update()
app._save_window_size()
sv = json.load(open(gb.SETTINGS_FILE, encoding='utf-8'))
ck('已存 window_size', sv.get('window_size') == '1100x880', sv.get('window_size'))
ck('_collect_settings 含 window_size', 'window_size' in app._collect_settings())
root_t.geometry('900x700'); root_t.update()
app._apply_window_size('1100x880')
root_t.update()
ck('恢复尺寸生效', (root_t.winfo_width(), root_t.winfo_height()) == (1100, 880),
   (root_t.winfo_width(), root_t.winfo_height()))
app._apply_window_size('zoomed')
ck('恢复最大化不报错', True)
app._apply_window_size('')
app._apply_window_size('乱码')
ck('非法值不崩', True)

# ================= 5. 日志复制/导出/清空 =================
print('--- 日志复制/导出/清空 ---')
for i in range(5):
    app._log(f'测试日志行 {i}')
root_t.update()
txt = app._log_text()
ck('读到日志内容', '测试日志行 0' in txt and '测试日志行 4' in txt)
app.copy_log()
root_t.update()
ck('已复制到剪贴板', '测试日志行 2' in root_t.clipboard_get())
exp = os.path.join(TMP, 'out_log.txt')
_open = gb.filedialog.asksaveasfilename
gb.filedialog.asksaveasfilename = lambda **kw: exp
app.export_log()
gb.filedialog.asksaveasfilename = _open
ck('日志已导出成文件', os.path.exists(exp) and '测试日志行 1' in open(exp, encoding='utf-8').read())
app.clear_log(); root_t.update()
ck('清空后为空', app._log_text() == '')
# 清空必须丢弃“清空前已排队”的日志, 否则界面一刷新旧行会冒回来
app._log('排队中的日志')
app.clear_log()
for _ in range(6):
    root_t.update(); time.sleep(0.05)
ck('清空后不残留排队日志', app._log_text() == '', repr(app._log_text()))
# 但清空之后新写的日志要保留
app._log('清空之后的新行')
for _ in range(6):
    root_t.update(); time.sleep(0.05)
ck('清空后的新日志仍会显示', app._log_text() == '清空之后的新行', repr(app._log_text()))

# ================= 6. 线程堆积已修 =================
print('--- 连接轮询不再堆积线程 ---')
root_t.destroy()
root2 = tk.Tk(); root2.withdraw()
app2 = gb.App(root2)
SLOW = 6.0
concurrent = {'n': 0, 'peak': 0, 'calls': 0}
lk = threading.Lock()

class SlowCtl:
    def __init__(self, *, activate=True):
        with lk:
            concurrent['n'] += 1; concurrent['calls'] += 1
            concurrent['peak'] = max(concurrent['peak'], concurrent['n'])
        try:
            time.sleep(SLOW)
            raise Exception('not found (simulated)')
        finally:
            with lk:
                concurrent['n'] -= 1

gb.JianyingController = SlowCtl
app2._start_link_polling()
root2.after(20000, root2.quit)
root2.mainloop()
ck('检测线程不并发(峰值=1)', concurrent['peak'] == 1, concurrent)
ck('20 秒内启动次数合理(约 3 次)', 2 <= concurrent['calls'] <= 5, concurrent['calls'])
root2.destroy()

shutil.rmtree(TMP, ignore_errors=True)
print()
if fails:
    print(f'FAILED {len(fails)}: ' + '; '.join(fails)); sys.exit(1)
print('ALL PASS')
