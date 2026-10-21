"""One bounded model turn through the existing application's graph APIs.

No private queue, implicit enrollment, approval, completion claim or retry loop.
The host supplies an already bound worker and an already approved exact grant.
Publishing the result is separate so a lost message response cannot rerun a model.
"""
from dataclasses import dataclass, field
import json
from typing import Mapping

from .universal_cell import InvalidCell
from .model_router import resolve_model_route, ModelRouteRefused


@dataclass(frozen=True)
class PreparedModelWork:
    work_root: str
    worker_root: str
    cognition_root: str
    delegation_root: str
    model: str
    input_digest: str
    review_text: str = field(repr=False)


@dataclass(frozen=True)
class SettledModelWork:
    prepared: PreparedModelWork
    receipt_root: str
    proposal_root: str | None
    reconciled: bool
    review_text: str = field(default="", repr=False)


def _root(value):
    if type(value) is not str or not value or len(value) > 4096:
        raise InvalidCell("Workshop execution identity is invalid")
    return value


class ExistingWorkshopModelWorker:
    """Transient driver; the bound runtime owns claims, policy and settlement."""

    def __init__(self, client):
        self.client = client
        self.worker_root = _root(client.agent_session_root)

    def _bound(self):
        if self.client.agent_session_root != self.worker_root:
            raise InvalidCell("Workshop worker binding changed")

    def prepare_free_review(self, work_root: str, *, data_class: str, model="openrouter/free", expected_revision=None):
        """Claim one explicit Work and prepare its graph-held review input.

        The server verifies assignment and source/plan gates. This method stops
        at delegation; a different admitted founder context must approve it.
        """
        self._bound()
        _root(work_root)
        if type(model) is not str or not (model == "openrouter/free" or model.endswith(":free")):
            raise InvalidCell("Workshop worker requires an explicit free model")
        try:
            route = resolve_model_route(model)
        except ModelRouteRefused as exc:
            raise InvalidCell("Workshop worker requires a valid free OpenRouter route") from exc
        parts = route.model.split("/")
        if route.family != "openrouter" or route.model != model or not (
            model == "openrouter/free" or (len(parts) == 2 and all(parts)
                and parts[1] != ":free" and not any(char.isspace() for char in model))
        ):
            raise InvalidCell("Workshop worker requires a canonical free OpenRouter model")
        if data_class not in ("public-text", "internal-text", "confidential-text"):
            raise InvalidCell("Workshop review requires an explicit data classification")
        if expected_revision is None:
            self.client.claim_work(work_root)
        else:
            self.client.claim_work(work_root, expected_revision=expected_revision)
        self.client.request("POST", "/api/universal/work-plan", {"root":work_root})
        cognition = self.client.request("POST", "/api/universal/model-cognition", {
            "root":work_root, "provider":"openrouter", "model":model})
        if (cognition.get("work") != work_root or cognition.get("execution_session") != self.worker_root
                or cognition.get("provider") != "openrouter" or cognition.get("model") != model):
            raise InvalidCell("Workshop Cognition binding differs from this worker request")
        cognition_root = _root(cognition.get("request"))
        delegation = self.client.request("POST", "/api/universal/model-delegation", {
            "root":work_root, "provider":"openrouter", "model":model,
            "data_class":data_class, "cognition_request":cognition_root})
        if delegation.get("work") != work_root or delegation.get("model") != model:
            raise InvalidCell("Workshop delegation differs from the requested Work or model")
        digest, task = delegation.get("input_digest"), delegation.get("task")
        if (type(digest) is not str or len(digest) != 64 or
                cognition.get("input_digest") != digest or
                any(value not in "0123456789abcdef" for value in digest) or
                type(task) is not str or not task or len(task.encode("utf-8")) > 64 * 1024):
            raise InvalidCell("Workshop delegation review material is invalid")
        return PreparedModelWork(work_root, self.worker_root, cognition_root,
            _root(delegation.get("delegation")), model, digest, task)

    def execute_approved_grant(self, prepared: PreparedModelWork, grant: Mapping):
        """Use exactly this grant once; never mint another after an uncertain call."""
        self._bound()
        if type(prepared) is not PreparedModelWork or prepared.worker_root != self.worker_root:
            raise InvalidCell("Workshop preparation belongs to another worker")
        if not isinstance(grant, Mapping) or grant.get("delegation") != prepared.delegation_root:
            raise InvalidCell("Workshop grant belongs to another delegation")
        grant_root = _root(grant.get("grant"))
        capability = grant.get("capability")
        if type(capability) is not str or not capability:
            raise InvalidCell("Workshop grant capability is absent")
        # Transport errors propagate. Callers retain the exact grant and must
        # reconcile uncertainty; this driver does not issue a replacement grant.
        result = self.client.request("POST", "/api/universal/model-delegation-execute", {
            "grant":grant_root, "capability":capability})
        if (result.get("delegation") != prepared.delegation_root or
                type(result.get("reconciled")) is not bool or type(result.get("work_advanced")) is not bool or
                (result["reconciled"] and result["work_advanced"])):
            raise InvalidCell("Workshop execution returned an invalid settlement")
        proposal = result.get("proposal")
        if result["reconciled"] and proposal is None:
            raise InvalidCell("Workshop execution has no reconciled proposal")
        review = result.get("review")
        review_text = ""
        if result["reconciled"]:
            if type(review) is not dict or set(review) != {"summary", "next_actions", "risks", "uncertainty"}:
                raise InvalidCell("Workshop execution has no review content")
            review_text = json.dumps(review, ensure_ascii=False, indent=2)
            if len(review_text.encode("utf-8")) > 12000:
                raise InvalidCell("Workshop review content exceeds its message budget")
        return SettledModelWork(prepared, _root(result.get("receipt")),
            None if proposal is None else _root(proposal), result["reconciled"], review_text)

    def publish_result(self, settled: SettledModelWork, *, recipient_root: str, reply_to_root=None):
        """Publish graph evidence; safe to retry independently of execution."""
        self._bound()
        if type(settled) is not SettledModelWork or settled.prepared.worker_root != self.worker_root:
            raise InvalidCell("Workshop result belongs to another worker")
        _root(recipient_root)
        if reply_to_root is not None:
            _root(reply_to_root)
        # The server derives all content and Work/evidence associations from
        # registered graph records. This value object is not an authority proof.
        return self.client.request("POST", "/api/universal/model-result-publish", {
            "receipt":settled.receipt_root, "proposal":settled.proposal_root,
            "recipient":recipient_root, "reply_to":reply_to_root})
