"""Render non-secret Fly runtime environment from exact AWS stack outputs."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Mapping


_AUTHORITY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_AWS_REGION = re.compile(r"^[a-z]{2}(?:-gov)?-[a-z]+-\d$")
_KMS_ARN = re.compile(
    r"^arn:(?:aws|aws-us-gov|aws-cn):kms:"
    r"([a-z]{2}(?:-gov)?-[a-z]+-\d):\d{12}:"
    r"key/[0-9a-f-]{36}$"
)
_ROLE_ARN = re.compile(
    r"^arn:(?:aws|aws-us-gov|aws-cn):iam::\d{12}:"
    r"role/[A-Za-z0-9+=,.@_/-]{1,512}$"
)
_TABLE_NAME = re.compile(r"^[A-Za-z0-9_.-]{3,255}$")
_RELATIONSHIP_OUTPUT = re.compile(
    r"^RelationshipAuthorityKeyArnV([1-9][0-9]{0,3})$"
)
_COURT_OUTPUT = re.compile(
    r"^CourtAttestationKeyArnV([1-9][0-9]{0,3})$"
)
_BASE_OUTPUTS = frozenset(
    (
        "AwsRegion",
        "RevisionWitnessTableName",
        "RuntimeRoleArn",
    )
)


class ProvisioningContractError(ValueError):
    """Provider outputs are incomplete, ambiguous, or secret-bearing."""


def _key_versions(outputs: Mapping[str, str], pattern: re.Pattern) -> dict:
    versions = {}
    for name, value in outputs.items():
        match = pattern.fullmatch(name)
        if match is None:
            continue
        version = int(match.group(1))
        if version in versions:
            raise ProvisioningContractError("KMS key version is ambiguous")
        versions[version] = value
    if not versions:
        raise ProvisioningContractError("KMS key outputs are incomplete")
    return versions


def render_environment(
    outputs: Mapping[str, str],
    *,
    authority_id: str,
) -> dict[str, str]:
    """Return only the non-secret environment required beside the MPG DSN."""
    if not isinstance(outputs, Mapping):
        raise ProvisioningContractError("stack outputs are invalid")
    normalized = dict(outputs)
    if (
        any(not isinstance(key, str) for key in normalized)
        or any(not isinstance(value, str) for value in normalized.values())
        or not isinstance(authority_id, str)
        or _AUTHORITY_ID.fullmatch(authority_id) is None
    ):
        raise ProvisioningContractError("stack outputs are invalid")

    relationship = _key_versions(normalized, _RELATIONSHIP_OUTPUT)
    court = _key_versions(normalized, _COURT_OUTPUT)
    if set(relationship) != set(court):
        raise ProvisioningContractError("KMS key versions do not match")
    expected = set(_BASE_OUTPUTS)
    expected.update(
        f"RelationshipAuthorityKeyArnV{version}"
        for version in relationship
    )
    expected.update(
        f"CourtAttestationKeyArnV{version}"
        for version in court
    )
    if set(normalized) != expected:
        raise ProvisioningContractError("stack outputs are not exact")

    region = normalized["AwsRegion"]
    role = normalized["RuntimeRoleArn"]
    table = normalized["RevisionWitnessTableName"]
    if (
        _AWS_REGION.fullmatch(region) is None
        or _ROLE_ARN.fullmatch(role) is None
        or _TABLE_NAME.fullmatch(table) is None
    ):
        raise ProvisioningContractError("stack output identity is invalid")
    for key_arn in (*relationship.values(), *court.values()):
        match = _KMS_ARN.fullmatch(key_arn)
        if match is None or match.group(1) != region:
            raise ProvisioningContractError("KMS key output is invalid")

    key_map = {
        "archhub.local.court-attestation": {
            str(version): court[version] for version in sorted(court)
        },
        "archhub.local.relationship-authority": {
            str(version): relationship[version]
            for version in sorted(relationship)
        },
    }
    return {
        "ARCHHUB_AWS_KMS_HMAC_KEYS": json.dumps(
            key_map,
            separators=(",", ":"),
            sort_keys=True,
        ),
        "ARCHHUB_AWS_REGION": region,
        "ARCHHUB_DYNAMODB_REVISION_WITNESS_TABLE": table,
        "ARCHHUB_UNIVERSAL_POSTGRES_AUTHORITY_ID": authority_id,
        "AWS_REGION": region,
        "AWS_ROLE_ARN": role,
    }


def stack_outputs(document: Mapping) -> dict[str, str]:
    """Extract exactly one CloudFormation describe-stacks output set."""
    try:
        stacks = document["Stacks"]
        if not isinstance(stacks, list) or len(stacks) != 1:
            raise TypeError
        items = stacks[0]["Outputs"]
        if not isinstance(items, list):
            raise TypeError
        outputs = {}
        for item in items:
            name = item["OutputKey"]
            value = item["OutputValue"]
            if (
                not isinstance(name, str)
                or not isinstance(value, str)
                or name in outputs
            ):
                raise TypeError
            outputs[name] = value
    except (KeyError, TypeError):
        raise ProvisioningContractError(
            "CloudFormation output document is invalid"
        ) from None
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render secret-free ArchHub Fly runtime environment.",
    )
    parser.add_argument("--stack-output", required=True, type=Path)
    parser.add_argument("--authority-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    document = json.loads(
        arguments.stack_output.read_text(encoding="utf-8")
    )
    environment = render_environment(
        stack_outputs(document),
        authority_id=arguments.authority_id,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(environment, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(arguments.output)


if __name__ == "__main__":
    main()
