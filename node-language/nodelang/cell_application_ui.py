"""ArchHub's browser shell assembled from universal-cell UI relations."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .cell_ui import UIBuilder, UIProtocol
from .universal_cell import NULL_CELL_ID, Cell, CellStore
from .universal_presentation_seed import STYLESHEET, THEME


@dataclass(frozen=True, slots=True)
class ApplicationPresentationBuild:
    ui_root: str
    stylesheet_root: str
    theme_roots: Mapping[str, str]


def build_application_presentation(
    store: CellStore,
    protocol: UIProtocol,
) -> ApplicationPresentationBuild:
    """Build the current product shell and its presentation data as cells."""
    ui = UIBuilder(store, protocol)
    stylesheet_root = "app:presentation:stylesheet"
    ui.batch.add(Cell(
        stylesheet_root,
        NULL_CELL_ID,
        NULL_CELL_ID,
        STYLESHEET.encode("utf-8"),
    ))
    theme_roots = {}
    for name, value in THEME.items():
        root_id = "app:presentation:theme:%s" % name
        ui.batch.add(Cell(
            root_id,
            NULL_CELL_ID,
            NULL_CELL_ID,
            str(value).encode("utf-8"),
        ))
        theme_roots[name] = root_id

    def button(
        label: str,
        class_name: str,
        title: str,
        control_root: str,
    ) -> str:
        return ui.element(
            "button",
            class_name=class_name,
            text=label,
            attributes={
                "type": "button",
                "title": title,
                "data-universal-control": control_root,
            },
        )

    rail = ui.element("nav", class_name="icon-rail", attributes={
        "aria-label": "Application",
    }, children=(
        button(
            "Home", "rail-button rail-home", "Home",
            "app:control:rail:home",
        ),
        button(
            "Search", "rail-button rail-search", "Search",
            "app:control:rail:search",
        ),
        ui.element("div", class_name="rail-spacer"),
        button(
            "Share", "rail-button rail-share", "Share",
            "app:control:rail:share",
        ),
        button(
            "Settings", "rail-button rail-settings", "Settings",
            "app:control:rail:settings",
        ),
    ))
    library = ui.element(
        "section",
        class_name="library-panel",
        attributes={"data-visible": "True"},
    )
    sidebar = ui.element(
        "aside", class_name="sidebar", children=(rail, library)
    )

    wordmark = ui.element(
        "div",
        class_name="wordmark",
        attributes={"aria-label": "ArchHub"},
        children=(
            ui.element("span", text="Arch"),
            ui.element("strong", text="Hub"),
        ),
    )
    header = ui.element("header", class_name="workspace-header", children=(
        wordmark,
        ui.element(
            "div", class_name="session-tab", text="ArchHub Operating Graph"
        ),
        ui.element("div", class_name="header-spacer"),
        ui.element(
            "div", class_name="model-chip", text="universal-cell-v0"
        ),
    ))
    selection_box = ui.element(
        "div",
        class_name="selection-box",
        attributes={"data-mode": "window"},
    )
    stage = ui.element("div", class_name="canvas-stage")
    toolbar = ui.element(
        "div",
        class_name="canvas-toolbar",
        attributes={"role": "toolbar", "aria-label": "Canvas controls"},
    )
    canvas = ui.element(
        "section",
        class_name="canvas",
        attributes={
            "data-pan-surface": "true",
            "data-pan-x": "0",
            "data-pan-y": "0",
            "data-zoom": "1",
            "data-selection": "[]",
        },
        # The marquee is a screen-space overlay. Keeping it outside the
        # pan/zoom stage prevents the viewport transform being applied twice.
        children=(stage, selection_box, toolbar),
    )
    inspector = ui.element("aside", class_name="inspector")
    workspace = ui.element(
        "main", class_name="workspace", children=(header, canvas, inspector)
    )
    status = ui.element("div", class_name="status-strip", children=(
        ui.element(
            "span", class_name="status-live status-runtime", text="UNIVERSAL CELL RUNTIME"
        ),
        ui.element("span", class_name="status-catalog", text="CATALOGUE"),
        ui.element("span", class_name="status-composer", text="COMPOSER"),
        ui.element("span", class_name="status-adapters", text="ADAPTERS"),
        ui.element("span", class_name="status-lifecycle", text="WIP / SHARED / PUBLISHED"),
        ui.element(
            "span",
            class_name="status-message",
            attributes={
                "data-visible": "False",
                "role": "status",
                "aria-live": "polite",
            },
        ),
    ))
    root = ui.element(
        "div",
        class_name="archhub-app",
        attributes={"data-mode": "workspace"},
        children=(sidebar, workspace, status),
        element_id="app:ui:root",
    )
    ui.commit()
    return ApplicationPresentationBuild(
        root,
        stylesheet_root,
        MappingProxyType(theme_roots),
    )


__all__ = ["ApplicationPresentationBuild", "build_application_presentation"]
