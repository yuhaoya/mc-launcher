from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    IconWidget,
    PrimaryPushButton,
    PushButton,
    SettingCard,
    SimpleCardWidget,
    StrongBodyLabel,
    TitleLabel,
)

from .theme import palette


def _label(text: str, color: str, size: int = 10, weight: QFont.Weight = QFont.Normal) -> QLabel:
    label = QLabel(text)
    font = QFont(label.font())
    font.setPointSize(size)
    font.setWeight(weight)
    label.setFont(font)
    label.setStyleSheet(f"color: {color}; background: transparent;")
    return label


class BlockLogo(QWidget):
    """手绘等距草方块，避免直接使用游戏素材。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(190, 190)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        side = min(self.width(), self.height()) * 0.78
        cx = self.width() / 2
        top_y = (self.height() - side) / 2
        half = side / 2
        quarter = side / 4
        mid = cx
        top = QPointF(mid, top_y)
        right = QPointF(mid + half, top_y + quarter)
        bottom = QPointF(mid, top_y + side * 0.5)
        left = QPointF(mid - half, top_y + quarter)
        low_left = QPointF(mid - half, top_y + quarter + side * 0.5)
        low_mid = QPointF(mid, top_y + side)
        low_right = QPointF(mid + half, top_y + quarter + side * 0.5)

        # 地面柔和阴影
        shadow = QRadialGradient(QPointF(mid, top_y + side * 0.92), side * 0.55)
        shadow.setColorAt(0, QColor(0, 0, 0, 80))
        shadow.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(shadow)
        painter.drawEllipse(QRectF(mid - half * 0.9, top_y + side * 0.68, half * 1.8, side * 0.3))

        # 左侧面
        left_face = QPainterPath()
        left_face.moveTo(left)
        left_face.lineTo(bottom)
        left_face.lineTo(low_mid)
        left_face.lineTo(low_left)
        left_face.closeSubpath()
        left_grad = QLinearGradient(left, low_left)
        left_grad.setColorAt(0, QColor("#9A6A3A"))
        left_grad.setColorAt(1, QColor("#6E4523"))
        painter.fillPath(left_face, left_grad)
        painter.setPen(QPen(QColor(0, 0, 0, 60), 1.2))
        painter.drawPath(left_face)

        # 右侧面
        right_face = QPainterPath()
        right_face.moveTo(bottom)
        right_face.lineTo(right)
        right_face.lineTo(low_right)
        right_face.lineTo(low_mid)
        right_face.closeSubpath()
        right_grad = QLinearGradient(right, low_right)
        right_grad.setColorAt(0, QColor("#704824"))
        right_grad.setColorAt(1, QColor("#4F3018"))
        painter.fillPath(right_face, right_grad)
        painter.setPen(QPen(QColor(0, 0, 0, 70), 1.2))
        painter.drawPath(right_face)

        # 顶面
        top_face = QPainterPath()
        top_face.moveTo(top)
        top_face.lineTo(right)
        top_face.lineTo(bottom)
        top_face.lineTo(left)
        top_face.closeSubpath()
        top_grad = QLinearGradient(left, right)
        top_grad.setColorAt(0, QColor("#8BD34A"))
        top_grad.setColorAt(0.55, QColor("#5FAE2B"))
        top_grad.setColorAt(1, QColor("#3F8E1D"))
        painter.fillPath(top_face, top_grad)
        painter.setPen(QPen(QColor(255, 255, 255, 45), 1.2))
        painter.drawPath(top_face)

        # 草方块的像素纹理
        painter.setClipPath(top_face)
        rng = __import__("random").Random(7)
        for _ in range(26):
            x = left.x() + rng.random() * side
            y = top_y + rng.random() * quarter * 2
            # 仅绘制落在顶面范围内的点
            if abs(x - mid) / half + abs(y - (top_y + quarter)) / quarter <= 1.0:
                w = side * rng.uniform(0.035, 0.09)
                color = QColor("#77C63D" if rng.random() > 0.35 else "#4E9A24")
                painter.fillRect(QRectF(x, y, w, w * 0.72), color)
        painter.setClipping(False)

        # 侧面像素块
        for face, count, base in ((left_face, 12, "#7B4F2A"), (right_face, 10, "#5A361B")):
            painter.setClipPath(face)
            for _ in range(count):
                x = left.x() + side * 0.08 + rng.random() * side * 0.75
                y = top_y + quarter + rng.random() * side * 0.55
                size = side * rng.uniform(0.03, 0.07)
                painter.fillRect(QRectF(x, y, size, size * 0.8), QColor(base))
            painter.setClipping(False)


class AvatarCircle(QWidget):
    def __init__(self, name: str = "?", parent=None):
        super().__init__(parent)
        self._name = name
        self.setFixedSize(46, 46)

    def set_name(self, name: str) -> None:
        self._name = name or "?"
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0, QColor("#2B88D8"))
        gradient.setColorAt(1, QColor("#71AFE5"))
        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(rect)
        painter.setPen(QColor("white"))
        font = QFont(self.font())
        font.setPointSize(16)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, self._name[:1].upper())


class HeroCard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(255)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 20, 20)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0, QColor("#0A3557"))
        gradient.setColorAt(0.55, QColor("#0E5C86"))
        gradient.setColorAt(1, QColor("#0A7C78"))
        painter.fillPath(path, gradient)

        painter.setClipPath(path)
        glow = QRadialGradient(QPointF(rect.width() * 0.82, rect.height() * 0.2), rect.width() * 0.55)
        glow.setColorAt(0, QColor(90, 220, 255, 65))
        glow.setColorAt(1, QColor(90, 220, 255, 0))
        painter.fillRect(rect, glow)
        glow2 = QRadialGradient(QPointF(rect.width() * 0.15, rect.height() * 1.0), rect.width() * 0.45)
        glow2.setColorAt(0, QColor(70, 255, 190, 35))
        glow2.setColorAt(1, QColor(70, 255, 190, 0))
        painter.fillRect(rect, glow2)
        painter.setClipping(False)
        painter.setPen(QPen(QColor(255, 255, 255, 35), 1))
        painter.drawPath(path)


class StatCard(SimpleCardWidget):
    def __init__(self, icon: FluentIcon, title: str, value: str = "—", caption: str = "", parent=None):
        super().__init__(parent)
        self.setMinimumHeight(104)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(8)
        icon_widget = IconWidget(icon, self)
        icon_widget.setFixedSize(18, 18)
        top.addWidget(icon_widget)

        title_label = CaptionLabel(title, self)
        title_label.setTextColor(palette()["secondary"], palette()["secondary"])
        top.addWidget(title_label)
        top.addStretch(1)
        layout.addLayout(top)

        self.value_label = TitleLabel(value, self)
        # 👇 关键修复：用 QFont 代替 setStyleSheet
        font = self.value_label.font()
        font.setPixelSize(22)
        font.setWeight(QFont.DemiBold)
        self.value_label.setFont(font)

        layout.addWidget(self.value_label)
        self.caption_label = CaptionLabel(caption, self)
        self.caption_label.setTextColor(palette()["tertiary"], palette()["tertiary"])
        layout.addWidget(self.caption_label)

    def set_value(self, value: str, caption: str | None = None) -> None:
        self.value_label.setText(value)
        if caption is not None:
            self.caption_label.setText(caption)


class SectionHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        text_box = QVBoxLayout()
        text_box.setSpacing(2)

        self.title_label = StrongBodyLabel(title, self)
        # 👇 关键修复
        font = self.title_label.font()
        font.setPixelSize(16)
        self.title_label.setFont(font)

        text_box.addWidget(self.title_label)
        if subtitle:
            self.subtitle_label = CaptionLabel(subtitle, self)
            self.subtitle_label.setTextColor(palette()["secondary"], palette()["secondary"])
            text_box.addWidget(self.subtitle_label)
        layout.addLayout(text_box)
        layout.addStretch(1)


class SettingRow(SettingCard):
    """SettingCard + 右侧任意控件，避免为每个配置项创建 ConfigItem。"""

    def __init__(self, icon: FluentIcon, title: str, content: str, widget: QWidget, parent=None):
        super().__init__(icon, title, content, parent)
        widget.setParent(self)
        self.hBoxLayout.addWidget(widget, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(14)


class EmptyState(QWidget):
    def __init__(self, icon: FluentIcon, title: str, body: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 40, 0, 40)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignCenter)
        icon_widget = IconWidget(icon, self)
        icon_widget.setFixedSize(38, 38)
        layout.addWidget(icon_widget, 0, Qt.AlignCenter)
        title_label = StrongBodyLabel(title, self)
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        body_label = BodyLabel(body, self)
        body_label.setAlignment(Qt.AlignCenter)
        body_label.setTextColor(palette()["secondary"], palette()["secondary"])
        body_label.setWordWrap(True)
        layout.addWidget(body_label)


class AccountRow(QFrame):
    switchRequested = Signal(str)
    removeRequested = Signal(str)

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self.account_name = data.get("name", "")
        self.setObjectName("accountRow")
        self.setStyleSheet(
            """
            QFrame#accountRow { background: transparent; border-radius: 8px; }
            QFrame#accountRow:hover { background: rgba(127,127,127,18); }
            """
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 8, 9)
        layout.setSpacing(12)
        icon_widget = IconWidget(FluentIcon.PEOPLE, self)
        icon_widget.setFixedSize(22, 22)
        layout.addWidget(icon_widget)
        text_box = QVBoxLayout()
        text_box.setSpacing(1)
        name = StrongBodyLabel(self.account_name, self)
        text_box.addWidget(name)
        caption = CaptionLabel(f"{data.get('kind', '离线账号')} · {data.get('uuid', '')}", self)
        caption.setTextColor(palette()["tertiary"], palette()["tertiary"])
        text_box.addWidget(caption)
        layout.addLayout(text_box)
        layout.addStretch(1)

        if data.get("active"):
            badge = QLabel("当前", self)
            badge.setStyleSheet(
                f"background: {palette()['success']}22; color: {palette()['success']};"
                "border-radius: 6px; padding: 2px 10px; font-size: 8pt; font-weight: 600;"
            )
            layout.addWidget(badge)
        else:
            # 👇 替换为 PrimaryPushButton，自动跟随主题色
            switch_button = PrimaryPushButton("切换到此账号", self)
            switch_button.setFixedHeight(30)
            switch_button.setCursor(Qt.PointingHandCursor)
            switch_button.clicked.connect(lambda: self.switchRequested.emit(self.account_name))
            layout.addWidget(switch_button)

        # 👇 替换为 Fluent 的 PushButton，并去除边框，改为纯文本红色
        remove_button = PushButton("删除", self)
        remove_button.setFixedHeight(30)
        remove_button.setCursor(Qt.PointingHandCursor)
        remove_button.setStyleSheet(
            """
            PushButton { color: #C42B1C; }
            PushButton:hover { background: rgba(196, 43, 28, 0.1); }
            """
        )
        remove_button.clicked.connect(lambda: self.removeRequested.emit(self.account_name))
        layout.addWidget(remove_button)


class VersionRow(QFrame):
    playRequested = Signal(str)            # ← 新增：类级别信号定义

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self.version_id = data.get("id", "")
        self.setObjectName("versionRow")
        self.setStyleSheet(
            """
            QFrame#versionRow { background: transparent; border-radius: 8px; }
            QFrame#versionRow:hover { background: rgba(127,127,127,20); }
            """
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 8, 9)
        layout.setSpacing(12)
        icon_widget = IconWidget(FluentIcon.GAME, self)
        icon_widget.setFixedSize(22, 22)
        layout.addWidget(icon_widget)
        text_box = QVBoxLayout()
        text_box.setSpacing(1)
        name = StrongBodyLabel(self.version_id, self)
        text_box.addWidget(name)
        caption = CaptionLabel(data.get("size_text") or "已安装", self)
        caption.setTextColor(palette()["tertiary"], palette()["tertiary"])
        text_box.addWidget(caption)
        layout.addLayout(text_box)
        layout.addStretch(1)
        # 👇 换成 PrimaryPushButton
        play_button = PrimaryPushButton("启动", self)
        play_button.setFixedHeight(32)
        play_button.setMinimumWidth(72)
        play_button.setCursor(Qt.PointingHandCursor)
        play_button.clicked.connect(lambda: self.playRequested.emit(self.version_id))
        layout.addWidget(play_button)
