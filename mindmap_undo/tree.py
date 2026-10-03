"""导图树结构合法性校验。

合法树的定义：
- 节点集合固定，根节点固定，根没有父节点（parent 为 None）；
- 每个非根节点的父节点必须存在于节点集合中；
- 所有节点都属于以根为起点的同一棵树（无环、无脱离根的子树）；
- 根深度为 0，任何节点深度不超过 MAX_DEPTH。
"""

from __future__ import annotations

from typing import Dict, Hashable, Optional

MAX_DEPTH = 15

NodeId = Hashable


def validate_tree(parents: Dict[NodeId, Optional[NodeId]], root: NodeId) -> bool:
    """判断 parents 是否构成一棵以 root 为根、深度不超上限的单棵树。

    parents 必须恰好覆盖全部节点；根节点的值必须为 None。
    """
    if root not in parents or parents[root] is not None:
        return False
    # 从根向下做 DFS：若所有节点都可达且无环，则必为单棵树
    # （每节点至多一个父节点，n 个节点、n-1 条边且全部连通即为树）。
    children: Dict[NodeId, list] = {node: [] for node in parents}
    edge_count = 0
    for node, parent in parents.items():
        if node == root:
            continue
        if parent is None or parent not in parents:
            return False
        children[parent].append(node)
        edge_count += 1
    if edge_count != len(parents) - 1:
        return False
    stack = [(root, 0)]
    visited = 0
    while stack:
        node, depth = stack.pop()
        if depth > MAX_DEPTH:
            return False
        visited += 1
        for child in children[node]:
            stack.append((child, depth + 1))
    return visited == len(parents)
