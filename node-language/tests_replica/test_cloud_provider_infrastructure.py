"""Static courts for the physical Fly/AWS cloud authority boundary.

These courts validate deployable provider configuration. They do not claim that
the resources exist, that credentials are admitted, or that recovery works.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = (
    ROOT
    / "infrastructure"
    / "aws"
    / "build_cloud_authority_template.py"
)
RENDERER_PATH = (
    ROOT
    / "infrastructure"
    / "render_fly_runtime_environment.py"
)
GUIDE_PATH = ROOT / "CLOUD-PROVIDER-PROVISIONING.md"


def _template() -> dict:
    return _builder().build_template(
        fly_org_slug="archhub-org",
        fly_app_name="archhub-cloud",
        environment_name="production",
        key_versions=(1,),
    )


def _builder():
    spec = importlib.util.spec_from_file_location(
        "archhub_build_cloud_authority_template",
        BUILDER_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _renderer():
    spec = importlib.util.spec_from_file_location(
        "archhub_render_fly_runtime_environment",
        RENDERER_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _runtime_role(template: dict) -> dict:
    return template["Resources"]["ArchHubRuntimeRole"]["Properties"]


def test_template_restricts_fly_oidc_to_one_org_app_and_audience():
    template = _template()
    assert "Parameters" not in template
    assert template["Metadata"]["ArchHub"] == {
        "authority": "physical-capability-only",
        "environment": "production",
        "fly_app": "archhub-cloud",
        "fly_org": "archhub-org",
        "key_versions": [1],
    }

    provider = template["Resources"]["FlyOidcProvider"]["Properties"]
    assert provider == {
        "Url": "https://oidc.fly.io/archhub-org",
        "ClientIdList": ["sts.amazonaws.com"],
        "Tags": [
            {"Key": "archhub:boundary", "Value": "cloud-authority"},
        ],
    }

    trust = _runtime_role(template)["AssumeRolePolicyDocument"]
    assert trust["Statement"] == [
        {
            "Sid": "FlyMachineWorkloadIdentity",
            "Effect": "Allow",
            "Principal": {"Federated": {"Ref": "FlyOidcProvider"}},
            "Action": "sts:AssumeRoleWithWebIdentity",
            "Condition": {
                "StringEquals": {
                    "oidc.fly.io/archhub-org:aud": "sts.amazonaws.com",
                },
                "StringLike": {
                    "oidc.fly.io/archhub-org:sub": (
                        "archhub-org:archhub-cloud:*"
                    ),
                },
            },
        }
    ]


def test_template_builder_rejects_unsafe_or_ambiguous_identity():
    module = _builder()
    valid = {
        "fly_org_slug": "archhub-org",
        "fly_app_name": "archhub-cloud",
        "environment_name": "production",
        "key_versions": (1,),
    }
    invalid = (
        ("fly_org_slug", "ArchHub"),
        ("fly_org_slug", "archhub:*"),
        ("fly_app_name", "archhub/cloud"),
        ("environment_name", "../production"),
        ("key_versions", ()),
        ("key_versions", (0,)),
        ("key_versions", (1, 1)),
        ("key_versions", ("1",)),
    )
    for name, value in invalid:
        candidate = dict(valid)
        candidate[name] = value
        try:
            module.build_template(**candidate)
        except module.InfrastructureContractError:
            pass
        else:
            raise AssertionError(f"unsafe template input was admitted: {name}")


def test_manual_rotation_adds_new_keys_without_discarding_old_versions():
    template = _builder().build_template(
        fly_org_slug="archhub-org",
        fly_app_name="archhub-cloud",
        environment_name="production",
        key_versions=(2, 1),
    )
    assert template["Metadata"]["ArchHub"]["key_versions"] == [1, 2]
    for logical_id in (
        "RelationshipAuthorityKeyV1",
        "RelationshipAuthorityKeyV2",
        "CourtAttestationKeyV1",
        "CourtAttestationKeyV2",
        "UniversalCloudDpopNonceKeyV1",
        "UniversalCloudDpopNonceKeyV2",
    ):
        resource = template["Resources"][logical_id]
        assert resource["DeletionPolicy"] == "Retain"
        assert resource["UpdateReplacePolicy"] == "Retain"
    key_statements = _runtime_role(template)["Policies"][0][
        "PolicyDocument"
    ]["Statement"][:2]
    assert key_statements[0]["Action"] == ["kms:GenerateMac"]
    assert key_statements[0]["Resource"] == [
        {"Fn::GetAtt": ["RelationshipAuthorityKeyV2", "Arn"]},
        {"Fn::GetAtt": ["CourtAttestationKeyV2", "Arn"]},
        {"Fn::GetAtt": ["UniversalCloudDpopNonceKeyV2", "Arn"]},
    ]
    assert key_statements[1]["Action"] == ["kms:VerifyMac"]
    assert key_statements[1]["Resource"] == [
        {"Fn::GetAtt": ["RelationshipAuthorityKeyV1", "Arn"]},
        {"Fn::GetAtt": ["CourtAttestationKeyV1", "Arn"]},
        {"Fn::GetAtt": ["UniversalCloudDpopNonceKeyV1", "Arn"]},
        {"Fn::GetAtt": ["RelationshipAuthorityKeyV2", "Arn"]},
        {"Fn::GetAtt": ["CourtAttestationKeyV2", "Arn"]},
        {"Fn::GetAtt": ["UniversalCloudDpopNonceKeyV2", "Arn"]},
    ]


def test_committed_key_versions_are_reviewed_and_cli_loaded(tmp_path):
    module = _builder()
    versions = module.load_key_versions()
    assert versions == (1,)
    assert module.build_template(
        fly_org_slug="archhub-org",
        fly_app_name="archhub-cloud",
        environment_name="production",
        key_versions=versions,
    )["Metadata"]["ArchHub"]["key_versions"] == [1]

    malformed = tmp_path / "invalid-key-versions.json"
    malformed.write_text(
        json.dumps(
            {
                "schema": "archhub.aws-hmac-key-versions.v1",
                "versions": [2, 2],
            }
        ),
        encoding="utf-8",
    )
    try:
        module.load_key_versions(malformed)
    except module.InfrastructureContractError:
        pass
    else:
        raise AssertionError("ambiguous key version manifest was admitted")


def test_runtime_role_has_only_exact_kms_and_witness_permissions():
    template = _template()
    policies = _runtime_role(template)["Policies"]
    assert len(policies) == 1
    statements = policies[0]["PolicyDocument"]["Statement"]
    assert statements == [
        {
            "Sid": "GenerateCurrentArchHubHmacs",
            "Effect": "Allow",
            "Action": ["kms:GenerateMac"],
            "Resource": [
                {"Fn::GetAtt": ["RelationshipAuthorityKeyV1", "Arn"]},
                {"Fn::GetAtt": ["CourtAttestationKeyV1", "Arn"]},
                {"Fn::GetAtt": ["UniversalCloudDpopNonceKeyV1", "Arn"]},
            ],
            "Condition": {
                "StringEquals": {
                    "kms:MacAlgorithm": "HMAC_SHA_256",
                }
            },
        },
        {
            "Sid": "VerifyRetainedArchHubHmacs",
            "Effect": "Allow",
            "Action": ["kms:VerifyMac"],
            "Resource": [
                {"Fn::GetAtt": ["RelationshipAuthorityKeyV1", "Arn"]},
                {"Fn::GetAtt": ["CourtAttestationKeyV1", "Arn"]},
                {"Fn::GetAtt": ["UniversalCloudDpopNonceKeyV1", "Arn"]},
            ],
            "Condition": {
                "StringEquals": {
                    "kms:MacAlgorithm": "HMAC_SHA_256",
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
                "Fn::GetAtt": ["RevisionWitnessTable", "Arn"],
            },
        },
    ]
    rendered = json.dumps(policies, sort_keys=True)
    assert '"Action": "*"' not in rendered
    assert '"Resource": "*"' not in rendered
    assert "kms:Create" not in rendered
    assert "kms:ScheduleKeyDeletion" not in rendered
    assert "dynamodb:Delete" not in rendered
    assert "dynamodb:Scan" not in rendered


def test_hmac_keys_are_nonexporting_retained_and_manually_versioned():
    template = _template()
    for logical_id in (
        "RelationshipAuthorityKeyV1",
        "CourtAttestationKeyV1",
        "UniversalCloudDpopNonceKeyV1",
    ):
        resource = template["Resources"][logical_id]
        assert resource["Type"] == "AWS::KMS::Key"
        assert resource["DeletionPolicy"] == "Retain"
        assert resource["UpdateReplacePolicy"] == "Retain"
        properties = resource["Properties"]
        assert properties["KeySpec"] == "HMAC_256"
        assert properties["KeyUsage"] == "GENERATE_VERIFY_MAC"
        assert properties["MultiRegion"] is False
        assert properties["PendingWindowInDays"] == 30
        assert "EnableKeyRotation" not in properties
        key_policy = properties["KeyPolicy"]
        assert key_policy["Statement"] == [
            {
                "Sid": "EnableAccountPolicyAdministration",
                "Effect": "Allow",
                "Principal": {
                    "AWS": {
                        "Fn::Sub": "arn:${AWS::Partition}:iam::${AWS::AccountId}:root"
                    }
                },
                "Action": "kms:*",
                "Resource": "*",
            }
        ]


def test_witness_table_is_minimal_protected_and_recoverable():
    resource = _template()["Resources"]["RevisionWitnessTable"]
    assert resource["Type"] == "AWS::DynamoDB::Table"
    assert resource["DeletionPolicy"] == "Retain"
    assert resource["UpdateReplacePolicy"] == "Retain"
    properties = resource["Properties"]
    assert properties["BillingMode"] == "PAY_PER_REQUEST"
    assert properties["DeletionProtectionEnabled"] is True
    assert properties["PointInTimeRecoverySpecification"] == {
        "PointInTimeRecoveryEnabled": True,
    }
    assert properties["SSESpecification"] == {"SSEEnabled": True}
    assert properties["AttributeDefinitions"] == [
        {"AttributeName": "authority_id", "AttributeType": "S"}
    ]
    assert properties["KeySchema"] == [
        {"AttributeName": "authority_id", "KeyType": "HASH"}
    ]
    assert "StreamSpecification" not in properties
    assert "GlobalSecondaryIndexes" not in properties
    assert "LocalSecondaryIndexes" not in properties
    assert "TimeToLiveSpecification" not in properties


def test_template_outputs_only_nonsecret_runtime_capabilities():
    template = _template()
    outputs = template["Outputs"]
    assert set(outputs) == {
        "AwsRegion",
        "CourtAttestationKeyArnV1",
        "RelationshipAuthorityKeyArnV1",
        "UniversalCloudDpopNonceKeyArnV1",
        "RevisionWitnessTableName",
        "RuntimeRoleArn",
    }
    rendered = json.dumps(outputs, sort_keys=True).lower()
    for denied in (
        "access_key",
        "credential",
        "database_url",
        "dsn",
        "password",
        "private",
        "secret",
        "token",
    ):
        assert denied not in rendered
    resource_types = {
        resource["Type"]
        for resource in template["Resources"].values()
    }
    assert not any("RDS" in resource_type for resource_type in resource_types)
    assert not any("S3" in resource_type for resource_type in resource_types)


def test_renderer_builds_only_nonsecret_fly_environment_from_exact_outputs():
    module = _renderer()
    outputs = {
        "AwsRegion": "me-central-1",
        "CourtAttestationKeyArnV1": (
            "arn:aws:kms:me-central-1:111122223333:"
            "key/22222222-2222-2222-2222-222222222222"
        ),
        "RelationshipAuthorityKeyArnV1": (
            "arn:aws:kms:me-central-1:111122223333:"
            "key/11111111-1111-1111-1111-111111111111"
        ),
        "UniversalCloudDpopNonceKeyArnV1": (
            "arn:aws:kms:me-central-1:111122223333:"
            "key/33333333-3333-3333-3333-333333333333"
        ),
        "RevisionWitnessTableName": "archhub-production-witness",
        "RuntimeRoleArn": (
            "arn:aws:iam::111122223333:role/archhub-production-runtime"
        ),
    }
    environment = module.render_environment(
        outputs,
        authority_id="archhub-production",
    )

    assert environment == {
        "ARCHHUB_AWS_KMS_HMAC_KEYS": json.dumps(
            {
                "archhub.local.court-attestation": {
                    "1": outputs["CourtAttestationKeyArnV1"],
                },
                "archhub.local.relationship-authority": {
                    "1": outputs["RelationshipAuthorityKeyArnV1"],
                },
                "archhub.local.universal-cloud-dpop-nonce": {
                    "1": outputs["UniversalCloudDpopNonceKeyArnV1"],
                },
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
        "ARCHHUB_AWS_REGION": "me-central-1",
        "ARCHHUB_DYNAMODB_REVISION_WITNESS_TABLE": (
            "archhub-production-witness"
        ),
        "ARCHHUB_UNIVERSAL_POSTGRES_AUTHORITY_ID": (
            "archhub-production"
        ),
        "AWS_REGION": "me-central-1",
        "AWS_ROLE_ARN": outputs["RuntimeRoleArn"],
    }
    assert "ARCHHUB_UNIVERSAL_POSTGRES_DSN" not in environment
    assert "AWS_ACCESS_KEY_ID" not in environment
    assert "AWS_SECRET_ACCESS_KEY" not in environment


def test_renderer_rejects_partial_extra_or_secret_bearing_outputs():
    module = _renderer()
    valid = {
        "AwsRegion": "me-central-1",
        "CourtAttestationKeyArnV1": (
            "arn:aws:kms:me-central-1:111122223333:"
            "key/22222222-2222-2222-2222-222222222222"
        ),
        "RelationshipAuthorityKeyArnV1": (
            "arn:aws:kms:me-central-1:111122223333:"
            "key/11111111-1111-1111-1111-111111111111"
        ),
        "UniversalCloudDpopNonceKeyArnV1": (
            "arn:aws:kms:me-central-1:111122223333:"
            "key/33333333-3333-3333-3333-333333333333"
        ),
        "RevisionWitnessTableName": "archhub-production-witness",
        "RuntimeRoleArn": (
            "arn:aws:iam::111122223333:role/archhub-production-runtime"
        ),
    }
    for name in tuple(valid):
        candidate = dict(valid)
        del candidate[name]
        try:
            module.render_environment(
                candidate,
                authority_id="archhub-production",
            )
        except module.ProvisioningContractError:
            pass
        else:
            raise AssertionError(f"missing output was admitted: {name}")

    candidate = dict(valid)
    candidate["DatabaseUrl"] = "postgresql://fixture.invalid/archhub"
    try:
        module.render_environment(
            candidate,
            authority_id="archhub-production",
        )
    except module.ProvisioningContractError:
        pass
    else:
        raise AssertionError("extra secret-bearing output was admitted")

    candidate = dict(valid)
    candidate["UniversalCloudDpopNonceKeyArnV1"] = (
        candidate["CourtAttestationKeyArnV1"]
    )
    try:
        module.render_environment(
            candidate,
            authority_id="archhub-production",
        )
    except module.ProvisioningContractError:
        pass
    else:
        raise AssertionError("one KMS key was reused across logical authorities")


def test_renderer_extracts_exact_single_stack_outputs_and_rejects_ambiguity():
    module = _renderer()
    document = {
        "Stacks": [
            {
                "Outputs": [
                    {"OutputKey": "AwsRegion", "OutputValue": "me-central-1"},
                    {
                        "OutputKey": "RuntimeRoleArn",
                        "OutputValue": (
                            "arn:aws:iam::111122223333:"
                            "role/archhub-runtime"
                        ),
                    },
                ]
            }
        ]
    }
    assert module.stack_outputs(document) == {
        "AwsRegion": "me-central-1",
        "RuntimeRoleArn": (
            "arn:aws:iam::111122223333:role/archhub-runtime"
        ),
    }

    invalid_documents = (
        {},
        {"Stacks": []},
        {"Stacks": [{}, {}]},
        {
            "Stacks": [
                {
                    "Outputs": [
                        {"OutputKey": "A", "OutputValue": "1"},
                        {"OutputKey": "A", "OutputValue": "2"},
                    ]
                }
            ]
        },
    )
    for invalid in invalid_documents:
        try:
            module.stack_outputs(invalid)
        except module.ProvisioningContractError:
            pass
        else:
            raise AssertionError("ambiguous stack output was admitted")


def test_guide_answers_the_operating_questions_and_denies_false_activation():
    text = GUIDE_PATH.read_text(encoding="utf-8")
    for heading in (
        "## What",
        "## Why",
        "## How",
        "## Who",
        "## When",
        "## Where",
        "## Example",
        "## Evidence",
        "## Recovery",
        "## Cost Boundary",
        "## Activation Gate",
    ):
        assert heading in text
    assert "does not create cloud resources" in text
    assert "not deployed proof" in text
    assert "ARCHHUB_UNIVERSAL_POSTGRES_DSN" in text
    assert "never enters Git" in text
    assert "real restore drill" in text
    assert "HMAC keys require manual rotation" in text
