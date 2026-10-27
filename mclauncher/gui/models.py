from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from .theme import palette

TYPE_LABELS = {
    "release": "正式版",
    "snapshot": "快照",
    "old_beta": "远古 Beta",
    "old_alpha": "远古 Alpha",
}
TYPE_COLORS = {
    "release": "#0F6CBD",
    "snapshot": "#CA5010",
    "old_beta": "#7A7574",
    "old_alpha": "#7A7574",
}


class VersionTableModel(QAbstractTableModel):
    HEADERS = ["版本", "类型", "发布时间", "状态"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []

    def set_versions(self, rows: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def row_at(self, row: int) -> dict[str, Any] | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        column = index.column()
        if role == Qt.DisplayRole:
            if column == 0:
                return row.get("id", "")
            if column == 1:
                return TYPE_LABELS.get(row.get("type", ""), row.get("type", ""))
            if column == 2:
                return str(row.get("release_time", ""))[:10]
            if column == 3:
                return "已安装" if row.get("installed") else "未安装"
        if role == Qt.UserRole:
            return row
        return None


class VersionFilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.query = ""
        self.type_filter = "all"
        self.only_installed = False

    def set_filters(self, query: str = "", type_filter: str = "all", only_installed: bool = False) -> None:
        self.query = query.strip().lower()
        self.type_filter = type_filter
        self.only_installed = only_installed
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model = self.sourceModel()
        if not isinstance(model, VersionTableModel):
            return True
        row = model.row_at(source_row)
        if not row:
            return False
        if self.query and self.query not in row.get("id", "").lower():
            return False
        if self.only_installed and not row.get("installed"):
            return False
        if self.type_filter != "all":
            kind = row.get("type", "")
            if self.type_filter == "release" and kind != "release":
                return False
            if self.type_filter == "snapshot" and kind != "snapshot":
                return False
            if self.type_filter == "old" and kind not in ("old_beta", "old_alpha"):
                return False
        return True


class VersionDelegate(QStyledItemDelegate):
    ROW_HEIGHT = 48

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex):
        size = super().sizeHint(option, index)
        size.setHeight(self.ROW_HEIGHT)
        return size

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        row = index.data(Qt.UserRole) or {}
        column = index.column()
        colors = palette()
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = option.rect
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        bg = colors["selected"] if selected else (colors["hover"] if hovered else "transparent")
        if bg != "transparent":
            painter.fillRect(rect.adjusted(4, 2, -4, -2), QColor(bg))

        inner = rect.adjusted(14, 0, -12, 0)
        if column == 0:
            font = QFont(option.font)
            font.setPointSize(10)
            font.setWeight(QFont.DemiBold)
            painter.setFont(font)
            painter.setPen(QColor(colors["text"]))
            text = QFontMetrics(font).elidedText(row.get("id", ""), Qt.ElideRight, inner.width() - 16)
            painter.drawText(inner, Qt.AlignVCenter | Qt.AlignLeft, text)
        elif column == 1:
            kind = row.get("type", "release")
            label = TYPE_LABELS.get(kind, kind)
            color = QColor(TYPE_COLORS.get(kind, "#7A7574"))
            font = QFont(option.font)
            font.setPointSize(8)
            font.setWeight(QFont.DemiBold)
            painter.setFont(font)
            metrics = QFontMetrics(font)
            width = metrics.horizontalAdvance(label) + 18
            badge = rect.adjusted(12, 11, 0, -11)
            badge.setWidth(min(width, inner.width()))
            path = QPainterPath()
            path.addRoundedRect(badge, 7, 7)
            fill = QColor(color)
            fill.setAlpha(34 if not colors["bg"] == "#202020" else 54)
            painter.fillPath(path, fill)
            painter.setPen(QPen(color, 1))
            painter.drawText(badge, Qt.AlignCenter, label)
        elif column == 2:
            font = QFont(option.font)
            font.setPointSize(9)
            painter.setFont(font)
            painter.setPen(QColor(colors["secondary"]))
            painter.drawText(inner, Qt.AlignVCenter | Qt.AlignLeft, str(row.get("release_time", ""))[:10])
        else:
            installed = bool(row.get("installed"))
            color = QColor(colors["success"] if installed else colors["tertiary"])
            dot = rect.adjusted(14, rect.height() // 2 - 3, 0, 0)
            dot.setWidth(6)
            dot.setHeight(6)
            painter.setBrush(color)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(dot)
            font = QFont(option.font)
            font.setPointSize(9)
            painter.setFont(font)
            painter.setPen(QColor(colors["secondary"] if installed else colors["tertiary"]))
            painter.drawText(inner.adjusted(12, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, "已安装" if installed else "未安装")
        painter.restore()
