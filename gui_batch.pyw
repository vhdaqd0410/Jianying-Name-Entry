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
T_AFTER_EXPORT_KEY = 0.3      # Ctrl+M 后 (用户实测可直接接回车)
T_AFTER_ENTER = 0.5           # 回车确认导出后
T_BETWEEN_NAMES = 1.2         # 两个名字之间的间隔
T_CLICK_TEXTBOX = 0.25        # 点击文本框后
T_PASTE_WAIT = 0.35           # Ctrl+V 粘贴后
T_CLIPBOARD = 0.15            # 写剪贴板后
DEFAULT_OUTDIR = os.path.join(os.path.expanduser(r'~\Desktop'), '海外人名条')

# 草稿名历史记录文件 (存到项目目录, 随工具迁移)
HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.draft_history.json')
MAX_HISTORY = 20  # 最多保留的历史条数

# 设置文件 (剪映路径等)
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

# 剪映常见安装路径 (用于自动探测)
COMMON_JIANYING_PATHS = [
    os.path.join(os.environ.get('LOCALAPPDATA', ''), 'JianyingPro', 'Apps', 'JianyingPro.exe'),
    os.path.join(os.environ.get('LOCALAPPDATA', ''), 'JianyingPro', 'JianyingPro.exe'),
    os.path.join(os.environ.get('PROGRAMFILES', ''), 'JianyingPro', 'JianyingPro.exe'),
]

def detect_jianying_path():
    """自动探测剪映路径: 先找已运行的进程, 再查常见安装位置(标准库实现, 无额外依赖)"""
    # 1. 从运行中的进程找 (wmic 查询可执行路径)
    try:
        import subprocess as _sp
        out = _sp.check_output(
            'wmic process where "name=\'JianyingPro.exe\'" get ExecutablePath /value',
            shell=True, stderr=_sp.DEVNULL, timeout=8,
        ).decode('utf-8', 'ignore')
        for line in out.splitlines():
            if '=' in line:
                exe = line.split('=', 1)[1].strip()
                if exe and os.path.isfile(exe):
                    return exe
    except Exception:
        pass
    # 2. 查常见路径
    for p in COMMON_JIANYING_PATHS:
        if os.path.isfile(p):
            return p
    return ''

def connect_jianying_timeout(activate: bool = True, timeout: float = 5.0):
    """带硬超时的剪映连接。

    剪映未运行时 UIA 窗口查找可能无限挂起, 若在主线程直接调用会卡死界面。
    此函数把 JianyingController 放到后台线程执行, 主线程最多等 timeout 秒。

    返回:
        JianyingController 实例 (连接成功) 或 None (超时/连接失败)
    """
    holder = {}
    def worker():
        # 后台线程需自行初始化 COM, 否则 UIA 报 CoInitialize 错误
        try:
            ctypes.oledll.ole32.CoInitialize(None)
        except Exception:
            pass
        try:
            holder['ctrl'] = JianyingController(activate=activate)
        except Exception as exc:
            holder['err'] = exc
    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        # 超时: 后台线程仍在尝试(daemon, 不影响退出), 视为未连接
        return None
    if 'ctrl' in holder:
        return holder['ctrl']
    return None

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

    def _wait_file_stable(self, path, timeout=15):
        """等文件写入完成(大小稳定): 连续两次读取大小一致即视为写完。
        避免剪映还在写/占用时 move 导致等待或失败。"""
        last_size = -1
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                cur_size = os.path.getsize(path)
            except OSError:
                return  # 文件暂时不可读, 让后续move自己处理
            if cur_size == last_size:
                return  # 大小已稳定, 视为写完
            last_size = cur_size
            time.sleep(0.3)
        # 超时也返回, 让move尝试
        return

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

        # 等文件写入完成(大小稳定)后再移动, 避免剪映还在写导致等待
        self._wait_file_stable(src, timeout=15)

        # 移动归置 (文件名与名字一致)
        target = os.path.join(self.outdir, name + '.mp4')
        if os.path.exists(target):
            target = os.path.join(self.outdir, name + '(1).mp4')
        try:
            os.replace(src, target)  # 同盘原子操作, 比shutil.move更快更稳
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
        root.geometry('560x680')
        root.resizable(True, True)

        # ---- 链接状态指示器
        link_row = ttk.Frame(root); link_row.pack(fill='x', padx=10, pady=(8,0))
        ttk.Label(link_row, text='剪映连接状态:').pack(side='left')
        self.link_canvas = tk.Canvas(link_row, width=18, height=18, highlightthickness=0)
        self.link_canvas.pack(side='left', padx=(6,4))
        self.link_dot = self.link_canvas.create_oval(2, 2, 16, 16, fill='#cccccc', outline='')
        self.link_status_var = tk.StringVar(value='检测中...')
        ttk.Label(link_row, textvariable=self.link_status_var, font=('', 10, 'bold')).pack(side='left')

        # 剪映路径 + 启动
        ttk.Label(root, text='剪映路径 (用于启动剪映; 不填则自动探测)').pack(anchor='w', padx=10, pady=(10,2))
        jy_row = ttk.Frame(root); jy_row.pack(fill='x', padx=10)
        self.jy_path_var = tk.StringVar()
        ttk.Entry(jy_row, textvariable=self.jy_path_var).pack(side='left', fill='x', expand=True, padx=(0,5))
        ttk.Button(jy_row, text='浏览', command=self.pick_jianying).pack(side='left', padx=(0,3))
        ttk.Button(jy_row, text='自动探测', command=self.auto_detect_jianying).pack(side='left', padx=(0,3))
        ttk.Button(jy_row, text='启动剪映', command=self.launch_jianying).pack(side='left', padx=(0,6))
        ttk.Button(jy_row, text='帮助', command=self.show_help).pack(side='left')

        # 草稿名自动打开 (下拉框带历史记忆)
        ttk.Label(root, text='草稿名 (留空则跳过, 用于自动打开草稿并选中字幕条)').pack(anchor='w', padx=10, pady=(10,2))
        drow = ttk.Frame(root); drow.pack(fill='x', padx=10)
        self.draft_var = tk.StringVar()
        self.draft_history = self._load_history()
        self.draft_combo = ttk.Combobox(drow, textvariable=self.draft_var, values=self.draft_history, width=20)
        self.draft_combo.pack(side='left', fill='x', expand=True, padx=(0,5))
        self.draft_combo.bind('<Return>', lambda e: self.open_draft())
        ttk.Button(drow, text='打开草稿并选字幕', command=self.open_draft).pack(side='left')
        # 勾选后: 打开草稿成功即自动开始批量
        self.auto_run_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(root, text='打开草稿并选中后自动开始批量任务', variable=self.auto_run_var).pack(anchor='w', padx=12, pady=(3,0))

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
        # 完成后自动打开成品目录
        self.open_dir_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(ctl, text='完成后打开目录', variable=self.open_dir_var).pack(side='left', padx=6)
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

        # 加载已保存的剪映路径
        saved = self._load_setting('jianying_path')
        if saved:
            self.jy_path_var.set(saved)

        # 启动链接状态轮询
        self._polling = False
        self._start_link_polling()

    # ---- 设置持久化
    def _load_setting(self, key):
        """从设置文件读取某个键的值"""
        try:
            import json
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data.get(key, '')
        except Exception:
            pass
        return ''

    def _save_setting(self, key, value):
        """把某个键的值写入设置文件"""
        try:
            import json
            data = {}
            if os.path.exists(SETTINGS_FILE):
                try:
                    with open(SETTINGS_FILE, encoding='utf-8') as f:
                        data = json.load(f)
                except Exception:
                    data = {}
            if not isinstance(data, dict):
                data = {}
            data[key] = value
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ---- 剪映启动
    def pick_jianying(self):
        """手动选择剪映exe"""
        path = filedialog.askopenfilename(title='选择剪映程序 JianyingPro.exe', filetypes=[('剪映程序','JianyingPro.exe'),('可执行文件','*.exe'),('所有','*.*')])
        if path:
            self.jy_path_var.set(path)
            self._save_setting('jianying_path', path)
            self._log(f'已设置剪映路径: {path}')

    def auto_detect_jianying(self):
        """自动探测剪映路径(优先已运行进程)"""
        path = detect_jianying_path()
        if path:
            self.jy_path_var.set(path)
            self._save_setting('jianying_path', path)
            self._log(f'已自动探测到剪映: {path}')
        else:
            self._log('未探测到剪映, 请手动浏览选择路径')

    def launch_jianying(self):
        """启动剪映: 若剪映已在前台则提示, 否则用配置路径启动。
        全部在后台线程执行, 避免UIA检测阻塞主线程导致界面卡死。"""
        path = self.jy_path_var.get().strip()
        if not path:
            # 无路径则自动探测一次
            path = detect_jianying_path()
            if path:
                self.jy_path_var.set(path)
                self._save_setting('jianying_path', path)
        if not path or not os.path.isfile(path):
            messagebox.showwarning('提示', '请先设置剪映路径 (浏览选择 JianyingPro.exe)')
            return
        self._log(f'检查/启动剪映: {path}')
        self.prog_var.set('正在检查剪映...')
        self._set_link_status('checking', '检查中...')
        self._refresh_link_now()
        threading.Thread(target=self._launch_jianying_worker, args=(path,), daemon=True).start()

    def _launch_jianying_worker(self, path):
        """后台: 检测剪映是否在前台, 不在则启动, 再确认连接(全部带超时)"""
        # 检测剪映是否已在前台(带超时, 剪映未运行时UIA会挂起)
        ctrl = connect_jianying_timeout(activate=False, timeout=4)
        if ctrl is not None:
            # 能连到窗口说明已在前台, 不重复启动
            self.root.after(0, lambda: messagebox.showinfo('剪映', '剪映已在运行并显示在前台'))
            self.root.after(0, lambda: self.prog_var.set('剪映已在前台'))
            return
        # 不在前台(超时或失败), 启动剪映
        try:
            self.root.after(0, lambda: self._log('剪映未在前台, 正在启动...'))
            self.root.after(0, lambda: self.prog_var.set('正在启动剪映...'))
            os.startfile(path)
        except Exception as ex:
            self.root.after(0, lambda: self._log(f'启动剪映失败: {ex}'))
            return
        # 等剪映起来并连接(带超时, 避免挂起)
        for _ in range(20):
            time.sleep(0.5)
            ctrl = connect_jianying_timeout(activate=False, timeout=3)
            if ctrl is not None:
                self.root.after(0, lambda: self._log('✔ 剪映已启动并连接成功'))
                self.root.after(0, lambda: self.prog_var.set('剪映已启动'))
                return
        self.root.after(0, lambda: self._log('剪映启动中, 若未出现请稍候或手动打开'))

    def show_help(self):
        """显示使用帮助"""
        help_text = (
            "海外人名条批量生成 · 使用说明\n\n"
            "1. 剪映路径\n"
            "   设置 JianyingPro.exe 位置; 点'自动探测'自动找, 或'浏览'手动选。\n"
            "   点'启动剪映'可拉起剪映(若未在前台)。\n\n"
            "2. 打开草稿并选字幕\n"
            "   在'草稿名'下拉框输入或选草稿名, 点'打开草稿并选字幕'。\n"
            "   程序自动打开该草稿并点选时间轴上的字幕条。\n"
            "   草稿名会被记住, 下次可直接下拉选择。\n\n"
            "3. 名字列表\n"
            "   每行一个名字(英文名)。可'从CSV导入''从TXT导入'或直接'粘贴'。\n\n"
            "4. 开始批量\n"
            "   填好名字后点'▶ 开始批量', 逐条替换字幕文字并导出为 mp4。\n"
            "   文件按名字命名, 存到'输出目录'。\n\n"
            "5. 自动执行\n"
            "   勾选'打开草稿并选中后自动开始批量任务', 打开草稿成功即自动跑。\n\n"
            "6. 完成后打开目录\n"
            "   勾选后, 批量完整跑完自动弹出输出文件夹。\n\n"
            "小提示\n"
            "   - 请确保剪映专业版已打开、字幕条已就绪\n"
            "   - 支持先小批量试跑确认效果再全量"
        )
        messagebox.showinfo('帮助', help_text)

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
        self._start_run(names, self.outdir_var.get().strip() or DEFAULT_OUTDIR)

    def _start_run(self, names, outdir):
        """启动批量任务(供按钮与自动执行共用)。连接剪映放后台线程, 避免卡界面"""
        if not names:
            return
        self._log(f'输出目录: {outdir}')
        self._log(f'共{len(names)}个: {", ".join(names)}')
        self.start_btn.config(state='disabled'); self.stop_btn.config(state='normal')
        self.pbar.config(maximum=len(names), value=0)
        self.prog_var.set('启动中...')
        self._outdir = outdir
        self._thread = threading.Thread(target=self._run_worker, args=(names,), daemon=True)
        self._thread.start()

    def _run_worker(self, names):
        try:
            # 后台线程连接剪映(带超时, 避免UIA挂起)
            ctrl = connect_jianying_timeout(activate=True, timeout=6)
            if ctrl is None:
                self._log('✘ 未连接剪映(超时)。请用顶部"启动剪映"按钮启动后再试。')
                self.root.after(0, lambda: self._finish(None, names))
                return
            self._runner = BatchRunner(ctrl, self._outdir,
                                       log_cb=self._log,
                                       progress_cb=self._on_progress)
            results = self._runner.run(names)
        except Exception as ex:
            self._log(f'致命错误: {ex}')
            results = None
        finally:
            self.root.after(0, lambda: self._finish(results, names))

    def _finish(self, results, names):
        self.start_btn.config(state='normal'); self.stop_btn.config(state='disabled')
        # 判断是否完整跑完(非手动停止): 结果数==名字数
        completed = bool(results) and len(results) == len(names)
        self.prog_var.set('完成' if completed else '已停止')
        # 勾选'完成后打开成品目录'且完整跑完时, 打开输出目录
        if completed and self.open_dir_var.get():
            outdir = self.outdir_var.get().strip() or DEFAULT_OUTDIR
            if os.path.isdir(outdir):
                try:
                    os.startfile(outdir)
                    self._log(f'📁 已打开成品目录: {outdir}')
                except Exception as ex:
                    self._log(f'打开目录失败: {ex}')

    def _on_progress(self, idx, total, name, status):
        self.pbar.config(value=idx)
        if status == 'running': self.prog_var.set(f'正在处理 {name} ({idx}/{total})')
        elif status == 'ok': self.prog_var.set(f'✓ {name} 成功 ({idx}/{total})')
        else: self.prog_var.set(f'✗ {name} 失败 ({idx}/{total})')

    def stop(self):
        if self._runner: self._runner.stop()
        self.prog_var.set('正在停止...')

    def _load_history(self):
        """从配置文件加载草稿名历史"""
        try:
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE, encoding='utf-8') as f:
                    import json
                    data = json.load(f)
                if isinstance(data, list):
                    return [str(x) for x in data if str(x).strip()][:MAX_HISTORY]
        except Exception:
            pass
        return []

    def _save_history(self):
        """把当前历史写回配置文件"""
        try:
            import json
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.draft_history, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _remember_draft(self, draft):
        """记住草稿名: 置顶并去重, 刷新下拉框, 持久化"""
        draft = draft.strip()
        if not draft:
            return
        if draft in self.draft_history:
            self.draft_history.remove(draft)
        self.draft_history.insert(0, draft)
        self.draft_history = self.draft_history[:MAX_HISTORY]
        self.draft_combo['values'] = self.draft_history
        self._save_history()

    def open_draft(self):
        draft = self.draft_var.get().strip()
        if not draft:
            messagebox.showwarning('提示', '请先输入草稿名')
            return
        self._remember_draft(draft)
        auto_run = self.auto_run_var.get()
        self._log(f'开始自动打开草稿: {draft}' + ('(完成后自动开始批量)' if auto_run else ''))
        self.prog_var.set('正在打开草稿...')
        self._refresh_link_now()
        # 后台线程执行, 避免阻塞UI
        threading.Thread(target=self._open_draft_worker, args=(draft, auto_run), daemon=True).start()

    def _open_draft_worker(self, draft, auto_run=False):
        try:
            # 选字幕是只读定位场景, 不激活窗口, 加快响应
            ctrl = JianyingController(activate=False)
            ok = ctrl.open_draft_and_select_subtitle(draft)
            if ok:
                self._log(f'✔ 已打开草稿[{draft}]并选中字幕条')
                self.prog_var.set('草稿已打开, 字幕条已选中')
                # 若勾选了自动执行, 且名字列表非空, 直接开始批量
                if auto_run:
                    names = self._get_names()
                    if not names:
                        self._log('⚠ 未检测到名字列表, 自动执行取消 (请先填写名字)')
                        self.prog_var.set('自动执行取消: 无名字')
                    else:
                        self._log('→ 检测到自动执行勾选, 开始批量任务...')
                        self._start_run(names, self.outdir_var.get().strip() or DEFAULT_OUTDIR)
            else:
                self._log(f'✘ 打开草稿[{draft}]或选字幕条失败')
                self.prog_var.set('打开草稿失败')
        except Exception as ex:
            self._log(f'✘ 打开草稿异常: {ex}')
            self.prog_var.set('打开草稿异常')
        finally:
            self.root.after(0, lambda: self.prog_var.set(self.prog_var.get()))

    # ---- 链接状态指示器
    LINK_POLL_MS = 3000      # 轮询间隔(毫秒)
    LINK_CHECK_TIMEOUT = 3   # 每次检测的超时(秒)

    def _set_link_status(self, state, text):
        """更新状态指示灯: state ∈ connected/disconnected/checking"""
        color = {'connected': '#2ecc71', 'disconnected': '#e74c3c', 'checking': '#f1c40f'}
        try:
            self.link_canvas.itemconfig(self.link_dot, fill=color.get(state, '#cccccc'))
            self.link_status_var.set(text)
        except Exception:
            pass

    def _start_link_polling(self):
        """启动链接状态轮询(定时, 非阻塞)"""
        self._polling = True
        self._link_checking = False
        self.root.after(300, self._poll_link_status)

    def _refresh_link_now(self):
        """立即触发一次状态检测(供操作后即时反馈)"""
        if getattr(self, '_polling', True):
            self.root.after(150, self._poll_link_status)

    def _poll_link_status(self):
        """后台检测剪映连接状态, 完成后调度下一次轮询"""
        if not getattr(self, '_polling', True):
            return
        # 避免上一次检测还在进行时重复起线程
        if getattr(self, '_link_checking', False):
            self.root.after(self.LINK_POLL_MS, self._poll_link_status)
            return
        self._link_checking = True
        timeout = self.LINK_CHECK_TIMEOUT
        holder = {}
        def worker():
            try:
                ctypes.oledll.ole32.CoInitialize(None)
            except Exception:
                pass
            try:
                JianyingController(activate=False)
                holder['ok'] = True
            except Exception:
                holder['ok'] = False
        threading.Thread(target=worker, daemon=True).start()
        # 主线程不等待, 用定时器在超时后收结果
        def _check_done():
            self._link_checking = False
            if holder.get('ok'):
                self._set_link_status('connected', '已连接')
            else:
                self._set_link_status('disconnected', '未连接')
            if getattr(self, '_polling', True):
                self.root.after(self.LINK_POLL_MS, self._poll_link_status)
        self.root.after(int(timeout * 1000) + 200, _check_done)

    def _log(self, msg):
        def do():
            self.log_box.config(state='normal')
            self.log_box.insert('end', msg + '\n')
            self.log_box.see('end')
            self.log_box.config(state='disabled')
        try: self.root.after(0, do)
        except Exception: pass


def startup_check(root, app):
    """启动时检测剪映是否可连(带超时, 不阻塞界面)。

    剪映未运行时 UIA 查找可能挂起, 故用后台线程+超时检测,
    无论结果如何都放行进入主界面, 由用户用顶部'启动剪映'按钮控制。"""
    root.update()
    root.deiconify()
    ctrl = connect_jianying_timeout(activate=True, timeout=4)
    if ctrl is not None:
        app._log('✔ 剪映已连接, 可以开始使用')
        return True
    # 剪映未连接(超时或失败): 不阻塞, 提示用户自行启动
    app._log('⚠ 未检测到剪映(或连接超时)。请用顶部\'启动剪映\'按钮启动, 或手动打开剪映。')
    app.prog_var.set('剪映未连接')
    return True


def main():
    root = tk.Tk()
    app = App(root)
    # 启动检测(非阻塞): 检测剪映是否可连
    startup_check(root, app)
    app._log("就绪：请在剪映中保持已选中的字幕条")
    root.mainloop()

if __name__ == '__main__':
    main()
