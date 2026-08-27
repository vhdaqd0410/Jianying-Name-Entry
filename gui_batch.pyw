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

def resource_path(rel):
    """打包(exe)与开发(python)两种运行方式下都能定位到资源文件"""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


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

# 项目模板文件 (预设: 项目名/输出目录/勾选项组合)
TEMPLATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates.json')

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
    def __init__(self, ctrl, outdir, resolution=None, framerate=None, log_cb=None, progress_cb=None, dry_run=False):
        self.ctrl = ctrl
        self.outdir = outdir
        self.resolution = resolution
        self.framerate = framerate
        self.dry_run = dry_run
        self.log_cb = log_cb or (lambda *a: None)
        self.progress_cb = progress_cb or (lambda *a: None)
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._pause.set()   # 默认不暂停
        self._per_name_time = {}   # 每个名字的耗时, 供 run_log 使用
        self._outdir_actual = outdir  # 实际落盘目录(含归档子目录), run 后更新

    def stop(self):
        self._stop.set()
        self._pause.set()  # 解除暂停, 让线程能退出

    def pause(self):
        self._pause.clear()

    def resume(self):
        self._pause.set()

    @property
    def is_paused(self):
        return not self._pause.is_set()

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
        # 干跑模式: 不操作剪映, 只模拟预览
        if self.dry_run:
            return self._process_one_dry(name)
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
            # 同盘用原子replace更快; 跨盘(如桌面C盘→O盘)用shutil.move自动copy+delete
            if os.path.splitdrive(src)[0].lower() == os.path.splitdrive(target)[0].lower():
                os.replace(src, target)
            else:
                shutil.move(src, target)
            self._log(f'  -> {target}')
            before_set.discard(src)
            return True
        except Exception as ex:
            self._log(f'  移动失败:{ex}')
            before_set.add(src)
            return False

    # ---- 干跑预览: 不操作剪映, 只模拟预览每个名字将如何处理
    def _process_one_dry(self, name):
        issues = []
        # 输出路径检查
        target = os.path.join(self._outdir_actual, name + '.mp4')
        if os.path.exists(target):
            issues.append(f'⚠ 已存在同名文件, 将另存为 {name}(1).mp4')
        # 输出目录检查
        if not os.path.isdir(self._outdir_actual):
            issues.append('⚠ 输出目录不存在, 将自动创建')
        if issues:
            self._log('  ' + '; '.join(issues))
        self._log(f'  [预览] 将导出 → {target}')
        return True

    # ---- 批量入口
    def run(self, names, project=''):
        # 若指定了项目名, 输出目录下建 项目名_日期/ 子目录, 实现「项目+时间」归档
        outdir = self.outdir
        archive_sub = ''
        if project:
            safe = ''.join(c for c in project if c not in r'\/:*?"<>|').strip()
            if safe:
                date = time.strftime('%Y%m%d')
                archive_sub = f'{safe}_{date}'
                outdir = os.path.join(self.outdir, archive_sub)
        os.makedirs(outdir, exist_ok=True)
        self._outdir_actual = outdir
        before_set = set(self.desktop_exports())
        results = {}
        run_start = time.time()
        for idx, name in enumerate(names, 1):
            if self._stop.is_set():
                self._log('\n(已停止)')
                break
            self._pause.wait()  # 若暂停则等待(解除暂停/停止才继续)
            if self._stop.is_set():
                self._log('\n(已停止)')
                break
            self.progress_cb(idx, len(names), name, 'running')
            t0 = time.time()
            ok = self.process_one(name, before_set)
            results[name] = ok
            self._per_name_time[name] = time.time() - t0
            self.progress_cb(idx, len(names), name, 'ok' if ok else 'fail')
            time.sleep(T_BETWEEN_NAMES)

        ok_names = [n for n, v in results.items() if v]
        fail_names = [n for n, v in results.items() if not v]
        self._log(f'\n===== 结果: 成功{len(ok_names)} 失败{len(fail_names)} =====')
        if fail_names:
            self._log('失败: ' + ', '.join(fail_names))
        # 写 run_log.csv (成功/失败、耗时、时间戳)。干跑预览不写正式日志。
        if not self.dry_run:
            try:
                self._write_run_log(outdir, names, results, run_start)
            except Exception as ex:
                self._log(f'写run_log失败: {ex}')
        else:
            ok_names = [n for n, v in results.items() if v]
            self._log(f'\n[预览结束] 共{len(names)}个, 均可正常导出 (可开始正式批量)')
        return results

    def _write_run_log(self, outdir, names, results, run_start):
        """把本次批量结果写入 run_log.csv (成功/失败、耗时、时间戳)
        同一目录多次跑 append 到同一文件, 用时间戳区分。"""
        import csv as _csv
        log_path = os.path.join(outdir, 'run_log.csv')
        is_new = not os.path.exists(log_path)
        total_time = time.time() - run_start
        rows = []
        for name in names:
            ok = results.get(name, False)
            rows.append({
                '时间戳': time.strftime('%Y-%m-%d %H:%M:%S'),
                '名字': name,
                '结果': '成功' if ok else '失败',
                '耗时(秒)': round(self._per_name_time.get(name, 0), 1),
            })
        with open(log_path, 'a', newline='', encoding='utf-8-sig') as f:
            w = _csv.DictWriter(f, fieldnames=['时间戳', '名字', '结果', '耗时(秒)'])
            if is_new:
                w.writeheader()
            w.writerows(rows)
        self._log(f'📄 已写入日志: {log_path}  (本次{len(rows)}条, 总耗时{round(total_time,1)}s)')


# ------------------------------------------------------------------ 界面
class App:
    def __init__(self, root):
        self.root = root
        root.title('海外人名条批量生成')
        # 窗口图标(仅界面版; exe自带图标)
        try:
            root.iconbitmap(resource_path('icon.ico'))
        except Exception:
            pass
        root.geometry('960x760')
        root.minsize(820, 620)
        root.resizable(True, True)
        self._setup_theme(root)

    def _setup_theme(self, root):
        """统一界面主题与配色"""
        style = ttk.Style(root)
        try:
            style.theme_use('clam')
        except Exception:
            pass
        # 基础配色
        bg = '#f5f7fa'
        card_bg = '#ffffff'
        accent = '#2b5be6'      # 主色(蓝)
        ok_green = '#2ecc71'    # 成功/进度绿
        err_red = '#e74c3c'     # 停止/错误红
        text = '#1f2328'
        root.configure(bg=bg)
        try:
            style.configure('.', background=bg, foreground=text, font=('Microsoft YaHei', 9))
            style.configure('TLabel', background=bg, foreground=text)
            style.configure('Card.TLabelframe', background=card_bg)
            style.configure('Card.TLabelframe.Label', background=card_bg, foreground='#111111',
                            font=('Microsoft YaHei', 10, 'bold'))
            style.configure('TButton', padding=(10, 5), background=bg)
            style.map('TButton',
                      background=[('active', '#e9edf2'), ('pressed', '#dde3ea')])
            # 开始按钮(绿)
            style.configure('Start.TButton', background=ok_green, foreground='white',
                            font=('Microsoft YaHei', 10, 'bold'), padding=(14, 7))
            style.map('Start.TButton',
                      background=[('active', '#27ae60'), ('pressed', '#219a52'), ('disabled', '#b8c7bf')])
            # 停止按钮(红)
            style.configure('Stop.TButton', background=err_red, foreground='white',
                            font=('Microsoft YaHei', 10, 'bold'), padding=(14, 7))
            style.map('Stop.TButton',
                      background=[('active', '#c0392b'), ('pressed', '#b03a2e'), ('disabled', '#d8bfbc')])
            # 重跑按钮(橙)
            style.configure('Rerun.TButton', background='#f39c12', foreground='white',
                            font=('Microsoft YaHei', 10, 'bold'), padding=(14, 7))
            style.map('Rerun.TButton',
                      background=[('active', '#e67e22'), ('pressed', '#d35400'), ('disabled', '#e8d5b8')])
            # 暂停按钮(蓝灰)
            style.configure('Pause.TButton', background='#8e8ea0', foreground='white',
                            font=('Microsoft YaHei', 10, 'bold'), padding=(14, 7))
            style.map('Pause.TButton',
                      background=[('active', '#6e6e80'), ('pressed', '#5a5a6a'), ('disabled', '#c6c6d0')])
            # 干跑预览按钮(青)
            style.configure('Preview.TButton', background='#16a085', foreground='white',
                            font=('Microsoft YaHei', 10, 'bold'), padding=(14, 7))
            style.map('Preview.TButton',
                      background=[('active', '#138d75'), ('pressed', '#0e6e5c'), ('disabled', '#b5d8d0')])
            # 进度条
            style.configure('Highlight.Horizontal.TProgressbar',
                            troughcolor='#e0e0e0', background=ok_green, thickness=22)
        except Exception:
            pass

        # ============ 主容器: 左操作区 + 右日志区 ============
        main = ttk.Frame(root); main.pack(fill='both', expand=True, padx=12, pady=(8,10))
        left = ttk.Frame(main); left.pack(side='left', fill='both', expand=True)
        right = ttk.Frame(main); right.pack(side='right', fill='y', padx=(10,0))

        # ============ 卡片① 剪映连接 ============
        card1 = ttk.Labelframe(left, text='剪映连接', style='Card.TLabelframe')
        card1.pack(fill='x', padx=0, pady=(0,0))

        # 链接状态 + 启动按钮
        link_row = ttk.Frame(card1); link_row.pack(fill='x', padx=12, pady=(8,3))
        ttk.Label(link_row, text='状态').pack(side='left')
        self.link_canvas = tk.Canvas(link_row, width=18, height=18, bg='#ffffff', highlightthickness=0)
        self.link_canvas.pack(side='left', padx=(6,4))
        self.link_dot = self.link_canvas.create_oval(2, 2, 16, 16, fill='#cccccc', outline='')
        self.link_status_var = tk.StringVar(value='检测中...')
        ttk.Label(link_row, textvariable=self.link_status_var,
                  font=('Microsoft YaHei', 10, 'bold')).pack(side='left')
        # 右侧放帮助
        ttk.Button(link_row, text='帮助', command=self.show_help).pack(side='right')

        # 剪映路径
        ttk.Label(card1, text='剪映程序路径 (用于启动剪映; 不填则自动探测)').pack(anchor='w', padx=12, pady=(3,2))
        jy_row = ttk.Frame(card1); jy_row.pack(fill='x', padx=12, pady=(0,3))
        self.jy_path_var = tk.StringVar()
        ttk.Entry(jy_row, textvariable=self.jy_path_var).pack(side='left', fill='x', expand=True, padx=(0,5))
        ttk.Button(jy_row, text='浏览', command=self.pick_jianying).pack(side='left', padx=(0,3))
        ttk.Button(jy_row, text='自动探测', command=self.auto_detect_jianying).pack(side='left', padx=(0,3))
        ttk.Button(jy_row, text='启动剪映', command=self.launch_jianying).pack(side='left')

        # 草稿名自动打开
        ttk.Label(card1, text='草稿名 (留空跳过; 用于自动打开草稿并选中字幕条)').pack(anchor='w', padx=12, pady=(3,2))
        drow = ttk.Frame(card1); drow.pack(fill='x', padx=12, pady=(0,3))
        self.draft_var = tk.StringVar()
        self.draft_history = self._load_history()
        self.draft_combo = ttk.Combobox(drow, textvariable=self.draft_var, values=self.draft_history, width=20)
        self.draft_combo.pack(side='left', fill='x', expand=True, padx=(0,5))
        self.draft_combo.bind('<Return>', lambda e: self.open_draft())
        ttk.Button(drow, text='打开草稿并选字幕', command=self.open_draft).pack(side='left')
        # 勾选后: 打开草稿成功即自动开始批量
        self.auto_run_var = tk.BooleanVar(value=False)
        tk.Checkbutton(card1, text='打开草稿并选中后自动开始批量任务', variable=self.auto_run_var,
                       bg='#ffffff', activebackground='#ffffff', bd=0, highlightthickness=0,
                       font=('Microsoft YaHei', 9)).pack(anchor='w', padx=12, pady=(0,8))

        # ============ 卡片② 名字列表 ============
        card2 = ttk.Labelframe(left, text='名字列表', style='Card.TLabelframe')
        card2.pack(fill='x', padx=0, pady=(8,0))
        btns = ttk.Frame(card2); btns.pack(anchor='w', padx=12, pady=(10,2))
        ttk.Button(btns, text='从CSV导入', command=self.load_csv).pack(side='left', padx=(0,5))
        ttk.Button(btns, text='从TXT导入', command=self.load_txt).pack(side='left', padx=(0,5))
        ttk.Button(btns, text='粘贴', command=self.paste_names).pack(side='left', padx=(0,5))
        ttk.Button(btns, text='清空', command=self.clear_names).pack(side='left')
        ttk.Label(btns, text='每行一个名字', foreground='#888888').pack(side='right')

        self.name_box = tk.Text(card2, height=5, font=('Consolas', 10), bg='#ffffff', relief='solid', bd=1)
        self.name_box.pack(fill='x', padx=12, pady=(0,10))
        # 高亮样式: 运行中(黄底黑字) / 成功(浅绿) / 失败(浅红)
        self.name_box.tag_configure('hl_run', background='#fff3cd', foreground='#856404')
        self.name_box.tag_configure('hl_ok', background='#d4edda', foreground='#155724')
        self.name_box.tag_configure('hl_fail', background='#f8d7da', foreground='#721c24')

        # ============ 卡片③ 输出与导出 ============
        card3 = ttk.Labelframe(left, text='输出与导出', style='Card.TLabelframe')
        card3.pack(fill='x', padx=0, pady=(8,0))

        # 输出目录
        ttk.Label(card3, text='输出目录 (成片保存位置)').pack(anchor='w', padx=12, pady=(8,2))
        row = ttk.Frame(card3); row.pack(fill='x', padx=12)
        self.outdir_var = tk.StringVar(value=DEFAULT_OUTDIR)
        ttk.Entry(row, textvariable=self.outdir_var).pack(side='left', fill='x', expand=True, padx=(0,5))
        ttk.Button(row, text='浏览', command=self.pick_dir).pack(side='left')

        # 项目名 (用于「项目+时间」自动归档)
        ttk.Label(card3, text='项目名 (选填; 填了则自动归档到 输出目录/项目名_日期/)').pack(anchor='w', padx=12, pady=(6,2))
        proj_row = ttk.Frame(card3); proj_row.pack(fill='x', padx=12)
        self.project_var = tk.StringVar()
        ttk.Entry(proj_row, textvariable=self.project_var).pack(side='left', fill='x', expand=True, padx=(0,5))
        ttk.Label(proj_row, text='如: 项目A_2026', foreground='#888888').pack(side='left')

        # 导出设置
        set_row = ttk.Frame(card3); set_row.pack(fill='x', padx=12, pady=6)
        ttk.Label(set_row, text='分辨率').pack(side='left')
        self.res_var = tk.StringVar(value='不修改')
        ttk.Combobox(set_row, textvariable=self.res_var, values=['不修改','1080P','720P','4K'], width=8).pack(side='left', padx=(3,14))
        ttk.Label(set_row, text='帧率').pack(side='left')
        self.fps_var = tk.StringVar(value='不修改')
        ttk.Combobox(set_row, textvariable=self.fps_var, values=['不修改','25','30','60'], width=8).pack(side='left', padx=(3,0))
        # 完成后自动打开成品目录
        self.open_dir_var = tk.BooleanVar(value=True)
        tk.Checkbutton(set_row, text='完成后打开目录', variable=self.open_dir_var,
                       bg='#ffffff', activebackground='#ffffff', bd=0, highlightthickness=0,
                       font=('Microsoft YaHei', 9)).pack(side='left', padx=14)

        # 配置备份/恢复 (第二版: 配置中心化)
        cfg_row = ttk.Frame(card3); cfg_row.pack(fill='x', padx=12, pady=(0,4))
        ttk.Label(cfg_row, text='配置').pack(side='left')
        ttk.Button(cfg_row, text='💾 备份配置', command=self.backup_config).pack(side='left', padx=(6,3))
        ttk.Button(cfg_row, text='📂 恢复配置', command=self.restore_config).pack(side='left', padx=(0,3))
        ttk.Label(cfg_row, text='(导出/导入单个 .json, 换机迁移用)', foreground='#888888').pack(side='left', padx=4)

        # 项目模板 (第二版: 预设保存/加载)
        tpl_row = ttk.Frame(card3); tpl_row.pack(fill='x', padx=12, pady=(0,6))
        ttk.Label(tpl_row, text='项目模板').pack(side='left')
        self.tpl_combo = ttk.Combobox(tpl_row, width=16, state='readonly')
        self.tpl_combo.pack(side='left', padx=(6,3))
        self.tpl_combo.bind('<<ComboboxSelected>>', self._tpl_selected)
        ttk.Button(tpl_row, text='💾 存为模板', command=self.save_template).pack(side='left', padx=(0,3))
        ttk.Button(tpl_row, text='🗑 删除模板', command=self.delete_template).pack(side='left')

        # ============ 控制按钮 ============
        ctl = ttk.Frame(left); ctl.pack(fill='x', padx=0, pady=(8,0))
        self.start_btn = ttk.Button(ctl, text='▶ 开始批量', command=self.start, style='Start.TButton')
        self.start_btn.pack(side='left')
        self.preview_btn = ttk.Button(ctl, text='👁 干跑预览', command=self.preview, style='Preview.TButton')
        self.preview_btn.pack(side='left', padx=(0,8))
        self.stop_btn = ttk.Button(ctl, text='■ 停止', command=self.stop, state='disabled', style='Stop.TButton')
        self.stop_btn.pack(side='left', padx=8)
        # 暂停/继续按钮 (运行中可用; 或按 Ctrl+P / 空格)
        self.pause_btn = ttk.Button(ctl, text='⏸ 暂停', command=self.toggle_pause,
                                    state='disabled', style='Pause.TButton')
        self.pause_btn.pack(side='left', padx=(0,8))
        # 失败一键重跑按钮 (跑完有失败时自动点亮)
        self.rerun_btn = ttk.Button(ctl, text='↻ 重跑失败', command=self.rerun_failed,
                                    state='disabled', style='Rerun.TButton')
        self.rerun_btn.pack(side='left', padx=(0,8))
        self.prog_var = tk.StringVar(value='就绪')
        ttk.Label(ctl, textvariable=self.prog_var, font=('Microsoft YaHei', 9)).pack(side='left', padx=10)

        # ============ 进度条 ============
        pbar_wrap = ttk.Frame(left); pbar_wrap.pack(side='bottom', fill='x', padx=0, pady=(8,0))
        self.pbar = ttk.Progressbar(pbar_wrap, mode='determinate',
                                    style='Highlight.Horizontal.TProgressbar')
        self.pbar.pack(fill='x')
        # 进度文字 (百分比 + 计数)
        self.progress_text_var = tk.StringVar(value='就绪')
        ttk.Label(pbar_wrap, textvariable=self.progress_text_var,
                  font=('Microsoft YaHei', 11, 'bold')).pack(anchor='w', padx=2, pady=(4,0))
        # 时间显示 (已用 + 预计剩余)
        self.time_var = tk.StringVar(value='')
        ttk.Label(pbar_wrap, textvariable=self.time_var,
                  font=('Microsoft YaHei', 9), foreground='#666666').pack(anchor='w', padx=2)

        # ============ 日志(右侧面板) ============
        log_card = ttk.Labelframe(right, text='日志', style='Card.TLabelframe')
        log_card.pack(fill='both', expand=True)
        self.log_box = tk.Text(log_card, width=30, font=('Consolas', 9), state='disabled',
                               bg='#ffffff', relief='solid', bd=1, wrap='word')
        self.log_box.pack(fill='both', expand=True, padx=8, pady=8)
        self._runner = None
        self._thread = None

        # 加载已保存的设置(剪映路径/输出目录/项目名/勾选项等)
        self._load_all_settings()
        # 初始化项目模板下拉框
        self._templates = {}
        self._refresh_templates()

        # 启动链接状态轮询
        self._polling = False
        self._start_link_polling()

        # 暂停/继续热键: Ctrl+P 或 空格键 (运行中可用)
        try:
            self.root.bind('<Control-p>', lambda e: self._hotkey_toggle_pause())
            self.root.bind('<space>', lambda e: self._hotkey_toggle_pause())
        except Exception:
            pass

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

    # ---- 配置中心化 (第二版): 收集/应用所有设置 + 备份/恢复
    def _collect_settings(self):
        """把当前界面所有可持久化设置收集成 dict"""
        return {
            'jianying_path': self.jy_path_var.get().strip(),
            'output_dir': self.outdir_var.get().strip(),
            'project': self.project_var.get().strip(),
            'open_dir': bool(self.open_dir_var.get()),
            'auto_run': bool(self.auto_run_var.get()),
            'resolution': self.res_var.get(),
            'framerate': self.fps_var.get(),
        }

    def _apply_settings(self, data):
        """把设置 dict 应用到界面 (忽略不存在的键)"""
        if not isinstance(data, dict):
            return
        mapping = {
            'jianying_path': lambda v: self.jy_path_var.set(str(v)),
            'output_dir': lambda v: self.outdir_var.set(str(v)),
            'project': lambda v: self.project_var.set(str(v)),
            'open_dir': lambda v: self.open_dir_var.set(bool(v)),
            'auto_run': lambda v: self.auto_run_var.set(bool(v)),
            'resolution': lambda v: self.res_var.set(str(v)),
            'framerate': lambda v: self.fps_var.set(str(v)),
        }
        for k, fn in mapping.items():
            if k in data:
                try:
                    fn(data[k])
                except Exception:
                    pass

    def _save_all_settings(self):
        """把当前界面全部设置写入 config.json"""
        data = self._collect_settings()
        # 保留已有的其他键(如后续新增)
        try:
            import json
            if os.path.exists(SETTINGS_FILE):
                try:
                    with open(SETTINGS_FILE, encoding='utf-8') as f:
                        old = json.load(f)
                    if isinstance(old, dict):
                        old.update(data)
                        data = old
                except Exception:
                    pass
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load_all_settings(self):
        """启动时把 config.json 的全部设置应用到界面"""
        try:
            import json
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._apply_settings(data)
        except Exception:
            pass

    def backup_config(self):
        """备份配置: 把当前界面设置(含剪映路径/输出目录/项目名/勾选项)导出为单个 .json"""
        path = filedialog.asksaveasfilename(
            title='备份配置', defaultextension='.json',
            initialfile='剪映人名条_配置备份.json',
            filetypes=[('配置备份', '*.json')])
        if not path:
            return
        try:
            import json
            data = self._collect_settings()
            # 附上导出时间戳
            data['_backup_time'] = time.strftime('%Y-%m-%d %H:%M:%S')
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self._log(f'💾 配置已备份: {path}')
        except Exception as ex:
            messagebox.showerror('备份失败', str(ex))

    def restore_config(self):
        """恢复配置: 从备份 .json 导入设置并应用到界面"""
        path = filedialog.askopenfilename(title='选择配置备份', filetypes=[('配置备份', '*.json')])
        if not path:
            return
        try:
            import json
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError('备份文件格式不正确')
            self._apply_settings(data)
            self._save_all_settings()
            self._log(f'📂 已恢复配置: {path}')
            self._refresh_templates()
        except Exception as ex:
            messagebox.showerror('恢复失败', str(ex))

    # ---- 项目模板 (第二版): 预设保存/加载
    def _load_templates(self):
        """从模板文件读取项目模板 dict {名字: 设置dict}"""
        try:
            import json
            if os.path.exists(TEMPLATE_FILE):
                with open(TEMPLATE_FILE, encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {}

    def _save_templates(self, templates):
        """把项目模板 dict 写入模板文件"""
        try:
            import json
            with open(TEMPLATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(templates, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _refresh_templates(self):
        """刷新模板下拉框选项"""
        try:
            tpls = self._load_templates()
            self._templates = tpls
            self.tpl_combo['values'] = list(tpls.keys())
        except Exception:
            self._templates = {}
            self.tpl_combo['values'] = []

    def save_template(self):
        """把当前项目名/输出目录/勾选项存为一个模板"""
        project = self.project_var.get().strip()
        name = project or self.outdir_var.get().strip() or '未命名项目'
        # 让用户命名模板
        import tkinter.simpledialog as simpledialog
        tname = simpledialog.askstring('存为模板', '模板名称:', initialvalue=name, parent=self.root)
        if not tname:
            return
        tname = tname.strip()
        if not tname:
            return
        tpls = self._load_templates()
        tpls[tname] = self._collect_settings()
        self._save_templates(tpls)
        self._refresh_templates()
        self._log(f'💾 已保存项目模板: {tname}')

    def _tpl_selected(self, event):
        """从下拉框选择一个模板并应用"""
        name = self.tpl_combo.get()
        tpls = self._load_templates()
        if name in tpls:
            self._apply_settings(tpls[name])
            self._log(f'📂 已应用项目模板: {name}')

    def delete_template(self):
        """删除当前选中的模板"""
        name = self.tpl_combo.get()
        if not name:
            messagebox.showinfo('删除模板', '请先在下拉框选择要删除的模板')
            return
        if messagebox.askyesno('删除模板', f'确定删除模板「{name}」?'):
            tpls = self._load_templates()
            if name in tpls:
                del tpls[name]
                self._save_templates(tpls)
                self._refresh_templates()
                self.tpl_combo.set('')
                self._log(f'🗑 已删除模板: {name}')

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
            "5. 项目名归档\n"
            "   填了'项目名'后, 成片自动归档到 输出目录/项目名_日期/,\n"
            "   同目录自动生成 run_log.csv (成功/失败、耗时、时间戳)。\n\n"
            "6. 暂停/重跑\n"
            "   运行中可点'⏸ 暂停'或按空格/Ctrl+P 临时暂停/继续。\n"
            "   跑完若有失败, '↻ 重跑失败'按钮会点亮, 一键重试失败的名字。\n\n"
            "7. 干跑预览 (v1.2.0)\n"
            "   点'👁 干跑预览'先不操作剪映, 模拟预览每个名字将导出到哪、\n"
            "   有没有同名/路径问题。适合正式跑之前先试一遍。\n\n"
            "8. 项目模板 (v1.2.0)\n"
            "   把'项目名+输出目录+勾选项'存成模板, 下拉框一键加载/删除, 复用常用配置。\n\n"
            "9. 配置备份 (v1.2.0)\n"
            "   '💾 备份配置'把剪映路径/输出目录/项目名/勾选项导出为单个 .json, \n"
            "   '📂 恢复配置'换机迁移时一键导入。\n\n"
            "10. 自动执行\n"
            "   勾选'打开草稿并选中后自动开始批量任务', 打开草稿成功即自动跑。\n\n"
            "11. 完成后打开目录\n"
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

    def preview(self):
        """干跑预览: 不连接/不操作剪映, 只模拟预览每个名字将如何处理。
        契合'先小批量试跑再全量'工作流, 提前发现名字格式/输出路径/归档问题。"""
        names = self._get_names()
        if not names:
            messagebox.showwarning('提示', '请先输入名字列表')
            return
        project = self.project_var.get().strip()
        outdir = self.outdir_var.get().strip() or DEFAULT_OUTDIR
        self._log(f'\n[干跑预览] 共{len(names)}个名字, 项目={project or "(无)"}')
        self._log(f'[干跑预览] 输出目录: {outdir}')
        self._log(f'[干跑预览] 注意: 此模式不操作剪映, 仅模拟预览')
        self.start_btn.config(state='disabled')
        self.preview_btn.config(state='disabled')
        self.pbar.config(maximum=len(names), value=0)
        self._start_time = time.time()
        self._total = len(names)
        self._running = True
        self.progress_text_var.set(f'预览中... (0/{len(names)})')
        self.time_var.set('')
        # 用假 controller + dry_run, 在后台线程跑
        self._thread = threading.Thread(target=self._preview_worker,
                                        args=(names, project, outdir), daemon=True)
        self._thread.start()

    def _preview_worker(self, names, project, outdir):
        try:
            # 干跑不需要真实剪映连接; 用空 controller
            runner = BatchRunner(None, outdir, log_cb=self._log,
                                 progress_cb=self._on_progress, dry_run=True)
            results = runner.run(names, project)
        except Exception as ex:
            self._log(f'预览异常: {ex}')
            results = None
        finally:
            self.root.after(0, lambda: self._finish_preview(results, names))

    def _start_run(self, names, outdir):
        """启动批量任务(供按钮与自动执行共用)。连接剪映放后台线程, 避免卡界面"""
        if not names:
            return
        # 每次开始批量前持久化当前设置
        self._save_all_settings()
        project = self.project_var.get().strip()
        self._log(f'输出目录: {outdir}' + (f' | 项目: {project}' if project else ''))
        self._log(f'共{len(names)}个: {", ".join(names)}')
        self.start_btn.config(state='disabled'); self.stop_btn.config(state='normal')
        if hasattr(self, 'rerun_btn'):
            self.rerun_btn.config(state='disabled')
        if hasattr(self, 'pause_btn'):
            self.pause_btn.config(state='normal', text='⏸ 暂停')
        self._running = True
        self.pbar.config(maximum=len(names), value=0)
        self.prog_var.set('启动中...')
        self._start_time = time.time()
        self._total = len(names)
        self.progress_text_var.set(f'准备中... (0/{len(names)})')
        self.time_var.set('')
        self._outdir = outdir
        self._project = project
        self._last_fail_names = []
        self._thread = threading.Thread(target=self._run_worker, args=(names, project), daemon=True)
        self._thread.start()

    def _run_worker(self, names, project=''):
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
            results = self._runner.run(names, project)
        except Exception as ex:
            self._log(f'致命错误: {ex}')
            results = None
        finally:
            self.root.after(0, lambda: self._finish(results, names))

    def _finish(self, results, names):
        self.start_btn.config(state='normal'); self.stop_btn.config(state='disabled')
        self._running = False
        if hasattr(self, 'pause_btn'):
            self.pause_btn.config(state='disabled', text='⏸ 暂停')
        # 判断是否完整跑完(非手动停止): 结果数==名字数
        completed = bool(results) and len(results) == len(names)
        self.prog_var.set('完成' if completed else '已停止')
        if completed and getattr(self, '_start_time', None):
            used = time.time() - self._start_time
            self.time_var.set(f'总用时 {self._fmt_time(used)}')
        else:
            self.time_var.set('')
        # 记录失败名单, 有失败时点亮重跑按钮 + 提示音
        self._last_fail_names = []
        if results:
            self._last_fail_names = [n for n, v in results.items() if not v]
        if self._last_fail_names:
            self.rerun_btn.config(state='normal')
            self._play_beep('fail')
            self._log(f'↻ 共{len(self._last_fail_names)}个失败, 可点"重跑失败"重新尝试')
        elif completed:
            self.rerun_btn.config(state='disabled')
            self._play_beep('ok')
        # 勾选'完成后打开成品目录'且完整跑完时, 打开实际输出目录(含归档子目录)
        if completed and self.open_dir_var.get():
            outdir = self._runner._outdir_actual if (self._runner and hasattr(self._runner, '_outdir_actual')) else (self.outdir_var.get().strip() or DEFAULT_OUTDIR)
            if os.path.isdir(outdir):
                try:
                    os.startfile(outdir)
                    self._log(f'📁 已打开成品目录: {outdir}')
                except Exception as ex:
                    self._log(f'打开目录失败: {ex}')

    def _finish_preview(self, results, names):
        """干跑预览完成: 恢复按钮, 不打开目录、不写run_log"""
        self.start_btn.config(state='normal')
        self.preview_btn.config(state='normal')
        self._running = False
        self.prog_var.set('预览完成')
        if results and len(results) == len(names):
            self._play_beep('ok')
        else:
            self._log('预览中断')

    def rerun_failed(self):
        """一键重跑上次失败的名字 (契合先小批量试跑再全量的工作流)"""
        if not self._last_fail_names:
            messagebox.showinfo('重跑失败', '没有失败的名字可重跑')
            return
        # 重跑前把名字列表替换为失败名单, 便于用户看到在跑什么
        self._set_names(self._last_fail_names)
        self._log(f'↻ 重跑失败 {len(self._last_fail_names)} 个: {", ".join(self._last_fail_names)}')
        self._start_run(self._last_fail_names, self.outdir_var.get().strip() or DEFAULT_OUTDIR)

    def _play_beep(self, kind='ok'):
        """提示音: ok=完成/成功, fail=有失败。用 winsound 标准库, 无声环境静默"""
        try:
            import winsound
            if kind == 'fail':
                winsound.MessageBeep(winsound.MB_ICONHAND)
            else:
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            pass

    def _on_progress(self, idx, total, name, status):
        self.pbar.config(value=idx)
        pct = int(idx / total * 100) if total else 0
        # 高亮当前处理行 (在名字列表里)
        self._highlight_name(name, status)
        # 进度文字(醒目)
        if status == 'running':
            self.progress_text_var.set(f'▌处理中 {name}  ({idx}/{total} · {pct}%)')
        elif status == 'ok':
            self.progress_text_var.set(f'✓ {name} 成功  ({idx}/{total} · {pct}%)')
        else:
            self.progress_text_var.set(f'✗ {name} 失败  ({idx}/{total} · {pct}%)')
        self.prog_var.set(f'{idx}/{total} ({pct}%)')
        # 已用时间 + 预计剩余
        if getattr(self, '_start_time', None) and idx > 0:
            used = time.time() - self._start_time
            eta = used / idx * (total - idx)
            self.time_var.set(f'已用 {self._fmt_time(used)} · 预计剩余 {self._fmt_time(eta)}')

    def _highlight_name(self, name, status):
        """在名字列表里实时高亮当前处理的名字 (运行中=黄底, 成功=绿, 失败=红)"""
        try:
            self.name_box.tag_remove('hl_run', '1.0', 'end')
            self.name_box.tag_remove('hl_ok', '1.0', 'end')
            self.name_box.tag_remove('hl_fail', '1.0', 'end')
            # 在文本里找该名字所在行(每行一个名字, 去空白)
            target = name.strip()
            content = self.name_box.get('1.0', 'end').split('\n')
            for i, line in enumerate(content):
                if line.strip() == target:
                    start = f'{i+1}.0'
                    end = f'{i+1}.end'
                    tag = 'hl_run' if status == 'running' else ('hl_ok' if status == 'ok' else 'hl_fail')
                    self.name_box.tag_add(tag, start, end)
                    self.name_box.see(start)
                    break
        except Exception:
            pass

    def _fmt_time(self, sec):
        """秒 -> mm:ss (或 hh:mm:ss)"""
        sec = max(0, int(sec))
        h, rem = divmod(sec, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f'{h}:{m:02d}:{s:02d}'
        return f'{m:02d}:{s:02d}'

    def stop(self):
        if self._runner: self._runner.stop()
        self.prog_var.set('正在停止...')

    def toggle_pause(self):
        """暂停/继续切换。后台线程在 run() 循环的 _pause.wait() 处阻塞。"""
        runner = self._runner
        if not runner or getattr(self, '_running', False) is False:
            return
        if runner.is_paused:
            runner.pause()
            self.pause_btn.config(text='▶ 继续')
            self.prog_var.set('已暂停 (按空格/Ctrl+P 继续)')
            self._log('⏸ 已暂停')
        else:
            runner.resume()
            self.pause_btn.config(text='⏸ 暂停')
            self.prog_var.set('继续中...')
            self._log('▶ 已继续')

    def _hotkey_toggle_pause(self):
        """热键触发暂停: 仅在运行中且暂停按钮可用时生效"""
        if getattr(self, '_running', False) and self.pause_btn.cget('state') != 'disabled':
            self.toggle_pause()
        return 'break'  # 阻止空格在文本框输入空格

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
