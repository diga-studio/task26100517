"""批次整体生效与撤销/重做时的整树合法性。"""

import unittest

from mindmap_undo import FailureReason, MapSession


def make_session():
    # r -> a -> b, r -> c
    return MapSession("r", {
        "r": ("root", None),
        "a": ("A", "r"),
        "b": ("B", "a"),
        "c": ("C", "r"),
    })


class BatchAtomicityTest(unittest.TestCase):
    def test_final_tree_legal_despite_illegal_transition(self):
        s = make_session()
        # 逐项看：先把 a 挂到 b 下会成环(a->b->a)，再把 b 挂回根才解开。
        # 但最终树 r->b->a 合法，整批应成功。
        r = s.submit("u1", {"a": {"parent": "b"}, "b": {"parent": "r"}})
        self.assertTrue(r.ok, r)
        snap = s.snapshot()
        self.assertEqual(snap["a"]["parent"], "b")
        self.assertEqual(snap["b"]["parent"], "r")

    def test_final_tree_illegal_batch_rejected(self):
        s = make_session()
        r = s.submit("u1", {"a": {"parent": "b"}, "b": {"parent": "a"}})
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, FailureReason.INVALID_TREE)
        # 失败不得改变任何字段
        snap = s.snapshot()
        self.assertEqual(snap["a"]["parent"], "r")
        self.assertEqual(snap["b"]["parent"], "a")

    def test_self_loop_rejected(self):
        s = make_session()
        r = s.submit("u1", {"a": {"parent": "a"}})
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, FailureReason.INVALID_TREE)


class UndoTreeValidityTest(unittest.TestCase):
    def test_undo_creating_cycle_fails_without_side_effects(self):
        s = make_session()
        # u1 把 b 改挂到 c 下：r->a, r->c->b
        self.assertTrue(s.submit("u1", {"b": {"parent": "c"}}).ok)
        # 同事的独立改挂：a 挂到 b 下（合法：r->c->b->a）
        self.assertTrue(s.submit("u2", {"a": {"parent": "b"}}).ok)
        before = s.snapshot()
        # u1 撤销会把 b 恢复挂到 a 下，与 a->b 成环 -> 整体失败
        r = s.undo("u1")
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, FailureReason.INVALID_TREE)
        # 整图不变，且回退次序不变（再次撤销仍命中同一目标）
        self.assertEqual(s.snapshot(), before)
        r = s.undo("u1")
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, FailureReason.INVALID_TREE)
        # 同事撤销自己的改挂后，u1 的撤销恢复可行
        self.assertTrue(s.undo("u2").ok)
        self.assertTrue(s.undo("u1").ok)
        self.assertEqual(s.snapshot()["b"]["parent"], "a")

    def test_depth_limit_on_submit_and_undo(self):
        # 链 n0..n15（n15 深度 15），x 初始挂在 n14 下（深度 15），y 挂在根下
        nodes = {"n0": ("n0", None)}
        for i in range(1, 16):
            nodes[f"n{i}"] = (f"n{i}", f"n{i-1}")
        nodes["x"] = ("x", "n14")
        nodes["y"] = ("y", "n0")
        s = MapSession("n0", nodes)
        # 直接把 x 挂到 n15 下 -> 深度 16，拒绝
        r = s.submit("u0", {"x": {"parent": "n15"}})
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, FailureReason.INVALID_TREE)
        # u1 把 x 上移到根下（深度 1），合法
        self.assertTrue(s.submit("u1", {"x": {"parent": "n0"}}).ok)
        # u2 把 y 挂到 x 下（深度 2），合法
        self.assertTrue(s.submit("u2", {"y": {"parent": "x"}}).ok)
        before = s.snapshot()
        # u1 撤销会把 x 恢复到 n14 下（深度 15），连带 y 深度 16 -> 整体失败
        r = s.undo("u1")
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, FailureReason.INVALID_TREE)
        self.assertEqual(s.snapshot(), before)
        # u2 先撤销 y 的改挂，u1 的撤销即可行
        self.assertTrue(s.undo("u2").ok)
        self.assertTrue(s.undo("u1").ok)
        self.assertEqual(s.snapshot()["x"]["parent"], "n14")

    def test_redo_tree_validity_checked(self):
        s = make_session()
        # u1: b 挂到 c 下
        s.submit("u1", {"b": {"parent": "c"}})
        self.assertTrue(s.undo("u1").ok)  # 撤销，b 回到 a 下
        # u2 的独立改挂：c 挂到 b 下（合法：r->a->b->c）
        self.assertTrue(s.submit("u2", {"c": {"parent": "b"}}).ok)
        before = s.snapshot()
        # u1 重做会把 b 挂到 c 下 -> b->c->b 成环，整体失败
        r = s.redo("u1")
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, FailureReason.INVALID_TREE)
        self.assertEqual(s.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
