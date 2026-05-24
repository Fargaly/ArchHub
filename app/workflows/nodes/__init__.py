"""All built-in node types. Importing this package registers them.

Tool nodes are auto-generated from tool_engine.TOOLS via register_tool_nodes(),
which must be called once after the tool engine is available (typically at
app startup).
"""
from . import io_data       # noqa: F401  registers input.parameter, output.parameter, data.constant, data.template
from . import llm           # noqa: F401  registers llm.complete, llm.complete_with_tools, llm.classify
from . import control       # noqa: F401  registers control.if, control.merge, control.foreach
from . import aec           # noqa: F401  registers aec.dxf_reader, aec.ifc_reader, aec.csv_reader, aec.revit_wall, aec.column, aec.qto_pricing, aec.cost_estimate, aec.schedule_builder, aec.team_member_selector
from . import core          # noqa: F401  ADR-003 Phase 1: registers host.* (7), conversation.chat, doc.* (8)
from . import connector     # noqa: F401  node-grammar slice 2: registers connector.run (the master host node)
from . import host_typed    # noqa: F401  AgDR-0041 P1: typed host nodes (import_mesh / read_walls / export_viewport / run_script)
from . import render_typed  # noqa: F401  Tier 2 (2026-05-24): typed render/vision/mesh/anim primitives over comfyui + dashscope connectors
from . import shape         # noqa: F401  node-grammar slices 6-7: registers filter.apply, transform.apply, watch.preview
from . import trigger       # noqa: F401  node-grammar: registers trigger.emit (the graph entry-point node)
from . import math_text     # noqa: F401  node-grammar slice J: registers math.op + text.op
from . import share         # noqa: F401  node-grammar M1.5: registers share.server + share.publish + share.subscribe
from . import adapter       # noqa: F401  cross-host native-type mapping: registers adapter.cad_to_revit_wall + adapter.to_revit_directshape + adapter.max_to_revit_family
from . import code          # noqa: F401  SLICE L (AgDR-0020): registers code.expression + code.python
from . import ai_plan       # noqa: F401  M4 foundation (AgDR-0021): registers ai.plan
from . import aggregate     # noqa: F401  AgDR-0040 slice 2: registers data.reduce + accumulate + sort + group_by
from .tools import register_tool_nodes  # noqa: F401  call manually to register tool.* nodes
