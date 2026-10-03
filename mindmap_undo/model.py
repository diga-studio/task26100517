"""对外暴露的数据类型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

#: 导图允许的最大深度（根深度为 0）。
MAX_DEPTH = 15

#: 每图可成为撤销/重做目标的最近成功批次数。
HISTORY_WINDOW = 200

#: 标题字段名。
FIELD_TITLE = "title"

#: 父节点字段名。
FIELD_PARENT = "parent"

#: 允许在批次中写入的字段名。
WRITABLE_FIELDS = (FIELD_TITLE, FIELD_PARENT)


@dataclass(frozen=True)
class NodeState:
    """某一时刻单个节点的对外只读状态。"""

    node_id: str
    title: str
    parent_id: Optional[str]
    depth: int


@dataclass(frozen=True)
class NodePatch:
    """批次中对单个节点的修改；字段为 None 表示不修改。"""

    title: Optional[str] = None
    parent_id: Optional[str] = None
