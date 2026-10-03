"""思维导图协作撤销会话：上层直接调用的库入口。

核心机制：
- 每个 (节点, 字段) 维护一个编辑栈，栈顶即当前生效的编辑；栈底之下隐含着初始状态。
- 提交批次 = 把本批次的所有写入压入对应字段栈，批次整体生效。
- 撤销 = 目标批次写过的字段，其栈顶必须仍是本批次的编辑（否则冲突），
  弹出后恢复先前生效的编辑；恢复后的整树必须仍然合法。
- 重做 = 目标字段的栈顶必须仍是撤销时恢复出的那个编辑（初始状态视为固定来源），
  然后把本批次的编辑重新压栈。
- 每图仅最近 WINDOW_SIZE 个成功提交的批次可成为撤销/重做目标；
  批次被淘汰时其编辑固化，字段栈中位于固化编辑之下的历史被压缩回收，
  保证长序列编辑下内存有界。
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Deque, Dict, Hashable, List, Mapping, Optional, Tuple

from .errors import FailureReason, OpResult
from .model import Batch, Edit, FIELD_PARENT, FIELD_TITLE, FieldKey, NodeId
from .tree import validate_tree

#: 每图可成为撤销/重做目标的最近成功提交批次数
WINDOW_SIZE = 200


class MapSession:
    """单张思维导图的协作编辑会话，数据仅保存在进程内存中。"""

    def __init__(self, root: NodeId,
                 nodes: Mapping[NodeId, Tuple[Any, Optional[NodeId]]]) -> None:
        """root: 根节点 id；nodes: {节点id: (标题, 父节点id或None)}，必须本身合法。"""
        self._root = root
        self._initial_titles: Dict[NodeId, Any] = {}
        self._initial_parents: Dict[NodeId, Optional[NodeId]] = {}
        for node, (title, parent) in nodes.items():
            self._initial_titles[node] = title
            self._initial_parents[node] = parent
        if root not in self._initial_parents:
            raise ValueError("root not present in nodes")
        if not validate_tree(dict(self._initial_parents), root):
            raise ValueError("initial map is not a valid tree")
        self._titles = dict(self._initial_titles)
        self._parents = dict(self._initial_parents)
        self._stacks: Dict[FieldKey, List[Edit]] = {}
        self._batches: Dict[int, Batch] = {}
        self._window: Deque[int] = deque()
        self._next_batch_id = 1
        # 各用户在窗口内的批次（按提交顺序，含已撤销的）
        self._user_batches: Dict[Hashable, List[int]] = defaultdict(list)
        # 各用户的重做栈（最近撤销的在栈顶）
        self._user_redo: Dict[Hashable, List[int]] = defaultdict(list)

    # ------------------------------------------------------------------ 提交

    def submit(self, user: Hashable,
               changes: Mapping[NodeId, Mapping[str, Any]]) -> OpResult:
        """提交一个编辑批次。changes: {节点id: {"title": 新标题, "parent": 新父节点}}。

        批次整体生效：以全部改动后的树判断合法性，
        不因逐项过渡状态不合法而拒绝最终合法的批次。
        """
        writes: Dict[FieldKey, Any] = {}
        for node, fields in changes.items():
            if node not in self._parents:
                return OpResult(False, FailureReason.UNKNOWN_NODE)
            for field, value in fields.items():
                if field == FIELD_TITLE:
                    writes[(node, field)] = value
                elif field == FIELD_PARENT:
                    if node == self._root:
                        return OpResult(False, FailureReason.INVALID_VALUE)
                    if value not in self._parents:
                        return OpResult(False, FailureReason.INVALID_VALUE)
                    writes[(node, field)] = value
                else:
                    return OpResult(False, FailureReason.UNKNOWN_FIELD)
        if not writes:
            return OpResult(False, FailureReason.EMPTY_BATCH)
        parent_changes = {node: value for (node, field), value in writes.items()
                          if field == FIELD_PARENT}
        if parent_changes:
            candidate = dict(self._parents)
            candidate.update(parent_changes)
            if not validate_tree(candidate, self._root):
                return OpResult(False, FailureReason.INVALID_TREE)
        batch_id = self._next_batch_id
        self._next_batch_id += 1
        batch = Batch(batch_id, user, writes)
        for key, value in writes.items():
            edit = Edit(batch_id, value)
            self._stacks.setdefault(key, []).append(edit)
            batch.edits[key] = edit
            node, field = key
            if field == FIELD_TITLE:
                self._titles[node] = value
            else:
                self._parents[node] = value
        self._batches[batch_id] = batch
        self._window.append(batch_id)
        self._user_batches[user].append(batch_id)
        # 本人成功提交清空本人的重做分支；其他人的提交不影响
        self._user_redo[user].clear()
        if len(self._window) > WINDOW_SIZE:
            self._evict_oldest()
        return OpResult(True, batch_id=batch_id)

    # ------------------------------------------------------------------ 撤销

    def undo(self, user: Hashable) -> OpResult:
        """撤销该用户最近提交、仍生效且尚可回退的批次。"""
        target_id = None
        for bid in reversed(self._user_batches.get(user, ())):
            if not self._batches[bid].undone:
                target_id = bid
                break
        if target_id is None:
            return OpResult(False, FailureReason.NO_TARGET)
        batch = self._batches[target_id]
        # 冲突检查：目标写过的所有字段，当前生效的编辑必须仍是该批次
        for key, edit in batch.edits.items():
            stack = self._stacks[key]
            if not stack or stack[-1] is not edit:
                return OpResult(False, FailureReason.CONFLICT)
        # 计算每个字段将恢复出的编辑，并以恢复后的整树校验合法性
        restored: Dict[FieldKey, Optional[Edit]] = {}
        candidate_parents: Optional[Dict[NodeId, Optional[NodeId]]] = None
        for key in batch.edits:
            stack = self._stacks[key]
            prev = stack[-2] if len(stack) >= 2 else None
            restored[key] = prev
            node, field = key
            if field == FIELD_PARENT:
                if candidate_parents is None:
                    candidate_parents = dict(self._parents)
                candidate_parents[node] = (
                    prev.value if prev is not None else self._initial_parents[node])
        if candidate_parents is not None and not validate_tree(candidate_parents, self._root):
            return OpResult(False, FailureReason.INVALID_TREE)
        # 应用：弹出本批次编辑，恢复先前生效的值
        for key, prev in restored.items():
            stack = self._stacks[key]
            stack.pop()
            node, field = key
            if field == FIELD_TITLE:
                self._titles[node] = (prev.value if prev is not None
                                      else self._initial_titles[node])
            else:
                self._parents[node] = (prev.value if prev is not None
                                       else self._initial_parents[node])
        batch.undone = True
        batch.restored = restored
        self._user_redo[user].append(target_id)
        return OpResult(True, batch_id=target_id)

    # ------------------------------------------------------------------ 重做

    def redo(self, user: Hashable) -> OpResult:
        """重做该用户最近撤销且尚未重做的批次。"""
        redo_stack = self._user_redo.get(user)
        if not redo_stack:
            return OpResult(False, FailureReason.NO_TARGET)
        target_id = redo_stack[-1]
        batch = self._batches.get(target_id)
        if batch is None:
            return OpResult(False, FailureReason.EVICTED)
        restored = batch.restored
        assert restored is not None
        # 冲突检查：这些字段当前生效的编辑必须仍是撤销时恢复出的编辑
        for key, prev in restored.items():
            stack = self._stacks.get(key)
            if prev is None:
                if stack:
                    return OpResult(False, FailureReason.CONFLICT)
            elif not stack or stack[-1] is not prev:
                return OpResult(False, FailureReason.CONFLICT)
        # 以重做后的整树校验合法性
        parent_changes = {node: value for (node, field), value in batch.writes.items()
                          if field == FIELD_PARENT}
        if parent_changes:
            candidate = dict(self._parents)
            candidate.update(parent_changes)
            if not validate_tree(candidate, self._root):
                return OpResult(False, FailureReason.INVALID_TREE)
        # 应用：把本批次的编辑重新压栈
        for key, edit in batch.edits.items():
            self._stacks.setdefault(key, []).append(edit)
            node, field = key
            if field == FIELD_TITLE:
                self._titles[node] = edit.value
            else:
                self._parents[node] = edit.value
        batch.undone = False
        batch.restored = None
        redo_stack.pop()
        return OpResult(True, batch_id=target_id)

    # ------------------------------------------------------------------ 读取

    def snapshot(self) -> Dict[NodeId, Dict[str, Any]]:
        """读取当前导图：{节点id: {"title": ..., "parent": ...}}。"""
        return {node: {"title": self._titles[node], "parent": self._parents[node]}
                for node in self._titles}

    # ------------------------------------------------------------------ 窗口淘汰

    def _evict_oldest(self) -> None:
        """淘汰最早提交的批次：它永远不能再成为撤销/重做目标。

        淘汰不改变当前导图：该批次的编辑固化为永久编辑，
        字段栈中位于最高永久编辑之下的历史被压缩回收，保证内存有界。
        """
        old_id = self._window.popleft()
        batch = self._batches.pop(old_id)
        self._user_batches[batch.user].remove(old_id)
        redo_stack = self._user_redo.get(batch.user)
        if redo_stack and old_id in redo_stack:
            redo_stack.remove(old_id)
        touched: List[FieldKey] = []
        for key, edit in batch.edits.items():
            edit.permanent = True
            touched.append(key)
        for key in touched:
            stack = self._stacks[key]
            highest_permanent = -1
            for index, edit in enumerate(stack):
                if edit.permanent:
                    highest_permanent = index
            if highest_permanent > 0:
                del stack[:highest_permanent]
