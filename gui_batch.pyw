# -*- coding: utf-8 -*-
"""海外人名条批量生成 · 界面版 (方案B)
复用 batch12 内核: UIA SetValue 替换 → Ctrl+M 导出 → wait_for_export_completion → 移动归置
特点: 文件一出现即移动, 不依赖关掉成功弹窗; 失败单独重跑; 界面+日志
启动: 双击 gui_batch.pyw 或 `uv run python gui_batch.pyw`
"""
import sys, os, time, ctypes, shutil, threading, argparse
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from src.pyJianYingDraft.jianying_controller import JianyingController, AutomationError

user32 = ctypes.windll.user32


def enable_dpi_awareness():
    """让进程感知 DPI, 否则 2K/4K 屏上界面会被系统位图拉伸而发虚。

    tkinter 默认不声明 DPI 感知(实测为 UNAWARE=0), 高分屏 + 系统缩放时
    整窗被拉伸, 文字与线条均模糊。必须赶在创建 Tk 根窗口之前调用。

    优先 PER_MONITOR_AWARE_V2(缩放变化时表现最好) -> 系统级 -> 旧 API。
    返回实际生效的级别名(供日志/测试查看)。
    """
    try:
        # Windows 8.1+: DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return 'per_monitor_v2'
    except Exception:
        pass
    try:
        # Windows 8.1+
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:   # 2 = PER_MONITOR_AWARE
            return 'per_monitor'
    except Exception:
        pass
    try:
        # Vista+: 系统级
        if user32.SetProcessDPIAware():
            return 'system'
    except Exception:
        pass
    return 'none'


def get_dpi_scale(root=None):
    """当前 DPI 缩放比(1.0=100%)。拿不到就返回 1.0。"""
    try:
        hwnd = None
        if root is not None:
            try:
                hwnd = root.winfo_id()
            except Exception:
                hwnd = None
        if hwnd and hasattr(user32, 'GetDpiForWindow'):
            dpi = user32.GetDpiForWindow(hwnd)
            if dpi:
                return dpi / 96.0
    except Exception:
        pass
    try:
        dpi = user32.GetDpiForSystem()
        if dpi:
            return dpi / 96.0
    except Exception:
        pass
    return 1.0

def resource_path(rel):
    """打包(exe)与开发(python)两种运行方式下都能定位到资源文件"""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def is_lite():
    """是否为「精简版」构建。

    精简版 = 只把成片输出到输出目录, 不自动归档到 O 盘项目文件夹。

    判定只用打包内标记(_MEIPASS/lite.txt), **不看源码目录**:
    之前把 lite.txt 也放在项目根目录当模板, 结果源码运行/跑测试时
    全被判成精简版, 界面和功能都跟着变, 污染主版。
    好处: 主版与精简版共用同一份源码, 只差一个构建开关,
          修 bug 不用维护两套代码(避免两边逐渐不一致)。
    """
    meipass = getattr(sys, '_MEIPASS', '')
    if meipass and os.path.isfile(os.path.join(meipass, 'lite.txt')):
        return True
    # 源码调试用: 只在显式环境变量下开启, 不靠文件存在与否误判
    if os.environ.get('JY_NAME_LITE') == '1':
        return True
    return False


LITE = is_lite()     # 模块级缓存, 全程序只判一次


def app_dir():
    """可写数据的存放目录(配置/模板/草稿历史)。

    打包后 __file__ 指向 _MEIPASS 临时解包目录, 写在那里程序一退就被删,
    设置存不住。因此:
      - 冻结(exe)运行: %APPDATA%\\JianyingNameEntry\\  (不往 exe 旁边/桌面据文件)
      - 源码运行: 项目目录 (保持原有习惯)
    精简版用独立子目录, 避免与完整版互相覆盖设置。
    """
    sub = 'JianyingNameEntryLite' if LITE else 'JianyingNameEntry'
    if getattr(sys, 'frozen', False):
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
        d = os.path.join(base, sub)
        try:
            os.makedirs(d, exist_ok=True)
            return d
        except Exception:
            return os.path.dirname(os.path.abspath(sys.executable))
    # 源码运行: 精简版放到子目录, 不污染主版 config.json
    d = os.path.dirname(os.path.abspath(__file__))
    if LITE:
        d = os.path.join(d, '_lite_data')
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
    return d


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

# ffmpeg 默认路径 (用于导出后转透明通道)。工具会先探测 PATH, 再试默认安装位置。
FFMPEG_DEFAULT_PATHS = [
    r'C:\ffmpeg\bin\ffmpeg.exe',
    os.path.join(os.environ.get('PROGRAMFILES', ''), 'ffmpeg', 'bin', 'ffmpeg.exe'),
]


def detect_ffmpeg_path():
    """自动探测 ffmpeg 路径: 先查 PATH, 再查常见安装位置。找不到返回空串。"""
    import shutil as _sh
    try:
        p = _sh.which('ffmpeg')
        if p:
            return p
    except Exception:
        pass
    for p in FFMPEG_DEFAULT_PATHS:
        if p and os.path.isfile(p):
            return p
    return ''

# 草稿名历史记录文件 (存到程序目录, 随工具迁移)
HISTORY_FILE = os.path.join(app_dir(), '.draft_history.json')
MAX_HISTORY = 20  # 最多保留的历史条数

# 设置文件 (剪映路径等)
SETTINGS_FILE = os.path.join(app_dir(), 'config.json')

# 项目模板文件 (预设: 项目名/输出目录/勾选项组合)
TEMPLATE_FILE = os.path.join(app_dir(), 'templates.json')

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
    # 带扫描码的键盘事件: 剪映等现代编辑器对扫描码=0的合成按键可能不响应
    scan = user32.MapVirtualKeyW(vk, 0)
    user32.keybd_event(vk, scan, 0, 0); user32.keybd_event(vk, scan, 2, 0)

def ctrl_key(vk):
    user32.keybd_event(0x11, 0, 0, 0); key(vk); user32.keybd_event(0x11, 0, 2, 0)

def click(x, y):
    user32.SetCursorPos(int(x), int(y)); time.sleep(0.12)
    user32.mouse_event(0x0002, 0, 0, 0, 0); user32.mouse_event(0x0004, 0, 0, 0, 0); time.sleep(0.08)


DEFAULT_FINAL_ROOT = r'O:\AI漫剧剪辑一组'
FINAL_SUBDIR = '人名条'   # 项目目录内的子文件夹名(成片剪切到里面)

# 同名冲突策略: 界面显示名 -> 内部值 (顺序即下拉框顺序)
CONFLICT_LABELS = {
    '询问': 'ask',
    '覆盖': 'overwrite',
    '自动改名': 'rename',
    '跳过': 'skip',
}
FROM_CONFLICT_VALUE = {v: k for k, v in CONFLICT_LABELS.items()}
DEFAULT_CONFLICT_LABEL = '询问'   # 默认策略: 现场询问


def norm_title(s: str) -> str:
    """把剧名/文件夹名归一化成可比较的形式:
    去掉序号前缀(如 32_ / 731-11926-)、后缀(角色场景表/人物场景表)、
    以及所有标点与空白(书名号《》、顿号、括号等)。返回小写。

    归一化后两边都是纯「字母+数字+汉字」，于是 '合约八年我成了自己的靠山'
    能作为 '73111926海外合约八年我成了自己的靠山' 的子串命中。
    """
    import re
    s = os.path.splitext(str(s))[0]                 # 去扩展名
    s = re.sub(r'^(\d+[_\-\s]*)+', '', s)          # 去序号前缀(可能多层, 如 731-11926-)
    s = re.sub(r'[_\-\s]*(角色场景表|人物场景表|角色表|场景表|人名条|人物表)$', '', s)  # 去后缀
    s = re.sub(r'[^0-9A-Za-z\u4e00-\u9fff]+', '', s)  # 去标点/空白/下划线
    return s.lower()


def clean_title(s: str) -> str:
    """把剧名清理成适合显示/手改的形式: 去序号前缀与“角色场景表”这类后缀,
    但保留中间的可读标点(与 norm_title 不同, 后者是全量归一化仅用于比较)。
    如 '32_合约八年我成了自己的靠山_角色场景表' → '合约八年我成了自己的靠山'。"""
    import re
    s = os.path.splitext(str(s))[0].strip()
    s = re.sub(r'^(\d+[_\-\s]+)+', '', s)   # 去序号前缀(要求后面跟分隔符, 避免吃掉剧名开头的数字)
    s = re.sub(r'[_\-\s]*(角色场景表|人物场景表|角色表|场景表|人物表)$', '', s)  # 去后缀
    return s.strip(' _-')


def match_project(root: str, title: str, names=None):
    """在 root 下找剧名对应的项目文件夹。

    返回 (项目文件夹名, 依据) 或 (None, 原因)。
    第一优: 剧名归一化后是候选文件夹名的子串(唯一或取覆盖度最高者)。
    兜底: 候选项目 人名条/ 里已有文件的文件名与本次名字集合重合度过半。
    """
    try:
        subs = [d for d in sorted(os.listdir(root))
                if os.path.isdir(os.path.join(root, d))]
    except Exception:
        return None, '根目录不可读'
    if not subs:
        return None, '根目录下没有项目文件夹'

    nt = norm_title(title) if title else ''
    if nt:
        cands = [d for d in subs if nt in norm_title(d)]
        if len(cands) == 1:
            return cands[0], '剧名匹配'
        if len(cands) > 1:
            # 多个命中时取与剧名最接近的(归一化长度差最小)
            best = min(cands, key=lambda d: abs(len(norm_title(d)) - len(nt)))
            return best, '剧名匹配(多命中取最接近)'

    # 兜底: 用已有成片的文件名与本次名字集合比重合度
    if names:
        want = {norm_title(n) for n in names if str(n).strip()}
        best, best_score = None, 0.0
        for d in subs:
            p = os.path.join(root, d, FINAL_SUBDIR)
            if not os.path.isdir(p):
                continue
            try:
                have = {norm_title(f) for f in os.listdir(p)}
            except Exception:
                continue
            if not want:
                continue
            score = len(have & want) / len(want)
            if score > best_score:
                best, best_score = d, score
        if best and best_score >= 0.5:
            return best, f'已有成片名字重合 {int(best_score * 100)}%'

    return None, ('剧名未匹配到任何项目文件夹' if nt else '未提供剧名')


class BatchRunner:
    """批量导出运行器(在后台线程跑, 界面用回调更新)"""
    def __init__(self, ctrl, outdir, resolution=None, framerate=None, log_cb=None, progress_cb=None, dry_run=False,
                 transparent=False, ffmpeg_path='', final_root='', final_title='', final_subdir=FINAL_SUBDIR,
                 final_move=True, conflict_policy='ask', conflict_cb=None, resume=False, export_dir=''):
        self.ctrl = ctrl
        self.outdir = outdir
        self.resolution = resolution
        self.framerate = framerate
        self.dry_run = dry_run
        self.transparent = transparent   # 导出后是否转透明通道(ProRes 4444 MOV)
        self.ffmpeg_path = ffmpeg_path   # ffmpeg 可执行文件路径
        self.final_root = (final_root or '').strip()      # 最终位置根目录(如 O:\AI漫剧剪辑一组)
        self.final_title = (final_title or '').strip()    # 剧名, 用于匹配项目文件夹
        self.final_subdir = (final_subdir or FINAL_SUBDIR).strip()  # 项目内子文件夹名
        self.final_move = bool(final_move)  # True=剪切(移动), False=复制留原件
        self.conflict_policy = conflict_policy or 'ask'   # 同名冲突: ask/overwrite/rename/skip
        self.conflict_cb = conflict_cb      # 询问回调(conflicts)->策略; 主线程弹窗
        self.resume = bool(resume)      # 断点续跑: 已生成过的名字直接跳过, 不重复导出
        self.export_dir = (export_dir or '').strip()   # 剪映导出目录(可选; 空=自动按常见位置扫描)
        self._produced = []             # 本次运行产生的文件(仅这些会被投送)
        self._archive_sub = ''          # 项目归档子目录名(如 项目A_20260902), run 后更新
        self._final_project = None      # 解析出的项目文件夹名
        self._final_dir = ''            # 解析出的最终落盘目录(项目\人名条)
        self._final_moved = 0           # 成功投送到最终位置的次数
        self._final_delivered = 0       # 本次实际投送成功的文件数(供界面判断该打开哪里)
        self._skipped = []              # 断点续跑跳过的名字
        self.log_cb = log_cb or (lambda *a: None)
        self.progress_cb = progress_cb or (lambda *a: None)
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._pause.set()   # 默认不暂停
        self._per_name_time = {}   # 每个名字的耗时, 供 run_log 使用
        self._outdir_actual = outdir  # 实际落盘目录(含归档子目录), run 后更新
        self._transparent_fails = 0   # 转透明失败计数

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
        """用真实键盘替换文字: 点击文本框→全选→直接粘贴(不删除)。
        剪映认的是真实编辑(会提交到时间线素材), SetValue只是UIA显示层假替换。
        关键: 全选后直接 Ctrl+V 粘贴(不按 Delete), 剪映用“替换选中文本”语义保留字体格式;
        若先 Delete 删除再粘贴, 段落格式丢失、新文字套默认字体。
        替换后重试读回验证, 确认文字真的被替换才返回True。"""
        # 取文本框中心坐标
        try:
            r = edit_ctrl.BoundingRectangle
            cx, cy = (r.left + r.right) // 2, (r.top + r.bottom) // 2
        except Exception as ex:
            self._log(f'  取文本框坐标失败:{ex}')
            return False
        # 真实键盘输入: 全选→直接粘贴(不删除, 保留字体)
        click(cx, cy); time.sleep(T_CLICK_TEXTBOX)
        ctrl_key(0x41); time.sleep(0.25)   # Ctrl+A 全选 (不按Delete, 直接粘贴覆盖选中文本)
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

    # 剪映可能用到的导出目录候选(不同机器/不同版本默认位置不同)
    EXPORT_DIR_CANDIDATES = [
        '~\\Desktop',                                  # 桌面(最常见)
        '~\\Videos',                                   # 视频
        '~\\Videos\\JianyingPro',
        '~\\Downloads',                                # 下载
        '~\\Documents',
    ]
    # 剪映导出文件的默认前缀(本机是「海外人名条」, 但别的机器/草稿可能不同);
    # 因此它只作为“优先候选”, 不是唯一依据
    EXPORT_NAME_HINTS = ['海外人名条']

    def export_dirs(self):
        """返回本次要扫描的导出目录列表(去重、只保留存在的)。
        包含: 用户指定的导出目录 > 输出目录 > 常见默认位置。"""
        dirs = []
        def add(p):
            if not p:
                return
            p = os.path.expandvars(os.path.expanduser(str(p)))
            if p and os.path.isdir(p) and p not in dirs:
                dirs.append(p)
        add(getattr(self, 'export_dir', ''))
        add(self.outdir)
        add(getattr(self, '_outdir_actual', None))
        for c in self.EXPORT_DIR_CANDIDATES:
            add(c)
        return dirs

    def _snapshot_exports(self):
        """对候选目录做视频文件快照: {path: (size, mtime)}。

        不再依赖文件名前缀 —— 别的电脑上草稿名不同、导出名就不同,
        写死前缀会直接导致“卡在等文件”。改用快照差异: 新出现或大小/时间变化的都算新导出。
        """
        snap = {}
        for d in self.export_dirs():
            try:
                with os.scandir(d) as it:
                    for e in it:
                        try:
                            if not e.is_file():
                                continue
                            ext = os.path.splitext(e.name)[1].lower()
                            if ext not in ('.mp4', '.mov'):
                                continue
                            st = e.stat()
                            snap[e.path] = (st.st_size, st.st_mtime)
                        except Exception:
                            continue
            except Exception:
                continue
        return snap

    def _scan_exports(self):
        """兼容旧接口: 返回当前候选目录里所有视频文件路径集合。"""
        return set(self._snapshot_exports().keys())

    def _diff_exports(self, before_snap):
        """比对快照, 返回新增或发生变化的视频文件(新的优先)。

        加入时间窗: 只认最近 10 分钟内写过的文件, 避开目录里本来就有的旧片。
        优先取名字带剪映默认前缀的, 其次取最新的。
        """
        now = time.time()
        cands = []
        cur = self._snapshot_exports()
        for path, (size, mtime) in cur.items():
            old = before_snap.get(path)
            changed = (old is None) or (old != (size, mtime))
            if not changed:
                continue
            if size <= 0:
                continue
            # 时间窗: 只认刚写过的(避免把很久以前的旧文件当成新导出)
            if now - mtime > 600:
                continue
            pref = 1 if any(h in os.path.basename(path) for h in self.EXPORT_NAME_HINTS) else 0
            cands.append((pref, mtime, path))
        if not cands:
            return None
        cands.sort(reverse=True)     # 前缀命中优先, 其次最新的
        return cands[0][2]

    def wait_new_export(self, before_state, timeout=120):
        """等新导出文件出现。

        before_state 可为旧接口的 set(向后兼容) 或快照 dict。
        超时时会把扫描过的目录写进日志, 便于现场定位到底导出到哪了。
        """
        before_snap = before_state if isinstance(before_state, dict) else None
        if before_snap is None:
            # 旧接口传入的是路径集合, 转成快照便于比较
            before_snap = {}
            for p in (before_state or ()):
                try:
                    st = os.stat(p)
                    before_snap[p] = (st.st_size, st.st_mtime)
                except Exception:
                    before_snap[p] = (0, 0)
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self._stop.is_set():
                return None
            hit = self._diff_exports(before_snap)
            if hit:
                return hit
            time.sleep(0.5)
        # 超时: 把找过的目录与每个目录里的视频数量打出来(取证用)
        try:
            self._log(f'  !!{timeout}s 内未找到新导出文件, 已扫描目录:')
            for d in self.export_dirs():
                n = 0
                try:
                    with os.scandir(d) as it:
                        for e in it:
                            if e.is_file() and os.path.splitext(e.name)[1].lower() in ('.mp4', '.mov'):
                                n += 1
                except Exception:
                    n = -1
                self._log(f'     {d}  (视频文件 {n} 个)')
            self._log('    请确认剪映“导出”对话框里的导出位置是否在上面这些目录里。')
        except Exception:
            pass
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

        # 移动归置 (文件名与名字一致); 用 _outdir_actual 才能落到 项目名_日期/ 归档子目录
        target = os.path.join(self._outdir_actual, name + '.mp4')
        if os.path.exists(target):
            target = os.path.join(self._outdir_actual, name + '(1).mp4')
        try:
            # 同盘用原子replace更快; 跨盘(如桌面C盘→O盘)用shutil.move自动copy+delete
            if os.path.splitdrive(src)[0].lower() == os.path.splitdrive(target)[0].lower():
                os.replace(src, target)
            else:
                shutil.move(src, target)
            self._log(f'  -> {target}')
            # before_set 现在是快照 dict(路径 -> (size, mtime)); 搬走后在快照里标记为已处理
            try:
                if isinstance(before_set, dict):
                    before_set[src] = (0, 0)
                else:
                    before_set.discard(src)
            except Exception:
                pass
            produced = [target]
            # 若勾选转透明, 导出后把该 MP4 转成带透明通道的 MOV
            if self.transparent:
                ok_t = self._convert_transparent(target, name)
                if ok_t:
                    produced.append(os.path.splitext(target)[0] + '_透明.mov')
                else:
                    self._transparent_fails += 1
            # 仅登记产物, 不搬; 整批输出完成后由 deliver_all() 统一投送
            self._produced.extend(produced)
            return True
        except Exception as ex:
            self._log(f'  移动失败:{ex}')
            try:
                if not isinstance(before_set, dict):
                    before_set.add(src)
            except Exception:
                pass
            return False

    # ---- 最终位置: 自动定位项目文件夹, 把成片剪切(或复制)到 项目\人名条\
    def resolve_final_dir(self, names=None):
        """根据 final_root + final_title 定位出最终落盘目录 项目\人名条\。
        找不到返回空串(不报错), 把原因写进日志。已解析过则直接复用。"""
        if not self.final_root:
            return ''
        if self._final_dir:
            return self._final_dir
        if not os.path.isdir(self.final_root):
            self._log(f'!!最终位置根目录不存在: {self.final_root} (本次不剪切)')
            return ''
        proj, why = match_project(self.final_root, self.final_title, names)
        if not proj:
            self._log(f'!!未定位到项目文件夹({why}); 根目录={self.final_root} 剧名={self.final_title or "(空)"}')
            return ''
        d = os.path.join(self.final_root, proj, self.final_subdir)
        try:
            os.makedirs(d, exist_ok=True)
        except Exception as ex:
            self._log(f'!!最终目录创建失败: {d} ({ex})')
            return ''
        self._final_project = proj
        self._final_dir = d
        self._log(f'最终位置已定位: {d}   [{why}]')
        return d

    def _deliver_final(self, files):
        """[旧接口, 保留兼容] 单次投递, 不询问。"""
        self._produced.extend(files)
        self.deliver_all()

    def deliver_all(self, names_for_match=None):
        """整批输出全部结束后, 统一把本次产物投送到最终目录。

        只搬 self._produced 里显式登记的文件(本次运行真正生成的),
        绝不扫描目录, 因此输出目录里的其它文件不会被误搬。
        同名冲突按 conflict_policy 处理: overwrite / rename / skip / ask。
        返回统计 dict。"""
        stat = {'moved': 0, 'overwritten': 0, 'renamed': 0, 'skipped': 0, 'failed': 0, 'aborted': False}
        if not self.final_root:
            return stat
        # 只留真实存在且确实位于本次输出目录内的文件
        out_root = os.path.abspath(self._outdir_actual)
        files, seen = [], set()
        for p in self._produced:
            if not p:
                continue
            ap = os.path.abspath(p)
            if ap in seen or not os.path.isfile(ap):
                continue
            if not ap.lower().startswith(out_root.lower() + os.sep):
                self._log(f'!!跳过非本次输出文件: {ap}')
                continue
            seen.add(ap); files.append(ap)
        if not files:
            self._log('\n(无可投送的产物)')
            return stat

        dst_dir = self.resolve_final_dir(names_for_match)
        if not dst_dir:
            # 定位失败: 文件全部留在输出目录, 不乱放
            self._log(f'\n未定位到项目文件夹, {len(files)} 个文件保留在输出目录')
            return stat

        self._log(f'\n===== 输出完成, 开始投送到最终目录 ({len(files)} 个文件) =====')
        # 先算同名冲突
        plan = []
        conflicts = []
        for src in files:
            base = os.path.basename(src)
            dst = os.path.join(dst_dir, base)
            if os.path.exists(dst):
                conflicts.append((src, dst))
            plan.append((src, dst, os.path.exists(dst)))

        policy = self.conflict_policy or 'rename'
        if conflicts:
            self._log(f'同名冲突 {len(conflicts)} 个: ' +
                      ', '.join(os.path.basename(d) for _, d in conflicts[:6]) +
                      ('...' if len(conflicts) > 6 else ''))
            if policy == 'ask':
                if self.conflict_cb:
                    ans = self.conflict_cb(conflicts) or 'cancel'
                    self._log(f'用户选择: {ans}')
                else:
                    ans = 'skip'   # 无弹窗回调时宁可不动, 绝不默认覆盖
                    self._log('(无法弹窗询问, 改为跳过同名文件)')
                if ans == 'cancel':
                    self._log('已取消投送, 文件全部保留在输出目录')
                    stat['aborted'] = True
                    return stat
                policy = ans
        else:
            self._log('无同名冲突')

        # 执行
        for src, dst, existed in plan:
            base = os.path.basename(src)
            if existed and policy == 'skip':
                self._log(f'  - 跳过(已存在): {base}')
                stat['skipped'] += 1
                continue
            target = dst
            if existed and policy == 'rename':
                stem, ext = os.path.splitext(base)
                for i in range(1, 100):
                    cand = os.path.join(dst_dir, f'{stem}({i}){ext}')
                    if not os.path.exists(cand):
                        target = cand
                        break
            try:
                if existed and policy == 'overwrite':
                    # 先删目标再搬: 跨盘时 shutil.move 到已存在文件在部分文件系统上会失败
                    try:
                        os.remove(target)
                    except Exception:
                        pass
                if self.final_move:
                    if os.path.splitdrive(src)[0].lower() == os.path.splitdrive(target)[0].lower():
                        os.replace(src, target)
                    else:
                        shutil.move(src, target)
                    verb = '剪切'
                else:
                    shutil.copy2(src, target)
                    verb = '复制'
                if existed:
                    if policy == 'overwrite':
                        stat['overwritten'] += 1
                        self._log(f'  ⇢ 已{verb}(覆盖同名): {os.path.basename(target)}')
                    else:
                        stat['renamed'] += 1
                        self._log(f'  ⇢ 已{verb}(改名避让): {os.path.basename(target)}')
                else:
                    stat['moved'] += 1
                    self._log(f'  ⇢ 已{verb}: {os.path.basename(target)}')
                self._final_moved += 1
            except Exception as ex:
                stat['failed'] += 1
                self._log(f'  !!投送失败({base}): {ex}')

        self._log(f'投送完成: 新搬{stat["moved"]} 覆盖{stat["overwritten"]} '
                  f'改名{stat["renamed"]} 跳过{stat["skipped"]} 失败{stat["failed"]}')
        self._final_delivered = (stat['moved'] + stat['overwritten'] + stat['renamed'])
        return stat

    # ---- 干跑预览: 不操作剪映, 只模拟预览每个名字将如何处理
    # ---- 转透明通道: 把已归置的 MP4 用 colorkey 抠黑转成 ProRes 4444 MOV
    def _convert_transparent(self, mp4_path, name):
        """把单个 MP4 转成带透明通道的 ProRes 4444 MOV (colorkey 抠黑底)。
        成功返回 True; 失败返回 False。保留原 MP4。"""
        ff = self.ffmpeg_path
        if not ff:
            ff = detect_ffmpeg_path()
        if not ff or not os.path.isfile(ff):
            self._log(f'  !!未找到 ffmpeg, 无法转透明 (已保留原MP4)')
            return False
        base, _ = os.path.splitext(mp4_path)
        out_mov = base + '_透明.mov'   # 与 MP4 同名, 后缀区分
        try:
            import subprocess as _sp
            # colorkey 抠纯黑 + ProRes 4444 带 alpha
            r = _sp.run([ff, '-y', '-i', mp4_path,
                         '-vf', 'colorkey=black:0.15:0.1,format=yuva444p10le',
                         '-c:v', 'prores_ks', '-profile:v', '4',
                         '-pix_fmt', 'yuva444p10le', '-an', out_mov],
                        capture_output=True, text=True, timeout=180)
            if r.returncode == 0 and os.path.exists(out_mov) and os.path.getsize(out_mov) > 0:
                self._log(f'  ✦ 已转透明: {os.path.basename(out_mov)}')
                return True
            else:
                self._log(f'  !!转透明失败: {name}')
                # 清理可能残留的半成品
                if os.path.exists(out_mov):
                    try: os.remove(out_mov)
                    except Exception: pass
                return False
        except Exception as ex:
            self._log(f'  !!转透明异常: {ex}')
            return False

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
        if self.final_root:
            self._log(f'  [预览] 全部导出完成后统一剪切到最终位置 → {self._final_dir or "(运行开始时自动定位)"}')
        return True

    # ---- 批量入口
    def _produced_names(self):
        """断点续跑: 扫输出目录与最终目录, 收集已经出过的成片名(不含扩展名)。
        包含被重命名为 姓名(1).mp4 的情况, 一并归到 姓名。"""
        import re as _re
        names = set()
        dirs = []
        if getattr(self, '_outdir_actual', ''):
            dirs.append(self._outdir_actual)
        fd = self._final_dir
        if fd:
            dirs.append(fd)
        for d in dirs:
            if not d or not os.path.isdir(d):
                continue
            try:
                for f in os.listdir(d):
                    stem, ext = os.path.splitext(f)
                    if not _re.fullmatch(r'\.(mp4|mov)', ext, _re.I):
                        continue
                    # 转透明产物 姓名_透明.mov 是成片的附庸, 不单独作为一个“已完成名字”
                    stem = _re.sub(r'_透明$', '', stem)
                    stem = _re.sub(r'\(\d+\)$', '', stem)   # 同名避让产生的 姓名(1) 归到 姓名
                    if stem:
                        names.add(stem)
            except Exception:
                pass
        return names

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
        self._archive_sub = archive_sub
        # 最终位置(若设置): 先定位一次项目文件夹并提示, 避免每条都报错
        if self.final_root:
            self.resolve_final_dir(names)
        # 断点续跑: 先盘点已经出过的名字, 这些本次直接跳过
        self._done_names = set()
        self._skipped = []
        if self.resume and not self.dry_run:
            self._done_names = self._produced_names()
            hit = [n for n in names if n in self._done_names]
            if hit:
                self._log(f'\n[断点续跑] 已有 {len(hit)}/{len(names)} 条成片, 将跳过: ' +
                          ', '.join(hit[:10]) + ('...' if len(hit) > 10 else ''))
            else:
                self._log('\n[断点续跑] 未发现已生成的成片, 本次全部导出')
            todo = [n for n in names if n not in self._done_names]
            if not todo:
                self._log('[断点续跑] 全部已完成, 无需导出')
                return {n: True for n in names}
        else:
            todo = list(names)

        before_set = self._snapshot_exports()
        results = {}
        run_start = time.time()
        # 跳过的不计入进度分母, 让剩余条数才是真实的待处理量
        for idx, name in enumerate(todo, 1):
            if self._stop.is_set():
                self._log('\n(已停止)')
                break
            self._pause.wait()  # 若暂停则等待(解除暂停/停止才继续)
            if self._stop.is_set():
                self._log('\n(已停止)')
                break
            self.progress_cb(idx, len(todo), name, 'running')
            t0 = time.time()
            ok = self.process_one(name, before_set)
            results[name] = ok
            self._per_name_time[name] = time.time() - t0
            self.progress_cb(idx, len(todo), name, 'ok' if ok else 'fail')
            time.sleep(T_BETWEEN_NAMES)

        # 跳过的名字按成功计入结果, 便于 run_log 与后续流程一致
        skipped = [n for n in names if n not in results]
        self._skipped = skipped
        for n in skipped:
            results[n] = True

        ok_names = [n for n, v in results.items() if v]
        fail_names = [n for n, v in results.items() if not v]
        if skipped:
            self._log(f'\n(其中跳过 {len(skipped)} 条已完成)')
        self._log(f'\n===== 结果: 成功{len(ok_names)} 失败{len(fail_names)} =====')
        if fail_names:
            self._log('失败: ' + ', '.join(fail_names))
        # 写 run_log.csv (成功/失败、耗时、时间戳)。干跑预览不写正式日志。
        if not self.dry_run:
            try:
                log_path = self._write_run_log(outdir, names, results, run_start)
                # run_log.csv 留在输出目录, 不随成片投送
            except Exception as ex:
                self._log(f'写run_log失败: {ex}')
            # 整批输出已全部完成, 现在才统一投送到最终目录
            self.deliver_all(names)
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
        return log_path


# ------------------------------------------------------------------ 界面
class App:
    def __init__(self, root):
        self.root = root
        root.title('海外人名条批量生成' if not LITE else '海外人名条批量生成 · 精简版')
        # 窗口图标(仅界面版; exe自带图标)
        try:
            root.iconbitmap(resource_path('icon.ico'))
        except Exception:
            pass
        # 默认尺寸随 DPI 缩放: 高分屏按物理像素给足, 避免一打开就看不到按钮
        scale = get_dpi_scale(root)
        w = int(1060 * min(scale, 1.5))
        h = int(880 * min(scale, 1.5))
        # 不超过屏幕可用区(留出任务栏)
        try:
            sw = root.winfo_screenwidth()
            sh = root.winfo_screenheight()
            w = min(w, max(900, sw - 120))
            h = min(h, max(660, sh - 120))
        except Exception:
            pass
        root.geometry(f'{w}x{h}')
        root.minsize(860, 640)
        root.resizable(True, True)
        self._setup_theme(root)

    # ------------------------------------------------------------ 主题/样式
    # 统一间距节奏(像素)。改这里就能整体调疏密, 不用逐处改数字。
    PAD_X = 14          # 卡片内左右留白
    PAD_CARD = 8        # 卡片之间的垂直间距
    PAD_HINT = (0, 2)   # 灰字说明行

    def _setup_theme(self, root):
        """统一界面主题、配色与样式"""
        style = ttk.Style(root)
        try:
            style.theme_use('clam')      # clam 才能自定义背景色/边框
        except Exception:
            pass
        # ---- 配色
        self.C_BG = '#f2f4f7'        # 页面底色(稍冷灰, 衬白卡片)
        self.C_CARD = '#ffffff'      # 卡片底
        self.C_HINT = '#8a9099'      # 灰字说明
        self.C_BORDER = '#e3e6eb'    # 分隔/边框
        self.C_TEXT = '#1f2328'
        self.C_TITLE = '#111418'
        self.C_ACCENT = '#2b5be6'    # 主色(蓝)
        accent = self.C_ACCENT
        ok_green = '#2ecc71'         # 成功/进度绿
        err_red = '#e74c3c'          # 停止/错误红
        card_bg = self.C_CARD
        bg = self.C_BG
        text = self.C_TEXT
        root.configure(bg=bg)

        # 字体随 DPI 放大, 否则高分屏上字太小
        scale = get_dpi_scale(root)
        f_base = max(9, int(round(9 * min(scale, 1.6))))
        f_small = max(8, f_base - 1)
        f_title = f_base + 1
        f_big = f_base + 2
        self._F = {'base': f_base, 'small': f_small, 'title': f_title, 'big': f_big,
                   'hint': ('Microsoft YaHei', f_small), 'mono': ('Consolas', f_base)}

        try:
            style.configure('.', background=bg, foreground=text,
                            font=('Microsoft YaHei', f_base))
            style.configure('TLabel', background=bg, foreground=text)
            # 卡片内专用: 白底, 否则卡片里会出现页面灰的色块
            style.configure('Card.TLabel', background=card_bg, foreground=text)
            style.configure('CardHint.TLabel', background=card_bg, foreground=self.C_HINT)
            # 卡片内容器也必需白底: clam 下 ttk.Frame 会继承页面灰, 在卡片里成灰块
            style.configure('Card.TFrame', background=card_bg)
            style.configure('Card.TCheckbutton', background=card_bg, foreground=text)
            style.map('Card.TCheckbutton', background=[('active', card_bg)])
            style.configure('Card.TLabelframe.Label', background=card_bg, foreground=self.C_TITLE,
                            font=('Microsoft YaHei', f_title, 'bold'))
            style.configure('TCheckbutton', background=card_bg, foreground=text)
            style.map('TCheckbutton', background=[('active', card_bg)])
            style.configure('TLabelframe', background=card_bg, bordercolor=self.C_BORDER,
                            relief='solid', borderwidth=1)
            style.configure('TLabelframe.Label', background=card_bg, foreground=self.C_TITLE,
                            font=('Microsoft YaHei', f_title, 'bold'))
            # 普通描边按钮
            style.configure('TButton', padding=(10, 5), background='#fbfcfd',
                            bordercolor=self.C_BORDER, relief='solid', borderwidth=1)
            style.map('TButton',
                      background=[('active', '#eef2f7'), ('pressed', '#e2e8f0')],
                      bordercolor=[('active', '#c9d3e0')])
            # 主按钮(各大色块)
            for name, base, hover, press, dis in (
                ('Start.TButton',   ok_green,  '#27ae60', '#219a52', '#b8c7bf'),
                ('Stop.TButton',    err_red,   '#c0392b', '#b03a2e', '#d8bfbc'),
                ('Rerun.TButton',   '#f39c12', '#e67e22', '#d35400', '#e8d5b8'),
                ('Pause.TButton',   '#8e8ea0', '#6e6e80', '#5a5a6a', '#c6c6d0'),
                ('Preview.TButton', '#16a085', '#138d75', '#0e6e5c', '#b5d8d0'),
            ):
                style.configure(name, background=base, foreground='white',
                                font=('Microsoft YaHei', f_big, 'bold'), padding=(14, 7),
                                relief='flat', borderwidth=0)
                style.map(name, background=[('active', hover), ('pressed', press), ('disabled', dis)])
            # 细边框: 输入框/下拉框
            style.configure('TEntry', fieldbackground='#ffffff', bordercolor=self.C_BORDER,
                            relief='solid', borderwidth=1, padding=3)
            style.configure('TCombobox', fieldbackground='#ffffff', bordercolor=self.C_BORDER,
                            padding=2, arrowcolor='#6b7280')
            style.map('TCombobox', fieldbackground=[('readonly', '#ffffff')])
            # 进度条
            style.configure('Highlight.Horizontal.TProgressbar',
                            troughcolor='#e6e9ee', background=ok_green, thickness=20,
                            bordercolor='#e6e9ee', lightcolor=ok_green, darkcolor=ok_green)
            # 折叠区的展开/收起小按钮
            style.configure('Fold.TButton', padding=(2, 0), font=('Microsoft YaHei', f_small),
                            background=card_bg, relief='flat', borderwidth=0)
            style.map('Fold.TButton',
                      background=[('active', card_bg), ('pressed', card_bg)],
                      foreground=[('active', accent)])
        except Exception:
            pass

        self._build_ui(root, bg)

    def _hint(self, parent, text, **pk):
        """灰字说明行(统一字号/颜色/间距; 卡片内白底避免色块)"""
        lb = ttk.Label(parent, text=text, style='CardHint.TLabel',
                       font=('Microsoft YaHei', self._F['small']))
        lb.pack(anchor='w', **pk)
        return lb

    def _cbtn(self, parent, text, var, **pk):
        """白色背景的勾选框。

        用原生 tk.Checkbutton 而非 ttk: clam 主题的 ttk 勾选框在“选中/未选中”
        都画成方框(X 形), 状态辨识度差; 原生的是“方框+打勾”, 一眼可辨。
        """
        cb = tk.Checkbutton(parent, text=text, variable=var,
                            bg=self.C_CARD, activebackground=self.C_CARD,
                            selectcolor=self.C_ACCENT, bd=0, highlightthickness=0,
                            anchor='w', font=('Microsoft YaHei', self._F['base']))
        cb.pack(anchor='w', **pk)
        return cb

    def _retint_card_widgets(self, node):
        """把卡片内所有标签/勾选框统一成白底。

        ttk 背景由 style 决定, 全局 TLabel 用的是页面灰,
        放进白色卡片(含卡片内的折叠分组 Frame)就会形成明显色块。
        这里递归全树统一重染 —— 不能只扫一层, 折叠区的 body 是子级 Frame。
        """
        try:
            children = node.winfo_children()
        except Exception:
            return
        for c in children:
            try:
                cls = c.winfo_class()
                if cls in ('TLabel', 'TCheckbutton'):
                    st = ''
                    try:
                        st = str(c.cget('style'))
                    except Exception:
                        pass
                    # 已显式指定 Hint 样式的保留其灰色字色, 但仍需白底
                    if cls == 'TCheckbutton':
                        if st != 'Card.TCheckbutton':
                            c.configure(style='Card.TCheckbutton')
                    else:
                        if st == 'CardHint.TLabel':
                            pass
                        elif st != 'Card.TLabel':
                            c.configure(style='Card.TLabel')
                elif cls == 'TFrame':
                    # 卡片内容器同样要白底(clam 下 TFrame 默认继承页面灰)
                    st = ''
                    try:
                        st = str(c.cget('style'))
                    except Exception:
                        pass
                    if st != 'Card.TFrame':
                        c.configure(style='Card.TFrame')
            except Exception:
                pass
            self._retint_card_widgets(c)

    def _fold_section(self, card, title, opened=True):
        """在卡片里插一个可折叠小节, 返回放内容的 Frame。
        用于把长卡片分成几组, 默认只展开常用的那组, 降低拥挤感。"""
        head = ttk.Frame(card)
        head.pack(fill='x', padx=self.PAD_X, pady=(8, 0))
        body = ttk.Frame(card)
        state = {'open': opened}

        # 标题左侧的蓝色细条, 作为分组视觉锚点
        bar = tk.Frame(head, bg='#c9d3e0', width=3, height=13)
        bar.pack(side='left', padx=(0, 6))
        arrow = ttk.Button(head, text='▾' if opened else '▸', style='Fold.TButton', width=2)
        arrow.pack(side='left')
        lb = ttk.Label(head, text=title, font=('Microsoft YaHei', self._F['base'], 'bold'),
                       foreground='#39414d')
        lb.pack(side='left', padx=(2, 0))
        line = tk.Frame(head, bg=self.C_BORDER, height=1)
        line.pack(side='left', fill='x', expand=True, padx=(8, 0))

        def apply():
            if state['open']:
                body.pack(fill='x', after=head)
            else:
                body.pack_forget()
            arrow.config(text='▾' if state['open'] else '▸')

        def toggle(_e=None):
            state['open'] = not state['open']
            apply()

        arrow.config(command=toggle)
        lb.bind('<Button-1>', toggle)
        head.bind('<Button-1>', toggle)
        apply()
        return body

    def _build_archive_sections(self, card3):
        """构建完整版的归档分组(保存位置 + 归档规则)。
        精简版不调用本方法。"""
        # 分组 A: 保存位置(常用, 默认展开)
        secA = self._fold_section(card3, '保存位置', opened=True)
        ttk.Label(secA, text='输出目录 (成片先存这里)').pack(
            anchor='w', padx=self.PAD_X, pady=(6, 2))
        row = ttk.Frame(secA); row.pack(fill='x', padx=self.PAD_X)
        self.outdir_var = tk.StringVar(value=DEFAULT_OUTDIR)
        ttk.Entry(row, textvariable=self.outdir_var).pack(
            side='left', fill='x', expand=True, padx=(0, 5))
        ttk.Button(row, text='浏览', command=self.pick_dir).pack(side='left')

        ttk.Label(secA, text='最终位置根目录').pack(anchor='w', padx=self.PAD_X, pady=(8, 2))
        self._hint(secA, '填了则按剧名自动匹配项目文件夹, 成片剪切到 项目\\人名条\\',
                   padx=self.PAD_X, pady=(0, 3))
        fin_row = ttk.Frame(secA); fin_row.pack(fill='x', padx=self.PAD_X, pady=(0, 8))
        self.final_root_var = tk.StringVar()
        ttk.Entry(fin_row, textvariable=self.final_root_var).pack(
            side='left', fill='x', expand=True, padx=(0, 5))
        ttk.Button(fin_row, text='浏览', command=self.pick_final_root).pack(side='left', padx=(0, 3))
        ttk.Button(fin_row, text='清除', command=lambda: self.final_root_var.set('')).pack(side='left')

        # 分组 B: 归档规则(默认展开)
        secB = self._fold_section(card3, '归档规则', opened=True)
        ttk.Label(secB, text='剧名 (匹配项目文件夹)').pack(
            anchor='w', padx=self.PAD_X, pady=(6, 2))
        fin_row2 = ttk.Frame(secB); fin_row2.pack(fill='x', padx=self.PAD_X)
        self.final_title_var = tk.StringVar()
        self.final_title_entry = ttk.Entry(fin_row2, textvariable=self.final_title_var)
        self.final_title_entry.pack(side='left', fill='x', expand=True, padx=(0, 8))
        # 用户手改剧名 -> 取消自动标记, 后续导入不再覆盖(尊重手填)
        self.final_title_entry.bind('<KeyRelease>', lambda e: self._on_title_typed())
        self.final_title_entry.bind('<<Paste>>', lambda e: self._on_title_typed())
        ttk.Label(fin_row2, text='子文件夹').pack(side='left')
        self.final_subdir_var = tk.StringVar(value=FINAL_SUBDIR)
        ttk.Entry(fin_row2, textvariable=self.final_subdir_var, width=10).pack(side='left', padx=(3, 8))
        ttk.Button(fin_row2, text='匹配预览', command=self.preview_final_match).pack(side='left')
        self._hint(secB, '导入CSV时自动用文件名填剧名; “匹配预览”先看会送到哪个项目',
                   padx=self.PAD_X, pady=(2, 4))
        fin_row3 = ttk.Frame(secB); fin_row3.pack(fill='x', padx=self.PAD_X, pady=(0, 4))
        ttk.Label(fin_row3, text='同名处理').pack(side='left')
        self.conflict_var = tk.StringVar(value=DEFAULT_CONFLICT_LABEL)
        ttk.Combobox(fin_row3, textvariable=self.conflict_var, values=list(CONFLICT_LABELS),
                     state='readonly', width=8).pack(side='left', padx=(3, 10))
        ttk.Label(fin_row3, text='最终目录已有同名文件时', foreground=self.C_HINT).pack(side='left')
        self.final_move_var = tk.BooleanVar(value=True)
        self._cbtn(secB, '剪切(不勾=只复制到最终位置)', self.final_move_var,
                   padx=self.PAD_X, pady=(0, 4))
        self._hint(secB, '投送时机: 全部导出完成后统一剪切; 输出目录里的其它文件不会被搬',
                   padx=self.PAD_X, pady=(0, 8))

    # ------------------------------------------------------------ 界面搭建
    def _build_ui(self, root, bg):
        """搭建界面。

        结构要点(改了会直接影响“小窗口能不能操作”):
          root
          └ main
             ├ left_zone (fill=both, expand)
             │   ├ scroll(卡片区)  <- 纵向可滚动, 防止小窗口溢出看不见
             │   └ bottom(控制区)  <- 固定在底部, 永远可见(开始/停止/进度/时间)
             └ right(日志)
        """
        main = ttk.Frame(root); main.pack(fill='both', expand=True, padx=12, pady=(10, 10))

        # ============ 右: 日志 ============
        right = ttk.Frame(main); right.pack(side='right', fill='y', padx=(12, 0))
        log_card = ttk.Labelframe(right, text='日志', style='TLabelframe')
        log_card.pack(fill='both', expand=True)
        log_btns = ttk.Frame(log_card); log_btns.pack(fill='x', padx=10, pady=(8, 0))
        ttk.Button(log_btns, text='复制', command=self.copy_log).pack(side='left')
        ttk.Button(log_btns, text='导出', command=self.export_log).pack(side='left', padx=(5, 0))
        ttk.Button(log_btns, text='清空', command=self.clear_log).pack(side='left', padx=(5, 0))
        self.log_box = tk.Text(log_card, width=34, font=self._F['mono'], state='disabled',
                               bg='#ffffff', relief='flat', bd=0, wrap='word',
                               highlightthickness=1, highlightbackground=self.C_BORDER,
                               highlightcolor=self.C_BORDER)
        self.log_box.pack(fill='both', expand=True, padx=10, pady=(6, 10))

        # ============ 左: 卡片区(可滚动) + 底部控制区(固定) ============
        left_zone = ttk.Frame(main); left_zone.pack(side='left', fill='both', expand=True)
        scroll, left = self._scrollable_left(left_zone, bg)
        scroll.pack(fill='both', expand=True)
        bottom = ttk.Frame(left_zone); bottom.pack(side='bottom', fill='x', pady=(8, 0))

        # ---------- 卡片① 剪映连接 ----------
        card1 = ttk.Labelframe(left, text='剪映连接', style='TLabelframe')
        card1.pack(fill='x', padx=0, pady=(0, self.PAD_CARD))
        link_row = ttk.Frame(card1); link_row.pack(fill='x', padx=self.PAD_X, pady=(8, 3))
        ttk.Label(link_row, text='状态').pack(side='left')
        self.link_canvas = tk.Canvas(link_row, width=16, height=16, bg=self.C_CARD,
                                     highlightthickness=0)
        self.link_canvas.pack(side='left', padx=(6, 4))
        self.link_dot = self.link_canvas.create_oval(1, 1, 15, 15, fill='#c9ced6', outline='')
        self.link_status_var = tk.StringVar(value='检测中...')
        ttk.Label(link_row, textvariable=self.link_status_var,
                  font=('Microsoft YaHei', self._F['base'], 'bold')).pack(side='left')
        ttk.Button(link_row, text='帮助', command=self.show_help).pack(side='right')

        ttk.Label(card1, text='剪映程序路径').pack(anchor='w', padx=self.PAD_X, pady=(4, 2))
        self._hint(card1, '不填则自动探测; 用于“启动剪映”', padx=self.PAD_X, pady=(0, 3))
        jy_row = ttk.Frame(card1); jy_row.pack(fill='x', padx=self.PAD_X, pady=(0, 3))
        self.jy_path_var = tk.StringVar()
        ttk.Entry(jy_row, textvariable=self.jy_path_var).pack(side='left', fill='x', expand=True, padx=(0, 5))
        ttk.Button(jy_row, text='浏览', command=self.pick_jianying).pack(side='left', padx=(0, 3))
        ttk.Button(jy_row, text='自动探测', command=self.auto_detect_jianying).pack(side='left', padx=(0, 3))
        ttk.Button(jy_row, text='启动剪映', command=self.launch_jianying).pack(side='left')

        ttk.Label(card1, text='草稿名 (留空跳过)').pack(anchor='w', padx=self.PAD_X, pady=(4, 2))
        self._hint(card1, '用于自动打开草稿并选中字幕条', padx=self.PAD_X, pady=(0, 3))
        drow = ttk.Frame(card1); drow.pack(fill='x', padx=self.PAD_X, pady=(0, 3))
        self.draft_var = tk.StringVar()
        self.draft_history = self._load_history()
        self.draft_combo = ttk.Combobox(drow, textvariable=self.draft_var, values=self.draft_history, width=20)
        self.draft_combo.pack(side='left', fill='x', expand=True, padx=(0, 5))
        self.draft_combo.bind('<Return>', lambda e: self.open_draft())
        ttk.Button(drow, text='打开草稿并选字幕', command=self.open_draft).pack(side='left')
        self.auto_run_var = tk.BooleanVar(value=False)
        self._cbtn(card1, '打开草稿并选中后自动开始批量', self.auto_run_var, padx=self.PAD_X, pady=(2, 8))

        # ---------- 卡片② 名字列表 ----------
        card2 = ttk.Labelframe(left, text='名字列表', style='TLabelframe')
        card2.pack(fill='x', padx=0, pady=(0, self.PAD_CARD))
        btns = ttk.Frame(card2); btns.pack(anchor='w', padx=self.PAD_X, pady=(8, 3))
        ttk.Button(btns, text='从CSV导入', command=self.load_csv).pack(side='left', padx=(0, 5))
        ttk.Button(btns, text='从TXT导入', command=self.load_txt).pack(side='left', padx=(0, 5))
        ttk.Button(btns, text='粘贴', command=self.paste_names).pack(side='left', padx=(0, 5))
        ttk.Button(btns, text='清空', command=self.clear_names).pack(side='left')
        ttk.Label(btns, text='每行一个名字', foreground=self.C_HINT).pack(side='right')
        self.name_box = tk.Text(card2, height=5, font=self._F['mono'], bg='#ffffff',
                                relief='flat', bd=0, highlightthickness=1,
                                highlightbackground=self.C_BORDER, highlightcolor=self.C_BORDER)
        self.name_box.pack(fill='x', padx=self.PAD_X, pady=(0, 8))
        self.name_box.tag_configure('hl_run', background='#fff3cd', foreground='#856404')
        self.name_box.tag_configure('hl_ok', background='#d4edda', foreground='#155724')
        self.name_box.tag_configure('hl_fail', background='#f8d7da', foreground='#721c24')

        # ---------- 卡片③ 输出（精简版）/ 输出与归档（完整版）----------
        card3 = ttk.Labelframe(left, text=('输出' if LITE else '输出与归档'), style='TLabelframe')
        card3.pack(fill='x', padx=0, pady=(0, self.PAD_CARD))

        if LITE:
            # === 精简版: 只要一个输出目录, 不做任何归档 ===
            ttk.Label(card3, text='输出目录 (成片保存位置)').pack(
                anchor='w', padx=self.PAD_X, pady=(10, 2))
            row = ttk.Frame(card3); row.pack(fill='x', padx=self.PAD_X)
            self.outdir_var = tk.StringVar(value=DEFAULT_OUTDIR)
            ttk.Entry(row, textvariable=self.outdir_var).pack(
                side='left', fill='x', expand=True, padx=(0, 5))
            ttk.Button(row, text='浏览', command=self.pick_dir).pack(side='left')
            self._hint(card3, '成片按名字命名后直接存到这里，不会自动归档到其它位置',
                       padx=self.PAD_X, pady=(2, 10))
            # 精简版不存在的控件用占位变量, 保证其余代码不因缺属性报错
            self.final_root_var = tk.StringVar(value='')
            self.final_title_var = tk.StringVar(value='')
            self.final_subdir_var = tk.StringVar(value=FINAL_SUBDIR)
            self.conflict_var = tk.StringVar(value=DEFAULT_CONFLICT_LABEL)
            self.final_move_var = tk.BooleanVar(value=True)
            self.final_title_entry = None
        else:
            self._build_archive_sections(card3)

        # ---------- 分组 C: 高级选项(两版共用, 默认折叠) ----------
        secC = self._fold_section(card3, '高级选项', opened=False)
        if not LITE:
            # 项目名会让成片落到 输出目录/项目名_日期/ 子目录, 属于归档行为,
            # 精简版不提供(用户要求“就输出到输出目录”)。
            ttk.Label(secC, text='项目名 (选填)').pack(anchor='w', padx=self.PAD_X, pady=(6, 2))
            self._hint(secC, '填了则成片先归到 输出目录/项目名_日期/', padx=self.PAD_X, pady=(0, 3))
            proj_row = ttk.Frame(secC); proj_row.pack(fill='x', padx=self.PAD_X, pady=(0, 4))
            self.project_var = tk.StringVar()
            ttk.Entry(proj_row, textvariable=self.project_var).pack(
                side='left', fill='x', expand=True, padx=(0, 5))
            ttk.Label(proj_row, text='如: 项目A_2026', foreground=self.C_HINT).pack(side='left')
        else:
            self.project_var = tk.StringVar(value='')   # 占位, 保证不建子目录

        # 剪映导出目录(解决别的电脑上“卡在等文件”)
        ttk.Label(secC, text='剪映导出目录 (选填)').pack(
            anchor='w', padx=self.PAD_X, pady=(6, 2))
        self._hint(secC, '留空=自动扫桌面/视频/下载/输出目录；找不到文件时在此填剪映实际导出位置',
                   padx=self.PAD_X, pady=(0, 3))
        exp_row = ttk.Frame(secC); exp_row.pack(fill='x', padx=self.PAD_X, pady=(0, 8))
        self.export_dir_var = tk.StringVar()
        ttk.Entry(exp_row, textvariable=self.export_dir_var).pack(
            side='left', fill='x', expand=True, padx=(0, 5))
        ttk.Button(exp_row, text='浏览', command=self.pick_export_dir).pack(side='left', padx=(0, 3))
        ttk.Button(exp_row, text='清除', command=lambda: self.export_dir_var.set('')).pack(side='left')

        set_row = ttk.Frame(secC); set_row.pack(fill='x', padx=self.PAD_X, pady=(2, 4))
        ttk.Label(set_row, text='分辨率').pack(side='left')
        self.res_var = tk.StringVar(value='不修改')
        ttk.Combobox(set_row, textvariable=self.res_var,
                     values=['不修改','1080P','720P','4K'], width=8).pack(side='left', padx=(3, 14))
        ttk.Label(set_row, text='帧率').pack(side='left')
        self.fps_var = tk.StringVar(value='不修改')
        ttk.Combobox(set_row, textvariable=self.fps_var,
                     values=['不修改','25','30','60'], width=8).pack(side='left', padx=(3, 0))

        self.transparent_var = tk.BooleanVar(value=False)
        self._cbtn(secC, '导出后转透明通道(MOV)', self.transparent_var, padx=self.PAD_X, pady=(2, 2))
        self._hint(secC, '仅去纯黑底, 光晕字幕可能有残留', padx=self.PAD_X + 18, pady=(0, 3))
        trans_row = ttk.Frame(secC); trans_row.pack(fill='x', padx=self.PAD_X, pady=(0, 4))
        ttk.Label(trans_row, text='ffmpeg', foreground=self.C_HINT).pack(side='left')
        self.ffmpeg_var = tk.StringVar(value=detect_ffmpeg_path())
        ttk.Entry(trans_row, textvariable=self.ffmpeg_var, width=22).pack(
            side='left', fill='x', expand=True, padx=(4, 3))
        ttk.Button(trans_row, text='浏览', command=self.pick_ffmpeg).pack(side='left')

        cfg_row = ttk.Frame(secC); cfg_row.pack(fill='x', padx=self.PAD_X, pady=(0, 4))
        ttk.Label(cfg_row, text='配置').pack(side='left')
        ttk.Button(cfg_row, text='备份', command=self.backup_config).pack(side='left', padx=(6, 3))
        ttk.Button(cfg_row, text='恢复', command=self.restore_config).pack(side='left', padx=(0, 3))
        ttk.Label(cfg_row, text='换机迁移用', foreground=self.C_HINT).pack(side='left', padx=4)

        tpl_row = ttk.Frame(secC); tpl_row.pack(fill='x', padx=self.PAD_X, pady=(0, 8))
        ttk.Label(tpl_row, text='项目模板').pack(side='left')
        self.tpl_combo = ttk.Combobox(tpl_row, width=16, state='readonly')
        self.tpl_combo.pack(side='left', padx=(6, 3))
        self.tpl_combo.bind('<<ComboboxSelected>>', self._tpl_selected)
        ttk.Button(tpl_row, text='存为模板', command=self.save_template).pack(side='left', padx=(0, 3))
        ttk.Button(tpl_row, text='删除模板', command=self.delete_template).pack(side='left')

        # ---------- 底部固定控制区(不随滚动, 永远可见) ----------
        # 分隔线, 把固定区与滚动内容在视觉上分开
        tk.Frame(bottom, bg=self.C_BORDER, height=1).pack(fill='x', pady=(0, 8))

        self.pbar = ttk.Progressbar(bottom, mode='determinate',
                                    style='Highlight.Horizontal.TProgressbar')
        self.pbar.pack(fill='x')
        # 进度主文字(左) + 紧凑计数(右); 两者均置于整宽行, 避免被按钮行挤掉
        row_info = ttk.Frame(bottom); row_info.pack(fill='x', pady=(4, 0))
        self.progress_text_var = tk.StringVar(value='就绪')
        ttk.Label(row_info, textvariable=self.progress_text_var,
                  font=('Microsoft YaHei', self._F['big'], 'bold')).pack(side='left')
        self.prog_var = tk.StringVar(value='')
        ttk.Label(row_info, textvariable=self.prog_var, foreground='#5b6270').pack(side='right')
        self.time_var = tk.StringVar(value='')
        ttk.Label(bottom, textvariable=self.time_var, foreground='#5b6270',
                  font=('Microsoft YaHei', self._F['small'])).pack(anchor='w')

        ctl = ttk.Frame(bottom); ctl.pack(fill='x', pady=(8, 0))
        self.start_btn = ttk.Button(ctl, text='▶ 开始批量', command=self.start, style='Start.TButton')
        self.start_btn.pack(side='left')
        self.preview_btn = ttk.Button(ctl, text='👁 干跑预览', command=self.preview, style='Preview.TButton')
        self.preview_btn.pack(side='left', padx=(6, 0))
        self.stop_btn = ttk.Button(ctl, text='■ 停止', command=self.stop, state='disabled', style='Stop.TButton')
        self.stop_btn.pack(side='left', padx=(6, 0))
        self.pause_btn = ttk.Button(ctl, text='⏸ 暂停', command=self.toggle_pause,
                                    state='disabled', style='Pause.TButton')
        self.pause_btn.pack(side='left', padx=(6, 0))
        self.rerun_btn = ttk.Button(ctl, text='↻ 重跑失败', command=self.rerun_failed,
                                    state='disabled', style='Rerun.TButton')
        self.rerun_btn.pack(side='left', padx=(6, 0))

        # 断点续跑贴在控制区上方(与“开始”同时看到, 属于本趟怎么跑)
        opt_row = ttk.Frame(bottom); opt_row.pack(fill='x', pady=(6, 0))
        self.resume_var = tk.BooleanVar(value=False)
        self._cbtn(opt_row, '⏭ 断点续跑(已有成片的名字直接跳过)', self.resume_var, side='left')
        self.open_dir_var = tk.BooleanVar(value=True)
        self._cbtn(opt_row, '完成后打开目录', self.open_dir_var, side='left', padx=(14, 0))

        self._runner = None
        self._thread = None
        self._log_serial = 0        # 日志清空序号(用于丢弃清空前排队的日志)

        # 加载已保存的设置 + 初始化模板下拉框
        self._load_all_settings()
        self._templates = {}
        self._refresh_templates()

        # 卡片内控件统一白底(否则标签/勾选框会带页面灰色块)
        for _c in (card1, card2, card3):
            self._retint_card_widgets(_c)

        # 启动链接状态轮询
        self._polling = False
        self._start_link_polling()

        # 暂停/继续热键: Ctrl+P 或 空格键 (运行中可用)
        # 空格必须全局绑定(绑到按钮上无效: ttk.Button 拿不到键盘焦点),
        # 但处理函数里要按焦点让路 —— 焦点在输入框时不能吞掉空格。
        try:
            self.root.bind('<Control-p>', lambda e: self._hotkey_toggle_pause())
            self.root.bind('<space>', lambda e: self._hotkey_toggle_pause())
        except Exception:
            pass

    def _scrollable_left(self, main, bg):
        """左操作区包一层纵向滚动容器。

        控件行数多了之后小窗口会溢出到看不见(默认 960x760 时开始按钮/进度条全部不可见),
        加滚动条才能保证任何尺寸都能触达。滚轮仅在该区域悬停时生效。
        返回 (外层Frame, 放内容的innerFrame)。
        """
        outer = ttk.Frame(main)
        canvas = tk.Canvas(outer, bg=bg, highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        inner = ttk.Frame(canvas)
        win_id = canvas.create_window((0, 0), window=inner, anchor='nw')

        def on_inner(_e=None):
            canvas.configure(scrollregion=canvas.bbox('all'))

        def on_canvas(e):
            canvas.itemconfigure(win_id, width=e.width)   # 内容宽度跟随可视区

        inner.bind('<Configure>', on_inner)
        canvas.bind('<Configure>', on_canvas)

        def wheel(e):
            if inner.winfo_reqheight() <= canvas.winfo_height():
                return None            # 内容没溢出就不接管
            canvas.yview_scroll(int(-1 * (e.delta / 120)), 'units')
            return 'break'

        def bind_wheel(_e=None):
            canvas.bind_all('<MouseWheel>', wheel)

        def unbind_wheel(_e=None):
            canvas.unbind_all('<MouseWheel>')

        canvas.bind('<Enter>', bind_wheel, add='+')
        canvas.bind('<Leave>', unbind_wheel, add='+')
        return outer, inner


    # ---- 设置持久化
    def _current_window_size(self):
        """当前窗口尺寸字符串 'WxH'; 拿不到返回空串"""
        try:
            if self.root.state() == 'zoomed':
                return 'zoomed'   # 记住最大化状态
            return f'{self.root.winfo_width()}x{self.root.winfo_height()}'
        except Exception:
            return ''

    def _apply_window_size(self, v):
        """恢复上次的窗口尺寸(或最大化状态)"""
        s = str(v or '').strip()
        if not s:
            return
        try:
            if s == 'zoomed':
                self.root.state('zoomed')
                return
            import re as _re
            if _re.fullmatch(r'\d+x\d+', s):
                w, h = (int(x) for x in s.split('x'))
                # 防止上次在超大屏上留的尺寸把窗口放到看不见的地方
                w = max(820, min(w, 10000))
                h = max(620, min(h, 10000))
                self.root.geometry(f'{w}x{h}')
        except Exception:
            pass

    def _save_window_size(self):
        """关窗时记下当前尺寸(最大化存 'zoomed')"""
        try:
            self._save_setting('window_size', self._current_window_size())
        except Exception:
            pass

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
            'final_root': self.final_root_var.get().strip(),
            'final_title': self.final_title_var.get().strip(),
            'final_subdir': self.final_subdir_var.get().strip(),
            'final_move': bool(self.final_move_var.get()),
            'final_conflict': self._conflict_policy(),
            'resume': bool(self.resume_var.get()),
            'export_dir': self.export_dir_var.get().strip(),
            'window_size': self._current_window_size(),
            'project': self.project_var.get().strip(),
            'open_dir': bool(self.open_dir_var.get()),
            'auto_run': bool(self.auto_run_var.get()),
            'resolution': self.res_var.get(),
            'framerate': self.fps_var.get(),
            'transparent': bool(self.transparent_var.get()),
            'ffmpeg_path': self.ffmpeg_var.get().strip(),
        }

    def _apply_settings(self, data):
        """把设置 dict 应用到界面 (忽略不存在的键)"""
        if not isinstance(data, dict):
            return
        mapping = {
            'jianying_path': lambda v: self.jy_path_var.set(str(v)),
            'output_dir': lambda v: self.outdir_var.set(str(v)),
            'final_root': lambda v: self.final_root_var.set(str(v)),
            'final_title': lambda v: self.final_title_var.set(str(v)),
            'final_subdir': lambda v: self.final_subdir_var.set(str(v)),
            'final_move': lambda v: self.final_move_var.set(bool(v)),
            'final_conflict': lambda v: self.conflict_var.set(FROM_CONFLICT_VALUE.get(str(v), DEFAULT_CONFLICT_LABEL)),
            'resume': lambda v: self.resume_var.set(bool(v)),
            'export_dir': lambda v: self.export_dir_var.set(str(v)),
            'window_size': lambda v: self._apply_window_size(v),
            'project': lambda v: self.project_var.set(str(v)),
            'open_dir': lambda v: self.open_dir_var.set(bool(v)),
            'auto_run': lambda v: self.auto_run_var.set(bool(v)),
            'resolution': lambda v: self.res_var.set(str(v)),
            'framerate': lambda v: self.fps_var.set(str(v)),
            'transparent': lambda v: self.transparent_var.set(bool(v)),
            'ffmpeg_path': lambda v: self.ffmpeg_var.set(str(v)),
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
        """启动时把 config.json 的全部设置应用到界面。

        读回来的剧名一律视为“可被下次导入覆盖” —— 它只是上次的值,
        不应当作“用户手填”而永远挡住新 CSV 的自动填入。
        """
        try:
            import json
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._apply_settings(data)
        except Exception:
            pass
        # 关键: 把启动读回的剧名当作自动值, 这样下次导入 CSV 会正常覆盖
        self._auto_title = (self.final_title_var.get().strip() or None)

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
            "6. 最终位置 (选填)\n"
            "   填了“最终位置根目录”(如 O:\\AI漫剧剪辑一组)后, 程序会自动在该目录下\n"
            "   按“剧名”寻找对应项目文件夹, 把成片剪切到 项目\\人名条\\ 里。\n"
            "   - 剧名: 导入CSV/TXT时自动用文件名填入, 也可手改\n"
            "   - 子文件夹: 默认“人名条”, 可改成别的名字\n"
            "   - 剪切: 默认勾选(输出目录不留原件); 不勾则只复制\n"
            "   - 投送时机: 全部导出完成后统一剪切, 不是出一条剪一条;\n"
            "     只搬本次生成的成片, 输出目录里的其它文件不会被碰\n"
            "   - 人名条子目录不存在会自动创建\n"
            "   - run_log.csv 留在输出目录, 不随成片拷过去\n"
            "   - 同名处理: 最终目录已有同名文件时的做法\n"
            "     询问(默认, 弹窗让你现场选) / 覆盖 / 自动改名 / 跳过\n"
            "   - 匹配预览: 先看看能定位到哪个项目文件夹, 不改任何文件\n"
            "   匹配失败时不会乱放, 成片留在输出目录并写日志。\n\n"
            "7. 暂停/重跑\n"
            "   运行中可点'⏸ 暂停'或按空格/Ctrl+P 临时暂停/继续。\n"
            "   跑完若有失败, '↻ 重跑失败'按钮会点亮, 一键重试失败的名字。\n\n"
            "8. 干跑预览 (v1.2.0)\n"
            "   点'👁 干跑预览'先不操作剪映, 模拟预览每个名字将导出到哪、\n"
            "   有没有同名/路径问题。适合正式跑之前先试一遍。\n\n"
            "9. 项目模板 (v1.2.0)\n"
            "   把'项目名+输出目录+最终位置+勾选项'存成模板, 下拉框一键加载/删除, 复用常用配置。\n\n"
            "10. 配置备份 (v1.2.0)\n"
            "   '💾 备份配置'把剪映路径/输出目录/项目名/最终位置/勾选项导出为单个 .json, \n"
            "   '📂 恢复配置'换机迁移时一键导入。\n\n"
            "11. 自动执行\n"
            "   勾选'打开草稿并选中后自动开始批量任务', 打开草稿成功即自动跑。\n\n"
            "12. 完成后打开目录\n"
            "   勾选后, 批量完整跑完自动弹出文件夹。\n"
            "   投送成功则弹最终位置(项目\\人名条\\)；未投送则弹输出目录。\n\n"
            "13. 卡在“等文件”怎么办\n"
            "   导出后程序要找到剪映刚生成的文件才能继续。它默认扫:\n"
            "   剪映导出目录(你填的) > 输出目录 > 桌面/视频/下载/文档。\n"
            "   完全不依赖文件名前缀(草稿名不同也能认出), 靠文件新增/大小变化判断。\n"
            "   如果一直等文件: 看日志里列出的“已扫描目录”, 确认剪映导出对话框\n"
            "   里的位置是否在内; 不在就到 高级选项 > 剪映导出目录 里指过去。\n\n"
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

    def _fill_title_from_path(self, path):
        """导入CSV/TXT 时自动把剧名填到“剧名”输入框。

        剧名取自文件名(去序号/后缀), 拿不到则退回父文件夹名 ——
        文件名就是你选的那部剧, 是最可靠的依据。

        覆盖规则:
          - 本次导入前手改过剧名 -> 不覆盖(尊重手填)
          - 其余情况(含上次运行留下的旧剧名) -> 一律用新文件名覆盖
        注意: _auto_title 必须跟剧名一起持久化, 否则重启后旧剧名会被
        误判成“手填”而挡住新导入(之前的 bug)。
        """
        try:
            stem = os.path.splitext(os.path.basename(path))[0]
            cand = clean_title(stem) or os.path.basename(os.path.dirname(path))
            if not cand:
                return
            cur = self.final_title_var.get().strip()
            last_auto = getattr(self, '_auto_title', '') or ''
            # 非空、且不是上一次自动填的 -> 认为用户手改过, 不覆盖
            if cur and cur != last_auto:
                self._log(f'剧名保留手填值: {cur}  (如需用文件名, 请手动改)')
                return
            self.final_title_var.set(cand)
            self._auto_title = cand
            self._log(f'剧名已自动填入: {cand}  (最终位置匹配用)')
        except Exception as ex:
            self._log(f'自动填剧名失败: {ex}')

    def mark_title_manual(self):
        """用户手改剧名: 去掉自动标记, 后续导入不再覆盖它。"""
        self._auto_title = None

    def _on_title_typed(self):
        """剧名框被手工修改: 标记为手填。
        与自动填入值相同的键盘输入不算手改(过滤掉程序自己 set 造成的误判)。"""
        try:
            cur = self.final_title_var.get().strip()
            if cur != (getattr(self, '_auto_title', '') or ''):
                self._auto_title = None
        except Exception:
            pass

    def load_csv(self, auto_preview=True):
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
            self._fill_title_from_path(path)
            if auto_preview:
                self._run_match_preview_async()
        except Exception as ex:
            messagebox.showerror('导入失败', str(ex))

    def load_txt(self, auto_preview=True):
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
            self._fill_title_from_path(path)
            if auto_preview:
                self._run_match_preview_async()
        except Exception as ex:
            messagebox.showerror('导入失败', str(ex))

    def _run_match_preview_async(self):
        """导入后自动弹匹配预览（仅完整版）。

        用 after 延后一拍再弹: 导入时刚 set 完名字框/剧名, 立即开模态窗会在
        事件队列里抢光, 导致界面状态还没刷新完弹窗就出来了。
        精简版没有归档概念, 直接不弹。
        """
        try:
            if LITE:
                return
            if not self.final_root_var.get().strip():
                self._log('（未设置最终位置根目录，跳过自动匹配预览）')
                return
            self.root.after(120, lambda: self.preview_final_match(auto=True))
        except Exception:
            pass

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

    def pick_export_dir(self):
        """选择剪映实际导出目录(用于自动找新导出的文件)"""
        d = filedialog.askdirectory(title='选择剪映导出目录')
        if d:
            self.export_dir_var.set(d)

    def _conflict_policy(self):
        """界面上的“同名处理”选择 -> 策略值"""
        return CONFLICT_LABELS.get(self.conflict_var.get(), 'ask')

    def _ask_conflict(self, conflicts):
        """工作线程调用: 转到主线程弹窗询问同名处理方式。
        返回 overwrite / rename / skip / cancel。"""
        holder, ev = {}, threading.Event()

        def show():
            try:
                holder['ans'] = self._conflict_dialog(conflicts)
            except Exception:
                holder['ans'] = 'cancel'
            finally:
                ev.set()

        try:
            self.root.after(0, show)
        except Exception:
            return 'cancel'
        ev.wait(timeout=900)   # 等用户拍板(最长15分钟)
        return holder.get('ans', 'cancel')

    def _conflict_dialog(self, conflicts):
        """主线程上的同名冲突对话框(四个选项)"""
        top = tk.Toplevel(self.root)
        top.title('最终目录有同名文件')
        top.transient(self.root)
        top.resizable(False, False)
        ans = {'v': 'cancel'}
        ttk.Label(top, text=f'最终目录里已有 {len(conflicts)} 个同名文件:',
                  font=('Microsoft YaHei', 10, 'bold')).pack(anchor='w', padx=14, pady=(12, 4))
        box = tk.Text(top, height=min(8, max(3, len(conflicts))), width=48,
                      font=('Consolas', 9), relief='solid', bd=1)
        box.pack(padx=14)
        for _, d in conflicts[:80]:
            box.insert('end', os.path.basename(d) + '\n')
        if len(conflicts) > 80:
            box.insert('end', f'... 共 {len(conflicts)} 个\n')
        box.config(state='disabled')
        ttk.Label(top, text='覆盖=新文件替掉旧的；自动改名=新文件存为 xxx(1)；跳过=旧文件不动、这几个不投送',
                  foreground='#888888').pack(anchor='w', padx=14, pady=(6, 0))
        row = ttk.Frame(top); row.pack(padx=14, pady=12)

        def pick(v):
            ans['v'] = v
            top.destroy()

        ttk.Button(row, text='覆盖', command=lambda: pick('overwrite')).pack(side='left')
        ttk.Button(row, text='自动改名', command=lambda: pick('rename')).pack(side='left', padx=6)
        ttk.Button(row, text='跳过这些', command=lambda: pick('skip')).pack(side='left')
        ttk.Button(row, text='取消投送', command=lambda: pick('cancel')).pack(side='left', padx=(6, 0))
        top.protocol('WM_DELETE_WINDOW', lambda: pick('cancel'))
        try:
            top.update_idletasks()
            x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - top.winfo_width()) // 2)
            y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - top.winfo_height()) // 3)
            top.geometry(f'+{x}+{y}')
            top.grab_set()
            top.focus_force()
        except Exception:
            pass
        top.wait_window()
        return ans['v']

    def pick_final_root(self):
        """选择最终位置根目录 (如 O:\\AI漫剧剪辑一组)"""
        d = filedialog.askdirectory(title='选择最终位置根目录 (其下是各项目文件夹)')
        if d:
            self.final_root_var.set(d)

    def preview_final_match(self, auto=False):
        """匹配预览（自绘弹窗）。

        auto=True 时供导入 CSV/TXT 后自动调用。
        行为:
          - 匹配成功: 弹窗显示结果, 倒计时 3 秒自动关闭
          - 匹配失败: 弹窗里给剧名输入框 + 「检测」按钮, 改完重试;
            检测成功后转为成功态并倒计时关闭
        """
        root_dir = self.final_root_var.get().strip()
        # 没设最终位置就不弹(没有归档需求)
        if not root_dir:
            if not auto:
                messagebox.showinfo('匹配预览', '请先填写最终位置根目录')
            return
        if not os.path.isdir(root_dir):
            if not auto:
                messagebox.showerror('匹配预览', f'根目录不存在:\n{root_dir}')
            return
        self._open_match_dialog(root_dir, auto=auto)

    def _open_match_dialog(self, root_dir, auto=False):
        """匹配预览弹窗（成功倒计时关闭 / 失败可改剧名重试）"""
        sub = self.final_subdir_var.get().strip() or FINAL_SUBDIR
        names = self._get_names()

        top = tk.Toplevel(self.root)
        top.title('匹配预览')
        top.transient(self.root)
        top.resizable(False, False)
        top.configure(bg=self.C_CARD)

        state = {'timer': None, 'left': 0, 'done': False, 'proj': '', 'why': ''}

        # ---- 顶部结果区
        box = ttk.Frame(top, style='Card.TFrame')
        box.pack(fill='both', expand=True, padx=16, pady=(14, 0))
        title_lb = tk.Label(box, text='', bg=self.C_CARD, fg=self.C_TEXT,
                            font=('Microsoft YaHei', self._F['big'], 'bold'),
                            anchor='w', justify='left')
        title_lb.pack(anchor='w')
        detail_lb = tk.Label(box, text='', bg=self.C_CARD, fg='#5b6270',
                             font=('Microsoft YaHei', self._F['base']),
                             anchor='w', justify='left', wraplength=460)
        detail_lb.pack(anchor='w', pady=(6, 0))

        # ---- 失败时的剧名输入区（成功时 pack_forget 掉）
        retry = ttk.Frame(box, style='Card.TFrame')
        ttk.Label(retry, text='剧名', style='Card.TLabel').pack(side='left')
        edit_var = tk.StringVar(value=self.final_title_var.get().strip())
        edit = ttk.Entry(retry, textvariable=edit_var, width=34)
        edit.pack(side='left', fill='x', expand=True, padx=(6, 6))
        hint_lb = tk.Label(box, text='可直接改成项目文件夹里的剧名（如剧名本身），再点「检测」',
                           bg=self.C_CARD, fg=self.C_HINT,
                           font=('Microsoft YaHei', self._F['small']),
                           anchor='w', justify='left')

        # ---- 底部按钮区
        row = ttk.Frame(top, style='Card.TFrame')
        row.pack(fill='x', padx=16, pady=(12, 14))
        btn_check = ttk.Button(row, text='检测')
        btn_ok = ttk.Button(row, text='确定')
        btn_cancel = ttk.Button(row, text='关闭')

        def cancel_timer():
            if state['timer']:
                try:
                    top.after_cancel(state['timer'])
                except Exception:
                    pass
                state['timer'] = None

        def close(_e=None):
            cancel_timer()
            try:
                top.destroy()
            except Exception:
                pass

        def show_success(proj, why):
            state['done'] = True
            state['proj'] = proj
            state['why'] = why
            d = os.path.join(root_dir, proj, sub)
            exist = len(os.listdir(d)) if os.path.isdir(d) else 0
            act = '剪切' if self.final_move_var.get() else '复制'
            title_lb.config(text='✓ 匹配成功', fg='#1e8e4e')
            detail_lb.config(text=f'项目文件夹：{proj}\n匹配依据：{why}\n'
                                  f'成片将{act}到：{d}\n（该目录现有 {exist} 个文件）')
            # 失败态 UI 消失, 按钮收起
            try:
                retry.pack_forget(); hint_lb.pack_forget()
                btn_check.pack_forget(); btn_cancel.pack_forget()
            except Exception:
                pass
            btn_ok.pack(side='right')
            # 3 秒倒计时后自动关
            state['left'] = 3
            def tick():
                if not state.get('done'):
                    return
                state['left'] -= 1
                if state['left'] > 0:
                    btn_ok.config(text=f'确定 ({state["left"]}s)')
                    state['timer'] = top.after(1000, tick)
                else:
                    close()
            btn_ok.config(text=f'确定 ({state["left"]}s)')
            state['timer'] = top.after(1000, tick)
            self._log(f'✓ 匹配预览: {d}   [{why}]')

        def show_failure(why):
            title_lb.config(text='✗ 未匹配到项目文件夹', fg='#c0392b')
            detail_lb.config(text=f'原因：{why}\n根目录：{root_dir}')
            retry.pack(fill='x', pady=(12, 2))
            hint_lb.pack(anchor='w', pady=(0, 0))
            btn_ok.pack_forget()
            btn_check.pack(side='right', padx=(0, 6))
            btn_cancel.pack(side='right')
            cancel_timer()
            try:
                edit.focus_set()
                edit.select_range(0, 'end')
            except Exception:
                pass
            self._log(f'✗ 匹配预览失败: {why}')

        def do_check():
            t = edit_var.get().strip()
            if not t:
                title_lb.config(text='✗ 剧名不能为空', fg='#c0392b')
                return
            proj, why = match_project(root_dir, t, names)
            if proj:
                # 回写剧名, 让后续投送用这个值
                self.final_title_var.set(t)
                self._auto_title = t
                show_success(proj, why)
            else:
                show_failure(why)
                detail_lb.config(text=f'原因：{why}\n剧名：{t}\n根目录：{root_dir}')

        btn_check.config(command=do_check)
        btn_ok.config(command=close)
        btn_cancel.config(command=close)
        edit.bind('<Return>', lambda e: do_check())
        top.protocol('WM_DELETE_WINDOW', close)

        # 首次匹配（优先用输入框里的剧名, 空则用界面上的）
        first = (edit_var.get().strip() or self.final_title_var.get().strip())
        proj, why = match_project(root_dir, first, names)
        if proj:
            show_success(proj, why)
        else:
            show_failure(why)

        # 居中于主窗口
        try:
            top.update_idletasks()
            x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - top.winfo_width()) // 2)
            y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - top.winfo_height()) // 3)
            top.geometry(f'+{x}+{y}')
            if not state['done']:
                top.grab_set()      # 失败态需要交互, 模态
            else:
                top.lift()
        except Exception:
            pass

    def pick_ffmpeg(self):
        """选择 ffmpeg 可执行文件 (用于导出后转透明通道)"""
        p = filedialog.askopenfilename(
            title='选择 ffmpeg.exe',
            filetypes=[('ffmpeg', 'ffmpeg.exe'), ('可执行文件', '*.exe')])
        if p:
            self.ffmpeg_var.set(p)

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
                                 progress_cb=self._on_progress, dry_run=True,
                                 transparent=self.transparent_var.get(),
                                 ffmpeg_path=self.ffmpeg_var.get().strip(),
                                 final_root=self.final_root_var.get(),
                                 final_title=self.final_title_var.get(),
                                 final_subdir=self.final_subdir_var.get(),
                                 final_move=self.final_move_var.get(),
                                 conflict_policy=self._conflict_policy(),
                                 resume=self.resume_var.get(),
                                 export_dir=self.export_dir_var.get())
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
                                       progress_cb=self._on_progress,
                                       transparent=self.transparent_var.get(),
                                       ffmpeg_path=self.ffmpeg_var.get().strip(),
                                       final_root=self.final_root_var.get(),
                                       final_title=self.final_title_var.get(),
                                       final_subdir=self.final_subdir_var.get(),
                                       final_move=self.final_move_var.get(),
                                       conflict_policy=self._conflict_policy(),
                                       conflict_cb=self._ask_conflict,
                                       resume=self.resume_var.get(),
                                       export_dir=self.export_dir_var.get())
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
        # 勾选'完成后打开成品目录'且完整跑完时, 优先打开最终位置(投送落盘处), 退到输出目录
        if completed and self.open_dir_var.get():
            runner = self._runner
            final_dir = getattr(runner, '_final_dir', '') if runner else ''
            delivered = bool(getattr(runner, '_final_delivered', 0)) if runner else False
            outdir = (getattr(runner, '_outdir_actual', '') if runner else '') or self.outdir_var.get().strip() or DEFAULT_OUTDIR
            # 投送成功且最终目录存在 -> 打开最终位置; 否则打开输出目录
            target = final_dir if (delivered and final_dir and os.path.isdir(final_dir)) else outdir
            label = '最终位置' if target == final_dir else '输出目录'
            if os.path.isdir(target):
                try:
                    os.startfile(target)
                    self._log(f'📁 已打开{label}: {target}')
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
        """一键重跑上次失败的名字。

        不破坏用户原来的全量名单: 重跑直接在后台跑失败名单, 界面上的名字列表保持不动,
        (以前会把它换成失败名单, 导致全量名单丢失、想再全跑得重新导入。)"""
        if not self._last_fail_names:
            messagebox.showinfo('重跑失败', '没有失败的名字可重跑')
            return
        fails = list(self._last_fail_names)
        onscreen = self._get_names()
        self._log(f'↻ 重跑失败 {len(fails)} 个: {", ".join(fails)}')
        if set(fails) != set(onscreen):
            self._log(f'   (名字列表保持为原全量 {len(onscreen)} 个, 未被覆盖)')
        self._start_run(fails, self.outdir_var.get().strip() or DEFAULT_OUTDIR)

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

    def _focus_is_text(self):
        """当前焦点是否在文本输入类控件上(名字框/输入框/下拉框)。
        用 winfo_class 判断, 不依赖具体控件引用, 后续新增输入框也能自动受保护。"""
        try:
            w = self.root.focus_get()
        except Exception:
            return False
        if w is None:
            return False
        try:
            return w.winfo_class() in ('Text', 'Entry', 'TEntry', 'TCombobox', 'Spinbox', 'TSpinbox')
        except Exception:
            return False

    def _hotkey_toggle_pause(self):
        """热键触发暂停。

        两种情况必须放行(不拦键、不暂停):
          1. 焦点在输入框 —— 用户是在打空格(名字里常带空格, 如 Amanda Sterling)
          2. 没在运行或暂停按钮不可用 —— 热键无意义, 不该吞掉按键

        注: ttk 的 cget('state') 返回 Tcl 对象, 与字符串 'disabled' 直接比较不可靠,
        必须用 instate(['disabled']) 判断。
        """
        if self._focus_is_text():
            return None                       # 让空格正常输入
        if not getattr(self, '_running', False):
            return None
        try:
            if self.pause_btn.instate(['disabled']):
                return None
        except Exception:
            pass
        self.toggle_pause()
        return 'break'

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
        """后台检测剪映连接状态, 完成后调度下一次轮询。

        _link_checking 必须由后台线程真正结束时才清掉(而不是主线程定时器),
        否则剪映未开时查找窗口要重试很久, 主线程却提前补新线程 -> 并发堆积。"""
        if not getattr(self, '_polling', True):
            return
        # 上一次检测还在跑: 稍后再看, 不再起新线程
        if getattr(self, '_link_checking', False):
            self.root.after(500, self._poll_link_status)
            return
        self._link_checking = True
        holder = {}

        def _finish():
            """后台线程结束(无论成败)后在主线程收尾并安排下一轮"""
            self._link_checking = False
            ok = bool(holder.get('ok'))
            if ok:
                self._set_link_status('connected', '已连接')
            else:
                self._set_link_status('disconnected', '未连接')
            # 状态发生变化时写一条日志, 便于回溯(不在每轮轮询里刷屏)
            prev = getattr(self, '_link_last_ok', None)
            if ok != prev:
                self._link_last_ok = ok
                if ok:
                    self._log('✔ 已连接剪映，可以开始批量')
                else:
                    self._log('⚠ 未连接剪映：请确认剪映已打开并停留在编辑页'
                              '（用上方“启动剪映”按钮可直接启动）')
            if getattr(self, '_polling', True):
                self.root.after(self.LINK_POLL_MS, self._poll_link_status)

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
            finally:
                # 只有线程真结束才清标志位, 从根上避免多线程同时探测
                try:
                    self.root.after(0, _finish)
                except Exception:
                    self._link_checking = False

        threading.Thread(target=worker, daemon=True).start()

    def _log(self, msg):
        serial = self._log_epoch()          # 记录写入时的清空序号
        def do():
            # 这条日志排队期间用户点了“清空” -> 丢弃, 不再补写回去
            if serial != self._log_epoch():
                return
            self.log_box.config(state='normal')
            self.log_box.insert('end', msg + '\n')
            self.log_box.see('end')
            self.log_box.config(state='disabled')
        try: self.root.after(0, do)
        except Exception: pass

    # ---- 日志复制 / 导出 / 清空
    def _log_epoch(self):
        return getattr(self, '_log_serial', 0)

    def _log_text(self):
        try:
            return self.log_box.get('1.0', 'end').rstrip('\n')
        except Exception:
            return ''

    def copy_log(self):
        """把整个日志框内容复制到剪贴板"""
        txt = self._log_text()
        if not txt:
            messagebox.showinfo('复制日志', '日志为空')
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(txt)
        self.root.update()
        self._log(f'📋 已复制日志到剪贴板 ({len(txt)} 字符)')

    def export_log(self):
        """把日志存成 .txt 文件(默认放到输出目录, 便于随项目留档/发给别人)"""
        txt = self._log_text()
        if not txt:
            messagebox.showinfo('导出日志', '日志为空')
            return
        init_dir = self.outdir_var.get().strip() or DEFAULT_OUTDIR
        init_name = f'人名条日志_{time.strftime("%Y%m%d_%H%M%S")}.txt'
        path = filedialog.asksaveasfilename(
            title='导出日志', defaultextension='.txt', initialfile=init_name,
            initialdir=init_dir if os.path.isdir(init_dir) else None,
            filetypes=[('文本文件', '*.txt'), ('所有', '*.*')])
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(txt + '\n')
            self._log(f'📄 日志已导出: {path}')
        except Exception as ex:
            messagebox.showerror('导出失败', str(ex))

    def clear_log(self):
        """清空日志框。

        _log 走 after 排队写入, 所以清空时必须把“清空前排队的那些行”一并丢弃,
        否则刚清完、界面一刷新旧行又冒出来。用序号(serial)标识清空点。"""
        self._log_serial = self._log_epoch() + 1
        try:
            self.log_box.config(state='normal')
            self.log_box.delete('1.0', 'end')
            self.log_box.config(state='disabled')
        except Exception:
            pass
        return 'break'


def startup_check(root, app):
    """启动时预热剪映连接(不阻塞界面, 也不下“未连接”结论)。

    这里曾用 4 秒超时在主线程试连一次, 超时就写“未检测到剪映”。
    问题: 首次加载 COM + UIA DLL 本身可能超过 4 秒(尤其是刚开机/首次运行),
    于是日志先写了一条“未检测到”, 而随后轮询很快又显示“已连接”, 前后矛盾。
    现在只做预热, 真正的状态一律以连续轮询为准。
    """
    root.update()
    root.deiconify()
    connect_jianying_timeout(activate=True, timeout=4)   # 预热, 结果不重要
    return True


def main():
    # 必须在创建任何窗口前开 DPI 感知, 否则高分屏上整窗被拉伸发虚
    _aware = enable_dpi_awareness()
    root = tk.Tk()
    app = App(root)
    app._dpi_awareness = _aware
    try:
        app._log(f'DPI 感知: {_aware} · 缩放 {get_dpi_scale(root):.2f}x')
    except Exception:
        pass
    # 关窗前记下窗口尺寸, 下次启动恢复
    try:
        root.protocol('WM_DELETE_WINDOW', lambda: (app._save_window_size(), root.destroy()))
    except Exception:
        pass
    # 启动检测(非阻塞): 检测剪映是否可连
    startup_check(root, app)
    app._log("就绪：请在剪映中保持已选中的字幕条")
    app._log(f"设置文件：{SETTINGS_FILE}")
    root.mainloop()

if __name__ == '__main__':
    main()
