"""All built-in node types. Importing this package registers them.

Tool nodes are auto-generated from tool_engine.TOOLS via register_tool_nodes(),
which must be called once after the tool engine is available (typically at
app startup).
"""
from . import io_data       # noqa: F401  registers input.parameter, output.parameter, data.constant, data.template
from . import llm           # noqa: F401  registers llm.complete, llm.complete_with_tools, llm.classify
from . import control       # noqa: F401  registers control.if, control.merge, control.foreach
from .tools import register_tool_nodes  # noqa: F401  call manually to register tool.* nodes
