"""异常类型定义。"""


class MindMapError(Exception):
    """库内所有异常的基类。"""


class InvalidTreeError(MindMapError):
    """初始导图或提交批次会导致非法树（成环、脱离根、超深、根父节点被改等）。"""


class UnknownNodeError(MindMapError):
    """批次引用了不存在的节点或字段。"""


class DuplicateNodeError(MindMapError):
    """初始导图包含重复节点标识。"""
