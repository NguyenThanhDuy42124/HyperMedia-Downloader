"""Model dữ liệu danh sách video (thay thế QListWidget + widget-per-item)."""
import itertools
import uuid

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt

TITLE, URL, THUMB, THUMB_URL, STATUS, PROGRESS = range(6)
TYPE, RESOLUTION, BITRATE, CODEC, HEIGHTS, ERROR = range(6, 12)
UID_ROLE = Qt.UserRole + 30


class VideoRoles:
    Title = Qt.UserRole + 1
    Url = Qt.UserRole + 2
    Thumb = Qt.UserRole + 3
    ThumbUrl = Qt.UserRole + 4
    Status = Qt.UserRole + 5
    Progress = Qt.UserRole + 6
    Type = Qt.UserRole + 7
    Resolution = Qt.UserRole + 8
    Bitrate = Qt.UserRole + 9
    Codec = Qt.UserRole + 10
    Heights = Qt.UserRole + 11
    Error = Qt.UserRole + 12
    Uid = Qt.UserRole + 13
    FormatId = Qt.UserRole + 14
    FormatsList = Qt.UserRole + 15


ROLE_MAP = {
    VideoRoles.Title: "title",
    VideoRoles.Url: "url",
    VideoRoles.Thumb: "thumb",
    VideoRoles.ThumbUrl: "thumb_url",
    VideoRoles.Status: "status",
    VideoRoles.Progress: "progress",
    VideoRoles.Type: "type",
    VideoRoles.Resolution: "resolution",
    VideoRoles.Bitrate: "bitrate",
    VideoRoles.Codec: "codec",
    VideoRoles.Heights: "heights",
    VideoRoles.Error: "error",
    VideoRoles.Uid: "uid",
    VideoRoles.FormatId: "format_id",
    VideoRoles.FormatsList: "formats_list",
}

_uid_gen = itertools.count(1)


def new_uid():
    return f"v{next(_uid_gen)}"


class VideoListModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []

    # ---- Qt interface ----
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None
        item = self._items[index.row()]
        if role == Qt.DisplayRole:
            return item["title"]
        field = ROLE_MAP.get(role)
        if field is None:
            return None
        return item.get(field)

    def flags(self, index):
        return (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsEditable
        )

    # ---- Mutations ----
    def add_video(self, item):
        item = dict(item)
        if not item.get("uid"):
            item["uid"] = new_uid()
        item.setdefault("title", "Unknown")
        item.setdefault("url", "")
        item.setdefault("thumb_url", "")
        item.setdefault("thumb", None)
        item.setdefault("status", "")
        item.setdefault("progress", 0)
        item.setdefault("error", "")
        item.setdefault("type", "mp4")
        item.setdefault("resolution", "best")
        item.setdefault("bitrate", "320")
        item.setdefault("codec", "H.264")
        item.setdefault("heights", [])
        row = len(self._items)
        self.beginInsertRows(QModelIndex(), row, row)
        self._items.append(item)
        self.endInsertRows()
        return item["uid"]

    def remove_uid(self, uid):
        self.remove_uids([uid])

    def remove_uids(self, uids):
        uids = set(uids)
        rows = [i for i, it in enumerate(self._items) if it["uid"] in uids]
        if not rows:
            return
        for i in sorted(rows, reverse=True):
            self.beginRemoveRows(QModelIndex(), i, i)
            del self._items[i]
            self.endRemoveRows()

    def clear(self):
        if not self._items:
            return
        self.beginResetModel()
        self._items.clear()
        self.endResetModel()

    def set_field(self, uid, role, value):
        for i, it in enumerate(self._items):
            if it["uid"] == uid:
                field = ROLE_MAP.get(role)
                if field:
                    it[field] = value
                idx = self.index(i, 0)
                self.dataChanged.emit(idx, idx, [])
                return

    def set_thumb(self, uid, pixmap):
        self.set_field(uid, VideoRoles.Thumb, pixmap)

    def set_status(self, uid, status, error=""):
        for i, it in enumerate(self._items):
            if it["uid"] == uid:
                it["status"] = status
                if error is not None:
                    it["error"] = error
                idx = self.index(i, 0)
                self.dataChanged.emit(idx, idx, [])
                return

    def set_progress(self, uid, pct):
        for i, it in enumerate(self._items):
            if it["uid"] == uid:
                it["progress"] = pct
                idx = self.index(i, 0)
                self.dataChanged.emit(idx, idx, [])
                return

    # ---- Reads ----
    def get(self, uid):
        for it in self._items:
            if it["uid"] == uid:
                return it
        return None

    def index_for_uid(self, uid):
        for i, it in enumerate(self._items):
            if it["uid"] == uid:
                return self.index(i, 0)
        return QModelIndex()

    def uids(self):
        return [it["uid"] for it in self._items]

    def items(self):
        return list(self._items)

    def checked_uids(self, proxy=None):
        """uid được chọn: theo selection trên view nếu có proxy, ngược lại tất cả."""
        if proxy is None:
            return list(self.uids())
        return [self.data(proxy.index(i, 0), VideoRoles.Uid) for i in range(proxy.rowCount())]
