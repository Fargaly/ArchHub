"""Installing the new capabilities into the application the founder runs.

Every module built today was correct, tested, and imported by nothing. A
capability the running application cannot reach is not a capability -- it is a
library sitting next to a product, which is exactly the shape this migration
exists to end.

This installs each one into the SAME graph the application serves, so the
capability is present at the revision the app is on, not in a test fixture
beside it. Installing twice changes nothing.
"""
from __future__ import annotations

from dataclasses import dataclass

from .cell_brain_community import COMMUNITY_ROOT, ensure_community
from .cell_brain_explorer import SHELF_ROOT, ensure_shelf
from .cell_brain_groups import GROUPS_ROOT, ensure_groups
from .cell_brain_ownership import REGISTRY_ROOT as OWNERSHIP_ROOT, ensure_registry
from .cell_brain_recall import INDEX_ROOT, ensure_index
from .cell_brain_reflexion import LEDGER_ROOT, ensure_ledger
from .cell_brain_secrets import VAULT_ROOT, ensure_vault
from .cell_brain_skills import SKILL_LIBRARY_ROOT, ensure_skill_library
from .cell_model_providers import PROVIDERS_ROOT, ensure_providers
from .cell_selfext_intent import INTENTS_ROOT, ensure_intents
from .cell_session_state import SESSIONS_ROOT, ensure_sessions
from .cell_users_seats import FIRMS_ROOT, ensure_firms
from .cell_website_meta import META_ROOT, ensure_meta
from .universal_cell import InvalidCell

# Each capability, the root it must leave in the graph, and how it is installed.
CAPABILITIES = (
    ("brain-secrets", VAULT_ROOT, "vault"),
    ("brain-ownership", OWNERSHIP_ROOT, "ownership"),
    ("brain-skills", SKILL_LIBRARY_ROOT, "skills"),
    ("brain-reflexion", LEDGER_ROOT, "reflexion"),
    ("brain-recall", INDEX_ROOT, "recall"),
    ("brain-explorer", SHELF_ROOT, "shelf"),
    ("brain-community", COMMUNITY_ROOT, "community"),
    ("brain-groups", GROUPS_ROOT, "groups"),
    ("model-providers", PROVIDERS_ROOT, "providers"),
    ("selfext-intents", INTENTS_ROOT, "intents"),
    ("user-firms", FIRMS_ROOT, "firms"),
    ("sessions", SESSIONS_ROOT, "sessions"),
    ("website-meta", META_ROOT, "meta"),
)

_INSTALLERS = {
    "vault": ensure_vault,
    "ownership": ensure_registry,
    "skills": None,          # needs the assembly protocol; installed with it
    "reflexion": ensure_ledger,
    "recall": ensure_index,
    "shelf": ensure_shelf,
    "community": ensure_community,
    "groups": ensure_groups,
    "providers": ensure_providers,
    "intents": ensure_intents,
    "firms": ensure_firms,
    "sessions": ensure_sessions,
    "meta": ensure_meta,
}


@dataclass(frozen=True, slots=True)
class Installed:
    name: str
    root_id: str


def install_capabilities(store, *, assembly_protocol=None):
    """Put every capability into the live graph. Idempotent by construction."""
    installed = []
    for name, root_id, key in CAPABILITIES:
        installer = _INSTALLERS[key]
        if installer is None:
            if assembly_protocol is None:
                continue
            ensure_skill_library(store, assembly_protocol)
        else:
            installer(store)
        installed.append(Installed(name, root_id))
    return tuple(installed)


def missing_capabilities(snapshot, *, include_skills=True):
    """What the running graph cannot reach. Empty is the only passing answer."""
    missing = []
    for name, root_id, key in CAPABILITIES:
        if key == "skills" and not include_skills:
            continue
        if root_id not in snapshot.cells:
            missing.append(name)
    return tuple(missing)


def assert_capabilities_present(snapshot, *, include_skills=True):
    missing = missing_capabilities(snapshot, include_skills=include_skills)
    if missing:
        raise InvalidCell(
            "the application cannot reach these capabilities: %s"
            % ", ".join(missing)
        )
    return True
