"""Render a secret-free Fly application config for one Cell authority."""
from __future__ import annotations

import argparse
from pathlib import Path
import re


_APP_NAME = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_REGION = re.compile(r"[a-z]{3}")


def _validated(value: str, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(f"Fly {label} is invalid")
    return value


def render_fly_application_config(
    *,
    app_name: str,
    primary_region: str,
) -> str:
    """Return one config; credentials and provider handles are never inputs."""
    app_name = _validated(app_name, _APP_NAME, "application name")
    primary_region = _validated(primary_region, _REGION, "primary region")
    return f"""app = "{app_name}"
primary_region = "{primary_region}"
kill_signal = "SIGTERM"
kill_timeout = 120

[build]
  dockerfile = "packaging/cloud/Dockerfile"

[[services]]
  internal_port = 8482
  protocol = "tcp"
  auto_stop_machines = "off"
  auto_start_machines = false
  min_machines_running = 0

  [[services.ports]]
    handlers = ["http"]
    port = 80
    force_https = true

  [[services.ports]]
    handlers = ["tls", "http"]
    port = 443

  [[services.tcp_checks]]
    grace_period = "30s"
    interval = "15s"
    timeout = "2s"
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", required=True)
    parser.add_argument("--primary-region", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    rendered = render_fly_application_config(
        app_name=args.app,
        primary_region=args.primary_region,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
