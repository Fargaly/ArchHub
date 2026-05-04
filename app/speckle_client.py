"""Speckle GraphQL client for ArchHub.

Connects ArchHub to Speckle's data layer so the LLM can list projects,
fetch model versions, push/pull geometry, and use Speckle as the spine
between modeling tools.

Configuration: API token via Settings (stored in OS keyring as 'speckle').
Default server: https://app.speckle.systems
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from secrets_store import load_api_key, load_setting

DEFAULT_SERVER = "https://app.speckle.systems"


class SpeckleClient:
    def __init__(self):
        pass

    # ---- public dispatch -------------------------------------------------

    def dispatch(self, handler: str, args: dict) -> dict:
        token = load_api_key("speckle")
        if not token:
            return {"status": "error",
                    "error": "No Speckle API token. Add one in Settings → Speckle."}
        server = load_setting("speckle_server") or DEFAULT_SERVER

        if handler == "list_projects":
            return self._list_projects(server, token)
        if handler == "get_project":
            return self._get_project(server, token, args["project_id"])
        return {"status": "error", "error": f"Unknown speckle handler: {handler}"}

    # ---- queries ----------------------------------------------------------

    def _query(self, server: str, token: str, query: str, variables: dict) -> dict:
        url = f"{server.rstrip('/')}/graphql"
        body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data)

    def _list_projects(self, server: str, token: str) -> dict:
        q = """
        query ActiveUserProjects {
            activeUser {
                id
                projects(limit: 50) {
                    items { id name description createdAt updatedAt }
                    totalCount
                }
            }
        }
        """
        try:
            res = self._query(server, token, q, {})
        except urllib.error.HTTPError as e:
            return {"status": "error", "error": f"Speckle HTTP {e.code}: {e.reason}"}
        except Exception as e:
            return {"status": "error", "error": f"{type(e).__name__}: {e}"}

        if "errors" in res and res["errors"]:
            return {"status": "error", "error": res["errors"][0].get("message", "GraphQL error")}
        items = (((res.get("data") or {}).get("activeUser") or {}).get("projects") or {}).get("items") or []
        return {"status": "ok", "projects": items, "count": len(items)}

    def _get_project(self, server: str, token: str, project_id: str) -> dict:
        q = """
        query ($id: String!) {
            project(id: $id) {
                id name description createdAt updatedAt
                models(limit: 50) {
                    items {
                        id name updatedAt
                        versions(limit: 5) {
                            items { id message createdAt }
                        }
                    }
                }
            }
        }
        """
        try:
            res = self._query(server, token, q, {"id": project_id})
        except Exception as e:
            return {"status": "error", "error": f"{type(e).__name__}: {e}"}
        if "errors" in res and res["errors"]:
            return {"status": "error", "error": res["errors"][0].get("message", "GraphQL error")}
        return {"status": "ok", "project": (res.get("data") or {}).get("project")}
