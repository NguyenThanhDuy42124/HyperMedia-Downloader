"""Delegate vẽ card 320x280 cho grid 4 cột (ảo hóa: chỉ vẽ item nhìn thấy)."""
from PySide6.QtCore import QRect, QRectF, QSize, Qt, QPointF, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QComboBox, QStyledItemDelegate

from models import VideoRoles
from lucide_icons import draw_lucide_icon

CARD_W = 320
CARD_H = 300
GRID_W = 328
GRID_H = 308

# Palette
CARD_BG = QColor("#1f1f24")
CARD_HOVER = QColor("#282830")
CARD_SEL = QColor("#1e364e")
ACCENT = QColor("#00B0FF")
TEXT = QColor("#ffffff")
TEXT_DIM = QColor("#b0b0b0")
BORDER = QColor("#2e2e38")
FIELD_BG = QColor("#2b2b36")

STATUS_COLORS = {
    "": QColor("#aaaaaa"),
    "queued": QColor("#FFB74D"),
    "downloading": QColor("#00E5FF"),
    "done": QColor("#00E676"),
    "error": QColor("#FF5252"),
    "stopped": QColor("#FF9100"),
    "skipped": QColor("#B0BEC5"),
}


class VideoItemDelegate(QStyledItemDelegate):
    deleteRequested = Signal(str)
    retryRequested = Signal(str)
    formatSelectorRequested = Signal(str)

    FIELD_ROLE = {
        "type": VideoRoles.Type,
        "resolution": VideoRoles.Resolution,
        "quality": VideoRoles.Bitrate,
    }
    TYPE_ITEMS = ["mp4", "mp3", "av1"]

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self._model = model
        self._view = None
        self._pending_field = None
        self.hover_uid = None

    def set_view(self, view):
        self._view = view

    def sizeHint(self, option, index):
        return QSize(CARD_W, CARD_H)

    # ---------- geometry ----------
    def _layout(self, option):
        card = option.rect.adjusted(2, 2, -2, -2)
        x = card.x()
        y = card.y()
        w = card.width()
        h = card.height()
        thumb = QRect(x + 4, y + 4, w - 8, (w - 8) * 9 // 16)
        check = QRect(thumb.right() - 26, thumb.y() + 6, 20, 20)
        title = QRect(x + 8, thumb.bottom() + 6, w - 16, 36)
        status = QRect(x + 8, title.bottom() + 4, w - 16, 42)
        progress = QRect(x + 8, status.bottom() + 5, w - 16, 6)
        row_y = card.bottom() - 26
        type_ = QRect(x + 8, row_y, 52, 22)
        res = QRect(type_.right() + 4, row_y, 66, 22)
        quality = QRect(res.right() + 4, row_y, 105, 22)
        retry = QRect(card.right() - 50, row_y, 22, 22)
        delete = QRect(card.right() - 25, row_y, 22, 22)
        return {
            "card": card,
            "check": check,
            "thumb": thumb,
            "title": title,
            "status": status,
            "progress": progress,
            "type": type_,
            "resolution": res,
            "quality": quality,
            "retry": retry,
            "delete": delete,
        }

    # ---------- painting ----------
    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        uid = index.data(VideoRoles.Uid)
        layout = self._layout(option)
        card = layout["card"]

        selected = (
            self._view is not None
            and self._view.selectionModel().isSelected(index)
        )

        # Card background
        path = QPainterPath()
        path.addRoundedRect(QRectF(card), 10, 10)
        if selected:
            bg = CARD_SEL
        elif uid == self.hover_uid:
            bg = CARD_HOVER
        else:
            bg = CARD_BG
        painter.fillPath(path, bg)
        painter.setPen(QPen(ACCENT if selected else BORDER, 1))
        painter.drawPath(path)

        # Checkbox (góc thumbnail)
        self._draw_check(painter, layout["check"], selected)

        # Thumbnail lớn
        self._draw_thumb(painter, layout["thumb"], index.data(VideoRoles.Thumb))

        # Title (2 dòng)
        title_font = QFont(option.font)
        title_font.setBold(True)
        title_font.setPointSize(9)
        painter.setFont(title_font)
        painter.setPen(TEXT)
        self._draw_title(
            painter, layout["title"], index.data(VideoRoles.Title) or "Unknown"
        )

        # Status & Progress Details (2 dòng UI/UX mượt mà)
        status = index.data(VideoRoles.Status) or ""
        err = index.data(VideoRoles.Error) or ""
        status_rect = layout["status"]

        st_font = QFont(option.font)
        st_font.setPointSize(8)
        st_font.setWeight(QFont.Weight.Medium)
        painter.setFont(st_font)

        if status == "downloading" and err and ("TH:" in err or "|" in err):
            kv = {}
            for part in err.split("|"):
                if ":" in part:
                    k, v = part.split(":", 1)
                    kv[k.strip()] = v.strip()

            th_val = kv.get("TH", "16")
            time_val = kv.get("TIME", "00:00:00")
            dl_val = kv.get("DL", "Đang tải...")
            spd_val = kv.get("SPD", "0.00 MB/s")
            eta_val = kv.get("ETA", "Còn ~--")

            box_w = (status_rect.width() - 6) // 2
            box_h = 18

            # Box 1: Tốc độ tải (Electric Cyan Box + Zap Icon)
            b1_rect = QRect(status_rect.x(), status_rect.y(), box_w, box_h)
            self._draw_badge_chip(
                painter, b1_rect,
                QColor("#102330"), QColor("#005b8a"), QColor("#00E5FF"),
                spd_val, icon_name="zap"
            )

            # Box 2: Thời gian còn lại ETA (Orange/Gold Box + Clock Icon)
            b2_rect = QRect(b1_rect.right() + 6, status_rect.y(), box_w, box_h)
            self._draw_badge_chip(
                painter, b2_rect,
                QColor("#2b2014"), QColor("#8a5300"), QColor("#FFB74D"),
                eta_val, icon_name="clock"
            )

            # Box 3: Dung lượng MB/GB (Emerald Green Box + HardDrive Icon)
            b3_rect = QRect(status_rect.x(), status_rect.y() + 20, box_w, box_h)
            self._draw_badge_chip(
                painter, b3_rect,
                QColor("#102b1c"), QColor("#006e33"), QColor("#00E676"),
                dl_val, icon_name="hard-drive"
            )

            # Box 4: Thời lượng / Luồng (Dark Slate Box + Layers Icon)
            b4_rect = QRect(b3_rect.right() + 6, status_rect.y() + 20, box_w, box_h)
            time_short = time_val.split("/")[-1].strip() if "/" in time_val else time_val
            self._draw_badge_chip(
                painter, b4_rect,
                QColor("#1e1e28"), QColor("#383848"), QColor("#F4F4F5"),
                f"{th_val}L • {time_short}", icon_name="layers"
            )
        elif status == "downloading" and err:
            painter.setPen(STATUS_COLORS.get(status, TEXT_DIM))
            st_text = QFontMetrics(st_font).elidedText(err, Qt.TextElideMode.ElideRight, status_rect.width())
            painter.drawText(status_rect, Qt.AlignmentFlag.AlignVCenter, st_text)
        else:
            label = {
                "": "Sẵn sàng",
                "queued": "Đang chờ...",
                "downloading": "Đang tải...",
                "done": "✔ Hoàn tất 100%",
                "error": "Lỗi tải",
                "stopped": "Đã dừng",
                "skipped": "Đã có sẵn",
            }.get(status, status)
            if status == "error" and err:
                label = f"Lỗi: {err[:34]}"
            painter.setPen(STATUS_COLORS.get(status, TEXT_DIM))
            st_text = QFontMetrics(st_font).elidedText(label, Qt.TextElideMode.ElideRight, status_rect.width())
            painter.drawText(status_rect, Qt.AlignmentFlag.AlignVCenter, st_text)

        # Progress
        progress = index.data(VideoRoles.Progress) or 0
        self._draw_progress(
            painter, layout["progress"], progress, status in ("done", "skipped")
        )

        # Chips Loại / Độ phân giải / Chất lượng Bitrate & Codec
        type_str = str(index.data(VideoRoles.Type) or "mp4").upper()
        res_val = str(index.data(VideoRoles.Resolution) or "1080").lower()
        if res_val == "best":
            res_str = "1080p"
        elif res_val.isdigit():
            res_str = f"{res_val}p"
        else:
            res_str = res_val.title()

        bitrate_val = str(index.data(VideoRoles.Bitrate) or "320")
        codec_val = str(index.data(VideoRoles.Codec) or "H.264")
        qual_str = f"{bitrate_val}k • {codec_val}"

        self._draw_field(painter, layout["type"], "type", type_str)
        self._draw_field(painter, layout["resolution"], "resolution", res_str)
        self._draw_field(painter, layout["quality"], "quality", qual_str)

        # Delete & Retry buttons
        if uid == self.hover_uid or status in ("error", "stopped"):
            self._draw_retry(painter, layout["retry"])
        if uid == self.hover_uid:
            self._draw_delete(painter, layout["delete"])

        painter.restore()

    def _draw_retry(self, painter, rect):
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#0284c7"))
        painter.drawRoundedRect(QRectF(rect), 4, 4)
        draw_lucide_icon(painter, rect.adjusted(3, 3, -3, -3), "rotate-cw", "#ffffff")
        painter.restore()

    def _draw_badge_chip(self, painter, rect, bg_color, border_color, text_color, text, icon_name=None):
        painter.save()
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 4, 4)
        painter.fillPath(path, bg_color)
        if border_color:
            painter.setPen(QPen(border_color, 1))
            painter.drawPath(path)

        tx_x = rect.x() + 4
        tx_w = rect.width() - 8
        if icon_name:
            ic_size = 12
            ic_rect = QRect(rect.x() + 4, rect.y() + (rect.height() - ic_size) // 2, ic_size, ic_size)
            draw_lucide_icon(painter, ic_rect, icon_name, text_color.name())
            tx_x = ic_rect.right() + 4
            tx_w = rect.right() - tx_x - 2

        painter.setPen(text_color)
        f = QFont(painter.font())
        f.setPointSize(8)
        f.setWeight(QFont.Weight.DemiBold)
        painter.setFont(f)
        elided = QFontMetrics(f).elidedText(text, Qt.TextElideMode.ElideRight, tx_w)
        painter.drawText(QRect(tx_x, rect.y(), tx_w, rect.height()), Qt.AlignmentFlag.AlignVCenter, elided)
        painter.restore()

    def _draw_title(self, painter, rect, text):
        fm = QFontMetrics(painter.font())
        lh = fm.height()
        full_text = (text or "Unknown").strip()
        if not full_text:
            return

        max_w = rect.width()
        # Nếu toàn bộ vừa 1 dòng
        if fm.horizontalAdvance(full_text) <= max_w:
            painter.drawText(
                QRect(rect.x(), rect.y(), max_w, lh),
                Qt.AlignmentFlag.AlignVCenter,
                full_text,
            )
            return

        # Tìm điểm cắt tốt nhất cho dòng 1
        cut_idx = len(full_text)
        for i in range(1, len(full_text) + 1):
            if fm.horizontalAdvance(full_text[:i]) > max_w:
                cut_idx = i - 1
                break

        # Nếu có khoảng trắng gần cut_idx thì ưu tiên ngắt theo từ
        space_idx = full_text[:cut_idx].rfind(" ")
        if space_idx > cut_idx // 2:
            line1 = full_text[:space_idx].strip()
            rest = full_text[space_idx:].strip()
        else:
            line1 = full_text[:cut_idx].strip()
            rest = full_text[cut_idx:].strip()

        line2 = fm.elidedText(rest, Qt.TextElideMode.ElideRight, max_w)

        painter.drawText(
            QRect(rect.x(), rect.y(), max_w, lh),
            Qt.AlignmentFlag.AlignVCenter,
            line1,
        )
        if line2:
            painter.drawText(
                QRect(rect.x(), rect.y() + lh + 1, max_w, lh),
                Qt.AlignmentFlag.AlignVCenter,
                line2,
            )

    def _draw_check(self, painter, rect, checked):
        painter.save()
        painter.setPen(QPen(QColor("#888888"), 1))
        painter.setBrush(QColor("#3a3a3a"))
        painter.drawRoundedRect(QRectF(rect), 3, 3)
        if checked:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ACCENT)
            painter.drawRoundedRect(QRectF(rect), 3, 3)
            painter.setPen(QPen(QColor("#ffffff"), 2))
            path = QPainterPath()
            path.moveTo(rect.x() + 4, rect.y() + 10)
            path.lineTo(rect.x() + 9, rect.y() + 15)
            path.lineTo(rect.x() + 16, rect.y() + 5)
            painter.drawPath(path)
        painter.restore()

    def _draw_thumb(self, painter, rect, pixmap):
        painter.save()
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 8, 8)
        painter.setClipPath(path)
        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(
                rect.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = rect.x() + (rect.width() - scaled.width()) // 2
            y = rect.y() + (rect.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        else:
            painter.fillRect(rect, QColor("#222222"))
            painter.setPen(TEXT_DIM)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "No Img")
        painter.restore()

    def _draw_progress(self, painter, rect, progress, done):
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1a1a1a"))
        painter.drawRoundedRect(QRectF(rect), 3, 3)
        if progress > 0 or done:
            fill = QColor("#00E676") if done else QColor("#00B0FF")
            painter.setBrush(fill)
            w = int(rect.width() * min(progress, 100) / 100.0)
            if w > 0:
                painter.drawRoundedRect(
                    QRectF(rect.x(), rect.y(), w, rect.height()), 3, 3
                )
        painter.restore()

    def _draw_field(self, painter, rect, field, value):
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(FIELD_BG)
        painter.drawRoundedRect(QRectF(rect), 4, 4)
        f = QFont(painter.font())
        f.setPointSize(8)
        painter.setFont(f)
        painter.setPen(TEXT)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, value)
        painter.restore()

    def _draw_delete(self, painter, rect):
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#b71c1c"))
        painter.drawRoundedRect(QRectF(rect), 4, 4)
        draw_lucide_icon(painter, rect.adjusted(3, 3, -3, -3), "trash-2", "#ffffff")
        painter.restore()

    # ---------- interaction ----------
    def editorEvent(self, event, model, option, index):
        if event.type() not in (
            event.Type.MouseButtonPress,
            event.Type.MouseButtonDblClick,
        ):
            return super().editorEvent(event, model, option, index)
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        if self._view is None:
            return False

        layout = self._layout(option)
        pos = event.position().toPoint()
        uid = index.data(VideoRoles.Uid)

        if layout["check"].contains(pos):
            sm = self._view.selectionModel()
            sm.select(index, sm.SelectionFlag.Toggle)
            self._view.update(index)
            return True

        if layout["retry"].contains(pos):
            self.retryRequested.emit(uid)
            return True

        if layout["delete"].contains(pos):
            self.deleteRequested.emit(uid)
            return True

        if layout["resolution"].contains(pos) or layout["quality"].contains(pos):
            self.formatSelectorRequested.emit(uid)
            return True

        if layout["type"].contains(pos):
            self._pending_field = "type"
            self._view.edit(index)
            return True

        return False

    def createEditor(self, parent, option, index):
        field = self._pending_field
        if field is None:
            return None
        combo = QComboBox(parent)
        if field == "resolution":
            heights = index.data(VideoRoles.Heights) or [1080, 720, 480, 360]
            items = ["best"]
            for h in sorted(heights, reverse=True):
                if h >= 360:
                    items.append(str(h))
            combo.addItems(items)
        else:
            combo.addItems(self.TYPE_ITEMS)
        combo.setStyleSheet(
            "QComboBox{background:#3e3e3e;color:white;border-radius:3px;padding:2px;}"
        )
        return combo

    def setEditorData(self, editor, index):
        if isinstance(editor, QComboBox):
            field = self._pending_field
            role = self.FIELD_ROLE.get(field)
            value = str(index.data(role) or "")
            editor.setCurrentText(value)

    def setModelData(self, editor, model, index):
        if not isinstance(editor, QComboBox):
            return
        field = self._pending_field
        role = self.FIELD_ROLE.get(field)
        if role is None:
            return
        uid = index.data(VideoRoles.Uid)
        self._model.set_field(uid, role, editor.currentText())

    def updateEditorGeometry(self, editor, option, index):
        field = self._pending_field
        if field and field in self.FIELD_ROLE:
            rect = self._layout(option)[field]
            editor.setGeometry(rect)
        else:
            super().updateEditorGeometry(editor, option, index)