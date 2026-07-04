"""蓝图 NPC 卖家查询对话框"""

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

import ui_pyside6.theme as theme
from core.container import get_container


class NpcSellerDialog(QDialog):
    """蓝图 NPC 卖家信息弹窗 — 显示可购买 BPO 的 NPC 公司"""

    def __init__(self, blueprint_type_id: int, blueprint_name: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"蓝图 NPC 卖家 — {blueprint_name}")
        self.setMinimumSize(550, 350)
        self.setObjectName("npc_seller_dialog")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 蓝图基本信息
        header = QLabel(f"<b>{blueprint_name}</b>  (type_id: {blueprint_type_id})")
        header.setStyleSheet(f"color: {theme.PRIMARY}; font-size: 14px;")
        layout.addWidget(header)

        # 说明
        note = QLabel(
            "以下为与蓝图相关的 NPC 公司和研究代理机构。\n"
            "T1 蓝图原版(BPO)通常在 NPC 空间站有售，可通过市场界面购得。"
        )
        note.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        note.setWordWrap(True)
        layout.addWidget(note)

        # 查询 NPC 数据
        self._build_content(layout, blueprint_type_id)

        # 关闭按钮
        btn_bar = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_bar.rejected.connect(self.close)
        layout.addWidget(btn_bar)

    def _build_content(self, layout, blueprint_type_id: int):
        """查询并显示 NPC 公司"""
        db = get_container().db
        rows = []
        with db.connect("ref") as conn:
            cur = conn.cursor()

            # 1. 查 blueprint 的 market group
            market_path = ""
            cur.execute(
                "SELECT zh_name, en_name, market_group_id FROM item WHERE type_id = ?",
                (blueprint_type_id,),
            )
            item = cur.fetchone()
            if item:
                mg_id = item[2]
                if mg_id:
                    # 回溯 market tree 构建路径
                    path_parts = []
                    current_id = mg_id
                    while current_id:
                        cur.execute(
                            "SELECT parent_group_id, zh_name, en_name FROM market_tree WHERE market_group_id = ?",
                            (current_id,),
                        )
                        mg = cur.fetchone()
                        if mg:
                            path_parts.append(mg[1] or mg[2] or str(current_id))
                            current_id = mg[0]
                        else:
                            current_id = None
                    market_path = " → ".join(reversed(path_parts))

            # 2. 查 NPC 公司信息
            cur.execute(
                """
                SELECT nc.corporation_id, nc.zh_name, nc.en_name,
                       s.station_name, s.solar_system_id
                FROM npc_corporation nc
                LEFT JOIN station s ON nc.corporation_id = s.corporation_id
                WHERE nc.corporation_id IN (
                    SELECT corporation_id FROM agent WHERE division_id = 22  -- 研究代理
                    UNION
                    SELECT corporation_id FROM npc_corporation
                    WHERE corporation_id < 1001000  -- NPC 公司
                )
                ORDER BY nc.corporation_id
                LIMIT 50
            """,
            )
            rows = [dict(r) for r in cur.fetchall()]

        # Market group info
        if market_path:
            mg_label = QLabel(f"市场分类: {market_path}")
            mg_label.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 12px;")
            layout.addWidget(mg_label)

        # 表格展示 NPC 公司
        if rows:
            table = QTableWidget()
            table.setColumnCount(3)
            table.setHorizontalHeaderLabels(["NPC 公司", "空间站", "研究代理"])
            table.setAlternatingRowColors(True)
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.verticalHeader().setVisible(False)
            hdr = table.horizontalHeader()
            hdr.setStretchLastSection(True)
            hdr.resizeSection(0, 180)
            hdr.resizeSection(1, 200)

            table.setRowCount(len(rows))
            for i, r in enumerate(rows):
                name = r.get("zh_name") or r.get("en_name") or str(r["corporation_id"])
                station = r.get("station_name") or "—"
                table.setItem(i, 0, QTableWidgetItem(name))
                table.setItem(i, 1, QTableWidgetItem(station))
                table.setItem(i, 2, QTableWidgetItem("是" if r.get("solar_system_id") else "—"))

            layout.addWidget(table, stretch=1)
        else:
            no_data = QLabel("暂无 NPC 相关数据")
            no_data.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
            layout.addWidget(no_data)
