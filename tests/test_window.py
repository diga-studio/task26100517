"""历史窗口：最近 200 个成功提交的批次才可成为撤销/重做目标。"""

import unittest

from mindmap_undo import WINDOW_SIZE, FailureReason, MapSession


def make_session():
    return MapSession("r", {
        "r": ("root", None),
        "a": ("A", "r"),
        "b": ("B", "r"),
    })


class WindowEvictionTest(unittest.TestCase):
    def test_evicted_batch_never_targetable_newer_still_restores_it(self):
        s = make_session()
        # 独立推导用的模型
        model = {n: {"title": t, "parent": p} for n, (t, p) in
                 {"r": ("root", None), "a": ("A", "r"), "b": ("B", "r")}.items()}

        def check(step):
            snap = s.snapshot()
            for node, expected in model.items():
                self.assertEqual(snap[node]["title"], expected["title"],
                                 f"step {step} {node}.title")
                self.assertEqual(snap[node]["parent"], expected["parent"],
                                 f"step {step} {node}.parent")

        # 批次 #1：u1 把 a 标题改为 v1
        self.assertTrue(s.submit("u1", {"a": {"title": "v1"}}).ok)
        model["a"] = {"title": "v1", "parent": "r"}
        check(1)
        # 批次 #2：u2 把 a 标题覆盖为 v2
        self.assertTrue(s.submit("u2", {"a": {"title": "v2"}}).ok)
        model["a"]["title"] = "v2"
        check(2)
        # 批次 #3..#201：u2 轮流改 b 的标题，把窗口推满（共 201 批，#1 被淘汰）
        for i in range(3, WINDOW_SIZE + 2):
            self.assertTrue(s.submit("u2", {"b": {"title": f"b{i}"}}).ok)
            model["b"]["title"] = f"b{i}"
        check("after-201")
        # u1 唯一的批次 #1 已被淘汰：永远不能再成为目标
        r = s.undo("u1")
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, FailureReason.NO_TARGET)
        # 淘汰不改变当前导图
        check("after-failed-undo")
        # u2 连续撤销 #201..#3（b 的标题依次回退）
        for i in range(WINDOW_SIZE + 1, 2, -1):
            self.assertTrue(s.undo("u2").ok)
            model["b"]["title"] = f"b{i-1}" if i > 3 else "B"
            check(f"undo-{i}")
        # 撤销 #2：恢复出被淘汰批次 #1 留下的效果 v1
        self.assertTrue(s.undo("u2").ok)
        model["a"]["title"] = "v1"
        check("undo-#2")
        # 被淘汰的 #1 本身永远不能再成为目标
        r = s.undo("u1")
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, FailureReason.NO_TARGET)
        check("final")

    def test_evicted_redo_target_fails(self):
        s = make_session()
        s.submit("u1", {"a": {"title": "v1"}})
        self.assertTrue(s.undo("u1").ok)  # #1 进入 u1 的重做分支
        # 他人提交 200 批把 #1 挤出窗口；他人的提交不清空重做分支，
        # 但目标已被淘汰，永远不能再重做
        for i in range(WINDOW_SIZE):
            self.assertTrue(s.submit("u2", {"b": {"title": f"b{i}"}}).ok)
        r = s.redo("u1")
        self.assertFalse(r.ok)
        self.assertIn(r.reason, (FailureReason.NO_TARGET, FailureReason.EVICTED))
        # 失败后导图不变
        self.assertEqual(s.snapshot()["a"]["title"], "A")

    def test_undo_redo_do_not_refresh_window(self):
        s = make_session()
        # u1 提交 #1..#200
        for i in range(1, WINDOW_SIZE + 1):
            self.assertTrue(s.submit("u1", {"a": {"title": f"t{i}"}}).ok)
        # u1 撤销最早的 #1？不行——撤销目标总是最近的 #200
        self.assertTrue(s.undo("u1").ok)  # 撤销 #200
        # 撤销/重做不占用也不刷新窗口：u2 再提交 1 批，#1 仍被淘汰
        self.assertTrue(s.submit("u2", {"b": {"title": "x"}}).ok)
        # u1 一路撤销到窗口内最早的 #2
        for _ in range(WINDOW_SIZE - 2):
            self.assertTrue(s.undo("u1").ok)
        # 现在 u1 在窗口内的批次全部撤销完，#1 已被淘汰
        r = s.undo("u1")
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, FailureReason.NO_TARGET)
        # #2 也被撤销后，生效的是被淘汰批次 #1 留下的效果（其编辑已固化）
        self.assertEqual(s.snapshot()["a"]["title"], "t1")


class RedoAcrossOthersTest(unittest.TestCase):
    def test_others_commits_keep_redo_branch(self):
        s = make_session()
        s.submit("u1", {"a": {"title": "v1"}})
        self.assertTrue(s.undo("u1").ok)
        # 多名同事交错提交，本人重做分支保留
        for user in ("u2", "u3", "u4"):
            self.assertTrue(s.submit(user, {"b": {"title": f"by-{user}"}}).ok)
        self.assertTrue(s.redo("u1").ok)
        self.assertEqual(s.snapshot()["a"]["title"], "v1")
        self.assertEqual(s.snapshot()["b"]["title"], "by-u4")


if __name__ == "__main__":
    unittest.main()
