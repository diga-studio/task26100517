"""思维导图协作撤销库。"""

from .errors import FailureReason, OpResult
from .session import MapSession, WINDOW_SIZE
from .tree import MAX_DEPTH

__all__ = ["MapSession", "OpResult", "FailureReason", "WINDOW_SIZE", "MAX_DEPTH"]
