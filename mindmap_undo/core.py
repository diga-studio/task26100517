"""协作思维导图撤销库核心实现。"""

from __future__ import annotations

from typing import Dict, Mapping, Optional, Tuple

from .errors import DuplicateNodeError, InvalidTreeError, UnknownNodeError
from .model import (
    FIELD_PARENT,
    FIELD_TITLE,
    HISTORY_WINDOW,
    MAX_DEPTH,
    NodePatch,
    NodeState,
)

# 字段键：(节点标识, 字段名)。
FieldKey = Tuple[str, str]


class _Edit:
    """一个批次对单个字段的一次写入。"""

    __slots__ = ("batch", "value")

    def __init__(self, batch: "_Batch", value: object) -> None:
        self.batch = batch
        self.value = value


class _FieldHistory:
    """单个字段的编辑历史：初始值 + 按提交顺序的编辑列表。"""

    __slots__ = ("base_value", "edits")

    def __init__(self, base_value: object) -> None:
        self.base_value = base_value
        self.edits: list[_Edit] = []

    def effective_edit(self) -> Optional[_Edit]:
        """当前生效的编辑；没有生效编辑时返回 None（表示初始值）。"""
        for edit in reversed(self.edits):
            if edit.batch.active:
                return edit
        return None

    def effective_value(self) -> object:
        edit = self.effective_edit()
        return self.base_value if edit is None else edit.value


class _Batch:
    """一次成功提交的编辑批次。"""

    __slots__ = ("batch_id", "user_id", "writes", "active", "evicted", "undo_record")

    def __init__(self, batch_id: int, user_id: str) -> None:
        self.batch_id = batch_id
        self.user_id = user_id
        self.writes: Dict[FieldKey, _Edit] = {}
        self.active = True
        self.evicted = False
        self.undo_record: Optional[Dict[FieldKey, Optional[_Edit]]] = None


def _validate_tree(parents: Mapping[str, Optional[str]], root_id: str) -> Dict[str, int]:
    """校验整棵树：全部节点属于同一棵树、根深度为 0、最大深度不超过 MAX_DEPTH。

    返回各节点深度；非法时抛出 InvalidTreeError。
    """
    if parents.get(root_id) is not None:
        raise InvalidTreeError("根节点的父节点必须为空")
    depths: Dict[str, int] = {}
    for node_id in parents:
        if node_id in depths:
            continue
        # 沿父链向上走，记录路径以检测环。
        path: list[str] = []
        cursor = node_id
        while cursor not in depths:
            if cursor in path:
                raise InvalidTreeError(f"节点 {cursor!r} 处于环中")
            parent = parents.get(cursor)
            if parent is None:
                if cursor != root_id:
                    raise InvalidTreeError(f"节点 {cursor!r} 未连接到根")
                depths[cursor] = 0
                break
            if parent not in parents:
                raise InvalidTreeError(f"节点 {cursor!r} 的父节点 {parent!r} 不存在")
            path.append(cursor)
            cursor = parent
        # 路径上的节点深度 = 终点深度 + 剩余步数。
        base = depths[cursor]
        for offset, ancestor in enumerate(reversed(path), start=1):
            depth = base + offset
            if depth > MAX_DEPTH:
                raise InvalidTreeError(f"节点 {ancestor!r} 深度 {depth} 超过上限 {MAX_DEPTH}")
            depths[ancestor] = depth
    return depths


class MindMap:
    """单张协作思维导图；数据仅保存在进程内存中。

    nodes: {节点标识: (标题, 父节点标识)}，根节点的父节点标识必须为 None。
    """

    def __init__(self, root_id: str, nodes: Mapping[str, Tuple[str, Optional[str]]]) -> None:
        if root_id not in nodes:
            raise UnknownNodeError(f"根节点 {root_id!r} 不在节点集合中")
        seen: set[str] = set()
        for node_id in nodes:
            if node_id in seen:
                raise DuplicateNodeError(f"节点标识重复: {node_id!r}")
            seen.add(node_id)
        parents = {node_id: parent for node_id, (_, parent) in nodes.items()}
        _validate_tree(parents, root_id)

        self._root_id = root_id
        self._fields: Dict[FieldKey, _FieldHistory] = {}
        for node_id, (title, parent) in nodes.items():
            self._fields[(node_id, FIELD_TITLE)] = _FieldHistory(title)
            self._fields[(node_id, FIELD_PARENT)] = _FieldHistory(parent)

        self._next_batch_id = 0
        # 历史窗口：按首次提交顺序的最近 HISTORY_WINDOW 个成功批次。
        self._window: list[_Batch] = []
        # 每个用户的撤销栈（栈顶为最近提交）与重做栈（栈顶为最近撤销）。
        self._undo_stacks: Dict[str, list[_Batch]] = {}
        self._redo_stacks: Dict[str, list[_Batch]] = {}

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------

    def _current_parents(self) -> Dict[str, Optional[str]]:
        return {
            node_id: self._fields[(node_id, FIELD_PARENT)].effective_value()
            for (node_id, field) in self._fields
            if field == FIELD_PARENT
        }

    def snapshot(self) -> Dict[str, NodeState]:
        """读取当前导图全部节点状态。"""
        parents = self._current_parents()
        depths = _validate_tree(parents, self._root_id)
        return {
            node_id: NodeState(
                node_id=node_id,
                title=self._fields[(node_id, FIELD_TITLE)].effective_value(),
                parent_id=parents[node_id],
                depth=depths[node_id],
            )
            for node_id in parents
        }

    # ------------------------------------------------------------------
    # 提交 / 撤销 / 重做（后续步骤填充）
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # 提交
    # ------------------------------------------------------------------

    def submit(self, user_id: str, changes: Mapping[str, NodePatch]) -> int:
        """提交一个编辑批次，整体生效；返回批次号。

        以全部改动后的树判断合法性；任一字段非法则整批拒绝，不产生任何变化。
        本人成功提交会清空本人的重做分支。
        """
        # 汇总本批次写入的字段，并校验引用的节点存在。
        writes: Dict[FieldKey, object] = {}
        for node_id, patch in changes.items():
            if (node_id, FIELD_TITLE) not in self._fields:
                raise UnknownNodeError(f"节点 {node_id!r} 不存在")
            if patch.title is not None:
                writes[(node_id, FIELD_TITLE)] = patch.title
            if patch.parent_id is not None:
                writes[(node_id, FIELD_PARENT)] = patch.parent_id

        # 用改动后的父节点表校验整棵树（根不可改挂由父节点表校验保证）。
        parents = self._current_parents()
        for (node_id, field), value in writes.items():
            if field == FIELD_PARENT:
                if node_id == self._root_id:
                    raise InvalidTreeError("根节点的父节点不可修改")
                if value not in parents:
                    raise UnknownNodeError(f"父节点 {value!r} 不存在")
                parents[node_id] = value  # type: ignore[assignment]
        _validate_tree(parents, self._root_id)

        # 全部合法，落实写入。
        batch = _Batch(self._next_batch_id, user_id)
        self._next_batch_id += 1
        for key, value in writes.items():
            edit = _Edit(batch, value)
            self._fields[key].edits.append(edit)
            batch.writes[key] = edit

        self._undo_stacks.setdefault(user_id, []).append(batch)
        # 本人成功提交清空本人重做分支；其他人的提交不影响。
        self._redo_stacks[user_id] = []

        self._window.append(batch)
        if len(self._window) > HISTORY_WINDOW:
            self._evict(self._window.pop(0))
        return batch.batch_id

    # ------------------------------------------------------------------
    # 历史窗口淘汰
    # ------------------------------------------------------------------

    def _evict(self, batch: _Batch) -> None:
        """淘汰窗口内最老批次：永不可再成为撤销/重做目标，并回收字段历史。"""
        batch.evicted = True
        for stack in (self._undo_stacks.get(batch.user_id), self._redo_stacks.get(batch.user_id)):
            if stack and batch in stack:
                stack.remove(batch)
        for key, edit in batch.writes.items():
            history = self._fields[key]
            if not batch.active:
                # 已撤销的淘汰批次，其编辑不可能再生效，直接移除。
                history.edits.remove(edit)
                continue
            # 该编辑已永久生效：它之前的所有编辑都不可能再生效，回收。
            # 保留该编辑本身作为后续撤销/重做身份判断的锚点。
            index = history.edits.index(edit)
            if index > 0:
                del history.edits[:index]

    # ------------------------------------------------------------------
    # 撤销 / 重做（后续步骤填充）
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # 撤销 / 重做
    # ------------------------------------------------------------------

    def undo(self, user_id: str) -> bool:
        """撤销本人最近提交、仍生效且尚可回退的批次。

        目标批次写过的所有字段，当前生效的编辑必须仍是该批次（按字段判断，
        同值写入也算覆盖）；且回退后的整棵树必须合法。任一条件不满足则
        整体失败，不改变任何字段、回退次序或历史窗口。
        """
        stack = self._undo_stacks.get(user_id)
        if not stack:
            return False
        batch = stack[-1]

        # 字段覆盖冲突检查：目标写过的每个字段，当前生效编辑必须是它。
        for key, edit in batch.writes.items():
            if self._fields[key].effective_edit() is not edit:
                return False

        # 树合法性检查：把这些字段恢复为先前生效值后的整棵树必须合法。
        restored: Dict[FieldKey, Optional[_Edit]] = {}
        parents = self._current_parents()
        for key, edit in batch.writes.items():
            history = self._fields[key]
            previous = self._previous_effective(history, edit)
            restored[key] = previous
            if key[1] == FIELD_PARENT:
                parents[key[0]] = previous.value if previous else history.base_value  # type: ignore[assignment]
        try:
            _validate_tree(parents, self._root_id)
        except InvalidTreeError:
            return False

        # 落实撤销。
        batch.active = False
        batch.undo_record = restored
        stack.pop()
        self._redo_stacks.setdefault(user_id, []).append(batch)
        return True

    def redo(self, user_id: str) -> bool:
        """重做本人最近撤销且尚未重做的批次。

        目标批次写过的所有字段，当前生效的编辑必须仍是上次撤销恢复出的
        编辑（初始状态视为固定来源）；且重做后的整棵树必须合法。
        """
        stack = self._redo_stacks.get(user_id)
        if not stack:
            return False
        batch = stack[-1]
        restored = batch.undo_record
        if restored is None:
            return False

        # 字段冲突检查：当前生效编辑必须仍是撤销时恢复出的那个。
        for key, edit in batch.writes.items():
            if self._fields[key].effective_edit() is not restored[key]:
                return False

        # 树合法性检查：重新应用目标批次后的整棵树必须合法。
        parents = self._current_parents()
        for key, edit in batch.writes.items():
            if key[1] == FIELD_PARENT:
                parents[key[0]] = edit.value  # type: ignore[assignment]
        try:
            _validate_tree(parents, self._root_id)
        except InvalidTreeError:
            return False

        # 落实重做。
        batch.active = True
        batch.undo_record = None
        stack.pop()
        self._undo_stacks.setdefault(user_id, []).append(batch)
        return True

    @staticmethod
    def _previous_effective(history: _FieldHistory, edit: _Edit) -> Optional[_Edit]:
        """某字段在指定编辑之前最近一个仍生效的编辑；没有则返回 None。"""
        index = history.edits.index(edit)
        for candidate in reversed(history.edits[:index]):
            if candidate.batch.active:
                return candidate
        return None
