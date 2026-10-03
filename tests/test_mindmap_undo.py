"""验收测试。"""

import unittest

from mindmap_undo import InvalidTreeError, MindMap, NodePatch, UnknownNodeError


def make_map() -> MindMap:
    # R +- A +- B
    #  +- C
    return MindMap(
        "R",
        {
            "R": ("root", None),
            "A": ("a", "R"),
            "B": ("b", "A"),
            "C": ("c", "R"),
        },
    )


def titles(m: MindMap):
    return {nid: s.title for nid, s in m.snapshot().items()}


def parents(m: MindMap):
    return {nid: s.parent_id for nid, s in m.snapshot().items()}


class BasicTest(unittest.TestCase):
    def test_initial_snapshot(self):
        m = make_map()
        snap = m.snapshot()
        self.assertEqual(snap["R"].depth, 0)
        self.assertEqual(snap["A"].depth, 1)
        self.assertEqual(snap["B"].depth, 2)
        self.assertEqual(snap["B"].parent_id, "A")

    def test_submit_and_undo_redo(self):
        m = make_map()
        m.submit("u1", {"A": NodePatch(title="a2")})
        self.assertEqual(titles(m)["A"], "a2")
        self.assertTrue(m.undo("u1"))
        self.assertEqual(titles(m)["A"], "a")
        self.assertTrue(m.redo("u1"))
        self.assertEqual(titles(m)["A"], "a2")

    def test_undo_empty(self):
        m = make_map()
        self.assertFalse(m.undo("nobody"))
        self.assertFalse(m.redo("nobody"))

    def test_unknown_node_rejected(self):
        m = make_map()
        with self.assertRaises(UnknownNodeError):
            m.submit("u1", {"ZZZ": NodePatch(title="x")})
        with self.assertRaises(UnknownNodeError):
            m.submit("u1", {"A": NodePatch(parent_id="ZZZ")})

    def test_root_reparent_rejected(self):
        m = make_map()
        with self.assertRaises(InvalidTreeError):
            m.submit("u1", {"R": NodePatch(parent_id="A")})

    def test_cycle_batch_rejected(self):
        m = make_map()
        with self.assertRaises(InvalidTreeError):
            m.submit("u1", {"A": NodePatch(parent_id="B")})
        # 失败批次不产生任何变化
        self.assertEqual(parents(m)["A"], "R")

    def test_invalid_initial_map(self):
        with self.assertRaises(InvalidTreeError):
            MindMap("R", {"R": ("r", None), "A": ("a", "B"), "B": ("b", "A")})


class SameValueOverwriteTest(unittest.TestCase):
    """他人的同值写入阻挡原作者撤销；撤销覆盖后原作者又能撤销。"""

    def test_same_value_blocks_then_unblocks(self):
        m = make_map()
        m.submit("u1", {"A": NodePatch(title="x")})
        m.submit("u2", {"A": NodePatch(title="x")})  # 同值也算新编辑
        # u1 的编辑已被 u2 覆盖，撤销失败且无任何变化
        self.assertFalse(m.undo("u1"))
        self.assertEqual(titles(m)["A"], "x")
        # u2 撤销覆盖后，u1 的编辑重新生效，u1 可以撤销
        self.assertTrue(m.undo("u2"))
        self.assertEqual(titles(m)["A"], "x")  # u1 的编辑仍是 x
        self.assertTrue(m.undo("u1"))
        self.assertEqual(titles(m)["A"], "a")

    def test_other_field_edit_survives(self):
        m = make_map()
        m.submit("u1", {"A": NodePatch(title="x")})
        m.submit("u2", {"B": NodePatch(title="b2")})
        self.assertTrue(m.undo("u1"))  # 不同字段，不冲突
        self.assertEqual(titles(m)["A"], "a")
        self.assertEqual(titles(m)["B"], "b2")  # u2 的修改保留

    def test_failed_undo_no_partial_rollback(self):
        m = make_map()
        # u1 一批改两个字段
        m.submit("u1", {"A": NodePatch(title="x"), "B": NodePatch(title="y")})
        # u2 只覆盖其中一个字段
        m.submit("u2", {"A": NodePatch(title="z")})
        # u1 撤销失败，另一字段也不得回退
        self.assertFalse(m.undo("u1"))
        self.assertEqual(titles(m)["A"], "z")
        self.assertEqual(titles(m)["B"], "y")
        # 标题与父节点分别判断：u2 改 A 的父节点不影响 u1 对 A 标题的撤销
        m2 = make_map()
        m2.submit("u1", {"A": NodePatch(title="x")})
        m2.submit("u2", {"A": NodePatch(parent_id="C")})
        self.assertTrue(m2.undo("u1"))
        self.assertEqual(titles(m2)["A"], "a")
        self.assertEqual(parents(m2)["A"], "C")  # u2 的改挂保留


if __name__ == "__main__":
    unittest.main()
