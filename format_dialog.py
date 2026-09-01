"""Dialog chọn định dạng Video & Audio chi tiết theo Format ID (ID00050, ID30280...)."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QGroupBox,
    QCheckBox,
)

def fmt_bytes(b):
    if not b or b <= 0:
        return ""
    if b >= 1024 * 1024 * 1024:
        return f"{b / (1024**3):.2f} GB"
    if b >= 1024 * 1024:
        return f"{b / (1024**2):.1f} MB"
    return f"{b / 1024:.0f} KB"

def simplify_codec(codec):
    c = (codec or "").lower()
    if "avc1" in c or "h264" in c:
        return "H.264/AVC"
    if "hev1" in c or "h265" in c:
        return "HEVC/H.265"
    if "av01" in c or "av1" in c:
        return "AV1"
    if "mp4a" in c or "aac" in c:
        return "AAC"
    if "flac" in c:
        return "FLAC"
    return codec or "N/A"

class FormatSelectorDialog(QDialog):
    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.item = item
        self.setWindowTitle("Chọn Định Dạng Chi Tiết (Format ID)")
        self.setMinimumWidth(520)
        self.setup_ui()

    def setup_ui(self):
        vbox = QVBoxLayout(self)
        vbox.setSpacing(12)

        title = self.item.get("title", "Video")
        lbl_title = QLabel(f"<b>Video:</b> {title[:65]}")
        vbox.addWidget(lbl_title)

        formats = self.item.get("formats_list") or []

        # Video streams & Audio streams
        video_formats = [f for f in formats if f.get("vcodec") != "none" and f.get("format_id")]
        audio_formats = [f for f in formats if f.get("acodec") != "none" and f.get("format_id")]

        # Group Video
        gb_video = QGroupBox("Chọn Đoạn Hình Ảnh (Video Stream)")
        v_box = QVBoxLayout(gb_video)
        self.video_cb = QComboBox()

        default_v_idx = 0
        for i, f in enumerate(video_formats):
            fid = f["format_id"]
            ext = f["ext"].upper()
            res = f.get("resolution") or (f"{f.get('height')}p" if f.get('height') else "N/A")
            fps = f"{int(f['fps'])}fps" if f.get("fps") else ""
            codec = simplify_codec(f.get("vcodec"))
            size = fmt_bytes(f.get("filesize"))
            size_str = f" • {size}" if size else ""

            # Phân biệt chuẩn 1080P 高码率 (VIP) vs 1080P 高清 (Miễn Phí)
            vip_tag = ""
            if "1080" in str(res):
                if fid in ("100050", "100051"):
                    vip_tag = " [1080P 高码率 - Cần VIP]"
                elif fid in ("100026", "100024") or "AV1" in codec:
                    vip_tag = " [1080P 高清 - Miễn Phí]"

            # Nhãn dạng: 1080p • 30fps • H.264/AVC • 2.83 GB (ID: 100050)
            label_parts = [p for p in [res, fps, codec, ext] if p]
            label = " • ".join(label_parts) + f"{size_str} (ID: {fid}){vip_tag}"
            self.video_cb.addItem(label, fid)

            # Ưu tiên mặc định 1080p + H.264
            if "1080" in str(res) and ("H.264" in codec or default_v_idx == 0):
                default_v_idx = i

        if self.video_cb.count() > 0:
            self.video_cb.setCurrentIndex(default_v_idx)
        v_box.addWidget(self.video_cb)
        vbox.addWidget(gb_video)

        # Group Audio
        gb_audio = QGroupBox("Chọn Đoạn Âm Thanh (Audio Stream)")
        a_box = QVBoxLayout(gb_audio)
        self.audio_cb = QComboBox()

        default_a_idx = 0
        max_abr = -1
        for i, f in enumerate(audio_formats):
            fid = f["format_id"]
            ext = f["ext"].upper()
            abr = f.get("abr") or f.get("tbr") or 0
            abr_str = f"{int(abr)}kbps" if abr > 0 else ""
            codec = simplify_codec(f.get("acodec"))
            size = fmt_bytes(f.get("filesize"))
            size_str = f" • {size}" if size else ""

            label_parts = [p for p in [abr_str, codec, ext] if p]
            label = " • ".join(label_parts) + f"{size_str} (ID: {fid})"
            self.audio_cb.addItem(label, fid)

            # Ưu tiên audio bitrate cao nhất (VD 320k/153k)
            if abr > max_abr:
                max_abr = abr
                default_a_idx = i

        if self.audio_cb.count() > 0:
            self.audio_cb.setCurrentIndex(default_a_idx)
        a_box.addWidget(self.audio_cb)
        vbox.addWidget(gb_audio)

        # Custom Format ID manual input
        self.chk_custom = QCheckBox("Hoặc nhập chuỗi Format ID trực tiếp (VD: 100050+30280)")
        vbox.addWidget(self.chk_custom)

        # Buttons OK / Cancel
        btn_box = QHBoxLayout()
        btn_box.addStretch()
        btn_cancel = QPushButton(" Hủy")
        from lucide_icons import get_lucide_icon
        btn_cancel.setIcon(get_lucide_icon("x", "#ffffff", 14))
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton(" Áp Dụng")
        btn_ok.setIcon(get_lucide_icon("check", "#ffffff", 14))
        btn_ok.setStyleSheet("background:#00B0FF;color:white;font-weight:bold;padding:6px 16px;")
        btn_ok.clicked.connect(self.accept)
        btn_box.addWidget(btn_cancel)
        btn_box.addWidget(btn_ok)
        vbox.addLayout(btn_box)

    def get_selected_format(self):
        v_fid = self.video_cb.currentData()
        a_fid = self.audio_cb.currentData()

        if v_fid and a_fid:
            return f"{v_fid}+{a_fid}"
        if v_fid:
            return str(v_fid)
        if a_fid:
            return str(a_fid)
        return "bestvideo+bestaudio/best"
