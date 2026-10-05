"""跑测环境守卫（`tests/conftest.py`）的契约。

回归背景：Windows + `QT_QPA_PLATFORM=offscreen` 下 `QQuickWidget` 会卡死在
`PageHost.setSource()`（Qt 的 QML 线程空转、无 Python 栈），2026-09-27 把整个
`ui-retest` 档拖成无摘要，2026-10-05 本机又踩（同一文件真平台 2.36s 通过 / offscreen 卡死）。
这条规矩原先只在 `docs/dev/testing.md` 里当散文写，现在做成启动即拒绝的硬门 ——
这里钉住它的判定表：**只有 Windows + offscreen 才拒**，Linux CI 与真平台都要放行。
"""

from __future__ import annotations

import pytest

from tests.conftest import offscreen_is_forbidden


@pytest.mark.parametrize(
    ("platform_name", "qpa_platform", "allow_env", "expected"),
    [
        ("win32", "offscreen", "", True),  # 本机踩过的那个组合
        ("win32", "OFFSCREEN ", "", True),  # 大小写/空格不敏感
        ("win32", "offscreen", "1", False),  # 显式放行（做实验用）
        ("win32", "", "", False),  # 真平台：默认，也是推荐跑法
        ("win32", "minimal", "", False),  # 别的插件平台不受这条约束
        ("linux", "offscreen", "", False),  # Linux CI（无显示器）必须能用
        ("darwin", "offscreen", "", False),  # 非 Windows 一律不管
    ],
)
def test_offscreen_guard_only_refuses_windows(platform_name, qpa_platform, allow_env, expected):
    assert offscreen_is_forbidden(platform_name, qpa_platform, allow_env) is expected
