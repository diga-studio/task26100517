# mindmap_undo：思维导图协作撤销库

纯 Python、零依赖的进程内库。多名团队成员交错修改同一张思维导图时，
各自只能撤销/重做**自己的**操作，且不会抹掉同事后续的独立修改。
数据仅保存在进程内存中，不涉及任何外部服务。

## 业务规则实现要点

- **字段级覆盖**：每个 `(节点, 字段)` 维护独立的编辑栈。标题和父节点分别判断冲突，
  修改同一节点的另一字段不构成冲突。写入相同值也算一次新编辑。
- **批次整体生效**：提交时以全部改动后的最终树判断合法性，
  不因逐项过渡状态（如暂时成环）拒绝最终合法的批次。
- **撤销**：目标是本人最近提交、仍生效且在窗口内的批次。要求目标写过的所有字段，
  当前生效的编辑仍是该批次；满足时恢复这些字段先前的值。恢复后的整树必须合法
  （无环、不脱离根、深度 ≤ 15），否则整体失败且不改任何状态。
- **重做**：目标是本人最近撤销且尚未重做的批次。要求相关字段当前仍对应撤销时
  恢复出的编辑（初始状态视为固定来源）。本人成功提交新批次会清空本人的重做分支，
  他人的提交不会。
- **历史窗口**：每图仅最近 200 个成功提交的批次可成为撤销/重做目标，
  按首次提交顺序淘汰。淘汰不改变当前导图；被淘汰批次的编辑固化为永久编辑，
  字段栈中位于其下的历史被压缩回收，保证长序列编辑下内存有界（实测连续提交
  10 万次后常驻内存零增长，远低于 32 MiB 上限）。

## 快速开始

```python
from mindmap_undo import MapSession, FailureReason

# 初始导图：{节点id: (标题, 父节点id)}，根节点的父节点为 None，必须本身合法
session = MapSession("root", {
    "root": ("根", None),
    "a": ("节点A", "root"),
    "b": ("节点B", "root"),
})

# 提交编辑批次：{节点id: {"title": 新标题, "parent": 新父节点}}
# 未列出的字段保持原样；批次整体生效
result = session.submit("alice", {"a": {"title": "新A", "parent": "b"}})
assert result.ok

# 撤销 / 重做本人最近的操作
session.undo("alice")     # 若被同事的后续编辑覆盖则失败，result.reason == FailureReason.CONFLICT
session.redo("alice")

# 读取当前导图：{节点id: {"title": ..., "parent": ...}}
snapshot = session.snapshot()
```

所有写操作返回 `OpResult`：`ok` 表示是否成功；失败时 `reason` 为
`FailureReason` 枚举（`INVALID_TREE` / `CONFLICT` / `NO_TARGET` / `EVICTED` /
`UNKNOWN_NODE` / `UNKNOWN_FIELD` / `INVALID_VALUE` / `EMPTY_BATCH`），
成功时 `batch_id` 为批次号。失败不会留下任何部分生效的改动。

## 约束

- 节点集合固定，根固定；根深度为 0，最大深度 15（`mindmap_undo.MAX_DEPTH`）。
- 每图撤销/重做窗口为最近 200 个成功提交的批次（`mindmap_undo.WINDOW_SIZE`）。
- 调用需串行到达；库内部不做并发控制。

## 运行测试

```bash
python3 -m unittest discover -s tests -v
```

测试覆盖：同值覆盖阻挡与解除、字段级独立性、失败批次无部分回退、
过渡成环但最终合法的批次、撤销/重做时的成环与超深检测、
200 批窗口淘汰与跨淘汰恢复、他人提交不清空重做分支、
2000 节点 / 30 用户 / 单批 500 字段的规模冒烟，以及 10 万次提交的内存有界性检查。

## 代码结构

- `mindmap_undo/session.py` — 会话主入口（提交/撤销/重做/读取、窗口淘汰与内存压缩）
- `mindmap_undo/model.py` — 字段编辑（`Edit`）与批次（`Batch`）的内部记录
- `mindmap_undo/tree.py` — 整树合法性校验（单树、无环、深度上限）
- `mindmap_undo/errors.py` — `OpResult` 与 `FailureReason`
