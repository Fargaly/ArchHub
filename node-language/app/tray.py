"""System tray icon and menu for ArchHub."""
from __future__ import annotations

from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from chat_window import ChatWindow
from manager import ConnectorManager


class ArchHubTray(QSystemTrayIcon):
    def __init__(self, icon: QIcon, window: ChatWindow, manager: ConnectorManager):
        super().__init__(icon)
        self.setToolTip("ArchHub — AI for your AEC tools")
        self.window = window
        self.manager = manager

        menu = QMenu()
        open_action = QAction("Open ArchHub", self)
        open_action.triggered.connect(self.window.show_centered)
        menu.addAction(open_action)

        menu.addSeparator()

        # Quick toggle submenu
        self.toggles_menu = menu.addMenu("Connectors")
        self._rebuild_toggles()

        menu.addSeparator()

        refresh_action = QAction("Refresh detection", self)
        refresh_action.triggered.connect(self._refresh)
        menu.addAction(refresh_action)
        menu.addSeparator()

        quit_action = QAction("Quit ArchHub", self)
        quit_action.triggered.connect(QApplication.quit)
        menu.addAction(quit_action)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.window.show_centered()

    def _refresh(self) -> None:
        self.manager.refresh()
        self._rebuild_toggles()

    def _rebuild_toggles(self) -> None:
        self.toggles_menu.clear()
        for entry in self.manager.entries:
            act = QAction(entry.display_name, self)
            act.setCheckable(True)
            act.setChecked(entry.state.name == "ACTIVE")
            act.setEnabled(entry.state.name != "UNAVAILABLE")
            def make_handler(e_id=entry.id):
                def handler(checked: bool):
                    if checked:
                        self.manager.activate(e_id)
                    else:
                        self.manager.deactivate(e_id)
                return handler
            act.toggled.connect(make_handler())
            self.toggles_menu.addAction(act)
