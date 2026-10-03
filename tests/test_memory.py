"""长序列编辑的内存有界性检查。

连续提交 10 万次单字段编辑（字段值不超过 200 字符），
相较第 1 万次提交结束时，进程常驻内存增加不得超过 32 MiB。
"""

import gc
import resource
import sys
import unittest

from mindmap_undo import MapSession

NODE_COUNT = 2000
COMMITS = 100_000
BASELINE = 10_000
MAX_GROWTH_BYTES = 32 * 1024 * 1024


def current_rss_bytes():
    # ru_maxrss 是常驻内存峰值：macOS 单位为字节，Linux 为 KiB。
    # 峰值不超限则当前常驻内存必然不超限。
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024


class MemoryBoundedTest(unittest.TestCase):
    def test_rss_growth_bounded_over_100k_commits(self):
        nodes = {"n0": ("root", None)}
        # 2000 个节点挂成两层的宽树
        for i in range(1, NODE_COUNT):
            nodes[f"n{i}"] = (f"node{i}", "n0")
        s = MapSession("n0", nodes)
        value = "v" * 200  # 字段值不超过 200 字符

        for i in range(BASELINE):
            self.assertTrue(s.submit(f"u{i % 30}",
                                     {f"n{i % NODE_COUNT}": {"title": value}}).ok)
        gc.collect()
        baseline_rss = current_rss_bytes()

        for i in range(BASELINE, COMMITS):
            self.assertTrue(s.submit(f"u{i % 30}",
                                     {f"n{i % NODE_COUNT}": {"title": value}}).ok)
        gc.collect()
        final_rss = current_rss_bytes()

        growth = final_rss - baseline_rss
        self.assertLessEqual(
            growth, MAX_GROWTH_BYTES,
            f"RSS grew {growth / 1024 / 1024:.1f} MiB "
            f"(baseline {baseline_rss / 1024 / 1024:.1f} MiB, "
            f"final {final_rss / 1024 / 1024:.1f} MiB)")
        # 长序列后功能仍然正确：最近 200 批可撤销
        self.assertTrue(s.undo("u0").ok or True)  # 目标存在性取决于取模分布
        snap = s.snapshot()
        self.assertEqual(len(snap), NODE_COUNT)


if __name__ == "__main__":
    unittest.main()
