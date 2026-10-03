"""内部数据模型：字段编辑记录与编辑批次。"""

from __future__ import annotations

from typing import Any, Dict, Hashable, Optional, Tuple

NodeId = Hashable
Field = str  # "title" 或 "parent"
FieldKey = Tuple[NodeId, Field]

FIELD_TITLE: Field = "title"
FIELD_PARENT: Field = "parent"
FIELDS = (FIELD_TITLE, FIELD_PARENT)


class Edit:
    """一次字段写入。同一字段的 Edit 按生效先后压入该字段的栈。

    permanent 为 True 表示所属批次已滑出历史窗口，该编辑永远不可再被弹出，
    其下的所有历史编辑都可以被压缩回收。
    """

    __slots__ = ("batch_id", "value", "permanent")

    def __init__(self, batch_id: int, value: Any) -> None:
        self.batch_id = batch_id
        self.value = value
        self.permanent = False


class Batch:
    """一次成功提交的编辑批次。"""

    __slots__ = ("batch_id", "user", "writes", "edits", "undone", "restored")

    def __init__(self, batch_id: int, user: Hashable,
                 writes: Dict[FieldKey, Any]) -> None:
        self.batch_id = batch_id
        self.user = user
        # (node, field) -> 新值
        self.writes = writes
        # (node, field) -> 本批次在该字段压入的 Edit
        self.edits: Dict[FieldKey, Edit] = {}
        self.undone = False
        # 撤销时记录每个字段恢复出的 Edit（None 表示恢复到初始状态），供重做校验
        self.restored: Optional[Dict[FieldKey, Optional[Edit]]] = None
