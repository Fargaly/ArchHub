# Remote Device and Session Authority

Status: WIP returning-device authority implemented; transport and pairing unreleased

Date reviewed: 2026-07-26

Controlling sources:

1. `AUTHORITY.md`
2. `SPEC.md`
3. the founder Core Values authority named by `AUTHORITY.md`
4. the Grand Map requirement graph named by `AUTHORITY.md`

This record does not authorise deployment or claim that remote device access is
complete. It defines the smallest security and authority boundary that must be
proved before the cloud runtime can be called usable from another device.

## 1. What

ArchHub needs two different device ceremonies:

1. **Returning-device authentication.** A device whose public proof key already
   has one active subject, tenant, audience, and custody binding may obtain a
   new short-lived, DPoP-bound Cloud Session after a fresh OpenID Connect
   Authorization Code flow with PKCE.
2. **New-device admission.** A public key with no active graph binding may not
   become trusted merely because somebody completed OpenID Connect. It needs a
   separate, graph-held pairing approval from an active trusted session, or a
   deliberately released recovery ceremony.

The browser, native desktop, cloud gateway, Brain, and visual application are
lenses and physical adapters over the same accepted `CellStore`. They do not
receive separate user, device, token, or session databases.

## 2. Why

The current source has most of the required mechanisms, but they do not form a
remote product path:

- `NativeAuthorizationBroker` creates graph-held native authorization
  transactions and keeps state, nonce, and PKCE verifier in process memory.
- `FederatedIdentityBroker` verifies an ID token through a court, then resolves
  signed audience binding and tenant membership from the graph.
- `CloudSessionBroker` issues a short-lived token bound to an existing device
  key thumbprint and rechecks session authority, device binding, tenant
  release, membership, DPoP proof, and replay on every request.
- `NativeCloudLogin` joins those mechanisms only when it is given the same
  `CellStore` locally.
- `UniversalCloudGateway` accepts only a Cloud Session that has already been
  issued.
- `cloud_application_entrypoint.py` currently exposes the browser application
  server, not the DPoP cloud gateway or a remote login ceremony.

Therefore an enrolled device cannot presently re-authenticate against the
remote authority after its local session expires, and a new device has no
released pairing path. Exposing the browser bootstrap token on the public
listener would bypass the intended remote trust boundary and is forbidden.

OpenID Connect proves control of an admitted external identity. It does not by
itself prove that a new operating-system key, device, or custody boundary
should receive persistent ArchHub authority. Collapsing identity login and
device admission would turn an identity-provider compromise into silent device
enrollment.

## 3. How

### 3.1 One authority

The remote process owns one canonical `CellStore`, one runtime fence, and one
accepted revision sequence.

```text
PostgreSQL Cell journal + independent revision witness
                         |
                  one CellStore
                         |
       +-----------------+------------------+
       |                 |                  |
 application graph   login ceremony    DPoP resource gate
       |                 |                  |
  UI projections    session issuance    bounded API lenses
```

The login ceremony and resource gateway receive the existing store by
reference. They may not open another journal, write a shadow user table, copy a
session graph, or maintain a semantic cache.

### 3.2 Returning-device authentication

The intended sequence is:

```text
enrolled native device
  -> selects the released provider/client composition
  -> requests a short-lived login transaction for its public-key thumbprint
  -> cloud reads active native-client, device-binding, custody, tenant,
     audience, and policy relations from the accepted graph revision
  -> cloud creates the existing graph-held native authorization transaction
  -> native app opens the system browser by explicit user gesture
  -> provider returns code + exact state + exact response issuer to the
     native app loopback listener
  -> native app sends the bounded callback to the same cloud transaction
  -> cloud consumes state and PKCE custody once, exchanges the code at the
     pinned token endpoint, and verifies the ID token through the admitted
     OIDC court
  -> cloud resolves the exact graph-held external-identity binding,
     membership, assurance, device binding, and active custody
  -> cloud creates one short-lived Cloud Session composition
  -> cloud returns its process-held access token once over TLS
  -> every resource request requires a fresh RFC 9449 proof from that exact
     device key; revocation is rechecked on every request
```

The authorization code, provider tokens, ArchHub access token, state, nonce,
and PKCE verifier never become Cell atoms, log fields, URLs owned by ArchHub,
command-line arguments, or files. Digests and non-secret references may be
Cells when required for audit and replay denial.

The login endpoints are a bounded physical adapter. They are not added to the
already-authenticated `REMOTE_RUNTIME_ROUTES` list. Their admission decision
must read released native-client, identity, device, custody, tenant, audience,
and policy relations from the same store. Their public wire shape is a
constant allowlist with strict size, method, content-type, rate, and lifetime
bounds.

### 3.3 New-device admission

A new key cannot use the returning-device path. Its intended sequence is:

```text
new device creates non-exporting key
  -> new device presents only public JWK/thumbprint and a short pairing handle
  -> active trusted session sees the new-device request in the graph
  -> authorised user approves or denies the exact subject, tenant, audience,
     key, device description, expiry, and evidence
  -> approved pairing executes through the allowlisted device adapter
  -> graph records request, authorization, attempt, result, custody, binding,
     evidence, and history as separate related compositions
  -> one-use pairing authority is consumed
  -> new device uses returning-device authentication
```

The first device for a tenant requires a separate bootstrap/recovery authority.
That cannot be made "automatic" without selecting some other root of trust.
The released choice must be one of:

- an administrator-controlled recovery ceremony with independently protected
  recovery capability;
- an enterprise device-attestation and administrator policy;
- a founder-operated provisioning ceremony.

OIDC alone is not an acceptable first-device root of trust.

### 3.4 Process and network shape

The deployable process must expose one public ASGI surface behind Fly edge TLS.
The DPoP resource gateway and bounded login adapter share the same process and
store. The browser application listener is loopback/internal only and its
bootstrap token is never a public route.

Fly termination does not prove application identity. The application must use
the configured canonical HTTPS resource origin for DPoP `htu`, nonce audience,
redirect generation, and issuer/audience checks. Forwarded headers are not
authority unless an admitted proxy contract validates them.

## 4. Who

- **Founder/tenant administrator:** releases the native client, identity
  binding, tenant policy, new-device pairing, and recovery method.
- **Returning user:** initiates OIDC login and proves possession of the already
  bound device key on resource requests.
- **Trusted existing device/session:** may approve a new-device pairing only
  when its graph authority permits the exact action.
- **OIDC provider:** verifies external identity and signs a short-lived ID
  token; it does not grant ArchHub device authority.
- **Cloud runtime:** consumes the provider evidence, reads graph authority,
  issues the sender-constrained session, and records non-secret evidence.
- **Agent:** may explain or propose a ceremony, but may not approve a new
  device, select a weaker provider, widen actions, or handle raw secrets.

## 5. When

- Returning-device login starts only after the server has re-read active
  device binding, custody, native-client activation, tenant release, and
  provider metadata from one accepted revision.
- Callback completion occurs once, before transaction and metadata expiry.
- Session issuance occurs only after exact state, response issuer, PKCE, nonce,
  ID-token signature, issuer, audience, time, assurance, subject binding,
  membership, device binding, custody, and tenant release checks.
- Every resource request rechecks the current graph authority and uses a fresh
  DPoP proof and server nonce.
- Device, membership, client, tenant release, action, or policy revocation
  denies the next request. It does not wait for a cached permission.
- New-device pairing expires quickly, is one-use, and is not silently renewed.

## 6. Where

Persisted semantic facts belong in the Universal Cell authority:

- native provider/client registration and activation;
- external identity reference and signed local-subject binding;
- tenant membership and released tenant policy;
- device public-key custody and subject/audience binding;
- authorization transaction and completion digests;
- pairing request, decision, attempt, result, evidence, and lifecycle;
- Cloud Session manifest and revocable delegation;
- DPoP proof-use digest and audit/history facts.

Ephemeral secret custody remains outside the graph in the one owning process:

- state;
- nonce;
- PKCE verifier;
- authorization code;
- provider ID/access/refresh tokens;
- ArchHub access token;
- private device key;
- private signing and encryption keys.

No secret may enter Git, a Cell atom, log output, exception text, a browser URL
owned by ArchHub, a command line, a test artifact, or a generated document.

## 7. Evidence and required courts

Implementation advances only through red courts for the affected contracts.

### 7.1 Returning-device functional courts

1. An active already-enrolled device completes Authorization Code + PKCE and
   receives one DPoP-bound Cloud Session without a pre-existing Cloud Session.
2. The same ceremony denies an unknown device key.
3. Revoked custody, revoked device binding, revoked native-client activation,
   inactive membership, changed tenant release, wrong audience, or insufficient
   assurance denies issuance.
4. Wrong state, missing/wrong response issuer, wrong nonce, wrong PKCE
   verifier, token-endpoint redirect, non-JSON response, oversized response,
   invalid ID-token signature, stale token, or replayed callback denies.
5. Restart/loss of process-held transaction secrets fails closed; the visible
   graph transaction expires and cannot be completed.
6. Callback and issued session are one-use where required; concurrent replay
   yields one winner.
7. Provider code, provider tokens, ArchHub access token, state, nonce, PKCE
   verifier, private JWK material, and raw ID token are absent from Cells,
   logs, errors, files, URLs owned by ArchHub, and test artifacts.
8. The first accepted resource request succeeds only with the exact bound key;
   token-only, wrong-key, wrong-`htu`, wrong-`htm`, wrong-`ath`, wrong nonce,
   stale proof, or replay denies.

### 7.2 New-device courts

1. OIDC success alone cannot create custody or a device binding.
2. A pairing names one subject, tenant, audience, public-key thumbprint,
   expiry, authorising session, action, and evidence set.
3. Pairing approval requires an active trusted session and explicit admitted
   authority; an agent proposal is not approval.
4. Pairing denial, expiry, replay, cancellation, revocation, subject drift,
   tenant drift, audience drift, key drift, or authorising-session revocation
   denies enrollment.
5. Request, authorization, attempt, provider/adapter result, custody, binding,
   and history remain separately inspectable and recoverable.
6. First-device recovery has a separately released court and cannot reuse the
   normal pairing or OIDC path.

### 7.3 One-authority and transport courts

1. The login adapter, application, DPoP gateway, Brain lens, and visual client
   address the same store object, application root, and accepted revision.
2. No login or gateway path constructs a second `CellStore`, journal, identity
   table, session table, permission cache, or command queue.
3. The public listener exposes the bounded login adapter and DPoP gateway, not
   the browser bootstrap endpoint.
4. Every public route has a constant physical allowlist and a graph-read
   admission/gate; undeclared paths return a bounded denial.
5. Request body, response body, header, URL, lifetime, pending-transaction,
   concurrency, and rate limits are enforced before expensive provider work.
6. Provider, graph, database, KMS, witness, or network failure returns a
   content-free denial and never falls back to local or bearer authority.
7. Deleting disposable process state changes no graph semantics; losing it
   fails the in-flight ceremony closed.

### 7.4 Deployment courts

1. A packaged client on a second controlled device signs in, reconnects after
   process restart, reads its authorised graph lens, and cannot read another
   tenant or audience.
2. Device revocation from a trusted session denies the other device's next
   request.
3. Interrupted login, interrupted commit, expired session, lost device, key
   rotation, provider key rotation, database restore, and regional restart
   have rehearsed recovery evidence.
4. Installer signature, update signature, rollback protection, update
   recovery, and version compatibility are proven on actual packaged
   artifacts.

## 8. Standards mapping

The following are external research, not ArchHub semantic authority:

- [OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0-18.html):
  Authorization Code flow and ID-token issuer, audience, nonce, signature, and
  time validation.
- [RFC 8252](https://www.rfc-editor.org/rfc/rfc8252.html): native applications
  are public clients; use the system browser, loopback redirect, Authorization
  Code flow, and PKCE.
- [RFC 7636](https://www.rfc-editor.org/rfc/rfc7636.html): S256 PKCE binds the
  callback code to the initiating client.
- [RFC 8414](https://www.rfc-editor.org/rfc/rfc8414.html): exact issuer-pinned
  authorization-server metadata and endpoint discovery.
- [RFC 9207](https://www.rfc-editor.org/rfc/rfc9207.html): exact authorization
  response issuer comparison prevents mix-up.
- [RFC 9449](https://www.rfc-editor.org/rfc/rfc9449.html): DPoP
  sender-constrains the ArchHub access token to the device key and requires
  fresh method, target, time, identifier, token hash, and nonce claims where
  applicable.
- [RFC 9700](https://www.rfc-editor.org/rfc/rfc9700.html): OAuth security best
  current practice, including authorization-code use, mix-up defense,
  sender-constrained access tokens, audience restriction, and minimum
  privilege.
- [RFC 7009](https://www.rfc-editor.org/rfc/rfc7009.html): revocation model
  lineage. ArchHub additionally rechecks graph authority on every request.

## 9. Current measured boundary

As of 2026-07-26:

- local native login mechanisms exist and have scoped courts;
- DPoP resource-gateway mechanisms exist and have scoped courts;
- `RemoteNativeCloudLoginBroker` now joins returning-device admission, native
  authorization, federated identity, and Cloud Session issuance against one
  caller-owned `CellStore`; it creates no store, listener, or enrollment;
- active device custody is required at session issuance and is rechecked at
  the same accepted revision that records each one-use request proof;
- authorization completion retains process-held state, nonce, and PKCE custody
  across preparation or commit failure and consumes them only after commit;
- 111 source-light identity, device, OIDC, gateway, bootstrap, primitive-floor,
  and entrypoint courts pass together; the two transaction-race courts were
  independently reviewed with no unresolved P0, P1, or P2 finding;
- the cloud process package exists and is pushed to the WIP branch;
- no production OIDC client/issuer is released in the Universal graph;
- no deployable public login transport exposes the returning-device mechanism;
- no new-device pairing/recovery ceremony is released;
- no controlled second-device deployment court has passed.

The product is therefore not yet remotely usable or release eligible.

## 10. Bounded ephemeral authorization custody

### 10.1 Measured pre-change state

At commit `2f78bb8888ccd78dccda121a50dee410e366002e`,
`NativeAuthorizationBroker` owns pending state, nonce, and PKCE verifier values
in one process-local dictionary. Entries leave that dictionary after successful
completion, failed graph commit, or an attempted callback that discovers
expiry. Repeated starts without callbacks have no global or per-device bound,
and ordinary expiry does not proactively release their secret custody.

This is not presently an Internet-reachable exploit because the public login
transport is still absent. It is a release blocker: an admitted device or a
future exposed adapter could otherwise create unbounded pending process state
and graph transactions.

### 10.2 Smallest authority-preserving repair

The existing broker remains the only owner of ephemeral authorization secrets.
It receives fixed positive global and per-device custody bounds. Under its
existing lock, each start:

1. removes expired entries that are not currently completing;
2. counts all remaining pending entries and entries for the exact device;
3. denies capacity exhaustion before graph commit;
4. reserves one entry atomically;
5. removes that entry if the canonical graph commit fails.

Expiry pruning deletes only disposable process-held secrets. It does not delete
or rewrite the graph transaction; the graph continues to expose the expired
transaction and its evidence. No store, schema, route, session authority, or
semantic cache is added.

### 10.3 Red acceptance courts

1. A device cannot exceed its pending authorization custody bound.
2. Different devices cannot exceed the broker-wide custody bound.
3. An expired, non-completing entry releases its process slot before the next
   start while its graph transaction remains inspectable as expired.
4. Invalid zero, negative, or per-device-greater-than-global bounds fail at
   broker construction.
5. Existing commit-failure, completion-race, one-use, secret-absence, and
   returning-device courts remain unchanged and green.

### 10.4 Implementation evidence

Implemented on 2026-07-26 in the existing `NativeAuthorizationBroker`:

- default process-custody bounds are 128 pending transactions globally and 4
  per device, with smaller positive bounds injectable by the owning
  composition;
- admission, expiry pruning, per-device counting, and reservation occur under
  the broker's existing lock;
- an expired entry releases only its ephemeral secret custody and leaves its
  Cell transaction inspectable as expired;
- a graph commit failure removes the reservation, and a completing entry is
  never pruned out from under its completion;
- 8 focused capacity/configuration/concurrency courts pass;
- the unchanged combined device, native authorization, OIDC, identity, cloud
  gateway, bootstrap, entrypoint, and primitive-floor suite passes 119 courts.

This closes pending-secret resource bounding only. Authentication freshness,
provider assurance negotiation, nonce-key custody, replay-evidence retention,
public transport, pairing, recovery, and deployment remain separate gates.

## 11. Linux cloud nonce-key custody

### 11.1 What and why

The DPoP resource server issues short-lived nonces that bind an access token,
audience, time window, and server-generated entropy. On the local Windows
runtime, the existing gateway may use Windows DPAPI for the nonce HMAC key. A
Linux cloud process cannot use that provider.

At commit `6bd5b26d997073e9b0b8443e76e11e723f2c827a`, the cloud bootstrap
admits only `archhub.local.relationship-authority` and
`archhub.local.court-attestation`. The cloud factory does not pass an admitted
nonce provider into the sole application owner. If a cloud gateway is enabled,
the existing default attempts Windows DPAPI. This fails closed, but makes the
Linux cloud boundary unusable and leaves nonce custody outside the exact
provider contract.

### 11.2 How, who, when, and where

The smallest repair keeps one graph, one process owner, and one physical KMS
provider:

1. The exact cloud key map contains only the relationship, court-attestation,
   and DPoP-nonce logical authorities.
2. Each logical authority maps reviewed integer versions to exact AWS KMS key
   ARNs.
3. CloudFormation creates and retains one `HMAC_256`,
   `GENERATE_VERIFY_MAC` key per authority and version.
4. The Fly runtime role may call only `kms:GenerateMac` and `kms:VerifyMac`,
   with `kms:MacAlgorithm` equal to `HMAC_SHA_256`, on those exact ARNs.
   Only the current version may generate; retained historical versions may
   verify only.
5. The cloud bootstrap constructs one `AwsKmsHmacSigningKeyProvider` and passes
   that same provider to graph build/restore and the existing nonce-broker
   parameter of the sole application server.
6. Before the witness, journal, `CellStore`, or server is constructed, the
   bootstrap generates and verifies one domain-separated admission MAC with
   each current authority.
7. Missing, extra, duplicated, version-mismatched, malformed, unavailable, or
   unauthorized key authority fails before the runtime starts or opens a cloud
   listener.

The founder or released provisioning service approves physical creation and
promotion. The infrastructure renderer handles only non-secret ARNs and role
identity. The Universal runtime can request MAC generation or verification but
cannot export HMAC bytes. This contract applies whenever the Linux cloud
runtime is constructed; it does not claim that a cloud gateway, TLS
certificate, or real provider deployment is released.

### 11.3 Red acceptance courts

1. Configuration rejects a missing nonce authority and any extra logical
   authority.
2. Infrastructure creates the retained nonce key and alias for every reviewed
   version.
3. The runtime role grants the nonce key only the exact MAC operations and
   algorithm already granted to the other two authorities.
4. The output renderer requires same-version relationship, court, and nonce
   ARNs and emits exactly those three maps.
5. The cloud factory passes the same admitted KMS provider to graph
   build/restore and the existing nonce-provider server parameter.
6. Existing secret-redaction, one-CellStore, runtime-fence, entrypoint, and
   no-listener construction courts remain green.

### 11.4 Primary evidence

Reviewed on 2026-07-26:

- AWS KMS HMAC keys:
  https://docs.aws.amazon.com/kms/latest/developerguide/hmac.html
- AWS KMS `GenerateMac`:
  https://docs.aws.amazon.com/kms/latest/APIReference/API_GenerateMac.html
- AWS KMS `VerifyMac`:
  https://docs.aws.amazon.com/kms/latest/APIReference/API_VerifyMac.html

AWS documents that HMAC key material remains in KMS, HMAC keys use
`GenerateMac` and `VerifyMac`, and the operation requires a compatible
`GENERATE_VERIFY_MAC` key and MAC algorithm. These sources inform the physical
adapter; the Universal Cell graph and ArchHub courts remain semantic
authority.

## 12. Bounded DPoP replay evidence

### 12.1 What and why

Every accepted DPoP request must carry a unique proof identifier. ArchHub hashes
that identifier and records its use so the same proof cannot be accepted twice.
At commit `9d09f278cc37361c4d859b3ce8654881629b2917`, one accepted request:

- creates one proof-use relation and four scalar evidence Cells;
- appends the proof-use root to the shared cloud-session protocol relation;
- increases the current graph by 16 Cells;
- increases retained Cell versions by 17 records;
- traverses the shared protocol relation with a `100000`-Cell budget.

There is no admitted request-rate boundary ahead of that commit. Repeated valid
requests therefore grow both the current graph and one shared relation without a
fixed limit. The replay check is durable, but the storage shape is not safe for
an Internet-facing service.

RFC 9449 Section 11.1 requires proofs to be accepted only for a limited time,
permits the server to retain each `jti` during that acceptance window, and
recommends hashing identifiers to reduce memory-exhaustion risk. A bounded
window must not evict an identifier while the same proof could still be
accepted. Capacity exhaustion therefore denies new proofs until a slot expires;
it never overwrites live replay evidence.

### 12.2 How

The Cloud Session protocol contains one wired replay-policy composition.
Session issuance is denied until an authenticated resource-lifecycle action
has promoted that exact composition through Shared to Published. Each session
issued after that release copies its capacity and retention into exactly one
replay-window relation. The session manifest commits to the window root and
those fixed policy values. Each slot is an openable relation containing:

1. the hashed proof identifier;
2. the verified HTTP method;
3. the verified target-URI digest;
4. the observation time.

Session issuance creates only the empty window and its policy wiring. A slot is
created lazily in the same accepted revision as its first proof and appended to
that session's window, never to the shared protocol relation. Slot identities
are deterministic and contiguous, and the window cannot contain more slots than
its policy capacity. Once capacity is reached, no proof creates another current
Cell.

For each verified request, the broker reads the latest accepted snapshot,
re-verifies the session manifest, device custody, tenant release, membership,
and requested action, then:

1. rejects a matching digest in any unexpired slot;
2. selects the oldest expired or unused slot;
3. creates the next deterministic slot when capacity remains;
4. denies without a graph mutation when every slot is unexpired and the window
   is at capacity;
5. otherwise atomically replaces only an expired slot's four scalar Cells;
6. retries from a fresh snapshot after a commit conflict.

The current graph grows only until the admitted slot limit and is fixed
afterwards. Historical slot values remain addressable through the Cell journal
revision APIs. Immutable proof evidence identity is therefore the slot root plus
the accepted revision, never the reusable slot root alone. There is no Python
replay set, second database, semantic cache, deletion, or hidden JSON record.

### 12.3 Who, when, and where

The Published Cloud Session protocol policy owns capacity and retention
values. Startup may stage the candidate WIP policy, but cannot publish it. The
Cloud Session broker reads only a released graph contract and performs the
atomic rewrite. The JOSE verifier declares its accepted proof-time envelope;
session issuance denies a draft policy or a policy shorter than that envelope.

The window is used after signature, method, target, nonce, token hash, key, and
time verification but before request authentication is minted. It lives in the
same `CellStore`, session manifest, journal, and accepted revision as the rest of
the cloud authority. A caller may inspect the current slots through the
authorised Govern or Floor lens and inspect older values by exact revision.

### 12.4 Red acceptance courts

1. Session issuance creates one empty fixed-capacity replay window and commits
   its policy into the session manifest without preallocating slots.
2. Accepted proofs create at most the policy number of slots; repeated accepted
   proofs do not increase the current Cell count after capacity is reached.
3. A repeated proof in the active window is denied.
4. A full unexpired window denies without changing the revision or graph.
5. An expired slot can be reused, while its prior values remain readable at the
   earlier revision.
6. Reopening the journal preserves active replay denial and slot history.
7. Concurrent writers cannot overwrite an unexpired proof after a conflict.
8. Session, token, action, tenant, membership, and device custody are
   revalidated in the exact snapshot used for the slot rewrite.
9. No successful request appends a `proof-use-member` to the shared protocol
   relation.
10. Zero, negative, non-finite, excessive, verifier-shorter retention, invalid
    capacity, or foreign policy/value wiring fail before authority is used.
11. Eight unrelated global graph revisions cannot exhaust the bounded replay
    conflict policy, and no retry bypasses revalidation.
12. Pre-window sessions are intentionally denied and require explicit
    reauthentication; they are not silently presented as migrated.

### 12.5 Primary evidence

Reviewed on 2026-07-26:

- RFC 9449, especially Sections 4.2, 4.3, and 11.1:
  https://www.rfc-editor.org/rfc/rfc9449.html
- Current Cell journal revision and selected historical-value APIs:
  `nodelang/universal_cell.py`
- Current Cloud Session and proof-use authority:
  `nodelang/cell_cloud_sessions.py`

RFC 9449 is external protocol lineage, not ArchHub semantic authority. The
session composition and its passing courts remain the executable ArchHub
contract.

### 12.6 Implementation evidence and remaining boundary

Implemented on 2026-07-26 in the existing Cloud Session composition:

- fresh protocols contain the seven replay-policy/window roles and do not create the
  retired `proof-use-member` role;
- a legacy journal may retain that retired role and its historical relations,
  but migration adds only the seven new roles and rejects any other missing,
  duplicated, extended, or drifted vocabulary;
- the default and admitted maximum are 1,024 slots, and the default JOSE
  verifier accepts a proof for at most 10 seconds with 5 seconds of future
  clock skew, publishing a 15-second retention envelope;
- issuance creates no slots; one measured first request created 14 current
  slot/wiring Cells, 15 historical versions, and one revision, while a reused
  expired slot changes zero current Cells and four historical versions;
- source-light capacity diagnostics accepted 256 proofs in 0.740 seconds
  (2.892 ms mean), 512 in 2.465 seconds (4.815 ms mean), and 1,024 in 8.454
  seconds (8.255 ms mean) through the canonical in-memory request path;
- the candidate capacity-to-retention ratio is 68.27 accepted proof
  identifiers per second, and a court exercises a 64-request-per-second logical window
  before proving that a 1,025th unexpired proof fails without mutation;
- those timings and the logical-window court are diagnostic source-light
  evidence, not real PostgreSQL, provider, network, or deployed cloud latency
  acceptance;
- fixed-window, replay, exhaustion, reuse, history, reopen, contention,
  ownership-tampering, retention, capacity, and legacy-migration courts pass
  with the unchanged identity/session suite.

This repair bounds current replay topology and removes the shared per-request
relation append. The immutable journal still gains 15 Cell versions while a
new slot is created and four versions when an expired slot is reused. Durable
history residency is now governed separately by
`DURABLE-HISTORY-RESIDENCY-AUTHORITY.md`: SQLite, PostgreSQL, and witnessed
journals use the same head-bound append-only history while process-resident
version archives remain absent. Real PostgreSQL/provider execution, archive,
partitioning, recovery drills, and deployed retention operations remain part
of the cloud release gate; they cannot be represented as completed by this
local replay-window mechanism. No live process, remote deployment, or real AWS
KMS court was changed or claimed by this local repair.

### 12.7 Replay-policy release authority

#### What

Replay capacity and retention are security configuration, not startup defaults
that become authoritative merely because their Cells are structurally valid.
The replay policy therefore uses the existing Versioned Asset lifecycle:

1. the policy relation is the WIP graph content;
2. an authenticated and authorised resource-lifecycle action requests Shared;
3. a second authenticated and authorised action requests Published;
4. each action receives exact-content court evidence and records its actor;
5. the Cloud Session protocol is explicitly wired to that lifecycle instance;
6. every issued session binds the exact Published revision as evidence.

#### Why

Without that chain, startup or migration can create a valid-looking policy and
silently change the security envelope for future sessions. NIST SP 800-53
Revision 5 CM-3 requires configuration-controlled changes to be reviewed,
approved or disapproved with security impact considered, documented,
implemented only after approval, and retained. NIST SP 800-218 PS.3 and PW.1.2
require release provenance and tracked security requirements, risks, and design
decisions. RFC 9449 Section 11.1 requires a proof identifier to remain tracked
for the whole interval in which that proof remains acceptable.

#### How

The implementation must preserve one CellStore and reuse the generic lifecycle
and court machinery. A released-policy verifier must prove all of the following
from one accepted snapshot:

- one protocol wire identifies one lifecycle instance;
- that instance has one Published head;
- the Published revision points to the replay-policy relation;
- its predecessor chain includes the court-evidenced Shared and WIP revisions;
- the graph-content digest still matches capacity and retention;
- the exact Published revision is present in both the session manifest and the
  signed session authority evidence;
- a changed, missing, unbound, draft-only, Shared-only, forged, or stale release
  fails closed and requires a newly issued session.

The startup and restore paths may create or migrate WIP graph vocabulary and
wire its lifecycle instance. They do not promote it. A broker may be
constructed, but session issuance and request admission fail closed until
explicit authenticated lifecycle actions and the admitted court have
Published the exact policy graph.

#### Who

The application authority actor proposes the WIP policy revision. An
authenticated user with exact `share` or `publish` authority makes each
promotion decision through the existing resource-lifecycle action; startup
cannot impersonate that action. The admitted resource-lifecycle court supplies
exact-content evidence. The Cloud Session broker only reads the resulting
Published authority and cannot promote it.

#### When

The check runs at session issuance and again for every request. A policy release
change invalidates the old session evidence instead of silently applying new
values to an existing session.

#### Where

- policy graph and replay window: `nodelang/cell_cloud_sessions.py`;
- generic WIP/Shared/Published history: `nodelang/cell_lifecycle.py`;
- application composition and restore: `nodelang/universal_application.py`;
- request admission: `nodelang/application_server.py`;
- executable courts: `tests_replica/test_cell_federated_identity.py` and
  `tests_replica/test_universal_application.py`.

#### Evidence and release boundary

Primary references reviewed on 2026-07-26:

- RFC 9449 Section 11.1:
  https://www.rfc-editor.org/rfc/rfc9449.html#section-11.1
- NIST SP 800-53 Revision 5, CM-3:
  https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final
- NIST SP 800-218 Secure Software Development Framework:
  https://csrc.nist.gov/pubs/sp/800/218/final

These sources are research lineage, not ArchHub semantic authority. The
controlling requirements remain `SPEC.md`, this WIP design record, and
revision-bound passing courts. This record does not release the candidate
policy. Real PostgreSQL and deployed-provider execution remain mandatory cloud
release evidence and cannot be inferred from local SQLite or fake-driver
courts.
