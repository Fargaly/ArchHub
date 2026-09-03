# Universal Cell Cloud Runtime Packaging

Date: 2026-07-26
Status: WIP packaging authority; source complete, not deployed evidence

## What

This package turns the existing remote Universal Cell authority into one
container process:

```text
Fly Machine
  -> nodelang.cloud_application_entrypoint
  -> create_cloud_application_server
  -> one CellStore
  -> witnessed PostgreSQL journal
  -> AWS KMS signing authorities
  -> DynamoDB external revision witness
```

The container contains the Node Language source and the public runtime map. It
does not contain Brain data, Grand Map private data, credentials, client data, a
second graph, or a legacy application launcher.

## Why

`create_cloud_application_server` already constructs the physical authority but
does not own process signals, startup failure, or container custody. Those are
required before the same authority can run away from the founder workstation.

The package keeps the physical boundary narrow:

| Part | Input | Output | Authority |
|---|---|---|---|
| Container | pinned image and hashed wheels | one Python process | none |
| Entrypoint | admitted environment capabilities | one running server | none |
| Runtime fence | canonical Cells and revision | one accepted owner or denial | graph |
| PostgreSQL | Cell revisions | durable journal | physical custody only |
| AWS KMS | MAC request | MAC result | key bytes never leave KMS |
| DynamoDB | revision digest | external witness | physical witness only |

## How

### Build

The Dockerfile pins `python:3.14.6-slim-bookworm` to an exact multi-platform
digest. Dependencies are resolved for CPython 3.14 on Linux x86-64 and every
installed distribution is exact-version and SHA-256 locked. The image copies
only `nodelang` and the lock file, then runs as UID/GID `10001:10001`.

Regenerate the reviewed lock after changing `requirements.txt`:

```powershell
uv pip compile requirements.txt `
  --python-version 3.14 `
  --python-platform x86_64-manylinux_2_17 `
  --generate-hashes `
  --output-file packaging/cloud/requirements.lock
```

Render a provider config into an ignored/generated location:

```powershell
python infrastructure/render_fly_application_config.py `
  --app <reviewed-fly-app> `
  --primary-region <reviewed-three-letter-region> `
  --output infrastructure/generated/fly.toml
```

The renderer admits identity and placement only. It has no argument for a DSN,
KMS map, AWS token, Fly token, or other secret.

### Start and stop

The container starts only:

```text
python -m nodelang.cloud_application_entrypoint
```

The entrypoint validates all physical capabilities before listening, explicitly
uses `nodelang/data/public_runtime_map.json`, and starts the existing fenced
Universal Application server. `SIGTERM` and `SIGINT` request one orderly drain.
The server releases runtime ownership, flushes the journal, closes capabilities,
and exits. Failure logs contain a fixed event only, never exception content.

### Health and ownership

The Fly TCP check proves process liveness only. It does not prove graph
integrity, security, visual acceptance, data recovery, or release eligibility.
Those require the revision-bound courts and provider acceptance listed below.

Fly configuration does not impose a maximum Machine count. Therefore:

1. deployment inventory MUST prove exactly one Machine before activation;
2. automatic stop and start are disabled in the rendered config;
3. the runtime ownership fence remains the actual authority and denies any
   second process even if a provider or operator creates one accidentally.

No HTTP health shell is added because an unauthorised status route would be a
second semantic report. A future semantic readiness lens must be graph-defined,
audience-authorised, revision-bound, and separately courted.

## Who

| Actor | Responsibility |
|---|---|
| Founder | approves provider accounts, cost, region, and production promotion |
| Release agent | renders config, verifies source revision, runs courts, deploys |
| Fly | runs the admitted container and terminates edge TLS |
| Fly Managed Postgres | holds the physical Cell journal |
| AWS KMS | holds HMAC key bytes and performs MAC operations |
| DynamoDB | holds the independent revision witness |
| Universal Cell runtime | remains the sole semantic authority |

An agent cannot approve its own provider admission or transform a green static
court into deployed proof.

## When

Use this package only after:

1. the exact source revision is committed and remotely retrievable;
2. provider resources match `CLOUD-PROVIDER-PROVISIONING.md`;
3. Fly OIDC trust binds the exact organisation and app;
4. Fly Managed Postgres patch and upgrade operations are accepted or replaced
   by a provider whose operating contract satisfies the release court;
5. secrets exist only in provider custody;
6. exactly one Machine is proven before activation.

Changing the base digest, lock, app, region, role, key version, table, database,
or graph protocol creates a new WIP revision and reruns the relevant courts.

## Where

| Artifact | Custody |
|---|---|
| `packaging/cloud/Dockerfile` | T0 public source |
| `packaging/cloud/requirements.lock` | T0 public source |
| `infrastructure/render_fly_application_config.py` | T0 public source |
| rendered `infrastructure/generated/fly.toml` | local generated evidence |
| DSN and provider credentials | Fly secret custody, never Git |
| AWS workload credentials | short-lived Fly OIDC exchange, never Git |
| Cell journal | Fly Managed Postgres |
| HMAC keys | AWS KMS |
| external revision digest | DynamoDB |

## Example

A correct activation sequence is:

```text
accepted source revision
  -> exact package courts
  -> provider inventory and policy courts
  -> render secret-free Fly config
  -> set DSN in Fly secret custody
  -> deploy one Machine with --ha=false
  -> prove one Machine inventory
  -> prove fenced runtime ownership
  -> write/read/restart/recovery courts
  -> browser, security, accessibility and performance courts
  -> release decision
```

An HTTP 200, open TCP socket, successful image build, or green unit suite is not
the final step and MUST NOT be labelled as release.

## Evidence

Current primary references:

- Fly application lifecycle, signals, services, and checks:
  https://fly.io/docs/reference/configuration/
- Fly Machine stop/start semantics:
  https://fly.io/docs/launch/autostop-autostart/
- Docker digest pinning and non-root guidance:
  https://docs.docker.com/build/building/best-practices/
- Dockerfile `FROM`, `ARG`, `USER`, and `WORKDIR`:
  https://docs.docker.com/reference/dockerfile
- uv exact dependency compilation:
  https://docs.astral.sh/uv/pip/compile/
- pip hash-checking mode:
  https://pip.pypa.io/en/stable/topics/secure-installs/
- Provider contracts and recovery evidence:
  `CLOUD-PROVIDER-PROVISIONING.md`

The base digest was resolved from the official Docker Hub `library/python`
`3.14.6-slim-bookworm` tag on 2026-07-26. A later update requires a reviewed
source change; floating tags are not accepted.

## Recovery

Before production promotion, perform and record:

1. stop the admitted Machine through the provider;
2. verify the runtime enters drain and releases ownership;
3. start one replacement from the exact image digest;
4. restore the exact PostgreSQL snapshot/PITR target;
5. compare the journal head with the DynamoDB witness;
6. verify retained evidence with the matching retained KMS key version;
7. prove stale, rolled-back, foreign-authority, or second-owner state fails
   closed;
8. rerun browser and domain courts against the recovered revision.

Rollback changes the selected deployment revision. It never rewrites published
Cell history.

## Open release gates

This source does not deploy resources and does not prove release eligibility.
The remaining real-artifact gates are:

- a reviewed Fly app, organisation, region, and exact one-Machine inventory;
- real Fly OIDC to the exact AWS role;
- real KMS GenerateMac/VerifyMac without exported key bytes;
- real DynamoDB conditional witness writes and rollback denial;
- real Fly Managed Postgres write, restart, PITR, and recovery;
- image build and vulnerability/SBOM/provenance verification;
- controlled browser/editor performance and security acceptance;
- multi-device identity, synchronisation, revocation, and recovery;
- explicit founder production promotion.

Fly Managed Postgres currently advertises HA, backups, private networking, and
encryption, but its documentation also says security patching and major/minor
version upgrades are still under development. That is a production admission
gap, not a detail to hide behind packaging.
