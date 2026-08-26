# -*- coding: utf-8 -*-
"""剪映自动化控制（精简自包含版）
仅保留海外人名条批量导出所需的窗口查找、文字框定位与导出完成等待逻辑。
独立于 capcut-mate，仅依赖 uiautomation。原版源自 capcut-mate 的 jianying_controller。
"""
import ctypes
import logging
import sys
import time

if sys.platform != "win32":
    raise ImportError("JianyingController is only available on Windows platform")

try:
    import uiautomation as uia
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "Missing required Windows dependency uiautomation. "
        "Please install with: pip install -r requirements.txt"
    ) from e

from typing import Optional, Literal, Callable

from .exceptions import AutomationError, DraftNotFound

logger = logging.getLogger("jianying")

# Windows UI Automation COM 错误
COM_UIA_ERROR_HRESULT = -2147220991
COM_UIA_ERROR_MARKER = "事件无法调用任何订户"
COM_E_FAIL_HRESULT = -2147467259
COM_E_FAIL_MARKER = "未指定的错误"
UIA_CLICK_MAX_RETRIES = 4
UIA_CLICK_RETRY_INTERVAL = 1.0


def is_com_uia_error(exc: BaseException) -> bool:
    """判断异常是否为 UIA COM 偶发错误（可安全重试）"""
    text = str(exc)
    return (
        str(COM_UIA_ERROR_HRESULT) in text
        or str(COM_E_FAIL_HRESULT) in text
        or COM_UIA_ERROR_MARKER in text
        or COM_E_FAIL_MARKER in text
    )


class ControlFinder:
    """控件查找器，封装控件查找匹配逻辑"""

    @staticmethod
    def desc_matcher(target_desc: str, depth: int = 2, exact: bool = False) -> Callable[[uia.Control, int], bool]:
        """根据 full_description 查找控件的匹配器"""
        target_desc = target_desc.lower()

        def matcher(control: uia.Control, _depth: int) -> bool:
            if _depth != depth:
                return False
            full_desc: str = control.GetPropertyValue(30159).lower()
            return (target_desc == full_desc) if exact else (target_desc in full_desc)

        return matcher


class JianyingController:
    """剪映控制器（精简版，仅导出所需能力）"""

    WINDOW_FIND_MAX_RETRIES = 12
    WINDOW_FIND_RETRY_INTERVAL = 1.0

    app: uia.WindowControl
    app_status: Literal["home", "edit", "pre_export"]
    app_sub_status: Literal["none", "export_start", "exporting", "export_succeed"]

    def __init__(self):
        """初始化剪映控制器，此时剪映应处于目录或编辑页"""
        self.get_window()

    # ------------------------------------------------------------------ 底层工具
    def _safe_click(
        self,
        get_control: Callable[[], uia.Control],
        operation: str,
        *,
        exists_timeout: float = 1.0,
        max_retries: int = UIA_CLICK_MAX_RETRIES,
        retry_interval: float = UIA_CLICK_RETRY_INTERVAL,
    ) -> None:
        """带 COM 重试的控件点击"""
        last_exc: Optional[BaseException] = None
        for attempt in range(1, max_retries + 1):
            try:
                control = get_control()
                if not control.Exists(exists_timeout, 0.5):
                    raise AutomationError(f"{operation}: control not found")
                control.Click(simulateMove=False)
                return
            except Exception as exc:
                last_exc = exc
                if not is_com_uia_error(exc) or attempt >= max_retries:
                    logger.error(
                        "UIA click failed: operation=%s attempt=%d/%d error=%r",
                        operation, attempt, max_retries, exc,
                    )
                    raise
                logger.warning("UIA COM error on click, retrying: operation=%s attempt=%d/%d",
                               operation, attempt, max_retries)
                time.sleep(retry_interval)
                self.get_window()
        if last_exc is not None:
            raise last_exc

    def _exists_with_com_retry(
        self,
        control: uia.Control,
        operation: str,
        *,
        timeout: float = 0,
        max_retries: int = UIA_CLICK_MAX_RETRIES,
        retry_interval: float = UIA_CLICK_RETRY_INTERVAL,
        raise_on_exhausted: bool = True,
    ) -> bool:
        """对单个控件的 Exists 调用做 COM 重试"""
        search_interval = 0.5 if timeout > 0 else 0
        last_exc: Optional[BaseException] = None
        for attempt in range(1, max_retries + 1):
            try:
                return control.Exists(timeout, search_interval)
            except Exception as exc:
                last_exc = exc
                if not is_com_uia_error(exc) or attempt >= max_retries:
                    logger.error("UIA Exists failed: operation=%s attempt=%d/%d error=%r",
                                 operation, attempt, max_retries, exc)
                    if raise_on_exhausted:
                        raise
                    return False
                logger.warning("UIA COM error on Exists, retrying: operation=%s attempt=%d/%d",
                               operation, attempt, max_retries)
                time.sleep(retry_interval)
        if last_exc is not None:
            if raise_on_exhausted:
                raise last_exc
            return False
        return False

    def _safe_exists(
        self,
        get_control: Callable[[], uia.Control],
        operation: str,
        *,
        timeout: float = 0.5,
        max_retries: int = UIA_CLICK_MAX_RETRIES,
        retry_interval: float = UIA_CLICK_RETRY_INTERVAL,
    ) -> bool:
        """带 COM 重试的控件 Exists 检测"""
        last_exc: Optional[BaseException] = None
        for attempt in range(1, max_retries + 1):
            try:
                return get_control().Exists(timeout, 0.5)
            except Exception as exc:
                last_exc = exc
                if not is_com_uia_error(exc) or attempt >= max_retries:
                    logger.error("UIA Exists failed: operation=%s attempt=%d/%d error=%r",
                                 operation, attempt, max_retries, exc)
                    raise
                logger.warning("UIA COM error on Exists, retrying: operation=%s attempt=%d/%d",
                               operation, attempt, max_retries)
                time.sleep(retry_interval)
                self.get_window()
        if last_exc is not None:
            raise last_exc
        return False

    # ------------------------------------------------------------------ 导出完成
    def _make_export_succeed_close_btn(self, *, from_export_window: bool = False) -> uia.Control:
        root = self.app
        if from_export_window:
            root = self.app.WindowControl(searchDepth=2, Name="导出")
        return root.TextControl(
            searchDepth=2 if from_export_window else 3,
            Compare=ControlFinder.desc_matcher("ExportSucceedCloseBtn"),
        )

    def _find_export_succeed_close_btn(self) -> Optional[uia.Control]:
        if self._safe_exists(
            lambda: self._make_export_succeed_close_btn(from_export_window=False),
            "find_export_succeed_close_btn.main",
        ):
            return self._make_export_succeed_close_btn(from_export_window=False)

        if self._safe_exists(
            lambda: self.app.WindowControl(searchDepth=2, Name="导出"),
            "find_export_succeed_close_btn.export_window",
        ):
            if self._safe_exists(
                lambda: self._make_export_succeed_close_btn(from_export_window=True),
                "find_export_succeed_close_btn.in_export_window",
            ):
                return self._make_export_succeed_close_btn(from_export_window=True)
        return None

    def _require_export_succeed_close_btn(self) -> uia.Control:
        btn = self._find_export_succeed_close_btn()
        if btn is None:
            raise AutomationError("export succeed close button not found")
        return btn

    def _minimize_window(self) -> None:
        """最小化剪映主窗口（后台运行）"""
        try:
            hwnd = self.app.NativeWindowHandle
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
                logger.info("Jianying window minimized for background run")
        except Exception as exc:
            logger.warning("Failed to minimize Jianying window: %r", exc)

    def _poll_export_completion_no_focus(self) -> bool:
        """轻量轮询：不激活窗口，仅检查导出是否完成（成功关闭按钮是否出现）"""
        try:
            export_win = self.app.WindowControl(searchDepth=1, Name="导出")
            if self._safe_exists(
                lambda: self._make_export_succeed_close_btn(from_export_window=True),
                "poll_export_completion.main",
            ):
                return True
            return export_win.Exists(0)
        except Exception:
            return False

    def _restore_and_activate(self) -> None:
        """恢复并激活剪映主窗口到前台"""
        try:
            hwnd = self.app.NativeWindowHandle
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                time.sleep(0.5)
                self.app.SetActive()
                time.sleep(0.5)
        except Exception as exc:
            logger.warning("Failed to restore/activate Jianying window: %r", exc)

    def wait_for_export_completion(self, timeout: float, *, minimize: bool = False) -> bool:
        """等待导出完成

        Args:
            timeout: 超时时间（秒）
            minimize: 是否在渲染等待期最小化窗口。默认 False（保持前台，不最小化）

        Returns:
            bool: 是否已关闭导出成功弹窗
        Raises:
            AutomationError: 导出超时
        """
        export_succeeded = False

        if minimize:
            self._minimize_window()

        st = time.time()
        while True:
            if self._poll_export_completion_no_focus():
                if minimize:
                    logger.info("Export finished, restoring window to close success dialog")
                    self._restore_and_activate()
                    time.sleep(1)
                self._safe_click(
                    self._require_export_succeed_close_btn,
                    "wait_for_export_completion.close_success",
                )
                time.sleep(2)
                export_succeeded = True
                break

            if time.time() - st > timeout:
                if minimize:
                    self._restore_and_activate()
                raise AutomationError("导出超时, 时限为%d秒" % timeout)

            time.sleep(1)
        time.sleep(2)
        return export_succeeded

    # ------------------------------------------------------------------ 窗口连接
    def init_export_sub_status(self) -> None:
        if self.app_status == "pre_export":
            self.app_sub_status = "exporting"
            export_ok_btn = self.app.TextControl(
                searchDepth=2, Compare=ControlFinder.desc_matcher("ExportOkBtn", exact=True)
            )
            if export_ok_btn.Exists(0):
                self.app_sub_status = "export_start"
                return
            if self._safe_exists(
                lambda: self._make_export_succeed_close_btn(from_export_window=False),
                "init_export_sub_status.export_succeed",
                timeout=0,
            ):
                self.app_sub_status = "export_succeed"
                return
        else:
            self.app_sub_status = "none"

    def __jianying_window_cmp(self, control: uia.WindowControl, depth: int) -> bool:
        try:
            name = control.Name
        except Exception:
            return False
        if name != "剪映专业版":
            return False
        try:
            class_name = control.ClassName
        except Exception:
            return False
        class_name_lower = class_name.lower()
        if "homepage" in class_name_lower:
            self.app_status = "home"
            return True
        if "mainwindow" in class_name_lower:
            self.app_status = "edit"
            return True
        return False

    def get_window(
        self,
        max_retries: Optional[int] = None,
        retry_interval: Optional[float] = None,
    ) -> None:
        """寻找剪映窗口；未找到时按间隔重试"""
        if max_retries is None:
            max_retries = self.WINDOW_FIND_MAX_RETRIES
        if retry_interval is None:
            retry_interval = self.WINDOW_FIND_RETRY_INTERVAL

        if hasattr(self, "app"):
            try:
                if self._exists_with_com_retry(
                    self.app, "get_window.clear_topmost",
                    timeout=0, raise_on_exhausted=False,
                ):
                    self.app.SetTopmost(False)
            except Exception:
                pass

        for attempt in range(max_retries):
            self.app = uia.WindowControl(searchDepth=1, Compare=self.__jianying_window_cmp)
            if self._exists_with_com_retry(
                self.app, "get_window.find_main",
                timeout=0, raise_on_exhausted=False,
            ):
                if attempt > 0:
                    logger.info("Jianying main window matched on attempt %d/%d", attempt + 1, max_retries)
                break
            if attempt < max_retries - 1:
                time.sleep(retry_interval)
        else:
            raise AutomationError(
                "Jianying window not found after %d attempts (%.1fs interval); "
                "ensure Jianying Pro is open on the home or edit screen."
                % (max_retries, retry_interval)
            )

        export_window = self.app.WindowControl(searchDepth=1, Name="导出")
        if self._exists_with_com_retry(
            export_window, "get_window.find_export",
            timeout=0, raise_on_exhausted=False,
        ):
            self.app = export_window
            self.app_status = "pre_export"

        self.init_export_sub_status()

        logger.info("app_status: %s, app_sub_status: %s", self.app_status, self.app_sub_status)

        self.app.SetActive()
        try:
            self.app.SetTopmost(False)
        except Exception:
            pass

    # ------------------------------------------------------------------ 打开草稿
    def find_and_click_draft(self, draft_name: str, max_retries: int = 6, retry_interval: float = 5.0) -> None:
        """在剪映首页查找并点击打开指定名称的草稿

        Args:
            draft_name: 草稿名称
            max_retries: 最大重试次数
            retry_interval: 重试间隔(秒)

        Raises:
            DraftNotFound: 未找到指定名称的剪映草稿
        """
        last_exc: Optional[BaseException] = None
        for attempt in range(max_retries):
            try:
                draft_text = self.app.TextControl(
                    searchDepth=2,
                    Compare=ControlFinder.desc_matcher(f"HomePageDraftTitle:{draft_name}", exact=True),
                )
                if not self._safe_exists(
                    lambda: draft_text, "find_and_click_draft.find", timeout=0
                ):
                    raise DraftNotFound(f"未找到名为{draft_name}的剪映草稿")
                draft_btn = draft_text.GetParentControl()
                if draft_btn is None:
                    raise DraftNotFound(f"草稿{draft_name}无父控件")
                logger.info("found draft %s, clicking", draft_name)
                self._safe_click(lambda: draft_btn, f"find_and_click_draft.click:{draft_name}")
                # 等草稿加载进入编辑页
                time.sleep(8)
                self.get_window()
                return
            except DraftNotFound as e:
                last_exc = e
                if attempt < max_retries - 1:
                    logger.info("draft %s not found, retry %d/%d", draft_name, attempt + 1, max_retries)
                    time.sleep(retry_interval)
                    self.get_window()
        if last_exc is not None:
            raise last_exc
        raise DraftNotFound(f"未找到名为{draft_name}的剪映草稿")

    def click_subtitle_clip(self) -> bool:
        """在编辑页时间轴上找到字幕条并点击选中。

        字幕条位于 MainTimeLine 内的 GroupControl(QQuickItem)，内部含 QQuickText 显示文字。
        点击其中心坐标以选中，便于后续替换文字。

        Returns:
            bool: 是否成功点击字幕条
        """
        try:
            # MainTimeLine 是主窗口的直接子控件(depth=1), 用浅层查找大幅减少UIA遍历时间
            tl = self.app.Control(
                searchDepth=3, ClassName="MainTimeLine_QMLTYPE_494"
            )
            if not self._safe_exists(lambda: tl, "click_subtitle_clip.find_timeline", timeout=0.3):
                logger.warning("timeline not found")
                return False
            # 时间轴内的字幕条: GroupControl(QQuickItem), 内部含 QQuickText
            candidates = []
            for child in tl.GetChildren():
                try:
                    cn = child.ClassName
                except Exception:
                    continue
                if cn.startswith("QQuickItem"):
                    # 字幕条是扁横条(高度明显小于宽度)
                    try:
                        r = child.BoundingRectangle
                    except Exception:
                        continue
                    w = r.right - r.left
                    h = r.bottom - r.top
                    if w > 100 and h < 60 and w > h:
                        candidates.append(child)
            if not candidates:
                logger.warning("no subtitle clip found in timeline")
                return False
            # 点击第一个(通常即当前可见/目标字幕条), 点击确认用短超时
            target = candidates[0]
            r = target.BoundingRectangle
            cx, cy = (r.left + r.right) // 2, (r.top + r.bottom) // 2
            self._safe_click(lambda: target, "click_subtitle_clip.click", exists_timeout=0.3)
            logger.info("clicked subtitle clip at (%d,%d)", cx, cy)
            time.sleep(0.2)
            return True
        except Exception as exc:
            logger.error("click_subtitle_clip failed: %r", exc)
            return False

    def open_draft_and_select_subtitle(self, draft_name: str) -> bool:
        """打开指定草稿并点击选中字幕条（组合操作）

        Args:
            draft_name: 草稿名称

        Returns:
            bool: 是否成功打开草稿并选中字幕条
        """
        try:
            self.find_and_click_draft(draft_name)
            return self.click_subtitle_clip()
        except DraftNotFound as e:
            logger.error("open_draft failed: %r", e)
            return False
