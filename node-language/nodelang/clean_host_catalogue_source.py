"""The host operations this build can actually carry out.

The catalogue that matters lives on the graph, not here. What lives here
is the source it is installed from, and the reason this file exists at
all: the running catalogue was installed once, by hand, from a shell, and
nothing in the repository could rebuild it or say what was in it. A
catalogue nobody can reproduce is a catalogue nobody can review.

Every record below names an operation an adapter carries out today. That
is the whole rule, and `test_no_declared_operation_is_a_dead_button`
enforces it in both directions: nothing declared here without an adapter
behind it, and no adapter script for something undeclared. A button that
refuses is worse than a button that is absent, because the person who
pressed it now has to work out whether the model or the program is
broken.

Operations an adapter cannot yet carry out are not listed. They are not
promises kept somewhere else -- they are simply not offered.

This file holds records and nothing else. Which machine a host reaches
is named in the entry point that stands the runtime up, because a
library that chose its own adapters would be a runtime that could
touch a host nobody chose.
"""

from __future__ import annotations

def _read(op_id, host, label, description, output_type="row"):
    """One read: no arguments beyond the instance, and no side effect."""
    return {
        "op_id": op_id,
        "host": host,
        "kind": "read",
        "label": label,
        "description": description,
        "output_type": output_type,
        "destructive": False,
        "inputs": [{
            "id": "instance",
            "label": "Session",
            "type": "text",
            "default": "",
            "required": False,
            "help": "Which running session to ask. Blank picks the one "
                    "holding a document.",
        }],
    }


REVIT_OPERATIONS = [
    _read("revit.list_doors", "revit", "Doors",
          "Every door placed in the model, with its family and level."),
    _read("revit.list_windows", "revit", "Windows",
          "Every window placed in the model, with its family and level."),
    _read("revit.list_walls", "revit", "Walls",
          "Every wall in the model, with its type and level."),
    _read("revit.list_rooms", "revit", "Rooms",
          "Every room, with its number and area."),
    _read("revit.list_levels", "revit", "Levels",
          "Every level, with its elevation."),
    _read("revit.list_views", "revit", "Views",
          "Every view in the project browser."),
    _read("revit.list_sheets", "revit", "Sheets",
          "Every sheet, with its number and name."),
    _read("revit.list_families", "revit", "Families",
          "Every loaded family, with its category."),
    _read("revit.list_warnings", "revit", "Warnings",
          "Every warning Revit is currently holding against the model."),
    _read("revit.get_selection", "revit", "Selection",
          "Whatever is selected in the active view right now."),
    _read("revit.list_schedules", "revit", "Schedules",
          "Every schedule, and whether it is a titleblock revision "
          "schedule."),
    _read("revit.list_revisions", "revit", "Revisions",
          "Every revision, with its sequence, date and issued state."),
    _read("revit.list_grids", "revit", "Grids",
          "Every grid line in the model."),
    _read("revit.list_worksets", "revit", "Worksets",
          "Every user workset, whether it is open, and who owns it."),
    _read("revit.list_links", "revit", "Linked models",
          "Every linked Revit model and whether its file is still found."),
    _read("revit.list_cad_imports", "revit", "CAD imports",
          "Every CAD link and every imported CAD instance. Imports that "
          "are not links are the ones that bloat a model."),
    _read("revit.list_view_templates", "revit", "View templates",
          "Every view template defined in the project."),
    _read("revit.list_phases", "revit", "Phases",
          "Every phase, in order."),
    _read("revit.list_design_options", "revit", "Design options",
          "Every design option, its set, and whether it is primary."),
    _read("revit.list_groups", "revit", "Groups",
          "Every group instance and how many members it holds."),
    _read("revit.list_in_place_families", "revit", "In-place families",
          "Every in-place family. These cannot be scheduled or reused and "
          "are worth knowing about."),
    _read("revit.list_titleblocks", "revit", "Titleblocks",
          "Every titleblock type loaded in the project."),
    _read("revit.list_materials", "revit", "Materials",
          "Every material, with its class."),
    _read("revit.list_project_parameters", "revit", "Project parameters",
          "Every project parameter binding, instance or type, and how "
          "many categories it reaches."),
    _read("revit.list_views_not_on_sheet", "revit", "Views not on a sheet",
          "Every view that no viewport places on a sheet."),
    _read("revit.list_rooms_unplaced", "revit", "Unplaced rooms",
          "Every room that is not placed or encloses no area."),
    _read("revit.count_by_category", "revit", "Element census",
          "How many placed elements each category holds."),
    _read("revit.list_text_notes", "revit", "Text notes",
          "Every text note and the view it sits in."),
    _read("revit.list_floors", "revit", "Floors",
          "Every floor, with its type, level and area."),
    _read("revit.list_ceilings", "revit", "Ceilings",
          "Every ceiling, with its type and level."),
    _read("revit.list_roofs", "revit", "Roofs",
          "Every roof, with its type and level."),
    _read("revit.list_columns", "revit", "Columns",
          "Every column, architectural and structural."),
    _read("revit.list_stairs", "revit", "Stairs",
          "Every stair, with its type and level."),
    _read("revit.list_railings", "revit", "Railings",
          "Every railing, with its type and level."),
    _read("revit.list_curtain_walls", "revit", "Curtain walls",
          "Every wall whose type is a curtain wall."),
    _read("revit.list_wall_types", "revit", "Wall types",
          "Every wall type, its kind and width."),
    _read("revit.list_areas", "revit", "Areas",
          "Every area, with its scheme and size."),
    _read("revit.list_line_styles", "revit", "Line styles",
          "Every line style and its projection weight."),
    _read("revit.list_sheet_revisions", "revit", "Sheet revisions",
          "Every sheet and the revisions clouded on it."),
    _read("revit.list_view_filters", "revit", "View filters",
          "Every view filter and how many categories it reaches."),
    _read("revit.list_scope_boxes", "revit", "Scope boxes",
          "Every scope box in the model."),
    _read("revit.list_reference_planes", "revit", "Reference planes",
          "Every reference plane and the view that owns it."),
    _read("revit.list_door_types", "revit", "Door types",
          "Every door type loaded, with its family."),
    _read("revit.list_window_types", "revit", "Window types",
          "Every window type loaded, with its family."),
    _read("revit.list_generic_models", "revit", "Generic models",
          "Every generic model placed, with its level."),
    _read("revit.list_furniture", "revit", "Furniture and equipment",
          "Furniture, casework and speciality equipment."),
    _read("revit.list_dimensions", "revit", "Dimensions",
          "Every dimension, its view, and whether its value was overridden."),
    _read("revit.list_legends", "revit", "Legends",
          "Every legend view."),
]

OFFICE_OPERATIONS = [
    _read("excel.list_workbooks", "excel", "Open workbooks",
          "Every workbook open in the running Excel."),
    _read("excel.list_worksheets", "excel", "Worksheets",
          "Every worksheet in the active workbook."),
    _read("word.list_documents", "word", "Open documents",
          "Every document open in the running Word."),
    _read("word.list_paragraphs", "word", "Paragraphs",
          "Every paragraph in the active document."),
    _read("powerpoint.list_presentations", "powerpoint", "Open presentations",
          "Every presentation open in the running PowerPoint."),
    _read("powerpoint.list_slides", "powerpoint", "Slides",
          "Every slide in the active presentation."),
]

HOST_OPERATION_RECORDS = REVIT_OPERATIONS + OFFICE_OPERATIONS

__all__ = [
    "HOST_OPERATION_RECORDS",
    "OFFICE_OPERATIONS",
    "REVIT_OPERATIONS",
]
