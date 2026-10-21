"""Short-lived authenticated primitive inputs; never a policy decision.

Construct inside the owning runtime with its registry and trusted graph predicate
selection. This does not establish that selection's published protocol binding,
activate clean admission, persist facts, or supply allow/deny predicates.
Use evaluate_logic's default per-evaluation memo with these context facts.
"""
from types import MappingProxyType
from dataclasses import dataclass
import math
import time

from .cell_authorization import AuthorizationDenied, AuthorizationRequest
from .cell_identity import active_membership_roots, verify_relationship_authority_snapshot
from .cell_logic import PrimitiveFact
from .cell_protocols import read_relation, _relation_chain_ids
from .universal_cell import InvalidCell, NULL_CELL_ID
from .application_policy_binding import CONTEXT_FIELDS, read_policy_context_binding


MAX_RELATIONSHIPS = 4096


@dataclass(frozen=True, slots=True)
class PolicyObligationDecision:
    source_revision: int
    obligation_root: str
    read_roots: tuple[str, ...]
    allowed: bool
    proofs: tuple


class ApplicationPolicyContextFactory:
    """Trusted owner-side factory; request bodies must never supply a registry."""

    def __init__(self, store, registry, predicates):
        selected = dict(predicates)
        snapshot = store.snapshot()
        if (set(selected) != set(CONTEXT_FIELDS) or
                any(type(root) is not str or root == NULL_CELL_ID or root not in snapshot.cells
                    for root in selected.values()) or
                len(set(selected.values())) != len(selected)):
            raise InvalidCell("policy context predicate selection is invalid")
        self._store, self._registry = store, registry
        self._predicates = MappingProxyType(selected)
        self._binding = None

    @classmethod
    def from_graph(cls, store, registry, binding_root):
        """Pin a descriptor selected by the owner, never by a request body."""
        snapshot = store.snapshot()
        binding = read_policy_context_binding(snapshot, binding_root)
        factory = cls(store, registry, binding.predicates)
        factory._binding = binding
        factory._binding_source = (registry.application_root, registry.roles["member"])
        factory._validate_binding(snapshot)
        return factory

    def _validate_binding(self, snapshot):
        if self._binding is None:
            return ()  # Trusted low-level construction; no graph-admission claim.
        registry = self._registry
        if (registry.application_root, registry.roles["member"]) != self._binding_source:
            raise AuthorizationDenied("policy context binding owner selection changed")
        members = read_relation(snapshot, registry.application_root,
            budget=10_000, retain_projection=False)
        matches = tuple(member for member in members if member.role_id == registry.roles["member"]
                and member.participant_id == self._binding.root)
        if len(matches) != 1:
            raise AuthorizationDenied("policy context binding is not attached to this application")
        current = read_policy_context_binding(snapshot, self._binding.root)
        if current.digest != self._binding.digest:
            raise AuthorizationDenied("policy context binding changed")
        return (registry.roles["member"], matches[0].incidence_id, *current.read_roots)

    def capture(self, *, authentication_context, action_root, object_root):
        if authentication_context is None:
            raise AuthorizationDenied("policy context requires explicit authentication")
        store, registry = self._store, self._registry
        authority = registry.authorization
        selected = self._selection(authority)
        snapshot = store.snapshot()
        binding_evidence = self._validate_binding(snapshot)
        captured_at, monotonic_start = time.time(), time.monotonic()
        if action_root not in authority.protocol.actions.values():
            raise AuthorizationDenied("policy context action is undeclared")
        request = AuthorizationRequest(action_root=action_root, object_root=object_root,
            resource_lineage_roots=(authority.scope_root,), purpose_root=authority.purpose_root,
            classification_root=authority.classification_root, audience_root=authority.audience_root,
            now=captured_at)
        required = (registry.application_root, object_root, action_root, authority.scope_root,
            *self._predicates.values())
        optional = (authority.purpose_root, authority.classification_root, authority.audience_root)
        if any(type(root) is not str or root == NULL_CELL_ID or root not in snapshot.cells
                for root in (*required, *(root for root in optional if root is not None))):
            raise InvalidCell("policy context references missing inputs")
        # Reject an oversized registry before the existing signed verifier walks it.
        members = read_relation(snapshot, authority.identity_protocol.root_id,
            budget=MAX_RELATIONSHIPS, retain_projection=False)
        registered = [member.participant_id for member in members
            if member.role_id == authority.identity_protocol.roles["relationship-member"]]
        if len(registered) > MAX_RELATIONSHIPS or len(set(registered)) != len(registered):
            raise InvalidCell("policy context relationship bound is invalid")
        verified = verify_relationship_authority_snapshot(snapshot, authority.identity_protocol,
            authority.relationship_broker, now=captured_at)
        identity, = authority.broker.resolve_for_requests(snapshot, authentication_context,
            (request,), now=captured_at, resolver_state=verified)
        if (not identity.tenant_root or identity.tenant_root not in active_membership_roots(
                snapshot, authority.identity_protocol, authority.relationship_broker,
                identity.subject_root, identity.tenant_root, now=captured_at,
                authority_snapshot=verified)):
            raise AuthorizationDenied("policy context requires signed tenant membership")
        expiry = min(captured_at + 5.0, identity.expires_at)
        for relationship in verified.active_relationships:
            if relationship.expires_at_root:
                try:
                    value = float(snapshot.cells[relationship.expires_at_root].atom.decode("ascii"))
                except (ValueError, UnicodeDecodeError, KeyError) as exc:
                    raise InvalidCell("policy context relationship expiry is invalid") from exc
                if not math.isfinite(value):
                    raise InvalidCell("policy context relationship expiry is invalid")
                expiry = min(expiry, value)
        values = {"subject":(identity.subject_root,), "principal":identity.principal_roots,
            "tenant":(identity.tenant_root,), "assurance":(identity.assurance_root,),
            "action":(action_root,), "object":(object_root,), "scope":(authority.scope_root,),
            "purpose":() if authority.purpose_root is None else (authority.purpose_root,),
            "classification":() if authority.classification_root is None else (authority.classification_root,),
            "audience":() if authority.audience_root is None else (authority.audience_root,)}
        if sum(map(len, values.values())) > MAX_RELATIONSHIPS:
            raise InvalidCell("policy context exceeds its fact bound")
        if any(type(root) is not str or root == NULL_CELL_ID or root not in snapshot.cells
                for rows in values.values() for root in rows):
            raise InvalidCell("policy context identity references missing roots")
        evidence = tuple(dict.fromkeys((registry.application_root, *binding_evidence,
            authority.identity_protocol.root_id,
            *(relationship.root_id for relationship in verified.active_relationships))))
        by_predicate = {self._predicates[name]:tuple(rows) for name, rows in values.items()}
        initial_identity = authority.broker.resolve(authentication_context, now=captured_at)

        def fresh():
            now = time.time()
            if (not math.isfinite(expiry) or now < captured_at or now >= expiry or
                    time.monotonic() - monotonic_start >= 5.0):
                raise AuthorizationDenied("policy context expired")
            current = store.snapshot()
            if (self._registry is not registry or registry.authorization is not authority or
                    self._selection(authority) != selected or current.revision != snapshot.revision or
                    current.cells is not snapshot.cells):
                raise AuthorizationDenied("policy context source changed")
            if authority.broker.resolve(authentication_context, now=now) != initial_identity:
                raise AuthorizationDenied("policy context authentication changed")

        def provide(predicate_root, arguments, budget):
            fresh()
            if type(budget) is not int or budget < 1:
                raise InvalidCell("policy context fact budget is invalid")
            if type(arguments) is not tuple or len(arguments) != 1:
                return ()
            rows = tuple(root for root in by_predicate.get(predicate_root, ())
                if arguments[0] is None or arguments[0] == root)
            if len(rows) * (len(evidence) + 3) > budget:
                raise InvalidCell("policy context fact budget exceeded")
            facts = tuple(PrimitiveFact(predicate_root, (root,),
                (*evidence, predicate_root, root)) for root in rows)
            fresh()
            return facts

        fresh()
        provide.validate = fresh
        return provide

    def _selection(self, authority):
        return (self._registry.application_root, authority.protocol, authority.identity_protocol,
            authority.policy_root, authority.broker, authority.relationship_broker, authority.scope_root,
            authority.purpose_root, authority.classification_root, authority.audience_root,
            self._registry.roles["member"] if self._binding is not None else None)

    def evaluate_obligations(self, obligation_root, plan, *, authentication_context,
            budget=100_000):
        """Evaluate all concrete action/object pairs in an owner-selected relation.

        Selection must be authenticated by the adopting runtime. This method
        neither derives operation requirements nor authorizes their selection;
        request bodies must never choose this root or the compiled plan.
        Returns all proofs only when every obligation passes on one live source.
        """
        from .application_policy_compiler import evaluate_compiled_policy
        if type(budget) is not int or not 2 <= budget <= 1_000_000:
            raise InvalidCell("policy obligation budget is invalid")
        authority = self._registry.authorization
        if (plan.source_policy != authority.policy_root or
                plan.source_protocol != authority.protocol):
            raise AuthorizationDenied("policy obligation selection is not the owner's policy")
        snapshot = self._store.snapshot()
        members = read_relation(snapshot, obligation_root, budget=64,
            retain_projection=False)
        pairs = tuple((member.role_id, member.participant_id) for member in members)
        if (not pairs or len(pairs) > 32 or len(set(pairs)) != len(pairs) or
                any(action not in authority.protocol.actions.values() or
                    target == NULL_CELL_ID or target not in snapshot.cells
                    for action, target in pairs)):
            raise InvalidCell("policy obligations require one to 32 distinct declared action/object pairs")
        per_request = budget // len(pairs)
        read_roots = tuple(dict.fromkeys((*_relation_chain_ids(snapshot, obligation_root, budget=64),
            *(root for member in members for root in
                (member.incidence_id, member.role_id, member.participant_id)))))
        if per_request < 2:
            raise InvalidCell("policy obligation budget cannot cover all requests")
        providers, results = [], []
        for action, target in pairs:
            provider = self.capture(authentication_context=authentication_context,
                action_root=action, object_root=target)
            current = self._store.snapshot()
            if current.revision != snapshot.revision or current.cells is not snapshot.cells:
                raise AuthorizationDenied("policy obligation source changed")
            subjects = provider(self._predicates["subject"], (None,), per_request)
            if len(subjects) != 1:
                raise AuthorizationDenied("policy obligations require one authenticated subject")
            allowed, proofs = evaluate_compiled_policy(snapshot, plan,
                plan.logic_protocol, provider, subject=subjects[0].arguments[0],
                action=action, object_root=target, budget=per_request)
            providers.append(provider)
            for captured in providers:
                captured.validate()
            if not allowed:
                return PolicyObligationDecision(snapshot.revision, obligation_root, read_roots, False, ())
            results.append((action, target, proofs))
        for captured in providers:
            captured.validate()
        return PolicyObligationDecision(snapshot.revision, obligation_root, read_roots, True, tuple(results))
