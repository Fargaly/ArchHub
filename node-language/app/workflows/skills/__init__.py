"""Built-in Skills — composite Capability Nodes shipped with ArchHub.

Each Skill is a `impl.kind=graph` Capability spec (AgDR-0040 modular
logic) that composes typed primitives + host nodes + connector ops
into a one-click installable. Importing this package registers all
shipped Skills with the in-process registry; users can immediately
node_search / node_place them.

A Skill ships when:
  - It wires only primitives that already exist
  - Its inner graph is small enough to inspect (<10 nodes typical)
  - It demonstrates an end-to-end use case the founder cares about

Skills are NOT a god-class — they're plain Capability specs that
happen to ship in the box. Same registration path users follow
when they Save-as-Skill from the canvas.
"""
from . import revit_to_render        # noqa: F401  Use case A
from . import photo_to_rhino_mass    # noqa: F401  Use case B
from . import drone_to_revit_walls   # noqa: F401  Use case D
