"""InitService 并行调度单元测试 — services/init_service.py

覆盖:
  - 依赖顺序（schema → items → 其余并行）
  - 并行执行缩短总耗时（与串行对比）
  - 单步失败不阻塞其它步骤
  - cancel 语义（未完成步骤置 CANCELLED）

所有测试 patch 掉 _run_step / check_network / _prepare_ref_db_for_parallel，
不触网、不碰真实数据库。
"""

import asyncio
import time
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest

from services.init_service import STEPS, InitService, StepStatus

ALL_KEYS = [s.key for s in STEPS]


@pytest.fixture
def service():
    return InitService()


def _patch_execution(service, run_step):
    """patch 掉下载执行与网络检查，替换为可控的 fake（返回 ExitStack 作上下文管理器）"""
    stack = ExitStack()
    stack.enter_context(patch.object(service, "_run_step", side_effect=run_step))
    stack.enter_context(patch.object(service, "check_network", new=AsyncMock(return_value=True)))
    stack.enter_context(patch.object(service, "_prepare_ref_db_for_parallel", new=lambda: None))
    return stack


class TestDependencyOrder:
    @pytest.mark.asyncio
    async def test_schema_before_items_before_dependents(self, service):
        """依赖顺序：schema 先于一切；仅依赖 item 表的步骤（icons/sde_data）在 items 后，
        仅依赖 zip/网络的步骤（blueprints/implants/rigs/industry/price_baseline/sde_core）在 schema 后即可并行。
        """
        order: list[str] = []

        async def fake_run_step(key):
            order.append(key)
            return True, "ok"

        with _patch_execution(service, fake_run_step):
            await service._run_sequence(ALL_KEYS)

        assert order[0] == "schema", "schema 无依赖，最先执行"
        idx = {k: order.index(k) for k in order}
        assert idx["schema"] < idx["items"]
        # 依赖 item 表（需 items 写完）→ 在 items 后
        for dep in ["icons", "sde_data", "implants", "rigs"]:
            assert idx["items"] < idx[dep], f"{dep} 应在 items 之后"
        # 仅依赖 zip/网络 → 与 items 并行（只需在 schema 后）
        for dep in ["blueprints", "industry", "price_baseline", "sde_core"]:
            assert idx["schema"] < idx[dep], f"{dep} 应在 schema 之后"
        # sde_data 依赖 blueprints/sde_core/items 都完成
        assert idx["blueprints"] < idx["sde_data"]
        assert idx["sde_core"] < idx["sde_data"]
        assert all(service.get_status()[k] == StepStatus.COMPLETED for k in ALL_KEYS)


class TestParallelExecution:
    @pytest.mark.asyncio
    async def test_wall_clock_is_less_than_serial(self, service):
        """9 步各 50ms：串行需 450ms，并行关键路径仅 schema+items+max(其余)≈150ms"""

        async def fake_run_step(key):
            await asyncio.sleep(0.05)
            return True, "ok"

        with _patch_execution(service, fake_run_step):
            t0 = time.monotonic()
            await service._run_sequence(ALL_KEYS)
            elapsed = time.monotonic() - t0

        # 串行 = 9 × 50ms = 450ms；并行 ≈ 3 × 50ms = 150ms，留足调度余量
        assert elapsed < 0.35, f"应并行执行缩短总耗时，实际 {elapsed:.2f}s"


class TestFailureIsolation:
    @pytest.mark.asyncio
    async def test_one_failure_does_not_block_others(self, service):
        """implants 失败 → 自身 FAILED，其它步骤正常 COMPLETED"""

        async def fake_run_step(key):
            if key == "implants":
                return False, "网络超时"
            return True, "ok"

        with _patch_execution(service, fake_run_step):
            await service._run_sequence(ALL_KEYS)

        status = service.get_status()
        assert status["implants"] == StepStatus.FAILED
        assert service.get_errors()["implants"] == "网络超时"
        for k in [
            "schema",
            "items",
            "blueprints",
            "rigs",
            "industry",
            "icons",
            "sde_core",
            "sde_data",
            "price_baseline",
        ]:
            assert status[k] == StepStatus.COMPLETED, f"{k} 不应被 implants 失败影响"


class TestCancel:
    @pytest.mark.asyncio
    async def test_cancel_marks_unfinished_steps_cancelled(self, service):
        """运行中 cancel → items 置 CANCELLED，其后的依赖步骤也置 CANCELLED"""
        started = asyncio.Event()
        release = asyncio.Event()

        async def fake_run_step(key):
            if key == "items":
                started.set()
                await release.wait()
                return True, "ok"
            return True, "ok"

        async def run():
            with _patch_execution(service, fake_run_step):
                task = asyncio.create_task(service._run_sequence(ALL_KEYS))
                await started.wait()
                service.cancel()
                release.set()
                await task

        await run()

        status = service.get_status()
        assert status["items"] == StepStatus.CANCELLED
        # 依赖 items 的步骤（icons/sde_data/implants/rigs）被取消
        assert status["icons"] == StepStatus.CANCELLED, "依赖 items 的步骤应被取消"
        assert status["sde_data"] == StepStatus.CANCELLED, "依赖 items 的步骤应被取消"
        assert status["implants"] == StepStatus.CANCELLED, "依赖 items 的步骤应被取消"
        assert status["rigs"] == StepStatus.CANCELLED, "依赖 items 的步骤应被取消"
        # 仅依赖 zip/网络的步骤不再被 items 取消（提前并行）
        assert status["blueprints"] == StepStatus.COMPLETED
        assert status["sde_core"] == StepStatus.COMPLETED


class TestNetworkPrecheck:
    @pytest.mark.asyncio
    async def test_network_precheck_failure_does_not_block_steps(self, service):
        """网络预检失败 → 不 FAILED 步骤，继续尝试实际下载。

        大 YAML 解析（C loader 持 GIL）会阻塞事件循环导致预检超时误判，
        预检失败不应连累步骤——实际下载成功才算成功。
        """
        ran: list[str] = []

        async def fake_run_step(key):
            ran.append(key)
            return True, "ok"

        with (
            patch.object(service, "_run_step", side_effect=fake_run_step),
            patch.object(service, "check_network", new=AsyncMock(return_value=False)),
            patch.object(service, "_prepare_ref_db_for_parallel", new=lambda: None),
        ):
            await service._run_sequence(ALL_KEYS)

        # 所有网络步骤都实际执行了（而非被预检失败直接 FAILED）
        assert "blueprints" in ran
        assert "icons" in ran
        status = service.get_status()
        assert status["blueprints"] == StepStatus.COMPLETED
        assert status["icons"] == StepStatus.COMPLETED
