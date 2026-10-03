"""长序列提交的常驻内存检查。"""

import gc
import resource
import sys
import unittest

from mindmap_undo import MindMap, NodePatch

MIB = 1024 * 1024


def peak_rss_bytes() -> int:
    """进程常驻内存峰值（字节）。Linux 单位为 KiB，macOS 为字节。"""
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return usage if sys.platform == "darwin" else usage * 1024


class MemoryGrowthTest(unittest.TestCase):
    def test_100k_single_field_commits(self):
        # 30 个节点的小树，单字段编辑，值不超过 200 字符
        nodes = {"n0": ("t", None)}
        for i in range(1, 30):
            nodes[f"n{i}"] = ("t", "n0")
        m = MindMap("n0", nodes)
        value = "v" * 200

        total = 100_000
        checkpoint = 10_000
        rss_at_checkpoint = None
        for i in range(total):
            m.submit("u1", {"n1": NodePatch(title=f"{value}{i}")})
            if i + 1 == checkpoint:
                gc.collect()
                rss_at_checkpoint = peak_rss_bytes()
        gc.collect()
        rss_at_end = peak_rss_bytes()

        growth = rss_at_end - rss_at_checkpoint
        self.assertLessEqual(
            growth,
            32 * MIB,
            f"第 {checkpoint} 次到第 {total} 次提交之间常驻内存增长 "
            f"{growth / MIB:.1f} MiB，超过 32 MiB",
        )


if __name__ == "__main__":
    unittest.main()
