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
