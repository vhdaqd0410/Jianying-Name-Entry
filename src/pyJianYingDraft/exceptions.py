# -*- coding: utf-8 -*-
"""剪映自动化异常定义"""


class JianyingError(Exception):
    """剪映自动化基础异常"""


class AutomationError(JianyingError):
    """剪映自动化操作失败"""


class DraftNotFound(JianyingError):
    """未找到指定名称的剪映草稿"""
