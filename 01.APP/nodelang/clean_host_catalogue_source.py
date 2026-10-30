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

def _input(id, label, kind, *, default="", required=False, help="", **metadata):
    row = {
        "id": id,
        "label": label,
        "type": kind,
        "default": default,
        "required": required,
        "help": help,
    }
    row.update(metadata)
    return row


def _revit_session_input():
    return _input(
        "instance",
        "Revit session",
        "revit-document-picker",
        help="Select an open Revit document.",
        options_source="revit.open_documents",
        option_label="document",
        auto_select_single=True,
        text_input=False,
    )


def _read(op_id, host, label, description, output_type="row", inputs=()):
    """One read: host-appropriate inputs only, and no side effect."""
    held_inputs = list(inputs)
    if host == "revit":
        held_inputs = [_revit_session_input(), *held_inputs]
    return {
        "op_id": op_id,
        "host": host,
        "kind": "read",
        # Node contract C2: pure re-solves on input change; side-effect waits for Run + Approve.
        "effect": "pure",
        "label": label,
        "description": description,
        "output_type": output_type,
        "destructive": False,
        "inputs": held_inputs,
    }


def _write(op_id, host, label, description, inputs, output_type="row"):
    row = {
        "op_id": op_id,
        "host": host,
        "kind": "write",
        "effect": "side-effect",
        "label": label,
        "description": description,
        "output_type": output_type,
        "destructive": True,
        "inputs": list(inputs) + [_input(
            "grant",
            "Approval grant",
            "approval-grant",
            required=True,
            help="Comes from the Approval gate.",
        )],
    }
    return row


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
    # Geometry toolset folded from bimwright rvt-mcp (Apache-2.0); metric in and out.
    _read("revit.get_element_bounding_box", "revit", "Element bounding box",
          "Bounding box of each element in metres, optionally in a view.", inputs=(
              _input("elements", "Elements", "element-rows", required=True),
              _input("view_id", "View id", "element-id"),
              _input("include_transform", "Include transform", "boolean"),
          )),
    _read("revit.get_element_geometry", "revit", "Element geometry",
          "Solids, faces, edges, volume, area and location of each element.", inputs=(
              _input("elements", "Elements", "element-rows", required=True),
              _input("detail_level", "Detail level", "text"),
              _input("include_samples", "Include vertex samples", "boolean"),
              _input("sample_limit", "Sample limit", "number"),
          )),
    _read("revit.measure_distance_between_elements", "revit", "Distance between elements",
          "Shortest distance between two elements in metres (bounding box or location).", inputs=(
              _input("element_id_1", "First element", "element-id", required=True),
              _input("element_id_2", "Second element", "element-id", required=True),
              _input("strategy", "Strategy", "text"),
          )),
    _read("revit.clash_detection", "revit", "Clash detection",
          "Elements of categories A that clash with categories B, box first then solid.", inputs=(
              _input("categories_a", "Categories A", "category-names", required=True),
              _input("categories_b", "Categories B", "category-names", required=True),
              _input("view_id", "View id", "element-id"),
              _input("strategy", "Strategy", "text"),
              _input("max_pairs", "Max pairs", "number"),
              _input("max_results", "Max results", "number"),
          )),
    _read("revit.raycast_from_point", "revit", "Raycast from point",
          "The nearest element a ray hits in a 3D view; origin in metres.", inputs=(
              _input("view3d_id", "3D view id", "element-id", required=True),
              _input("x", "X (m)", "number", required=True),
              _input("y", "Y (m)", "number", required=True),
              _input("z", "Z (m)", "number", required=True),
              _input("dir_x", "Direction X", "number", required=True),
              _input("dir_y", "Direction Y", "number", required=True),
              _input("dir_z", "Direction Z", "number", required=True),
              _input("categories", "Categories", "category-names"),
              _input("max_distance", "Max distance (m)", "number"),
          )),
    _read("revit.find_elements_in_volume", "revit", "Elements in a volume",
          "Elements inside or crossing a box in metres, or a room's box.", inputs=(
              _input("volume", "Volume {min, max} (m)", "box"),
              _input("room_id", "Room id", "element-id"),
              _input("categories", "Categories", "category-names"),
              _input("view_id", "View id", "element-id"),
              _input("match", "Match", "text"),
              _input("limit", "Limit", "number"),
          )),
    _read("revit.compute_element_volume", "revit", "Element volume",
          "Solid volume of each element and the total, in cubic metres.", inputs=(
              _input("elements", "Elements", "element-rows", required=True),
              _input("detail_level", "Detail level", "text"),
          )),
    _read("revit.compute_element_area", "revit", "Element surface area",
          "Total face area of each element and the total, in square metres.", inputs=(
              _input("elements", "Elements", "element-rows", required=True),
              _input("detail_level", "Detail level", "text"),
          )),
    _read("revit.project_point_onto_face", "revit", "Project point onto face",
          "Where a point in metres lands on one face of an element.", inputs=(
              _input("element_id", "Element", "element-id", required=True),
              _input("x", "X (m)", "number", required=True),
              _input("y", "Y (m)", "number", required=True),
              _input("z", "Z (m)", "number", required=True),
              _input("face_index", "Face index", "number"),
              _input("detail_level", "Detail level", "text"),
          )),
    _read("revit.find_overlapping_elements", "revit", "Overlapping elements",
          "Pairs of one category whose bounding boxes overlap.", inputs=(
              _input("category", "Category", "category-name", required=True),
              _input("view_id", "View id", "element-id"),
              _input("max_pairs", "Max pairs", "number"),
              _input("max_results", "Max results", "number"),
          )),
    _read("revit.get_element_centroid", "revit", "Element centroid",
          "Volume-weighted centroid of each element in metres, box centre as fallback.", inputs=(
              _input("elements", "Elements", "element-rows", required=True),
              _input("strategy", "Strategy", "text"),
          )),
    _read("revit.analyze_geometry_complexity", "revit", "Geometry complexity",
          "Solid, face and curved-face counts per element, most complex first.", inputs=(
              _input("elements", "Elements", "element-rows"),
              _input("categories", "Categories", "category-names"),
              _input("view_id", "View id", "element-id"),
              _input("detail_level", "Detail level", "text"),
              _input("limit", "Limit", "number"),
          )),
    _write("revit.set_parameter_by_name", "revit", "Set parameter by name",
           "Write one named parameter on approved elements.", (
               _input("elements", "Elements", "element-rows", required=True),
               _input("parameter", "Parameter", "parameter-name", required=True),
               _input("value", "Parameter value", "parameter-value", required=True),
           )),
    _write("revit.create_sheets", "revit", "Create sheets",
           "Create approved sheets from rows.", (
               _input("rows", "Sheet rows", "sheet-rows", required=True),
           )),
    _write("revit.renumber_rename", "revit", "Renumber / rename",
           "Renumber or rename approved elements.", (
               _input("elements", "Elements", "element-rows", required=True),
               _input("number_format", "Number format", "index-format"),
               _input("name_format", "Name format", "index-format"),
           )),
]

def _layer_name():
    return _input("name", "Layer", "layer-name", required=True)


# Layer and linetype verb groups folded from U-C4N Autocad-MCP (MIT);
# clean_autocad_adapter carries them out through the signed AutoCAD broker.
AUTOCAD_OPERATIONS = [
    _read("autocad.layer_list", "autocad", "Layers",
          "Every layer with its colour, linetype, lineweight and state."),
    _read("autocad.linetype_list", "autocad", "Linetypes",
          "Every linetype loaded in the drawing."),
    _write("autocad.layer_create", "autocad", "Create layer",
           "Create a layer (or update one of that name) with colour, linetype and lineweight.", (
               _layer_name(),
               _input("color", "Colour index", "number"),
               _input("linetype", "Linetype", "text"),
               _input("lineweight", "Lineweight", "number"),
           )),
    _write("autocad.layer_delete", "autocad", "Delete layer",
           "Delete an unused layer; a layer in use, current, 0 or Defpoints is refused.",
           (_layer_name(),)),
    _write("autocad.layer_set_current", "autocad", "Set current layer",
           "Make a layer current.", (_layer_name(),)),
    _write("autocad.layer_modify", "autocad", "Modify layer",
           "Change a layer's colour, linetype or lineweight.", (
               _layer_name(),
               _input("color", "Colour index", "number"),
               _input("linetype", "Linetype", "text"),
               _input("lineweight", "Lineweight", "number"),
           )),
    _write("autocad.layer_freeze", "autocad", "Freeze layer", "Freeze a layer.", (_layer_name(),)),
    _write("autocad.layer_thaw", "autocad", "Thaw layer", "Thaw a layer.", (_layer_name(),)),
    _write("autocad.layer_lock", "autocad", "Lock layer", "Lock a layer.", (_layer_name(),)),
    _write("autocad.layer_unlock", "autocad", "Unlock layer", "Unlock a layer.", (_layer_name(),)),
    _write("autocad.layer_hide", "autocad", "Hide layer", "Turn a layer off.", (_layer_name(),)),
    _write("autocad.layer_show", "autocad", "Show layer", "Turn a layer on.", (_layer_name(),)),
    _write("autocad.linetype_load", "autocad", "Load linetype",
           "Load a linetype from acadiso.lin / acad.lin (by MEASUREMENT) or a named .lin file.", (
               _input("name", "Linetype", "text", required=True),
               _input("file", "Linetype file (.lin)", "text"),
           )),
]

OFFICE_OPERATIONS = [
    _read("excel.list_workbooks", "excel", "Open workbooks",
          "Every workbook open in the running Excel."),
    _read("excel.list_worksheets", "excel", "Worksheets",
          "Every worksheet in the active workbook.", inputs=(
              _input("workbook", "Workbook", "excel-workbook-picker"),
          )),
    _read("word.list_documents", "word", "Open documents",
          "Every document open in the running Word."),
    _read("word.list_paragraphs", "word", "Paragraphs",
          "Every paragraph in the active document.", inputs=(
              _input("document", "Document", "word-document-picker"),
          )),
    _read("powerpoint.list_presentations", "powerpoint", "Open presentations",
          "Every presentation open in the running PowerPoint."),
    _read("powerpoint.list_slides", "powerpoint", "Slides",
          "Every slide in the active presentation.", inputs=(
              _input("presentation", "Presentation", "powerpoint-presentation-picker"),
          )),
    # New operation records follow the complete released Office catalogue.
    _read("excel.read_range", "excel", "Read range",
          "Rows from a named range in a fixture workbook.", inputs=(
              _input("file", "Workbook file", "local-file", required=True),
              _input("sheet", "Sheet", "excel-worksheet", default="Sheet1"),
              _input("range", "Range", "excel-range", required=True),
          )),
    _write("excel.write_range", "excel", "Write Excel / CSV",
           "Rows written to an Excel or CSV file.", (
               _input("rows", "Rows", "table-rows", required=True),
               _input("format", "Format", "file-format", default="xlsx"),
           )),
]

HOST_OPERATION_RECORDS = REVIT_OPERATIONS + AUTOCAD_OPERATIONS + OFFICE_OPERATIONS

__all__ = [
    "AUTOCAD_OPERATIONS",
    "HOST_OPERATION_RECORDS",
    "OFFICE_OPERATIONS",
    "REVIT_OPERATIONS",
]
