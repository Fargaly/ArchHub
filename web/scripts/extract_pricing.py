#!/usr/bin/env python
"""extract_pricing.py — read the canonical Model C pricing from
cloud_backend/config.py and emit src/data/pricing.json so the Astro
pricing page renders live tier constants WITHOUT duplicating numbers.

Per CONTENT-ECOSYSTEM-2026-05-26.md §2 + §8 (Living-content invariants):
  "Pricing in one place (cloud_backend/config.py). All surfaces READ
   from the source."

Model C (founder-approved 2026-05-31): per-seat tiers + BYO/Hosted AI +
$10/1,000-msg credit packs + annual −20%. See
docs/prototypes/pricing-model-C-hybrid-2026-05-31.html.

Strategy (changed 2026-05-31):
  - config.py now exposes a TYPED accessor `public_pricing()` returning a
    secret-free Model C snapshot (per-seat prices, annual equivalents,
    seat floors, AI modes, the credit pack). We import config + call it —
    NO more ast-parsing dict literals or scraping the docstring (the old
    approach the investigation flagged as fragile). config imports only
    os + pathlib (+ optional dotenv) and `_req` tolerates missing env in
    dev, so importing it here is side-effect-free and cannot crash on a
    box without Stripe installed.

Run:
  python scripts/extract_pricing.py            # writes src/data/pricing.json
  python scripts/extract_pricing.py --print    # prints the JSON only
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
WEB_ROOT = HERE.parent
REPO_ROOT = WEB_ROOT.parent
CONFIG_PY = REPO_ROOT / "cloud_backend" / "config.py"
OUT = WEB_ROOT / "src" / "data" / "pricing.json"


def _load_config():
    """Import cloud_backend/config.py as a module without importing the
    rest of the backend package. Returns the module."""
    spec = importlib.util.spec_from_file_location("archhub_cloud_config",
                                                  CONFIG_PY)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {CONFIG_PY}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_payload() -> dict:
    config = _load_config()
    pricing = config.public_pricing()   # the typed Model C accessor
    # Stamp provenance so the page + a reader can see where this came
    # from (and that it is config-derived, not hand-edited).
    pricing["source"] = "cloud_backend/config.py :: public_pricing()"
    pricing["extracted_from"] = [str(CONFIG_PY.relative_to(REPO_ROOT))]
    return pricing


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", action="store_true",
                    help="print to stdout, do not write file")
    args = ap.parse_args()

    if not CONFIG_PY.exists():
        print(f"[extract_pricing] FAIL — {CONFIG_PY} not found",
              file=sys.stderr)
        return 1

    payload = build_payload()
    blob = json.dumps(payload, indent=2)

    if args.print:
        print(blob)
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(blob, encoding="utf-8")
    print(f"[extract_pricing] wrote {OUT} — Model {payload.get('model')} "
          f"· {len(payload.get('tiers', []))} tier(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
