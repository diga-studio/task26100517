"""协作思维导图撤销库：多用户交错编辑下的按人撤销/重做。"""

from .core import MindMap
from .errors import DuplicateNodeError, InvalidTreeError, MindMapError, UnknownNodeError
from .model import HISTORY_WINDOW, MAX_DEPTH, NodePatch, NodeState

__all__ = [
    "MindMap",
    "MindMapError",
    "InvalidTreeError",
    "UnknownNodeError",
    "DuplicateNodeError",
    "NodePatch",
    "NodeState",
    "MAX_DEPTH",
    "HISTORY_WINDOW",
]

__version__ = "0.1.0"
