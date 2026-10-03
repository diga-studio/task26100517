"""字段级覆盖关系、撤销/重做语义。"""

import unittest

from mindmap_undo import FailureReason, MapSession


def make_session():
    return MapSession("r", {
        "r": ("root", None),
        "a": ("A", "r"),
        "b": ("B", "r"),
        "c": ("C", "b"),
    })


class SameValueOverrideTest(unittest.TestCase):
    def test_same_value_write_blocks_original_author(self):
        s = make_session()
        # 原作者把 a 标题改为 X
        self.assertTrue(s.submit("u1", {"a": {"title": "X"}}).ok)
        # 同事写入相同值，也算一次新编辑
        self.assertTrue(s.submit("u2", {"a": {"title": "X"}}).ok)
        # 原作者撤销被同事的同值写入阻挡
        r = s.undo("u1")
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, FailureReason.CONFLICT)
        # 撤销该覆盖后，原作者又能撤销
        self.assertTrue(s.undo("u2").ok)
        self.assertTrue(s.undo("u1").ok)
        self.assertEqual(s.snapshot()["a"]["title"], "A")

    def test_rewrite_after_revert_counts_as_edit(self):
        s = make_session()
        s.submit("u1", {"a": {"title": "X"}})
        s.submit("u1", {"a": {"title": "A"}})  # 改走后再改回，仍是新编辑
        r = s.undo("u1")  # 撤销的是"改回 A"这次编辑
        self.assertTrue(r.ok)
        self.assertEqual(s.snapshot()["a"]["title"], "X")


class PerFieldIndependenceTest(unittest.TestCase):
    def test_other_field_edit_does_not_block_and_survives(self):
        s = make_session()
        # u1 一批同时改 a 的标题和父节点
        self.assertTrue(s.submit("u1", {"a": {"title": "X", "parent": "b"}}).ok)
        # u2 只覆盖 a 的标题（另一字段）
        self.assertTrue(s.submit("u2", {"a": {"title": "Y"}}).ok)
        # u1 撤销：标题字段被覆盖 -> 冲突，整批失败
        r = s.undo("u1")
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, FailureReason.CONFLICT)
        # 失败批次不得产生部分回退：父节点仍是 u1 写入的 b
        self.assertEqual(s.snapshot()["a"]["parent"], "b")
        self.assertEqual(s.snapshot()["a"]["title"], "Y")
        # u2 撤销标题覆盖后，u1 可以撤销整批
        self.assertTrue(s.undo("u2").ok)
        self.assertTrue(s.undo("u1").ok)
        self.assertEqual(s.snapshot()["a"]["title"], "A")
        self.assertEqual(s.snapshot()["a"]["parent"], "r")

    def test_undo_restores_covered_edit_per_field(self):
        s = make_session()
        s.submit("u1", {"a": {"title": "T1"}})
        s.submit("u2", {"a": {"title": "T2"}})
        s.submit("u1", {"b": {"title": "TB"}})
        # u2 撤销后，u1 先生效的标题编辑重新生效
        self.assertTrue(s.undo("u2").ok)
        self.assertEqual(s.snapshot()["a"]["title"], "T1")
        # b 的标题不受影响
        self.assertEqual(s.snapshot()["b"]["title"], "TB")


class RedoBranchTest(unittest.TestCase):
    def test_own_commit_clears_redo_others_dont(self):
        s = make_session()
        s.submit("u1", {"a": {"title": "X"}})
        self.assertTrue(s.undo("u1").ok)
        # 他人的新编辑不清空本人的重做分支
        self.assertTrue(s.submit("u2", {"b": {"title": "B2"}}).ok)
        r = s.redo("u1")
        self.assertTrue(r.ok)
        self.assertEqual(s.snapshot()["a"]["title"], "X")
        # 本人成功提交新批次清空本人的重做分支
        self.assertTrue(s.undo("u1").ok)
        self.assertTrue(s.submit("u1", {"c": {"title": "C2"}}).ok)
        r = s.redo("u1")
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, FailureReason.NO_TARGET)

    def test_redo_order_is_reverse_of_undo(self):
        s = make_session()
        s.submit("u1", {"a": {"title": "T1"}})
        s.submit("u1", {"a": {"title": "T2"}})
        self.assertTrue(s.undo("u1").ok)  # 撤销 T2
        self.assertTrue(s.undo("u1").ok)  # 撤销 T1
        self.assertEqual(s.snapshot()["a"]["title"], "A")
        self.assertTrue(s.redo("u1").ok)  # 先重做 T1
        self.assertEqual(s.snapshot()["a"]["title"], "T1")
        self.assertTrue(s.redo("u1").ok)  # 再重做 T2
        self.assertEqual(s.snapshot()["a"]["title"], "T2")

    def test_redo_conflict_when_field_changed_after_undo(self):
        s = make_session()
        s.submit("u1", {"a": {"title": "X"}})
        self.assertTrue(s.undo("u1").ok)
        # 同事在同一字段写入新值，撤销恢复出的编辑不再生效
        self.assertTrue(s.submit("u2", {"a": {"title": "Y"}}).ok)
        r = s.redo("u1")
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, FailureReason.CONFLICT)
        # 失败后状态不变
        self.assertEqual(s.snapshot()["a"]["title"], "Y")

    def test_undo_skips_already_undone_to_find_active(self):
        s = make_session()
        s.submit("u1", {"a": {"title": "T1"}})
        s.submit("u1", {"b": {"title": "TB"}})
        self.assertTrue(s.undo("u1").ok)  # 撤销 b 的批次
        # 下一个撤销目标是仍生效的 T1 批次，不能再撤销已撤销的
        self.assertTrue(s.undo("u1").ok)
        self.assertEqual(s.snapshot()["a"]["title"], "A")
        r = s.undo("u1")
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, FailureReason.NO_TARGET)


class InputValidationTest(unittest.TestCase):
    def test_invalid_inputs(self):
        s = make_session()
        r = s.submit("u1", {"zzz": {"title": "X"}})
        self.assertEqual(r.reason, FailureReason.UNKNOWN_NODE)
        r = s.submit("u1", {"a": {"weight": 1}})
        self.assertEqual(r.reason, FailureReason.UNKNOWN_FIELD)
        r = s.submit("u1", {"a": {"parent": "zzz"}})
        self.assertEqual(r.reason, FailureReason.INVALID_VALUE)
        r = s.submit("u1", {"r": {"parent": "a"}})
        self.assertEqual(r.reason, FailureReason.INVALID_VALUE)
        r = s.submit("u1", {})
        self.assertEqual(r.reason, FailureReason.EMPTY_BATCH)
        r = s.submit("u1", {"a": {}})
        self.assertEqual(r.reason, FailureReason.EMPTY_BATCH)
        # 全部失败，导图保持初始状态
        self.assertEqual(s.snapshot()["a"]["title"], "A")

    def test_initial_map_must_be_legal(self):
        with self.assertRaises(ValueError):
            MapSession("r", {"r": ("root", None), "a": ("A", "b"), "b": ("B", "a")})


if __name__ == "__main__":
    unittest.main()
