"""Render the exact AWS physical-capability boundary for ArchHub.

CloudFormation cannot substitute intrinsic functions into policy-map keys.
This generator therefore validates the Fly organization and application names,
then emits literal OIDC claim keys in a conventional CloudFormation template.
It creates no semantic store and handles no credentials.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Iterable


_FLY_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_ENVIRONMENT = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$"
)
DEFAULT_VERSION_MANIFEST = (
    Path(__file__).resolve().with_name("hmac-key-versions.json")
)


class InfrastructureContractError(ValueError):
    """A generated provider boundary would be ambiguous or over-broad."""


def _validated_name(value: str, *, label: str, pattern: re.Pattern) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise InfrastructureContractError(f"{label} is invalid")
    return value


def _validated_versions(key_versions: Iterable[int]) -> tuple[int, ...]:
    if isinstance(key_versions, (str, bytes)):
        raise InfrastructureContractError("key versions are invalid")
    try:
        values = tuple(key_versions)
    except TypeError:
        raise InfrastructureContractError("key versions are invalid") from None
    if (
        not values
        or any(type(value) is not int or not 1 <= value <= 9999 for value in values)
        or len(set(values)) != len(values)
    ):
        raise InfrastructureContractError("key versions are invalid")
    return tuple(sorted(values))


def load_key_versions(path: Path = DEFAULT_VERSION_MANIFEST) -> tuple[int, ...]:
    """Read the reviewed additive HMAC version set used by the deploy CLI."""
    if not isinstance(path, Path):
        raise InfrastructureContractError("key version manifest is invalid")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise InfrastructureContractError(
            "key version manifest is invalid"
        ) from None
    if (
        not isinstance(document, dict)
        or set(document) != {"schema", "versions"}
        or document["schema"] != "archhub.aws-hmac-key-versions.v1"
    ):
        raise InfrastructureContractError(
            "key version manifest is invalid"
        )
    return _validated_versions(document["versions"])


def _key_policy() -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "EnableAccountPolicyAdministration",
                "Effect": "Allow",
                "Principal": {
                    "AWS": {
                        "Fn::Sub": (
                            "arn:${AWS::Partition}:iam::"
                            "${AWS::AccountId}:root"
                        )
                    }
                },
                "Action": "kms:*",
                "Resource": "*",
            }
        ],
    }


def _hmac_key(
    *,
    purpose: str,
    environment_name: str,
    version: int,
) -> dict:
    return {
        "Type": "AWS::KMS::Key",
        "DeletionPolicy": "Retain",
        "UpdateReplacePolicy": "Retain",
        "Properties": {
            "Description": (
                f"ArchHub {environment_name} {purpose} HMAC key v{version}"
            ),
            "KeyPolicy": _key_policy(),
            "KeySpec": "HMAC_256",
            "KeyUsage": "GENERATE_VERIFY_MAC",
            "MultiRegion": False,
            "PendingWindowInDays": 30,
            "Tags": [
                {"Key": "archhub:boundary", "Value": "cloud-authority"},
                {"Key": "archhub:environment", "Value": environment_name},
                {"Key": "archhub:key-version", "Value": str(version)},
                {"Key": "archhub:purpose", "Value": purpose},
            ],
        },
    }


def _alias(
    *,
    target: str,
    purpose: str,
    environment_name: str,
    version: int,
) -> dict:
    return {
        "Type": "AWS::KMS::Alias",
        "Properties": {
            "AliasName": (
                f"alias/archhub/{environment_name}/{purpose}/v{version}"
            ),
            "TargetKeyId": {"Ref": target},
        },
    }


def build_template(
    *,
    fly_org_slug: str,
    fly_app_name: str,
    environment_name: str,
    key_versions: Iterable[int],
) -> dict:
    """Build a secret-free CloudFormation template for one runtime boundary."""
    fly_org_slug = _validated_name(
        fly_org_slug,
        label="Fly organization slug",
        pattern=_FLY_NAME,
    )
    fly_app_name = _validated_name(
        fly_app_name,
        label="Fly application name",
        pattern=_FLY_NAME,
    )
    environment_name = _validated_name(
        environment_name,
        label="environment name",
        pattern=_ENVIRONMENT,
    )
    versions = _validated_versions(key_versions)
    issuer = f"oidc.fly.io/{fly_org_slug}"
    subject = f"{fly_org_slug}:{fly_app_name}:*"

    resources: dict[str, dict] = {
        "FlyOidcProvider": {
            "Type": "AWS::IAM::OIDCProvider",
            "Properties": {
                "Url": f"https://{issuer}",
                "ClientIdList": ["sts.amazonaws.com"],
                "Tags": [
                    {
                        "Key": "archhub:boundary",
                        "Value": "cloud-authority",
                    }
                ],
            },
        },
        "RevisionWitnessTable": {
            "Type": "AWS::DynamoDB::Table",
            "DeletionPolicy": "Retain",
            "UpdateReplacePolicy": "Retain",
            "Properties": {
                "AttributeDefinitions": [
                    {
                        "AttributeName": "authority_id",
                        "AttributeType": "S",
                    }
                ],
                "BillingMode": "PAY_PER_REQUEST",
                "DeletionProtectionEnabled": True,
                "KeySchema": [
                    {
                        "AttributeName": "authority_id",
                        "KeyType": "HASH",
                    }
                ],
                "PointInTimeRecoverySpecification": {
                    "PointInTimeRecoveryEnabled": True,
                },
                "SSESpecification": {"SSEEnabled": True},
                "Tags": [
                    {
                        "Key": "archhub:boundary",
                        "Value": "cloud-authority",
                    },
                    {
                        "Key": "archhub:environment",
                        "Value": environment_name,
                    },
                ],
            },
        },
    }
    generate_key_arns = []
    verify_key_arns = []
    outputs: dict[str, dict] = {
        "AwsRegion": {
            "Description": "AWS region containing the physical capabilities.",
            "Value": {"Ref": "AWS::Region"},
        },
        "RevisionWitnessTableName": {
            "Description": "DynamoDB witness table name.",
            "Value": {"Ref": "RevisionWitnessTable"},
        },
    }
    for version in versions:
        relationship_key = f"RelationshipAuthorityKeyV{version}"
        court_key = f"CourtAttestationKeyV{version}"
        nonce_key = f"UniversalCloudDpopNonceKeyV{version}"
        resources[relationship_key] = _hmac_key(
            purpose="relationship-authority",
            environment_name=environment_name,
            version=version,
        )
        resources[f"RelationshipAuthorityAliasV{version}"] = _alias(
            target=relationship_key,
            purpose="relationship-authority",
            environment_name=environment_name,
            version=version,
        )
        resources[court_key] = _hmac_key(
            purpose="court-attestation",
            environment_name=environment_name,
            version=version,
        )
        resources[f"CourtAttestationAliasV{version}"] = _alias(
            target=court_key,
            purpose="court-attestation",
            environment_name=environment_name,
            version=version,
        )
        resources[nonce_key] = _hmac_key(
            purpose="universal-cloud-dpop-nonce",
            environment_name=environment_name,
            version=version,
        )
        resources[f"UniversalCloudDpopNonceAliasV{version}"] = _alias(
            target=nonce_key,
            purpose="universal-cloud-dpop-nonce",
            environment_name=environment_name,
            version=version,
        )
        relationship_arn = {
            "Fn::GetAtt": [relationship_key, "Arn"],
        }
        court_arn = {"Fn::GetAtt": [court_key, "Arn"]}
        nonce_arn = {"Fn::GetAtt": [nonce_key, "Arn"]}
        version_arns = (relationship_arn, court_arn, nonce_arn)
        verify_key_arns.extend(version_arns)
        if version == versions[-1]:
            generate_key_arns.extend(version_arns)
        outputs[f"RelationshipAuthorityKeyArnV{version}"] = {
            "Description": (
                "Relationship-authority KMS key ARN."
            ),
            "Value": relationship_arn,
        }
        outputs[f"CourtAttestationKeyArnV{version}"] = {
            "Description": "Court-attestation KMS key ARN.",
            "Value": court_arn,
        }
        outputs[f"UniversalCloudDpopNonceKeyArnV{version}"] = {
            "Description": "Universal-cloud DPoP nonce KMS key ARN.",
            "Value": nonce_arn,
        }

    resources["ArchHubRuntimeRole"] = {
        "Type": "AWS::IAM::Role",
        "Properties": {
            "AssumeRolePolicyDocument": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Sid": "FlyMachineWorkloadIdentity",
                        "Effect": "Allow",
                        "Principal": {
                            "Federated": {"Ref": "FlyOidcProvider"},
                        },
                        "Action": "sts:AssumeRoleWithWebIdentity",
                        "Condition": {
                            "StringEquals": {
                                f"{issuer}:aud": "sts.amazonaws.com",
                            },
                            "StringLike": {
                                f"{issuer}:sub": subject,
                            },
                        },
                    }
                ],
            },
            "Description": (
                "Short-lived Fly workload role for exact ArchHub "
                "KMS and revision-witness capabilities."
            ),
            "Policies": [
                {
                    "PolicyName": "archhub-runtime-physical-capabilities",
                    "PolicyDocument": {
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Sid": "GenerateCurrentArchHubHmacs",
                                "Effect": "Allow",
                                "Action": ["kms:GenerateMac"],
                                "Resource": generate_key_arns,
                                "Condition": {
                                    "StringEquals": {
                                        "kms:MacAlgorithm": (
                                            "HMAC_SHA_256"
                                        ),
                                    }
                                },
                            },
                            {
                                "Sid": "VerifyRetainedArchHubHmacs",
                                "Effect": "Allow",
                                "Action": ["kms:VerifyMac"],
                                "Resource": verify_key_arns,
                                "Condition": {
                                    "StringEquals": {
                                        "kms:MacAlgorithm": (
                                            "HMAC_SHA_256"
                                        ),
                                    }
                                },
                            },
                            {
                                "Sid": "UseExactRevisionWitness",
                                "Effect": "Allow",
                                "Action": [
                                    "dynamodb:GetItem",
                                    "dynamodb:PutItem",
                                    "dynamodb:UpdateItem",
                                ],
                                "Resource": {
                                    "Fn::GetAtt": [
                                        "RevisionWitnessTable",
                                        "Arn",
                                    ]
                                },
                            },
                        ],
                    },
                }
            ],
            "Tags": [
                {"Key": "archhub:boundary", "Value": "cloud-authority"},
                {"Key": "archhub:environment", "Value": environment_name},
            ],
        },
    }
    outputs["RuntimeRoleArn"] = {
        "Description": "Fly workload role ARN.",
        "Value": {"Fn::GetAtt": ["ArchHubRuntimeRole", "Arn"]},
    }

    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": (
            "ArchHub physical KMS and rollback-witness boundary; "
            "not semantic authority."
        ),
        "Metadata": {
            "ArchHub": {
                "authority": "physical-capability-only",
                "environment": environment_name,
                "fly_app": fly_app_name,
                "fly_org": fly_org_slug,
                "key_versions": list(versions),
            }
        },
        "Resources": resources,
        "Outputs": outputs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the ArchHub AWS physical-capability template.",
    )
    parser.add_argument("--fly-org", required=True)
    parser.add_argument("--fly-app", required=True)
    parser.add_argument("--environment", default="production")
    parser.add_argument(
        "--key-version-manifest",
        type=Path,
        default=DEFAULT_VERSION_MANIFEST,
    )
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    template = build_template(
        fly_org_slug=arguments.fly_org,
        fly_app_name=arguments.fly_app,
        environment_name=arguments.environment,
        key_versions=load_key_versions(arguments.key_version_manifest),
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(template, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(arguments.output)


if __name__ == "__main__":
    main()
