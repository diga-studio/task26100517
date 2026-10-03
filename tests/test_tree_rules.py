"""树合法性相关验收测试。"""

import unittest

from mindmap_undo import MAX_DEPTH, InvalidTreeError, MindMap, NodePatch


def parents(m: MindMap):
    return {nid: s.parent_id for nid, s in m.snapshot().items()}


class BatchAtomicityTest(unittest.TestCase):
    def test_batch_legal_final_tree_but_cyclic_transition(self):
        # R -> A -> B；一批内互换：A 挂到 B 下、B 挂回根。
        # 逐项过渡（先改 A.parent=B）会成环，但最终树 R->B->A 合法。
        m = MindMap("R", {"R": ("r", None), "A": ("a", "R"), "B": ("b", "A")})
        m.submit("u1", {"A": NodePatch(parent_id="B"), "B": NodePatch(parent_id="R")})
        self.assertEqual(parents(m), {"R": None, "A": "B", "B": "R"})

    def test_colleague_reparent_makes_undo_cyclic(self):
        # R +- P1 +- A
        #  +- P2
        m = MindMap(
            "R",
            {
                "R": ("r", None),
                "P1": ("p1", "R"),
                "P2": ("p2", "R"),
                "A": ("a", "P1"),
            },
        )
        before = parents(m)
        # u1 把 A 改挂到 P2 下
        m.submit("u1", {"A": NodePatch(parent_id="P2")})
        # 同事 u2 独立改挂：P1 挂到 A 下（合法：R->P2->A->P1）
        m.submit("u2", {"P1": NodePatch(parent_id="A")})
        # u1 撤销将恢复 A.parent=P1，形成 A->P1->A 环，必须整体失败
        self.assertFalse(m.undo("u1"))
        # 整图不变
        self.assertEqual(parents(m), {"R": None, "P1": "A", "P2": "R", "A": "P2"})
        # u1 的批次仍是撤销目标（失败不改变回退次序）：u2 先撤销后 u1 可撤销
        self.assertTrue(m.undo("u2"))
        self.assertTrue(m.undo("u1"))
        self.assertEqual(parents(m), before)

    def test_depth_limit_on_submit(self):
        # 构造一条深度恰为 MAX_DEPTH 的链，再尝试超限改挂
        nodes = {"n0": ("t", None)}
        for i in range(1, MAX_DEPTH + 1):
            nodes[f"n{i}"] = ("t", f"n{i - 1}")
        nodes["x"] = ("t", "n0")
        m = MindMap("n0", nodes)
        # x 挂到链尾 -> 深度 MAX_DEPTH+1，拒绝
        with self.assertRaises(InvalidTreeError):
            m.submit("u1", {"x": NodePatch(parent_id=f"n{MAX_DEPTH}")})
        # 挂到 n1 下 -> 深度 2，合法
        m.submit("u1", {"x": NodePatch(parent_id="n1")})
        self.assertEqual(m.snapshot()["x"].depth, 2)

    def test_depth_limit_on_undo(self):
        # 链深已达上限；u1 曾把 y 从链中移走，撤销会超深，必须失败
        nodes = {"n0": ("t", None)}
        for i in range(1, MAX_DEPTH):
            nodes[f"n{i}"] = ("t", f"n{i - 1}")
        nodes["y"] = ("t", f"n{MAX_DEPTH - 1}")  # y 深度 MAX_DEPTH
        nodes["z"] = ("t", "n0")
        m = MindMap("n0", nodes)
        # u1 把 z 改挂到 y 下（z 深度 MAX_DEPTH+1 会超限，改为先把 y 移浅再挂）
        m.submit("u1", {"y": NodePatch(parent_id="n0")})  # y 深度 1
        m.submit("u2", {"z": NodePatch(parent_id="y")})   # z 深度 2
        # u1 撤销会把 y 放回链尾（深度 MAX_DEPTH），z 随之到 MAX_DEPTH+1，超限
        self.assertFalse(m.undo("u1"))
        self.assertEqual(m.snapshot()["y"].parent_id, "n0")
        self.assertEqual(m.snapshot()["z"].parent_id, "y")


if __name__ == "__main__":
    unittest.main()
