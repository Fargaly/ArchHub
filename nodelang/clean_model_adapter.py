"""Explicit physical adapter for a graph-authorized free model review.

The runtime supplies its broker. This module creates no graph, agent session,
credential store or execution grant. Publishing the operation remains a separate
signed catalogue operation; importing this record does not publish it.
"""
from typing import Mapping
from copy import deepcopy
from .clean_host_execution import HostInvocationFailure
from .universal_cell import InvalidCell


MODEL_REVIEW_OPERATION = {
    "op_id": "model.review", "host": "model", "kind": "read",
    "label": "Free model review",
    "description": "Request a bounded proposal for public text from a free OpenRouter model.",
    "output_type": "map", "destructive": False,
    "inputs": [
        {"id":"task", "label":"Task", "type":"text", "required":True,
         "default":"", "help":"Public text to review; no private data or credentials."},
        {"id":"model", "label":"Model", "type":"text", "required":True,
         "default":"openrouter/free", "help":"OpenRouter free router or an explicit free model."},
        {"id":"data_class", "label":"Data class", "type":"text", "required":True,
         "default":"public-text", "help":"This remote adapter accepts public-text only."},
    ],
}


def prepare_model_review_catalogue(current):
    """Prepare an additive catalogue update; do not publish or overwrite a route."""
    from .clean_host_operations import compose_host_operations
    if current is None:
        return compose_host_operations([deepcopy(MODEL_REVIEW_OPERATION)])
    if (type(current) is not dict or type(current.get("operations")) is not list or
            type(current.get("hosts")) is not list or
            any(type(host) is not str for host in current["hosts"]) or
            any(type(operation) is not dict for operation in current["operations"])):
        raise InvalidCell("existing host catalogue is invalid")
    prepared = deepcopy(current)
    matches = [operation for operation in prepared["operations"]
               if operation.get("op_id") == MODEL_REVIEW_OPERATION["op_id"]]
    if matches:
        if len(matches) != 1 or matches[0] != MODEL_REVIEW_OPERATION:
            raise InvalidCell("model.review already has a different declaration; reconcile it explicitly")
        return prepared
    prepared["operations"].append(deepcopy(MODEL_REVIEW_OPERATION))
    if "model" not in prepared["hosts"]:
        prepared["hosts"].append("model")
    return prepared


class CleanModelAdapter:
    def __init__(self, broker):
        self._broker = broker

    def __call__(self, op_id: str, arguments: Mapping[str, object]):
        if op_id != MODEL_REVIEW_OPERATION["op_id"]:
            raise InvalidCell("model adapter operation is not admitted")
        if set(arguments) != {"task", "model", "data_class"}:
            raise InvalidCell("model review arguments do not match its declaration")
        if arguments["data_class"] != "public-text":
            raise InvalidCell("remote Workshop model review requires public-text")
        for name, maximum in (("task", 64 * 1024), ("model", 160)):
            value = arguments[name]
            if type(value) is not str or not value.strip() or len(value.encode("utf-8")) > maximum:
                raise InvalidCell("model review %s is invalid" % name)
        result = self._broker.execute(provider="openrouter", location="network:openrouter",
            model=arguments["model"], task=arguments["task"], data_class="public-text",
            free_only=True, reasoning_effort="none")
        if result.outcome != "succeeded" or result.proposal_payload is None:
            # The host execution path persists this as a failed attempt, not
            # as an apparently successful response containing an error field.
            raise HostInvocationFailure(result.error_code, result.output_digest, result.output_bytes)
        return {"result": result.proposal_payload, "output_digest": result.output_digest,
                "output_bytes": result.output_bytes, "requested_model": arguments["model"]}
