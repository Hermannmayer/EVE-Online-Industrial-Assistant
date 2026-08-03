"""状态栏统计测试 — status_bar.py（需求2 + 运行中计数 bug 修复）"""

from ui_pyside6.views.industry.status_bar import StatusBar


class TestStatusBarStats:
    def test_running_counts_in_progress_and_running(self, qapp):
        """DB 运行中写 in_progress → 运行中计数同时包含 in_progress 与 running。"""
        bar = StatusBar()
        plans = [
            {"status": "in_progress"},
            {"status": "running"},
            {"status": "pending"},
            {"status": "pending"},
            {"status": "ready"},
        ]
        bar.update_stats(plans)
        text = bar._stats_label.text()
        assert "运行中: 2" in text
        assert "待排: 2" in text

    def test_materials_lines_sums_checked_parallels(self, qapp):
        """产线(备料) = 勾选备料计划的 parallels 之和。"""
        bar = StatusBar()
        plans = [
            {"status": "pending", "materials_ready": 1, "parallels": 2},
            {"status": "pending", "materials_ready": 1, "parallels": 3},
            {"status": "pending", "materials_ready": 0, "parallels": 9},  # 未勾选不计
            {"status": "pending", "materials_ready": 1},  # 缺 parallels → 兜底 0
        ]
        bar.update_stats(plans)
        assert "产线(备料): 5" in bar._stats_label.text()

    def test_update_material_text(self, qapp):
        bar = StatusBar()
        bar.update_material(12345.67, 88.9)
        assert "备料中采购: 12,346 ISK" in bar._material_label.text()
        assert "体积: 88.9 m3" in bar._material_label.text()
