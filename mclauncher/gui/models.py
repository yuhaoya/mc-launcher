from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QStyleOptionViewItem
from qfluentwidgets import TableItemDelegate

TYPE_LABELS = {
    "release": "正式版",
    "snapshot": "快照",
    "old_beta": "远古 Beta",
    "old_alpha": "远古 Alpha",
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


class VersionDelegate(TableItemDelegate):
    """仅用来设置原生表格的行高，完全不干涉自带的绘制逻辑"""

    def __init__(self, parent=None):
        super().__init__(parent)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex):
        size = super().sizeHint(option, index)
        size.setHeight(48)  # 强制行高
        return size