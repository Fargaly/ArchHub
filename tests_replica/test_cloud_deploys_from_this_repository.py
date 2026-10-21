"""The live cloud (archhub-cloud) deploys from this repository.

12.PRODUCTION is retired; cloud_backend/ lives here. The deploy helper must
build the image from cloud_backend/ itself -- the Dockerfile copies
requirements.txt and main.py from its own directory -- whatever directory the
helper is started from, and must name no retired checkout.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_cloud_deploy_builds_from_cloud_backend_in_this_repository():
    script = (ROOT / "cloud_backend" / "deploy.ps1").read_text(encoding="utf-8")
    deploy = [line for line in script.splitlines() if line.strip().startswith("flyctl deploy")]
    assert len(deploy) == 1
    assert re.match(r"flyctl deploy \$context --config \$flyToml ", deploy[0].strip())
    assert '$context  = Join-Path $repoRoot "cloud_backend"' in script
    assert "12.PRODUCTION" not in script
    fly = (ROOT / "cloud_backend" / "fly.toml").read_text(encoding="utf-8")
    assert re.search(r"^app\s*=\s*['\"]archhub-cloud['\"]", fly, re.M)
    dockerfile = (ROOT / "cloud_backend" / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY requirements.txt ." in dockerfile
    assert (ROOT / "cloud_backend" / "requirements.txt").is_file()
    assert (ROOT / "cloud_backend" / "main.py").is_file()