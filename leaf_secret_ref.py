"""LEAF: a secret is a secret-REFERENCE node — the resolved value never lives in
the graph, the live state, a session snapshot, or the history tree.

The law made executable (SPEC.md §5b, boundary 1):
    "Secrets are secret-reference nodes, never raw. A secret node holds an
     op:// reference (resolved at run-time), never the resolved value. The value
     never lives in the graph, a session, a snapshot, or the history tree."

This REUSES node_lang.Graph / node_lang.History unchanged. The engine already
ships the safe `secret_ref` kind (eval returns the op:// REFERENCE, never the
secret) and a deliberately-separate `_resolve_secret` (run-time only, never
called by eval/state/to_session). This leaf proves that boundary holds end to end.

The proof is made adversarial: we put the REAL secret in the environment so the
run-time resolver CAN fetch it, confirm resolution works at run time, then assert
the resolved sentinel is ABSENT from every persisted surface while the op:// ref
is PRESENT in all of them.

Run it:  PYTHONIOENCODING=utf-8 python leaf_secret_ref.py
"""
import json
import os

from node_lang import Graph, History  # the real engine — reused, not rebuilt

REF = "op://vault/stripe/key"          # the reference that IS allowed to be stored
SECRET = "sk_live_REAL"                # the resolved secret — must NEVER be persisted

# The resolver reads env var REF.replace("op://","").replace("/","_").upper().
ENV_KEY = REF.replace("op://", "").replace("/", "_").upper()  # VAULT_STRIPE_KEY


def main():
    # Arm the run-time resolver with the REAL secret, so the only thing keeping it
    # out of the graph is the boundary itself — not a missing value.
    os.environ[ENV_KEY] = SECRET

    g = Graph()

    # 1) A secret is a secret-REFERENCE node. It carries the op:// ref, not the value.
    g.add("stripe_key", "secret_ref", params={"ref": REF})

    # 2) eval -> returns the op:// REFERENCE (the reference, not the secret).
    resolved_via_eval = g.eval("stripe_key")
    print("eval(secret_ref)         -> %r" % (resolved_via_eval,))
    assert resolved_via_eval == REF, resolved_via_eval
    assert resolved_via_eval != SECRET

    # Sanity: the run-time resolver REALLY can fetch the secret (so the boundary is
    # what protects us, not a dead/empty value). This value is used and discarded
    # here — it never touches the graph.
    runtime_secret = g._resolve_secret("stripe_key")
    print("_resolve_secret (runtime)-> %r  (used + discarded, never stored)"
          % ("<resolved>" if runtime_secret == SECRET else runtime_secret,))
    assert runtime_secret == SECRET, "resolver must fetch the real secret at run time"

    # Wire it through another node too, to be sure a consumer doesn't leak it either.
    g.add("ref_to_key", "ref", params={"ref": "stripe_key"})  # a node that reads it
    assert g.eval("ref_to_key") == REF

    # 3) Persist EVERY surface a UI / AI / disk could read, and dump to JSON.
    state_json = json.dumps(g.state())          # the live running graph + values
    session_json = json.dumps(g.to_session())   # a saved session snapshot

    h = History()
    h.commit(g, "secret-ref scenario")          # append-only history tree
    history_json = json.dumps(
        [{"label": v["label"], "session": v["session"]} for v in h.versions]
    )

    # Also a full round-trip: load the session back and re-dump — still no secret.
    reloaded = Graph.from_session(json.loads(session_json))
    reloaded_state_json = json.dumps(reloaded.state())
    assert reloaded.eval("stripe_key") == REF

    surfaces = {
        "state()": state_json,
        "to_session()": session_json,
        "history tree": history_json,
        "reloaded state()": reloaded_state_json,
    }

    print("-" * 64)
    for name, blob in surfaces.items():
        has_ref = REF in blob
        has_secret = SECRET in blob
        print("  %-18s  op://ref present=%s   secret present=%s"
              % (name, has_ref, has_secret))
        # The reference IS allowed (and required) to be present.
        assert has_ref, "%s must keep the op:// reference" % name
        # The resolved secret must NEVER appear on a persisted surface.
        assert not has_secret, "%s LEAKED the resolved secret!" % name

    # Belt-and-suspenders: the literal "sk_live" prefix appears nowhere either.
    for name, blob in surfaces.items():
        assert "sk_live" not in blob, "%s leaked an sk_live secret!" % name

    print("-" * 64)
    print('Reference "%s" present on every surface; resolved secret "%s" present on NONE.'
          % (REF, SECRET))
    print("SECRET_REF_OK")


if __name__ == "__main__":
    main()
