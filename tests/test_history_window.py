"""历史窗口与重做分支验收测试。"""

import unittest

from mindmap_undo import HISTORY_WINDOW, MindMap, NodePatch


def make_map() -> MindMap:
    return MindMap(
        "R",
        {
            "R": ("root", None),
            "A": ("a", "R"),
            "B": ("b", "R"),
            "C": ("c", "R"),
        },
        )


def titles(m: MindMap):
    return {nid: s.title for nid, s in m.snapshot().items()}


class HistoryWindowTest(unittest.TestCase):
    def test_evicted_batch_not_undoable_but_newer_restores_its_effect(self):
        m = make_map()
        # 第 1 批：u1 把 A 标题改为 v1（将被淘汰）
        m.submit("u1", {"A": NodePatch(title="v1")})
        # 再提交 HISTORY_WINDOW 批，把第 1 批挤出窗口
        for i in range(HISTORY_WINDOW):
            m.submit("u2", {"B": NodePatch(title=f"b{i}")})
        # 被淘汰批次永不可回退：u1 撤销失败
        self.assertFalse(m.undo("u1"))
        self.assertEqual(titles(m)["A"], "v1")
        # 窗口内较新批次仍可撤销：u2 撤销最近一批
        self.assertTrue(m.undo("u2"))
        self.assertEqual(titles(m)["B"], f"b{HISTORY_WINDOW - 2}")

    def test_newer_batch_undo_restores_evicted_value(self):
        m = make_map()
        m.submit("u1", {"A": NodePatch(title="v1")})  # 将被淘汰
        for i in range(HISTORY_WINDOW - 1):
            m.submit("u2", {"B": NodePatch(title=f"b{i}")})
        # 第 HISTORY_WINDOW+1 批：u3 覆盖 A 标题，把第 1 批挤出窗口
        m.submit("u3", {"A": NodePatch(title="v2")})
        self.assertFalse(m.undo("u1"))  # 已淘汰
        # u3 撤销后恢复被淘汰批次留下的效果 v1
        self.assertTrue(m.undo("u3"))
        self.assertEqual(titles(m)["A"], "v1")

    def test_others_commit_preserves_my_redo_branch(self):
        m = make_map()
        m.submit("u1", {"A": NodePatch(title="x")})
        self.assertTrue(m.undo("u1"))
        # 他人提交新批次，不清空 u1 的重做分支
        m.submit("u2", {"B": NodePatch(title="b2")})
        self.assertTrue(m.redo("u1"))
        self.assertEqual(titles(m)["A"], "x")
        self.assertEqual(titles(m)["B"], "b2")

    def test_own_commit_clears_redo_branch(self):
        m = make_map()
        m.submit("u1", {"A": NodePatch(title="x")})
        self.assertTrue(m.undo("u1"))
        m.submit("u1", {"C": NodePatch(title="c2")})
        self.assertFalse(m.redo("u1"))
        self.assertEqual(titles(m)["A"], "a")

    def test_full_tree_matches_reference_model(self):
        """多用户交错操作，每次成功后完整树与独立推导的参考模型一致。"""
        m = make_map()
        # 参考模型：字段 -> 按提交顺序的 (批次号, 生效中, 值)
        ref: dict = {}
        batches: dict = {}  # 批次号 -> (用户, {字段: 值}, 生效中)
        undo_stacks: dict = {}
        redo_stacks: dict = {}
        seq = 0

        def ref_value(node, field):
            for bid, active, value in reversed(ref.get((node, field), [])):
                if batches[bid][2]:
                    return value
            return {"R": "root", "A": "a", "B": "b", "C": "c"}[node] if field == "title" \
                else {"R": None, "A": "R", "B": "R", "C": "R"}[node]

        def check():
            snap = m.snapshot()
            for node in ("R", "A", "B", "C"):
                self.assertEqual(snap[node].title, ref_value(node, "title"))
                self.assertEqual(snap[node].parent_id, ref_value(node, "parent"))

        def submit(user, changes):
            nonlocal seq
            m.submit(user, changes)
            writes = {}
            for node, patch in changes.items():
                if patch.title is not None:
                    writes[(node, "title")] = patch.title
                if patch.parent_id is not None:
                    writes[(node, "parent")] = patch.parent_id
            batches[seq] = (user, writes, True)
            for key, value in writes.items():
                ref.setdefault(key, []).append((seq, True, value))
            undo_stacks.setdefault(user, []).append(seq)
            redo_stacks[user] = []
            seq += 1

        def undo(user):
            expected = bool(undo_stacks.get(user))
            if expected:
                bid = undo_stacks[user][-1]
                _, writes, _ = batches[bid]
                # 冲突判定：每个字段当前生效编辑必须是该批次
                for key, value in writes.items():
                    top = next(
                        (b for b, a, v in reversed(ref.get(key, [])) if batches[b][2]),
                        None,
                    )
                    if top != bid:
                        expected = False
                        break
            self.assertEqual(m.undo(user), expected)
            if expected:
                bid = undo_stacks[user].pop()
                user_, writes, _ = batches[bid]
                batches[bid] = (user_, writes, False)
                redo_stacks.setdefault(user, []).append(bid)

        def redo(user):
            expected = bool(redo_stacks.get(user))
            self.assertEqual(m.redo(user), expected)
            if expected:
                bid = redo_stacks[user].pop()
                user_, writes, _ = batches[bid]
                batches[bid] = (user_, writes, True)
                undo_stacks.setdefault(user, []).append(bid)

        # 交错操作序列（只含标题，避免参考模型里重复实现树校验）
        submit("u1", {"A": NodePatch(title="a1")})
        submit("u2", {"A": NodePatch(title="a2"), "B": NodePatch(title="b2")})
        check()
        undo("u1")          # 冲突：A.title 被 u2 覆盖
        check()
        undo("u2")          # 成功，u1 的编辑重新生效
        check()
        undo("u1")          # 现在可以撤销
        check()
        redo("u1")
        check()
        submit("u3", {"C": NodePatch(title="c3")})
        redo("u2")          # u3 的提交不清空 u2 的重做分支
        check()
        undo("u2")
        undo("u2")          # 连续撤销：上一撤销入重做栈，目标前移
        check()
        redo("u2")
        redo("u2")
        check()
        submit("u1", {"A": NodePatch(title="a9"), "B": NodePatch(title="b9")})
        undo("u1")
        check()
        redo("u1")
        check()


if __name__ == "__main__":
    unittest.main()
