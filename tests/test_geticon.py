"""图标下载服务单元测试 — services/workers/geticon.py

覆盖: 图标路径生成、缓存逻辑、下载触发。
使用 tmp_path + mock aiohttp 避免真实网络请求和磁盘污染。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from tools.downloaders.geticon import ICON_SIZE, download_all, download_icon


class TestDownloadIconCacheHit:
    """download_icon — 缓存命中时跳过下载"""

    @pytest.mark.asyncio
    async def test_returns_true_when_png_exists(self, tmp_path):
        """图标 .png 已存在时返回 True，不发起 HTTP 请求，不覆盖已有文件"""
        icon_file = tmp_path / "12345.png"
        icon_file.write_bytes(b"existing_data")

        session = MagicMock()
        semaphore = asyncio.Semaphore(1)
        progress = [0, 0]

        with patch("services.workers.geticon.ICON_CACHE_DIR", tmp_path):
            result = await download_icon(session, 12345, semaphore, progress)

        assert result is True
        assert progress == [1, 0]  # total +1, new_downloads 不变
        session.get.assert_not_called()
        assert icon_file.read_bytes() == b"existing_data"  # 确保未被覆盖


class TestDownloadIconSuccess:
    """download_icon — 成功下载新图标"""

    @pytest.mark.asyncio
    async def test_downloads_and_writes_bytes(self, tmp_path):
        """HTTP 200 时将响应体写入 {type_id}.png，更新进度计数"""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read = AsyncMock(return_value=b"fake_png_data")
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        session = MagicMock()
        session.get = MagicMock(return_value=mock_cm)
        semaphore = asyncio.Semaphore(1)
        progress = [0, 0]

        with patch("services.workers.geticon.ICON_CACHE_DIR", tmp_path):
            result = await download_icon(session, 12345, semaphore, progress)

        assert result is True
        assert progress == [1, 1]  # total +1, new_downloads +1
        session.get.assert_called_once_with(f"https://images.evetech.net/types/12345/icon?size={ICON_SIZE}")
        written = (tmp_path / "12345.png").read_bytes()
        assert written == b"fake_png_data"


class TestDownloadIconNoIcon:
    """download_icon — 服务器返回 404 时创建 .noicon 标记"""

    @pytest.mark.asyncio
    async def test_creates_noicon_marker_on_404(self, tmp_path):
        """HTTP 404 时创建 .noicon 标记文件避免重复请求，返回 False"""
        mock_resp = MagicMock()
        mock_resp.status = 404
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        session = MagicMock()
        session.get = MagicMock(return_value=mock_cm)
        semaphore = asyncio.Semaphore(1)
        progress = [0, 0]

        with patch("services.workers.geticon.ICON_CACHE_DIR", tmp_path):
            result = await download_icon(session, 12345, semaphore, progress)

        assert result is False
        assert progress == [1, 0]  # total +1, new_downloads 不变

        noicon_file = tmp_path / "12345.noicon"
        assert noicon_file.exists(), "应创建 .noicon 标记文件"
        assert not (tmp_path / "12345.png").exists(), "不应创建 .png 文件"


class TestDownloadIconClientError:
    """download_icon — 网络异常时优雅降级"""

    @pytest.mark.asyncio
    async def test_returns_false_on_aiohttp_error(self, tmp_path):
        """aiohttp.ClientError 时返回 False，不写任何文件"""
        session = MagicMock()
        session.get = MagicMock(side_effect=aiohttp.ClientError("Connection refused"))
        semaphore = asyncio.Semaphore(1)
        progress = [0, 0]

        with (
            patch("services.workers.geticon.ICON_CACHE_DIR", tmp_path),
            patch("services.workers.geticon.log"),  # 抑制错误日志
        ):
            result = await download_icon(session, 12345, semaphore, progress)

        assert result is False
        assert not (tmp_path / "12345.png").exists()
        assert not (tmp_path / "12345.noicon").exists()


class TestDownloadAllFilter:
    """download_all — 过滤已有图标并分批下载"""

    @pytest.mark.asyncio
    async def test_filters_existing_and_tracks_progress(self, tmp_path):
        """已有 .png / .noicon 被跳过，只下载缺失的 type_id，进度正确"""
        # ── 准备缓存目录 ──
        (tmp_path / "1.png").touch()  # 已有图标 → 跳过
        (tmp_path / "3.noicon").touch()  # 无图标标记 → 跳过
        # type_ids: 1(有png), 2(缺), 3(有noicon), 4(缺), 5(缺)
        type_ids = [1, 2, 3, 4, 5]

        downloaded = []

        async def fake_download_icon(_session, type_id, _semaphore, progress):
            downloaded.append(type_id)
            progress[0] += 1
            progress[1] += 1
            return True

        with (
            patch("services.workers.geticon.ICON_CACHE_DIR", tmp_path),
            patch("services.workers.geticon.download_icon", side_effect=fake_download_icon),
            patch("services.workers.geticon.log"),
        ):
            await download_all(MagicMock(), type_ids)

        assert downloaded == [2, 4, 5], f"应只下载缺失的 type_id, 实际: {downloaded}"
