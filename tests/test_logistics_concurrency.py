"""06-9 并发端到端回归 —— `compute_jumps` 的模块级星门图缓存。

背景（2026-10-17 审计 06-9）：`services/logistics.py` 的 `_GATE_GRAPH/_GATE_SECURITY/
_JUMP_CACHE` 是模块级可变缓存。旧实现先发布 `_GATE_GRAPH`、再原地 `_GATE_SECURITY.clear()`
+ `update()` —— 窗口期的并发读会拿到空安全等级表，`highsec` 口径返回 `None`，并且这个
错误结果会被 `_JUMP_CACHE` 固化（进程不重启就不会自愈）。修复：发布时先换 security、
后换 graph，两者都整体替换引用；`_JUMP_CACHE` 的读写进 `_CACHE_LOCK`，建图与 BFS 不进锁。

本用例用 threading + 假 DB（不碰真实 reference.db，CI/validate 可跑）做两段：
1) 发布窗口：用一个 `clear()` 会阻塞的 dict 把旧实现的窗口放大到必现；窗口内并发读
   `highsec` 必须仍返回正确跳数（旧实现返回 None → 红）。
2) 并发首建：8 个线程同时解锁星门图（Barrier 对齐），全部结果正确、无异常。
"""

from __future__ import annotations

import threading

import pytest

import services.logistics as logistics

pytestmark = pytest.mark.fast

#: 假星门图：1—2—3—4 一条链；所有星系 0.9 安全（highsec 全通）。
_GRAPH_ROWS = [(1, 2), (2, 3), (3, 4)]
_SECURITY_ROWS = [(1, 0.9), (2, 0.9), (3, 0.9), (4, 0.9)]

#: 无安全过滤与高安口径在一条链上的期望值（1→4 都是 3）。
_EXPECTED = {
    (1, 4, "shortest"): 3,
    (1, 4, "highsec"): 3,
    (4, 1, "highsec"): 3,
    (1, 3, "shortest"): 2,
    (2, 4, "shortest"): 2,
    (9, 1, "shortest"): None,  # 图上没有的星系 → 不可达
}


class _FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql: str):
        if "FROM solar_system" in sql:
            return list(_SECURITY_ROWS)
        return list(_GRAPH_ROWS)


class _FakeDb:
    def __init__(self) -> None:
        self.connects = 0

    def connect(self, *aliases: str):
        self.connects += 1
        return _FakeConn()


class _BlockingSecurity(dict):
    """把 `_GATE_SECURITY.clear()` 变成可等待的窗口（只为放大旧实现的竞态窗口）。"""

    def __init__(self) -> None:
        super().__init__()
        self.clearing = threading.Event()
        self.release = threading.Event()

    def clear(self) -> None:
        super().clear()
        self.clearing.set()
        self.release.wait(2.0)


def _reset(monkeypatch: pytest.MonkeyPatch, db: _FakeDb) -> None:
    monkeypatch.setattr(logistics, "_default_db", lambda: db)
    monkeypatch.setattr(logistics, "_GATE_GRAPH", None)
    monkeypatch.setattr(logistics, "_GATE_SECURITY", {})
    monkeypatch.setattr(logistics, "_JUMP_CACHE", {})


def test_concurrent_first_build_publishes_complete_graph(monkeypatch):
    # ── 1) 发布窗口：旧实现会命中慢 clear()，窗口内读 highsec 必须仍正确 ──
    db = _FakeDb()
    _reset(monkeypatch, db)
    slow = _BlockingSecurity()
    monkeypatch.setattr(logistics, "_GATE_SECURITY", slow)
    builder_result: dict[str, int | None] = {}

    def build() -> None:
        builder_result["shortest"] = logistics.compute_jumps(1, 4, "shortest")

    builder = threading.Thread(target=build)
    builder.start()
    window_hit = slow.clearing.wait(0.5)  # 旧实现：立刻命中；修复后：False
    during_build: int | None = None
    if window_hit:
        during_build = logistics.compute_jumps(1, 4, "highsec")
        slow.release.set()
    builder.join(timeout=10)
    assert not builder.is_alive()
    if window_hit:
        assert during_build == 3, "建图发布窗口内并发读不得看到半成品安全等级表（旧实现返回 None）"
    assert logistics.compute_jumps(1, 4, "highsec") == 3, "窗口期读到的错误不得被 _JUMP_CACHE 固化"

    # ── 2) 并发首建：8 线程同时解锁星门图，结果全部正确、无异常 ──
    db = _FakeDb()
    _reset(monkeypatch, db)
    barrier = threading.Barrier(8)
    results: list[tuple[tuple[int, int, str], int | None]] = []
    errors: list[BaseException] = []
    pairs = list(_EXPECTED)

    def call(pair: tuple[int, int, str]) -> None:
        barrier.wait()
        try:
            results.append((pair, logistics.compute_jumps(*pair)))
        except BaseException as exc:  # 线程里必须把异常带回主线程
            errors.append(exc)

    threads = [threading.Thread(target=call, args=(pairs[i % len(pairs)],)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"并发首建抛异常：{errors!r}"
    assert not any(t.is_alive() for t in threads), "并发首建线程未在 30s 内结束（疑似死锁）"
    assert db.connects >= 1, "星门图缓存没有真正构建"
    assert len(results) == 8
    for pair, got in results:
        assert got == _EXPECTED[pair], f"{pair}: 期望 {_EXPECTED[pair]}，并发调用得到 {got}"
