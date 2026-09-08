"""控件尺寸自适应工具测试。"""

import pytest
from PySide6.QtWidgets import QLabel, QLineEdit

from ui_pyside6.sizing import (
    _LINE_EDIT_CHROME_PX,
    ElidedLabel,
    elide_label,
    fit_line_edit_width,
    text_width,
)

pytestmark = pytest.mark.ui


class TestFitLineEditWidth:
    def test_uses_placeholder_as_probe(self, qapp):
        e = QLineEdit()
        e.setPlaceholderText("搜索物品名称")
        width = fit_line_edit_width(e)
        assert width > 0
        assert e.minimumWidth() == width
        # 必须有上限，否则 QLineEdit 会在工具栏里横向撑满
        assert e.maximumWidth() > width

    def test_sample_overrides_placeholder(self, qapp):
        e = QLineEdit()
        e.setPlaceholderText("很短")
        assert fit_line_edit_width(e, "100") == text_width(e, "100") + _LINE_EDIT_CHROME_PX

    def test_no_probe_leaves_widget_untouched(self, qapp):
        e = QLineEdit()
        assert fit_line_edit_width(e) == 0
        assert e.minimumWidth() == 0

    def test_width_grows_with_font(self, qapp):
        from PySide6.QtGui import QFont

        e = QLineEdit()
        e.setPlaceholderText("搜索物品名称")
        small = fit_line_edit_width(e)
        e.setFont(QFont(e.font().family(), e.font().pointSize() + 6))
        assert fit_line_edit_width(e) > small


class TestElideLabel:
    LONG = "一个非常非常长的标签文本内容"

    def test_elides_and_keeps_full_text_in_tooltip(self, qapp):
        lab = QLabel(self.LONG)
        elide_label(lab, 40)
        assert lab.text() != self.LONG
        assert lab.toolTip() == self.LONG

    def test_repeat_call_uses_original_text(self, qapp):
        """重复省略必须基于原文，不能对已省略的文本再省略。"""
        lab = QLabel(self.LONG)
        elide_label(lab, 40)
        first = lab.text()
        elide_label(lab, 40)
        assert lab.text() == first

    def test_short_text_is_untouched(self, qapp):
        lab = QLabel("短")
        elide_label(lab, 200)
        assert lab.text() == "短"
        assert lab.toolTip() == ""


class TestElidedLabel:
    LONG = "输入物品名称/ID后搜索，双击行查看实时订单"

    def _shown(self, qapp, width: int) -> ElidedLabel:
        """Qt 只在控件可见时投递 resizeEvent，因此测试需先 show。"""
        lab = ElidedLabel(self.LONG)
        lab.resize(width, 20)
        lab.show()
        qapp.processEvents()
        return lab

    def test_elides_when_narrow(self, qapp):
        lab = self._shown(qapp, 80)
        assert lab.text() != self.LONG
        assert lab.toolTip() == self.LONG
        assert lab.fullText() == self.LONG

    def test_full_text_when_wide_enough(self, qapp):
        lab = self._shown(qapp, 1000)
        assert lab.text() == self.LONG
        assert lab.toolTip() == ""

    def test_set_text_keeps_full_text(self, qapp):
        lab = self._shown(qapp, 80)
        lab.setText(self.LONG)
        assert lab.fullText() == self.LONG
        assert lab.text() != self.LONG
