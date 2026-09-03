"""Speckle GraphQL + REST client for ArchHub."""
from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from typing import Any, Optional

from secrets_store import load_api_key, load_setting

DEFAULT_SERVER   = "https://app.speckle.systems"
DEFAULT_BRANCH   = "archhub/main"
SPECKLE_APP_NAME = "ArchHub"


def _hash_object(obj: dict) -> str:
    copy = {k: v for k, v in obj.items() if k != "id"}
    canonical = json.dumps(copy, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class SpeckleClient:
    def __init__(self) -> None:
        pass

    def dispatch(self, handler: str, args: dict) -> dict:
        token = load_api_key("speckle")
        if not token:
            return {"status": "error", "error": "No Speckle API token. Add one in Settings -> Speckle."}
        server = load_setting("speckle_server") or DEFAULT_SERVER

        if handler == "list_projects":
            return self._list_projects(server, token)
        if handler == "get_project":
            return self._get_project(server, token, args["project_id"])
        if handler == "push_parameters":
            return self.push_parameters(
                args["project_id"],
                args.get("branch", DEFAULT_BRANCH),
                args.get("parameters", {}),
                args.get("geometry_ref", None),
                args.get("message", "ArchHub push"),
            )
        if handler == "pull_parameters":
            return self.pull_parameters(args["project_id"], args.get("branch", DEFAULT_BRANCH))
        return {"status": "error", "error": "Unknown speckle handler: " + handler}

    # ---- push ------------------------------------------------------------

    def push_parameters(
        self,
        project_id: str,
        branch: str = DEFAULT_BRANCH,
        parameters: Optional[dict] = None,
        geometry_ref: Optional[str] = None,
        message: str = "ArchHub push",
    ) -> dict:
        token = load_api_key("speckle")
        if not token:
            return {"status": "error", "error": "No Speckle API token configured."}
        server = load_setting("speckle_server") or DEFAULT_SERVER

        obj: dict[str, Any] = {
            "speckle_type": "Objects.BuiltElements.ArchHub.ParameterSet@1.0.0",
            "__closure": {},
            "applicationId": None,
            "parameters": parameters or {},
        }
        if geometry_ref:
            obj["geometry_ref"] = geometry_ref
        obj_id = _hash_object(obj)
        obj["id"] = obj_id

        try:
            self._upload_object(server, token, project_id, obj)
        except Exception as ex:
            return {"status": "error", "error": "Object upload failed: " + str(ex)}

        try:
            commit_id = self._create_commit(server, token, project_id, branch, obj_id, message)
        except Exception as ex:
            return {"status": "error", "error": "Commit creation failed: " + str(ex)}

        return {
            "status": "ok",
            "commit_id": commit_id,
            "object_id": obj_id,
            "branch": branch,
            "project_id": project_id,
        }

    # ---- pull ------------------------------------------------------------

    def pull_parameters(self, project_id: str, branch: str = DEFAULT_BRANCH) -> dict:
        token = load_api_key("speckle")
        if not token:
            return {"status": "error", "error": "No Speckle API token configured."}
        server = load_setting("speckle_server") or DEFAULT_SERVER

        try:
            commit = self._get_latest_commit(server, token, project_id, branch)
        except Exception as ex:
            return {"status": "error", "error": "Could not fetch commit: " + str(ex)}

        if commit is None:
            return {"status": "error",
                    "error": "No commits on branch '{}' in project {}.".format(branch, project_id)}

        object_id = commit.get("referencedObject")
        commit_id = commit.get("id")
        if not object_id:
            return {"status": "error", "error": "Commit has no referenced object."}

        try:
            obj = self._download_object(server, token, project_id, object_id)
        except Exception as ex:
            return {"status": "error", "error": "Object download failed: " + str(ex)}

        return {
            "status": "ok",
            "parameters": obj.get("parameters") or {},
            "geometry_ref": obj.get("geometry_ref"),
            "commit_id": commit_id,
            "object_id": object_id,
            "branch": branch,
        }

    # ---- GraphQL ---------------------------------------------------------

    def _query(self, server: str, token: str, query: str, variables: dict) -> dict:
        url = "{}/graphql".format(server.rstrip("/"))
        body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token,
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))

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
            return {"status": "error", "error": "HTTP {}: {}".format(e.code, e.reason)}
        except Exception as e:
            return {"status": "error", "error": "{}: {}".format(type(e).__name__, e)}

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
            return {"status": "error", "error": "{}: {}".format(type(e).__name__, e)}
        if "errors" in res and res["errors"]:
            return {"status": "error", "error": res["errors"][0].get("message", "GraphQL error")}
        return {"status": "ok", "project": (res.get("data") or {}).get("project")}

    # ---- REST object store -----------------------------------------------

    def _upload_object(self, server: str, token: str, stream_id: str, obj: dict) -> None:
        url = "{}/objects/{}".format(server.rstrip("/"), stream_id)
        body = json.dumps([obj], ensure_ascii=True).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp.read()

    def _download_object(self, server: str, token: str, stream_id: str, object_id: str) -> dict:
        url = "{}/objects/{}/{}/single".format(server.rstrip("/"), stream_id, object_id)
        req = urllib.request.Request(
            url, method="GET",
            headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # ---- commit helpers --------------------------------------------------

    def _create_commit(self, server: str, token: str, stream_id: str,
                       branch_name: str, object_id: str, message: str) -> str:
        mutation = """
        mutation CreateCommit($commit: CommitCreateInput!) {
            commitCreate(commit: $commit)
        }
        """
        variables = {
            "commit": {
                "streamId":          stream_id,
                "branchName":        branch_name,
                "objectId":          object_id,
                "message":           message,
                "sourceApplication": SPECKLE_APP_NAME,
            }
        }
        res = self._query(server, token, mutation, variables)
        if "errors" in res and res["errors"]:
            raise RuntimeError(res["errors"][0].get("message", "GraphQL error"))
        return (res.get("data") or {}).get("commitCreate", "")

    def _get_latest_commit(self, server: str, token: str,
                           stream_id: str, branch_name: str) -> Optional[dict]:
        query = """
        query GetBranchLatest($streamId: String!, $branchName: String!) {
            stream(id: $streamId) {
                branch(name: $branchName) {
                    commits(limit: 1) {
                        items { id referencedObject message createdAt }
                    }
                }
            }
        }
        """
        res = self._query(server, token, query,
                          {"streamId": stream_id, "branchName": branch_name})
        if "errors" in res and res["errors"]:
            raise RuntimeError(res["errors"][0].get("message", "GraphQL error"))
        items = (
            ((((res.get("data") or {}).get("stream") or {})
              .get("branch") or {})
             .get("commits") or {})
            .get("items") or []
        )
        return items[0] if items else None
