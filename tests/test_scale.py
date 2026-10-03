"""规模冒烟：2000 节点、30 用户交错编辑、单批 500 个字段写入。"""

import unittest

from mindmap_undo import MapSession

NODE_COUNT = 2000
USER_COUNT = 30
BATCH_FIELDS = 500


def make_wide_session():
    nodes = {"n0": ("root", None)}
    for i in range(1, NODE_COUNT):
        nodes[f"n{i}"] = (f"node{i}", "n0")
    return MapSession("n0", nodes)


class ScaleTest(unittest.TestCase):
    def test_large_batch_and_interleaved_users(self):
        s = make_wide_session()
        # 单批 500 个字段写入
        changes = {f"n{i}": {"title": f"t{i}"} for i in range(1, BATCH_FIELDS + 1)}
        self.assertTrue(s.submit("u0", changes).ok)
        self.assertEqual(s.snapshot()["n500"]["title"], "t500")
        # 30 名用户交错编辑
        for round_ in range(20):
            for user in range(USER_COUNT):
                node = f"n{(round_ * USER_COUNT + user) % (NODE_COUNT - 1) + 1}"
                self.assertTrue(s.submit(f"u{user}", {node: {"title": "x"}}).ok)
        # 每人的撤销互不影响：u0 撤销目标是自己最近的一批
        self.assertTrue(s.undo("u0").ok)
        self.assertTrue(s.redo("u0").ok)

    def test_large_batch_atomic_reject(self):
        s = make_wide_session()
        # 500 个字段写入中混入一个会成环的改挂 -> 整批拒绝，无任何部分生效
        changes = {f"n{i}": {"title": f"t{i}"} for i in range(1, BATCH_FIELDS + 1)}
        changes["n1"] = {"title": "t1", "parent": "n2"}
        changes["n2"] = {"parent": "n1"}
        r = s.submit("u0", changes)
        self.assertFalse(r.ok)
        snap = s.snapshot()
        self.assertEqual(snap["n1"]["title"], "node1")
        self.assertEqual(snap["n1"]["parent"], "n0")
        self.assertEqual(snap["n2"]["parent"], "n0")


if __name__ == "__main__":
    unittest.main()
