# Cloud Provider Provisioning

Status: WIP physical-capability contract; not deployed proof

This guide explains the provider boundary supporting the one Universal Cell
authority. The committed source does not create cloud resources by itself.
Applying the stack creates chargeable AWS resources and requires an authorised
human or release service.

## What

The boundary has four physical parts:

1. one Fly OpenID Connect provider in AWS;
2. one short-lived AWS role restricted to one Fly organization and app;
3. versioned AWS KMS HMAC keys for the three existing physical signing
   authorities; and
4. one protected DynamoDB table that witnesses the PostgreSQL revision chain.

The PostgreSQL Cell journal remains the only semantic authority. KMS stores key
bytes that ordinary Cells cannot export. DynamoDB stores one physical witness
item per authority. Neither AWS service becomes a product graph, Brain, queue,
status database, or copied control plane.

At the micro level:

| Part | Input | Output | Forbidden meaning |
|---|---|---|---|
| OIDC trust | Fly issuer, `aud`, `sub` | short-lived role session | user or graph identity |
| HMAC key | bounded digest, exact key ARN | relationship, court, or DPoP nonce MAC result | semantic rule or release decision |
| witness table | authority id, revision, digest, token | conditional physical head | second CellStore |
| PostgreSQL | exact Cell revision transaction | durable graph snapshot | disposable cache |

## Why

The founder machine must not be the only place where ArchHub can continue.
Code, graph state, signing custody, rollback evidence, backups, and runners need
durable remote custody with replaceable devices and agents.

PostgreSQL alone can preserve transactions and recovery history, but a database
operator with snapshot control could still present an older valid database.
The DynamoDB witness places the confirmed revision digest in a separate failure
and custody boundary. KMS prevents application code from exporting HMAC key
bytes. Fly OIDC removes long-lived AWS access keys from Fly secrets and images.

This is physical defence in depth. It does not change the Universal Cell shape,
root identities, protocols, lifecycle, governance, or release rules.

## How

The runtime sequence is:

```text
Fly Machine
  -> requests a 15-minute OIDC token for sts.amazonaws.com
  -> assumes the one app-scoped AWS role
  -> opens the private Managed Postgres capability
  -> reads the strongly consistent DynamoDB witness
  -> admits only the exact witnessed PostgreSQL head
  -> uses exact KMS key ARNs for GenerateMac and VerifyMac
  -> serves authorised lenses over the same graph
```

`infrastructure/aws/build_cloud_authority_template.py` validates the Fly
organization, app, environment, and retained key versions before rendering a
CloudFormation template. Literal `aud` and `sub` condition keys are generated
because CloudFormation cannot safely parameterize policy-map keys.

`infrastructure/render_fly_runtime_environment.py` accepts exactly one
CloudFormation output set and emits only:

- the AWS role and region;
- the DynamoDB witness table name;
- the three versioned KMS key maps; and
- the stable PostgreSQL authority id.

It deliberately omits `ARCHHUB_UNIVERSAL_POSTGRES_DSN`. The DSN is attached
through Fly Managed Postgres custody and never enters Git, stack output, command
history, a Cell atom, or this renderer.

## Who

| Actor | Allowed responsibility | Not allowed |
|---|---|---|
| Founder/release authority | approve provider, budget, region, deployment and promotion | bypass courts |
| Cloud provisioner | apply the reviewed stack and return provider receipts | read graph meaning or publish a release |
| Fly Machine | assume its exact app role and use admitted capabilities | create keys, tables, roles or broader access |
| Universal runtime | reconcile PostgreSQL, witness and KMS at one revision | auto-provision missing authority |
| Agent | propose reviewed source and evidence within a lease | receive unrestricted cloud credentials |
| Recovery operator | restore into isolated resources and run reconciliation | silently replace the active head |

The CloudFormation account-root KMS statement enables account policy
administration, as required by the KMS key-policy model. Runtime access remains
limited by identity policy to `GenerateMac` on the three current key ARNs and
`VerifyMac` on retained current and historical ARNs, always with
`HMAC_SHA_256`.

## When

Provision only after all of these are true:

1. the source revision and infrastructure courts are green;
2. the actual Fly organization and app names are known;
3. AWS region, account, cost ceiling, billing alerts, and administrator are
   approved;
4. the PostgreSQL provider passes the patching, upgrade, backup, encryption,
   private-network, failover, and restore admission review;
5. no unrelated machine-priority task owns the execution slot; and
6. the apply plan contains only the expected resources.

Provisioning is not activation. Activation occurs only after provider receipts,
real KMS/DynamoDB/PostgreSQL courts, restoration, two-device continuity,
revocation, and external security acceptance pass.

## Where

| Material | Custody |
|---|---|
| Template generator and courts | T0 public source |
| Generated template and stack outputs | disposable deployment workspace |
| PostgreSQL DSN | Fly secret custody only |
| AWS HMAC bytes | AWS KMS only |
| OIDC token and STS credentials | short-lived process memory only |
| Cell journal | private managed PostgreSQL |
| revision witness | protected DynamoDB table |
| evidence receipts and revision references | Universal Cell evidence graph |

The generated template is physical infrastructure, not graph semantic
authority. The resulting ARNs and table name become capability references;
requests, grants, denials, uses, outcomes, and receipts remain Cells.

## Example

The names below are placeholders, not active account data.

Generate a reviewable template:

```powershell
python infrastructure/aws/build_cloud_authority_template.py `
  --fly-org YOUR_FLY_ORG `
  --fly-app YOUR_ARCHHUB_APP `
  --environment production `
  --output infrastructure/generated/cloud-authority.json
```

Validate and review the change set before applying:

```powershell
aws cloudformation validate-template `
  --template-body file://infrastructure/generated/cloud-authority.json

aws cloudformation deploy `
  --stack-name archhub-production-physical-authority `
  --template-file infrastructure/generated/cloud-authority.json `
  --capabilities CAPABILITY_IAM `
  --no-execute-changeset
```

The first command is syntactic validation. The second must remain a nonexecuted
change set until an authorised review confirms the account, region, resources,
policies, costs, tags, retention, and deletion protection.

After an approved apply, capture outputs and render the public capability
references:

```powershell
aws cloudformation describe-stacks `
  --stack-name archhub-production-physical-authority `
  --output json `
  > infrastructure/generated/cloud-authority-outputs.json

python infrastructure/render_fly_runtime_environment.py `
  --stack-output infrastructure/generated/cloud-authority-outputs.json `
  --authority-id archhub-production `
  --output infrastructure/generated/fly-runtime-environment.json
```

The generated Fly environment is incomplete by design until the Managed
Postgres attachment supplies `ARCHHUB_UNIVERSAL_POSTGRES_DSN`.

To add a manual HMAC rotation, add version `2` to the reviewed
`infrastructure/aws/hmac-key-versions.json` manifest without removing version
`1`, then regenerate:

```powershell
python infrastructure/aws/build_cloud_authority_template.py `
  --fly-org YOUR_FLY_ORG `
  --fly-app YOUR_ARCHHUB_APP `
  --environment production `
  --output infrastructure/generated/cloud-authority.json
```

HMAC keys require manual rotation. The source-controlled version manifest is an
additive ratchet: the old key remains retained and verify-capable while
historical evidence still references its version, but it cannot mint new MACs.
Removing a version requires a separate proof that no retained evidence,
release, backup, or recovery path needs it.

## Evidence

Static source courts prove:

- the OIDC audience is exactly `sts.amazonaws.com`;
- the subject is one Fly organization, one app, and a replaceable Machine;
- runtime KMS and DynamoDB resources are exact, not wildcards;
- KMS use is limited to `HMAC_SHA_256`;
- KMS keys and the witness table are retained;
- DynamoDB uses one hash key, on-demand billing, server-side encryption,
  deletion protection, and point-in-time recovery;
- generated outputs contain no DSN, token, password, or access key; and
- no RDS, S3, second database, or semantic store is created by this stack.

These are source courts, not provider integration evidence.
The opt-in real-provider suite separately requires
`ARCHHUB_TEST_AWS_KMS_DPOP_NONCE_KEY_ARN` and mints and verifies one bounded
resource-server nonce. A skip is an open deployment gate, not a pass.

Primary references reviewed on 2026-07-26:

- Fly OpenID Connect, token claims and AWS trust:
  https://fly.io/docs/security/openid-connect/
- Fly Managed Postgres capabilities and stated gaps:
  https://fly.io/docs/mpg/
- Fly Managed Postgres private connection and secret attachment:
  https://fly.io/docs/mpg/create-and-connect/
- AWS IAM OIDC provider and TLS verification:
  https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_create_oidc.html
- AWS KMS HMAC behavior and rotation limitation:
  https://docs.aws.amazon.com/kms/latest/developerguide/hmac.html
- AWS KMS MAC algorithm policy condition:
  https://docs.aws.amazon.com/kms/latest/developerguide/conditions-kms.html
- AWS DynamoDB CloudFormation protection properties:
  https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-dynamodb-table.html

## Recovery

Recovery is an explicit new-head procedure:

1. freeze new Work and effects;
2. capture the PostgreSQL, witness, KMS, runtime, and release receipts;
3. restore PostgreSQL into an isolated new cluster;
4. restore DynamoDB point-in-time material into a new table when required;
5. retain every historical KMS key referenced by evidence;
6. compare the complete PostgreSQL revision chain with the confirmed witness;
7. run integrity, authorization, rollback, revocation, and application courts;
8. create a governed recovery decision and new capability references; and
9. switch traffic only after independent approval.

A backup setting or provider dashboard is not recovery proof. A real restore drill
must create isolated resources, reconstruct the exact accepted revision, and
demonstrate safe reversal before release.

## Cost Boundary

Cloud independence cannot consume zero resources. The goal is bounded,
observable, replaceable resource use:

- one active application owner, with disposable runners created per Work lease;
- one managed PostgreSQL cluster sized to measured load;
- three HMAC keys per active key version;
- one small on-demand witness table; and
- budget alerts and lease expiry before autonomous scale-up.

Fly's published Managed Postgres entry price, AWS prices, network costs, backup
retention, and regional availability can change. They must be checked in the
provider consoles immediately before an approved apply. No paid resource is
created by the current repository revision.

## Activation Gate

The boundary stays red until:

1. AWS and Fly identities are admitted without long-lived access keys;
2. the generated CloudFormation change set passes policy and cost review;
3. the real KMS round trip and DynamoDB conditional/PITR courts pass;
4. PostgreSQL fencing, backup, point-in-time restore, and failover pass;
5. one external revision witness is provisioned through an explicit genesis
   ceremony;
6. a lost-device and revoked-agent drill fails closed;
7. Device A can be turned off while Device B observes the same Work and remote
   runner evidence; and
8. the signed release and rollback pipeline passes independently.

The current Fly Managed Postgres documentation says security patches and
version upgrades are still under development. That is a production-admission
gap, not a minor note. Before using that provider for released authority,
ArchHub needs a verified provider commitment and acceptable operating control,
or it must select a managed PostgreSQL alternative through the same authority
change protocol.
