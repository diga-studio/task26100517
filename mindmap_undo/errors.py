"""错误与结果类型定义。"""

from __future__ import annotations

import enum


class FailureReason(enum.Enum):
    """操作失败的原因。"""

    INVALID_TREE = "invalid_tree"            # 结果树不合法（成环/脱根/超深）
    UNKNOWN_NODE = "unknown_node"            # 批次引用了不存在的节点
    UNKNOWN_FIELD = "unknown_field"          # 批次引用了不存在的字段
    INVALID_VALUE = "invalid_value"          # 字段值非法（如父节点指向自身/未知节点）
    EMPTY_BATCH = "empty_batch"              # 空批次
    NO_TARGET = "no_target"                  # 没有可撤销/可重做的目标批次
    CONFLICT = "conflict"                    # 目标批次被后续编辑覆盖，无法回退
    EVICTED = "evicted"                      # 目标批次已滑出历史窗口


class OpResult:
    """提交 / 撤销 / 重做的统一返回结果。"""

    __slots__ = ("ok", "reason", "batch_id")

    def __init__(self, ok: bool, reason: "FailureReason | None" = None,
                 batch_id: "int | None" = None) -> None:
        self.ok = ok
        self.reason = reason
        self.batch_id = batch_id

    def __repr__(self) -> str:  # pragma: no cover
        return f"OpResult(ok={self.ok}, reason={self.reason}, batch_id={self.batch_id})"
