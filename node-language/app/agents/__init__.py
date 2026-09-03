"""Agent registry. Add new agents here."""
from .base import Agent, AgentResult, REGISTRY
from .dimensions_agent import DimensionsAgent

# Register built-ins
for cls in (DimensionsAgent,):
    inst = cls()
    REGISTRY[inst.id] = inst

__all__ = ["Agent", "AgentResult", "REGISTRY"]
