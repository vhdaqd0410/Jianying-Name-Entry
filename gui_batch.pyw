# -*- coding: utf-8 -*-
"""海外人名条批量生成 · 界面版 (方案B)
复用 batch12 内核: UIA SetValue 替换 → Ctrl+M 导出 → wait_for_export_completion → 移动归置
特点: 文件一出现即移动, 不依赖关掉成功弹窗; 失败单独重跑; 界面+日志
启动: 双击 gui_batch.pyw 或 `uv run python gui_batch.pyw`
"""
import sys, os, time, ctypes, glob, shutil, threading, argparse
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from src.pyJianYingDraft.jianying_controller import JianyingController, AutomationError

user32 = ctypes.windll.user32

# ------------------------------------------------------------------ 时间配置 (可调)
# 固定等待时间均在此集中配置, 调快/调稳只需改这里。单位: 秒。
# 注意: 渲染等待(wait_for_export_completion)由剪映导出速度决定, 此处无法加速。
T_AFTER_EXPORT_KEY = 2.0      # Ctrl+M 后等剪映打开导出窗口
T_AFTER_ENTER = 0.5           # 回车确认导出后
T_BETWEEN_NAMES = 1.2         # 两个名字之间的间隔
T_CLICK_TEXTBOX = 0.25        # 点击文本框后
T_PASTE_WAIT = 0.35           # Ctrl+V 粘贴后
T_CLIPBOARD = 0.15            # 写剪贴板后
DEFAULT_OUTDIR = os.path.join(os.path.expanduser(r'~\Desktop'), '海外人名条')

# ------------------------------------------------------------------ 核心逻辑
def set_clipboard(text):
    """写入系统剪贴板 (真实键盘粘贴用)"""
    import subprocess
    subprocess.run(['clip'], input=text.encode('utf-16le'), shell=True, check=True)
    time.sleep(T_CLIPBOARD)

def key(vk):
    user32.keybd_event(vk, 0, 0, 0); user32.keybd_event(vk, 0, 2, 0)

def ctrl_key(vk):
    user32.keybd_event(0x11, 0, 0, 0); key(vk); user32.keybd_event(0x11, 0, 2, 0)

def click(x, y):
    user32.SetCursorPos(int(x), int(y)); time.sleep(0.12)
    user32.mouse_event(0x0002, 0, 0, 0, 0); user32.mouse_event(0x0004, 0, 0, 0, 0); time.sleep(0.08)


class BatchRunner:
    """批量导出运行器(在后台线程跑, 界面用回调更新)"""
    def __init__(self, ctrl, outdir, resolution=None, framerate=None, log_cb=None, progress_cb=None):
        self.ctrl = ctrl
        self.outdir = outdir
        self.resolution = resolution
        self.framerate = framerate
        self.log_cb = log_cb or (lambda *a: None)
        self.progress_cb = progress_cb or (lambda *a: None)
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def _log(self, msg):
        self.log_cb(msg)

    # ---- 文本框查找 (过滤底部数字框, 只取人名框 w>=80, y<900)
    def find_edit(self):
        root = self.ctrl.app; SEEN = set(); res = []
        def f(c, d=0):
            if d > 12: return
            try: rid = c.GetRuntimeId()
            except: rid = None
            if rid is None or rid in SEEN: return
            SEEN.add(rid)
            try:
                if c.ControlTypeName == 'EditControl':
                    try: v = c.GetValuePattern().Value if c.GetValuePattern() else ''
                    except: v = ''
                    if v and not v.lstrip('-').replace('.','').isdigit():
                        try:
                            r = c.BoundingRectangle
                            l, t, rr, b = int(r.left), int(r.top), int(r.right), int(r.bottom)
                            res.append((v, (l+rr)//2, (t+b)//2, c))
                        except: pass
            except: pass
            try:
                for ch in c.GetChildren()[:100]: f(ch, d+1)
            except: pass
        f(root); return res

    def get_textbox(self, timeout=20):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self._stop.is_set(): return None
            for v, cx, cy, c in self.find_edit():
                try:
                    r = c.BoundingRectangle
                    w = int(r.right) - int(r.left)
                except:
                    w = 0
                if cy < 900 and w >= 80:
                    return (v, cx, cy, c)
            time.sleep(0.5)
        return None

    def set_name(self, name, edit_ctrl):
        """用真实键盘输入替换文字: 点击文本框→全选→删除→粘贴。
        剪映认的是真实编辑(会提交到时间线素材), SetValue只是UIA显示层假替换。
        替换后重试读回验证, 确认文字真的被替换才返回True。"""
        # 取文本框中心坐标
        try:
            r = edit_ctrl.BoundingRectangle
            cx, cy = (r.left + r.right) // 2, (r.top + r.bottom) // 2
        except Exception as ex:
            self._log(f'  取文本框坐标失败:{ex}')
            return False
        # 真实键盘输入
        click(cx, cy); time.sleep(T_CLICK_TEXTBOX)
        ctrl_key(0x41); time.sleep(0.25)   # Ctrl+A 全选
        key(0x2E); time.sleep(0.15)         # Delete 删除
        set_clipboard(name)
        ctrl_key(0x56); time.sleep(T_PASTE_WAIT)   # Ctrl+V 粘贴
        time.sleep(0.3)
        # 重试读回验证: UIA树可能刷新, 需重新定位文本框
        for _ in range(5):
            tb = self.get_textbox(3)
            if tb and name in str(tb[0]):
                return True
            time.sleep(0.6)
        self._log(f'  !!替换后读回未确认到 {name} (读回{tb[0] if tb else "无"!r})')
        return False

    def desktop_exports(self):
        return glob.glob(os.path.join(os.path.expanduser(r'~\Desktop'), '海外人名条*.mp4'))

    def wait_new_export(self, before_set, timeout=120):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self._stop.is_set(): return None
            cur = set(self.desktop_exports())
            new = cur - before_set
            if new: return list(new)[0]
            time.sleep(0.5)
        return None

    # ---- 单名字处理, 返回 True=成功
    def process_one(self, name, before_set):
        self._log(f'\n=== {name} ===')
        # 确保剪映前台+文本框可见
        try:
            hwnd = self.ctrl.app.NativeWindowHandle
            user32.ShowWindow(hwnd, 9); time.sleep(0.3)
        except: pass
        tb = self.get_textbox(timeout=15)
        if not tb:
            self._log('  文本框不可见,尝试Esc恢复')
            key(0x1B); time.sleep(1.0)
            tb = self.get_textbox(timeout=15)
            if not tb:
                self._log('  仍无文本框,失败'); return False
        self._log(f'  当前: {tb[0]!r}')

        # 替换 (UIA SetValue) + 强验证: 读回确认文字真的被替换, 否则不导出
        if not self.set_name(name, tb[3]):
            self._log(f'  !!文字未确认替换为{name}, 中止本次导出')
            return False
        self._log(f'  已替换并确认: {name!r}')

        # 导出
        ctrl_key(0x4D); time.sleep(T_AFTER_EXPORT_KEY)
        self._log('  已按Ctrl+M')
        key(0x0D); time.sleep(T_AFTER_ENTER)
        self._log('  已按回车')

        # 等待导出完成并自动关闭 (minimize=False: 保持窗口在前台, 不最小化)
        try:
            done = self.ctrl.wait_for_export_completion(timeout=240, minimize=False)
            self._log(f'  导出完成: {done}')
        except AutomationError as ex:
            self._log(f'  导出超时: {ex}')
            key(0x1B); time.sleep(1.0)
            return False
        except Exception as ex:
            self._log(f'  导出异常: {ex}')
            return False

        # 等文件生成
        self._log('  等文件...')
        src = self.wait_new_export(before_set, timeout=120)
        if not src:
            self._log('  文件未生成'); return False
        self._log(f'  文件: {os.path.basename(src)}')

        # 移动归置 (文件名与名字一致)
        target = os.path.join(self.outdir, name + '.mp4')
        if os.path.exists(target):
            target = os.path.join(self.outdir, name + '(1).mp4')
        try:
            shutil.move(src, target)
            self._log(f'  -> {target}')
            before_set.discard(src)
            return True
        except Exception as ex:
            self._log(f'  移动失败:{ex}')
            before_set.add(src)
            return False

    # ---- 批量入口
    def run(self, names):
        os.makedirs(self.outdir, exist_ok=True)
        before_set = set(self.desktop_exports())
        results = {}
        for idx, name in enumerate(names, 1):
            if self._stop.is_set():
                self._log('\n(已停止)')
                break
            self.progress_cb(idx, len(names), name, 'running')
            ok = self.process_one(name, before_set)
            results[name] = ok
            self.progress_cb(idx, len(names), name, 'ok' if ok else 'fail')
            time.sleep(T_BETWEEN_NAMES)

        ok_names = [n for n, v in results.items() if v]
        fail_names = [n for n, v in results.items() if not v]
        self._log(f'\n===== 结果: 成功{len(ok_names)} 失败{len(fail_names)} =====')
        if fail_names:
            self._log('失败: ' + ', '.join(fail_names))
        return results


# ------------------------------------------------------------------ 界面
class App:
    def __init__(self, root):
        self.root = root
        root.title('海外人名条批量生成')
        root.geometry('560x640')
        root.resizable(True, True)

        # 名字来源
        ttk.Label(root, text='名字列表 (每行一个, 或从CSV导入)').pack(anchor='w', padx=10, pady=(10,2))
        btns = ttk.Frame(root); btns.pack(anchor='w', padx=10, pady=2)
        ttk.Button(btns, text='从CSV导入', command=self.load_csv).pack(side='left', padx=(0,5))
        ttk.Button(btns, text='从TXT导入', command=self.load_txt).pack(side='left', padx=(0,5))
        ttk.Button(btns, text='粘贴', command=self.paste_names).pack(side='left', padx=(0,5))
        ttk.Button(btns, text='清空', command=self.clear_names).pack(side='left')

        self.name_box = tk.Text(root, height=8, font=('Consolas', 10))
        self.name_box.pack(fill='x', padx=10, pady=5)

        # 输出目录
        ttk.Label(root, text='输出目录').pack(anchor='w', padx=10, pady=(8,2))
        row = ttk.Frame(root); row.pack(fill='x', padx=10)
        self.outdir_var = tk.StringVar(value=DEFAULT_OUTDIR)
        ttk.Entry(row, textvariable=self.outdir_var).pack(side='left', fill='x', expand=True, padx=(0,5))
        ttk.Button(row, text='浏览', command=self.pick_dir).pack(side='left')

        # 导出设置
        set_row = ttk.Frame(root); set_row.pack(fill='x', padx=10, pady=8)
        ttk.Label(set_row, text='分辨率').pack(side='left')
        self.res_var = tk.StringVar(value='不修改')
        ttk.Combobox(set_row, textvariable=self.res_var, values=['不修改','1080P','720P','4K'], width=8).pack(side='left', padx=(3,12))
        ttk.Label(set_row, text='帧率').pack(side='left')
        self.fps_var = tk.StringVar(value='不修改')
        ttk.Combobox(set_row, textvariable=self.fps_var, values=['不修改','25','30','60'], width=8).pack(side='left', padx=(3,0))

        # 控制
        ctl = ttk.Frame(root); ctl.pack(fill='x', padx=10, pady=6)
        self.start_btn = ttk.Button(ctl, text='▶ 开始批量', command=self.start)
        self.start_btn.pack(side='left')
        self.stop_btn = ttk.Button(ctl, text='■ 停止', command=self.stop, state='disabled')
        self.stop_btn.pack(side='left', padx=6)
        self.prog_var = tk.StringVar(value='就绪')
        ttk.Label(ctl, textvariable=self.prog_var).pack(side='left', padx=8)

        # 进度条
        self.pbar = ttk.Progressbar(root, mode='determinate')
        self.pbar.pack(fill='x', padx=10)

        # 日志
        ttk.Label(root, text='日志').pack(anchor='w', padx=10, pady=(8,2))
        self.log_box = tk.Text(root, height=14, font=('Consolas', 9), state='disabled')
        self.log_box.pack(fill='both', expand=True, padx=10, pady=(0,10))
        self._runner = None
        self._thread = None

    # ---- 名字输入
    def _is_english_name(self, s):
        """判断一个字符串是否像英文名(只含字母/空格/短横/点, 且有字母)"""
        s = s.strip()
        if not s: return False
        has_alpha = any(c.isalpha() for c in s)
        # 允许字母、空格、短横、点、撇; 排除含中文/数字/常见序号符号的
        for c in s:
            if c.isalpha():
                if not (ord('a') <= ord(c.lower()) <= ord('z')):
                    return False
            elif c not in ' .\'-':
                return False
        return has_alpha

    def _detect_english_col(self, header):
        """从表头找英文名列: 优先匹配常见英文名列名"""
        if not header: return None
        keywords = ['name', 'english', '英文', '英文名', 'firstname', 'lastname', 'cn']
        low = [str(h).strip().lower() for h in header]
        for kw in keywords:
            k = kw.lower()
            for i, h in enumerate(low):
                if k in h:
                    return i
        return None

    def load_csv(self):
        path = filedialog.askopenfilename(title='选择CSV', filetypes=[('CSV','*.csv'),('所有','*.*')])
        if not path: return
        try:
            import csv as _csv
            rows = []
            with open(path, encoding='utf-8-sig', newline='') as f:
                rows = list(_csv.reader(f))
            if not rows:
                self._log('CSV为空'); return
            # 尝试识别表头
            header = rows[0]
            col = self._detect_english_col(header)
            start = 1 if col is not None else 0
            # 若没识别到表头列名, 则用"整行中像英文名"的单元格
            names = []
            for row in rows[start:]:
                if col is not None and col < len(row):
                    cell = row[col].strip()
                    if self._is_english_name(cell):
                        names.append(cell)
                else:
                    for cell in row:
                        if self._is_english_name(cell):
                            names.append(cell)
                            break
            names = list(dict.fromkeys(names))  # 去重保序
            if not names:
                self._log('未能从CSV识别到英文名, 请检查列结构')
                return
            self._set_names(names)
            self._log(f'已从CSV导入{len(names)}个英文名(列:{col})')
        except Exception as ex:
            messagebox.showerror('导入失败', str(ex))

    def load_txt(self):
        path = filedialog.askopenfilename(title='选择TXT', filetypes=[('TXT','*.txt'),('所有','*.*')])
        if not path: return
        try:
            names = []
            with open(path, encoding='utf-8-sig') as f:
                for line in f:
                    s = line.strip()
                    if s and self._is_english_name(s):
                        names.append(s)
            names = list(dict.fromkeys(names))
            if not names:
                self._log('TXT中未识别到有效英文名'); return
            self._set_names(names)
            self._log(f'已从TXT导入{len(names)}个英文名')
        except Exception as ex:
            messagebox.showerror('导入失败', str(ex))

    def paste_names(self):
        try:
            txt = self.root.clipboard_get()
            names = [s.strip() for s in txt.splitlines() if s.strip()]
            self._set_names(names)
            self._log(f'已粘贴{len(names)}个名字')
        except Exception:
            messagebox.showinfo('提示', '剪贴板没有文本')

    def clear_names(self):
        self.name_box.delete('1.0', 'end')

    def _set_names(self, names):
        self.name_box.delete('1.0', 'end')
        for n in names: self.name_box.insert('end', n + '\n')

    def _get_names(self):
        txt = self.name_box.get('1.0', 'end')
        return [s.strip() for s in txt.splitlines() if s.strip()]

    def pick_dir(self):
        d = filedialog.askdirectory()
        if d: self.outdir_var.set(d)

    # ---- 控制
    def start(self):
        names = self._get_names()
        if not names:
            messagebox.showwarning('提示', '请先输入名字列表')
            return
        outdir = self.outdir_var.get().strip() or DEFAULT_OUTDIR
        self._log(f'输出目录: {outdir}')
        self._log(f'共{len(names)}个: {", ".join(names)}')
        self.start_btn.config(state='disabled'); self.stop_btn.config(state='normal')
        self.pbar.config(maximum=len(names), value=0)
        self.prog_var.set('启动中...')
        self._runner = BatchRunner(JianyingController(), outdir,
                                   log_cb=self._log,
                                   progress_cb=self._on_progress)
        self._thread = threading.Thread(target=self._run_worker, args=(names,), daemon=True)
        self._thread.start()

    def _run_worker(self, names):
        try:
            self._runner.run(names)
        except Exception as ex:
            self._log(f'致命错误: {ex}')
        finally:
            self.root.after(0, self._finish)

    def _finish(self):
        self.start_btn.config(state='normal'); self.stop_btn.config(state='disabled')
        self.prog_var.set('完成')

    def _on_progress(self, idx, total, name, status):
        self.pbar.config(value=idx)
        if status == 'running': self.prog_var.set(f'正在处理 {name} ({idx}/{total})')
        elif status == 'ok': self.prog_var.set(f'✓ {name} 成功 ({idx}/{total})')
        else: self.prog_var.set(f'✗ {name} 失败 ({idx}/{total})')

    def stop(self):
        if self._runner: self._runner.stop()
        self.prog_var.set('正在停止...')

    def _log(self, msg):
        def do():
            self.log_box.config(state='normal')
            self.log_box.insert('end', msg + '\n')
            self.log_box.see('end')
            self.log_box.config(state='disabled')
        try: self.root.after(0, do)
        except Exception: pass


def startup_check(root):
    """启动时提示用户：打开草稿并选中字幕条（前提准备）"""
    root.update()
    root.deiconify()
    msg = (
        "使用前请先在剪映中完成：\n\n"
        " 1. 打开你的草稿项目\n"
        " 2. 在时间轴上【选中字幕条】（点一下字幕即可）\n\n"
        "然后点击下方按钮继续。\n\n"
        "小提示：本工具会逐条替换你选中的字幕文字并导出。\n"
        "若没选中正确的字幕条，导出可能用的是旧文字。"
    )
    ok = messagebox.askokcancel("开始前请准备", msg)
    if not ok:
        return False
    # 再确认一次剪映是否可连
    try:
        JianyingController()
        return True
    except Exception as ex:
        messagebox.showerror("剪映未连接", f"无法连接剪映:\n{ex}\n\n请确认剪映专业版已打开。")
        return False


def main():
    root = tk.Tk()
    app = App(root)
    # 启动前提示：打开草稿并选中字幕条
    if not startup_check(root):
        root.destroy()
        return
    app._log("就绪：请在剪映中保持已选中的字幕条")
    root.mainloop()

if __name__ == '__main__':
    main()
