"""A node outlives the definition it was made from (SPEC 3.3, 5.2).

An instance names the definition revision it was made from, and
`revise_instance` refuses once that revision is superseded: "instance
definition revision is no longer current". That rule is right -- the
overrides were written against a contract -- but with no way to move an
instance forward it means publishing a new revision of Number silently
freezes every Number already on a canvas: selectable, readable,
uneditable, and unable to receive the answer a Run computes for it.

Adopting is the way forward, and it is a signed act with a receipt like
any other. What it must NOT do is decide for the founder: an override the
new revision no longer declares is refused by name, never dropped.
"""
import hashlib
import uuid
from pathlib import Path

import pytest

from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.clean_runtime_bootstrap import provision_clean_runtime
from nodelang.runtime_caller_capability import WindowsDpapiCallerKeyStore
from nodelang.unified_authority import (
    InvalidCell,
    adopt_definition_revision,
    declare_definition,
    instantiate_definition,
    promote_definition,
    read_scope_level,
    revise_definition,
    revise_instance,
)


PROVIDER = MemorySigningKeyProvider(
    "archhub.unified.bootstrap", b"adopt-revision" + b"0" * 18,
)
GRAND_MAP = (
    b'[{"key":"k","title":"K","nodes":[{"id":"a","cat":"note","title":"A",'
    b'"sub":"h","status":"vision","params":[],"evidence_ref":"",'
    b'"authority_source":"c"}],"wires":[],"cross":[]}]'
)


@pytest.fixture
def runtime(tmp_path):
    specification = (Path(__file__).parents[1] / "SPEC.md").read_bytes()
    built = provision_clean_runtime(
        tmp_path,
        PROVIDER,
        WindowsDpapiCallerKeyStore(tmp_path / "callers.dpapi.json"),
        caller_key_id="founder.bootstrap",
        specification_source=specification,
        specification_sha256=hashlib.sha256(specification).hexdigest(),
        grand_map_source=GRAND_MAP,
        grand_map_sha256=hashlib.sha256(GRAND_MAP).hexdigest(),
    )
    yield built
    built.location.authority.store.close()


def _placed(built, parameters, defaults):
    """One published definition with one instance of it in the map."""
    authority = built.location.authority
    caller = built.caller
    scope = built.grand_map.root_id
    definition = declare_definition(
        authority,
        "Adoptable",
        defaults,
        parameters=parameters,
        caller=caller,
        command_id=str(uuid.uuid4()),
    )
    shared = promote_definition(
        authority, definition.root_id, target_lifecycle="shared",
        version="1-shared", evidence_roots=(definition.receipt_root,),
        caller=caller, command_id=str(uuid.uuid4()),
    )
    promote_definition(
        authority, definition.root_id, target_lifecycle="published",
        version="1-published", evidence_roots=(shared.receipt_root,),
        caller=caller, command_id=str(uuid.uuid4()),
    )
    instance = instantiate_definition(
        authority,
        definition.root_id,
        {},
        scope_root=scope,
        caller=caller,
        command_id=str(uuid.uuid4()),
    )
    return definition.root_id, instance.root_id, scope


def _republished(built, definition_root, defaults, parameters):
    authority, caller = built.location.authority, built.caller
    revised = revise_definition(
        authority,
        definition_root,
        "Adoptable",
        defaults,
        parameters=parameters,
        caller=caller,
        command_id=str(uuid.uuid4()),
        version="2",
    )
    shared = promote_definition(
        authority, definition_root, target_lifecycle="shared",
        version="2-shared", evidence_roots=(revised.receipt_root,),
        caller=caller, command_id=str(uuid.uuid4()),
    )
    promote_definition(
        authority, definition_root, target_lifecycle="published",
        version="2-published", evidence_roots=(shared.receipt_root,),
        caller=caller, command_id=str(uuid.uuid4()),
    )


def test_an_edit_is_refused_once_the_definition_moves(runtime):
    authority, caller = runtime.location.authority, runtime.caller
    definition_root, instance_root, scope = _placed(
        runtime,
        {"value": {"type": "text", "editor": "text"}},
        {"value": "one"},
    )
    revise_instance(
        authority, instance_root, {"value": "two"},
        scope_root=scope, caller=caller, command_id=str(uuid.uuid4()),
    )
    _republished(
        runtime, definition_root,
        {"value": "one", "extra": "new"},
        {
            "value": {"type": "text", "editor": "text"},
            "extra": {"type": "text", "editor": "text"},
        },
    )
    with pytest.raises(InvalidCell, match="no longer current"):
        revise_instance(
            authority, instance_root, {"value": "three"},
            scope_root=scope, caller=caller, command_id=str(uuid.uuid4()),
        )


def test_adopting_restores_the_edit_and_keeps_the_override(runtime):
    authority, caller = runtime.location.authority, runtime.caller
    definition_root, instance_root, scope = _placed(
        runtime,
        {"value": {"type": "text", "editor": "text"}},
        {"value": "one"},
    )
    revise_instance(
        authority, instance_root, {"value": "kept"},
        scope_root=scope, caller=caller, command_id=str(uuid.uuid4()),
    )
    _republished(
        runtime, definition_root,
        {"value": "one", "extra": "new"},
        {
            "value": {"type": "text", "editor": "text"},
            "extra": {"type": "text", "editor": "text"},
        },
    )
    adopt_definition_revision(
        authority, instance_root, scope_root=scope, caller=caller,
        command_id=str(uuid.uuid4()),
    )
    level = read_scope_level(
        authority, scope, scope_root=scope, caller=caller,
    )
    values = level.instances[instance_root]["values"]
    assert values["value"] == "kept", values
    revise_instance(
        authority, instance_root, {"value": "three"},
        scope_root=scope, caller=caller, command_id=str(uuid.uuid4()),
    )
    level = read_scope_level(
        authority, scope, scope_root=scope, caller=caller,
    )
    assert level.instances[instance_root]["values"]["value"] == "three"


def test_adopting_refuses_by_name_when_the_new_revision_dropped_a_value(
    runtime,
):
    """What happens to the founder's value is the founder's decision."""
    authority, caller = runtime.location.authority, runtime.caller
    definition_root, instance_root, scope = _placed(
        runtime,
        {
            "value": {"type": "text", "editor": "text"},
            "doomed": {"type": "text", "editor": "text"},
        },
        {"value": "one", "doomed": "here"},
    )
    revise_instance(
        authority, instance_root, {"doomed": "mine"},
        scope_root=scope, caller=caller, command_id=str(uuid.uuid4()),
    )
    _republished(
        runtime, definition_root,
        {"value": "one"},
        {"value": {"type": "text", "editor": "text"}},
    )
    with pytest.raises(InvalidCell, match="doomed"):
        adopt_definition_revision(
            authority, instance_root, scope_root=scope, caller=caller,
            command_id=str(uuid.uuid4()),
        )


def test_adopting_an_instance_that_is_already_current_is_refused(runtime):
    """Nothing to adopt is not a quiet success; it is nothing to do."""
    authority, caller = runtime.location.authority, runtime.caller
    _definition_root, instance_root, scope = _placed(
        runtime,
        {"value": {"type": "text", "editor": "text"}},
        {"value": "one"},
    )
    with pytest.raises(InvalidCell, match="already names the current"):
        adopt_definition_revision(
            authority, instance_root, scope_root=scope, caller=caller,
            command_id=str(uuid.uuid4()),
        )
