"""Save downloads from one owned Studio page through Qt's real download path."""

from pathlib import Path
from urllib.parse import urlsplit

from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWebEngineCore import QWebEngineDownloadRequest


def _origin(value):
    try:
        url = urlsplit(value)
        if url.scheme not in ("http", "https") or url.username or url.password:
            return None
        return url.scheme, url.hostname, url.port or (443 if url.scheme == "https" else 80)
    except (ValueError, TypeError):
        return None


def _file_name(value):
    if (not isinstance(value, str) or not value or len(value) > 255
            or value in (".", "..") or value.endswith((".", " "))
            or any(ord(char) < 32 or char in '<>:"/\\|?*' for char in value)):
        raise ValueError("Unavailable download filename")
    return value


class StudioDownloadAdapter(QObject):
    """Own one page's downloads; callbacks never receive URLs or credentials.

    ``choose_path(name)`` selects a destination only. An injected chooser must
    return an unused absolute path; normal use keeps the native Save dialog's
    overwrite confirmation. ``on_status(dict)`` observes actual request states.
    """

    def __init__(self, profile, page, app_origin, *, parent=None,
                 choose_path=None, on_status=None):
        super().__init__(page)
        origin = _origin(app_origin)
        if (origin is None or origin[1] not in ("127.0.0.1", "localhost", "::1")
                or page.profile() != profile):
            raise ValueError("Downloads require the owned local application page and profile")
        self._profile = profile
        self._page = page
        self._origin = origin
        self._window = parent
        self._chooser = choose_path
        self._on_status = on_status
        self._active = {}
        self._choosing = False
        self._closed = False
        # Qt requires a synchronous decision before downloadRequested returns.
        profile.downloadRequested.connect(self._requested, Qt.ConnectionType.DirectConnection)
        page.destroyed.connect(self.close)

    def _notify(self, state, name, detail, request=None):
        payload = {"state": state, "name": name, "detail": detail,
                   "received_bytes": 0, "total_bytes": -1}
        if request is not None:
            try:
                payload.update(request_id=request.id(), received_bytes=request.receivedBytes(),
                               total_bytes=request.totalBytes())
            except RuntimeError:
                pass
        if self._on_status is not None:
            try:
                self._on_status(payload)
            except Exception:
                # An observer cannot interrupt Qt's accept/cancel lifecycle.
                pass

    def _admitted(self, request):
        source = request.url().toString()
        if source.startswith("blob:"):
            source = source[5:]
        return (not self._closed and request.page() == self._page
                and self._page.profile() == self._profile
                and _origin(self._page.url().toString()) == self._origin
                and _origin(source) == self._origin
                and not request.isSavePageDownload())

    def _refuse(self, request, state, name, detail):
        try:
            request.cancel()
        finally:
            self._notify(state, name, detail, request)

    def _choose(self, name):
        if self._chooser is not None:
            return self._chooser(name)
        from PyQt6.QtCore import QStandardPaths
        from PyQt6.QtWidgets import QFileDialog
        directory = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        chosen, _ = QFileDialog.getSaveFileName(
            self._window, "Save ArchHub download", str(Path(directory) / name), "All files (*)")
        return chosen

    def _requested(self, request):
        name = ""
        try:
            if not self._admitted(request):
                self._refuse(request, "refused", name, "Download refused: this is not the owned ArchHub page.")
                return
            name = _file_name(request.suggestedFileName())
            if self._choosing or self._active:
                self._refuse(request, "refused", name, "Finish the current download before starting another.")
                return
            if request.state() != QWebEngineDownloadRequest.DownloadState.DownloadRequested:
                self._refuse(request, "refused", name, "Download refused: the request is no longer pending.")
                return
            self._choosing = True
            try:
                self._notify("choosing", name, "Choose where to save the download.", request)
                chosen = self._choose(name)
            finally:
                self._choosing = False
            if not chosen:
                self._refuse(request, "cancelled", name, "Download cancelled; no file was saved.")
                return
            path = Path(chosen)
            _file_name(path.name)
            if (not path.is_absolute() or not path.parent.is_dir() or path.is_dir()
                    or path.is_symlink() or (self._chooser is not None and path.exists())):
                self._refuse(request, "refused", name, "Download refused: choose an available file destination.")
                return
            # The native chooser runs an event loop: the page may have changed.
            if not self._admitted(request):
                self._refuse(request, "refused", name, "Download cancelled: the ArchHub page changed.")
                return
            request.setDownloadDirectory(str(path.parent))
            request.setDownloadFileName(path.name)
            self._active[request.id()] = (request, path.name)
            request.stateChanged.connect(lambda _state, held=request: self._changed(held))
            request.receivedBytesChanged.connect(lambda held=request: self._changed(held))
            request.isFinishedChanged.connect(lambda held=request: self._changed(held))
            request.accept()
            self._changed(request)
        except Exception:
            # Never unwind through a Qt signal or reveal request URLs in errors.
            try:
                self._active.pop(request.id(), None)
                self._refuse(request, "failed", name, "The download could not be saved. Try another destination.")
            except Exception:
                self._notify("failed", name, "The download could not be saved.")

    def _changed(self, request):
        try:
            held = self._active.get(request.id())
            if held is None:
                return
            name = held[1]
            states = QWebEngineDownloadRequest.DownloadState
            state = request.state()
            if state == states.DownloadCompleted:
                self._active.pop(request.id(), None)
                self._notify("saved", name, "Saved " + name + " to the chosen folder.", request)
                request.deleteLater()
            elif state in (states.DownloadCancelled, states.DownloadInterrupted):
                self._active.pop(request.id(), None)
                if state == states.DownloadCancelled:
                    self._notify("cancelled", name, "Download cancelled before completion.", request)
                else:
                    reason = request.interruptReason().name
                    self._notify("failed", name, "Download failed (" + reason + ").", request)
                    request.cancel()
                request.deleteLater()
            elif state == states.DownloadInProgress:
                self._notify("downloading", name, "Saving " + name + "…", request)
        except Exception:
            try:
                self._active.pop(request.id(), None)
                request.cancel()
                request.deleteLater()
            except Exception:
                pass
            self._notify("failed", "", "Download status is unavailable; completion was not confirmed.")

    def close(self, *_args):
        if self._closed:
            return
        self._closed = True
        try:
            self._profile.downloadRequested.disconnect(self._requested)
        except (RuntimeError, TypeError):
            pass
        for request, name in list(self._active.values()):
            try:
                request.cancel()
                self._changed(request)
            except RuntimeError:
                self._notify("cancelled", name, "Download ended when ArchHub closed.")
        self._active.clear()


def install_studio_downloads(profile, page, app_origin, *, parent=None,
                             choose_path=None, on_status=None):
    return StudioDownloadAdapter(profile, page, app_origin, parent=parent,
                                 choose_path=choose_path, on_status=on_status)
