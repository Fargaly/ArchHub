"""Workspaces routes shared by the desktop and the historical clean consumer."""
from __future__ import annotations

import hashlib
import json
import time

from .universal_cell import InvalidCell

_KEY_RECOVERY_MESSAGE = "ArchHub's saved workspace key is missing. Restart ArchHub and try again. Your files are unchanged."


class WorkspaceRootsOwner:
    @property
    def workspace_roots_authority(self):
        return getattr(self, "_workspace_roots_binding", None) or self.clean_authority

    @property
    def workspace_roots_caller(self):
        if getattr(self, "_workspace_roots_binding", None) is not None:
            return self.universal_registry.authorization.subject_root
        return self.clean_caller

    def _check_workspace_roots(self):
        import uuid

        from . import commit_intent
        from .private_root_grants import record_grant_event
        from .workspace_roots_catalogue import (
            APP_KEY_ID,
            APP_WRITTEN,
            KEY_CHECK,
            _atomic_write,
            _verify_blob,
            archive_workspace_projection,
            app_signing_components,
            boot_check,
            default_app_key_path,
            default_pin_path,
            default_snapshot_path,
            find_workspace_root_catalogue,
            install_workspace_root_catalogue,
            owner_change,
            pin_signing_key,
            read_state,
            canonical,
            verify_workspace_projection_archive,
        )
        self._workspace_roots_repair_error = None
        self._workspace_roots_recovery = None
        self._workspace_roots_repair_stage = "read"
        try:
            caller = self.workspace_roots_caller
            actor = caller if isinstance(caller, str) else caller.actor_root
            with self._mutation_lock, commit_intent.declare(
                    commit_intent.MIGRATION, actor=actor,
                    reason="restore the workspace registry from the selected application graph"):
                catalogue = find_workspace_root_catalogue(
                    self.workspace_roots_authority, caller=self.workspace_roots_caller)
                identity = str(self.workspace_roots_authority.store.database_path) + "\0" + str(self.clean_workspace_root)
                archive_root = default_snapshot_path().parent / "ARCHIVE" / (
                    "WORKSPACE-ROOTS-" + hashlib.sha256(identity.encode()).hexdigest().upper())
                receipts = sorted(archive_root.glob("*/receipt.json"), key=lambda path: path.stat().st_mtime_ns)
                receipt = receipts[-1] if receipts else None
                self._workspace_roots_recovery_archive = str(receipt.parent) if receipt else None
                if receipt is not None:
                    self._workspace_roots_recovery = json.loads(receipt.read_text(encoding="utf-8"))
                self.workspace_roots_boot = boot_check(
                    self.workspace_roots_authority, catalogue, caller=self.workspace_roots_caller
                )
                pending = self._workspace_roots_recovery is not None and self._workspace_roots_recovery["state"] != "complete"
                if self.clean_workspace_root is not None and (
                        (catalogue is None and (default_snapshot_path().exists()
                         or default_pin_path().exists())) or pending):
                    if catalogue is None and not default_app_key_path().exists():
                        self._workspace_roots_repair_stage = "archive"
                        if pending and self._workspace_roots_recovery["state"] != "archiving":
                            recovery = self._workspace_roots_recovery
                            verify_workspace_projection_archive(receipt.parent, recovery)
                        else:
                            archive, recovery = archive_workspace_projection(archive_root)
                            receipt = archive / "receipt.json"
                            self._workspace_roots_recovery_archive = str(archive)
                        recovery.update(state="retiring", outcome="fresh")
                        _atomic_write(receipt, canonical(recovery))
                        # Retire only verified copies; old roots never become graph authority.
                        for path in (default_snapshot_path(), default_pin_path()):
                            if path.exists():
                                expected = next(entry["sha256"] for entry in recovery["files"]
                                                if entry["name"] == path.name)
                                if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                                    raise InvalidCell("the previous workspace list changed during archival")
                                path.unlink()
                        recovery["state"] = "complete"
                        _atomic_write(receipt, canonical(recovery))
                        self._workspace_roots_recovery = recovery
                        self.workspace_roots_boot = "missing"
                        record_grant_event("workspace-roots-repair", "ok",
                            "Unverifiable local workspace files archived; ready for first registration.",
                            directory=default_snapshot_path().parent)
                        return
                    if not default_app_key_path().exists():
                        raise InvalidCell("the app signing key is missing")
                    signer, fingerprint, verifier = app_signing_components()
                    proof = signer(None).sign(KEY_CHECK)
                    if not _verify_blob(APP_KEY_ID, verifier.public_blob(), 1, KEY_CHECK, proof, verifier):
                        raise InvalidCell("the app signing key could not be verified")
                    pin = fingerprint()
                    if catalogue is None:
                        self._workspace_roots_repair_stage = "archive"
                        archive, recovery = archive_workspace_projection(archive_root)
                        receipt = archive / "receipt.json"
                        self._workspace_roots_recovery = recovery
                        self._workspace_roots_recovery_archive = str(archive)
                    else:
                        recovery = self._workspace_roots_recovery
                        verify_workspace_projection_archive(receipt.parent, recovery)
                    catalogue = find_workspace_root_catalogue(
                        self.workspace_roots_authority, caller=self.workspace_roots_caller)
                    if catalogue is None:
                        self._workspace_roots_repair_stage = "install"
                        catalogue = install_workspace_root_catalogue(self.workspace_roots_authority,
                            caller=self.workspace_roots_caller, operation_id=recovery["operation_id"])
                    if read_state(self.workspace_roots_authority, catalogue,
                                  caller=self.workspace_roots_caller)[2] is None:
                        self._workspace_roots_repair_stage = "pin"
                        pin_signing_key(self.workspace_roots_authority, catalogue, pin,
                            caller=self.workspace_roots_caller, operation_id=recovery["operation_id"],
                            key_id=APP_KEY_ID, mode=APP_WRITTEN, allow_repin=False,
                            enrolled_by="archhub-browser-workspace-settings",
                            enrolled_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
                    self.workspace_roots_boot = boot_check(self.workspace_roots_authority, catalogue,
                        caller=self.workspace_roots_caller)
                if self.clean_workspace_root is not None and catalogue is not None and self.workspace_roots_boot in (
                        "unpinned", "unsigned", "mismatch"):
                    try:
                        if not default_app_key_path().exists():
                            raise InvalidCell("the app signing key is missing")
                        signer, fingerprint, verifier = app_signing_components()
                        self._workspace_roots_repair_stage = "publish"
                        view = owner_change(
                            self.workspace_roots_authority, catalogue, {"action": "republish"},
                            caller=self.workspace_roots_caller, operation_id=str(uuid.uuid4()),
                            admission={"principal": "archhub-browser-workspace-settings"},
                            lock=self._mutation_lock, built_in=self.clean_workspace_root,
                            signer_factory=signer, fingerprint_of=fingerprint, verifier=verifier,
                            signing_key_id=APP_KEY_ID, pin_mode=APP_WRITTEN,
                            allow_key_migration=True,
                        )
                        if view["projection"] != "match":
                            raise InvalidCell("the repaired workspace registry could not be verified")
                    except Exception as exc:  # noqa: BLE001 - preserve the repair cause for Settings
                        self._workspace_roots_repair_error = str(exc)
                        record_grant_event("workspace-roots-repair", "refused", str(exc),
                                           directory=default_snapshot_path().parent)
                    else:
                        self.workspace_roots_boot = "match"
                        record_grant_event("workspace-roots-repair", "ok",
                                           "Workspace registry restored from the graph.",
                                           directory=default_snapshot_path().parent)
                if self.workspace_roots_boot == "match" and self._workspace_roots_recovery is not None and self._workspace_roots_recovery["state"] != "complete":
                    self._workspace_roots_recovery["state"] = "complete"
                    _atomic_write(receipt, canonical(self._workspace_roots_recovery))
                    if any(entry["sha256"] is not None for entry in self._workspace_roots_recovery["files"]):
                        self._workspace_roots_recovery_notice = {
                            "message": "Workspace list restored from the graph. Previous local files were archived.",
                            "archive": self._workspace_roots_recovery_archive}
        except Exception as exc:  # noqa: BLE001 - a failed check is never a match
            self.workspace_roots_boot = "unverifiable: " + type(exc).__name__
            self._workspace_roots_repair_error = str(exc)

    def _clean_workspace_roots(self, body, admission=None):
        """The owner's Workspaces settings: list, register, unregister, republish.

        The transport supplies Settings admission, never a body field. The
        existing catalogue owns validation and the hooks' projection; this route
        does not open a graph or enroll a coordination owner.
        """
        import uuid as _uuid

        from .workspace_roots_catalogue import (
            WorkspaceRootRefused,
            APP_KEY_ID,
            APP_WRITTEN,
            KEY_ID,
            app_signing_components,
            find_workspace_root_catalogue,
            install_workspace_root_catalogue,
            NO_WINDOW,
            owner_change,
            roots_view,
            folder_identity,
            read_state,
        )
        if type(body) is not dict:
            raise WorkspaceRootRefused("workspace-roots request is invalid")
        if getattr(self, "_workspace_roots_binding", None) is not None and (
                body.get("action") == "prepare"
                or set(body) & {"signature", "public_blob", "key_check", "admission_ticket"}):
            raise WorkspaceRootRefused(
                "Submit the workspace action directly; signed approvals are no longer used by this desktop.")
        if self.clean_workspace_root is None:
            # This server's own root could not be resolved at start: refuse every
            # workspace-roots request before any read or change; never adopt a
            # root resolved later from a changed map or environment.
            raise WorkspaceRootRefused(
                "this ArchHub workspace root was not resolved at start; restart ArchHub")
        request = {key: value for key, value in body.items() if key != "command_id"}
        action = request.get("action")
        if action == "browse":
            # Browse is the desktop window's own folder dialog. The graph's owner
            # runs without a visible window: a dialog opened here would never be
            # seen, so it is refused instead of opened.
            if set(request) != {"action"}:
                raise WorkspaceRootRefused("workspace-roots request is invalid")
            raise WorkspaceRootRefused(NO_WINDOW.replace("approve this change",
                                                         "choose a folder"))
        if action == "prepare":
            # The change the desktop window will ask the owner to approve.
            change = request.get("change")
            action = change.get("action") if type(change) is dict else None
            if action not in ("register", "unregister", "republish", "update-writers"):
                raise WorkspaceRootRefused("only a change can be prepared for approval")
        if action in ("list", "register", "unregister", "update-writers"):
            self._check_workspace_roots()
        boot = self.workspace_roots_boot
        if action in ("register", "unregister", "update-writers") and boot not in ("match", "missing"):
            if self._workspace_roots_repair_error == "the app signing key is missing":
                raise WorkspaceRootRefused(_KEY_RECOVERY_MESSAGE)
            raise WorkspaceRootRefused(
                "ArchHub could not restore the workspace registry: %s" % (
                    self._workspace_roots_repair_error or boot)
            )
        with self._mutation_lock:
            catalogue = find_workspace_root_catalogue(
                self.workspace_roots_authority, caller=self.workspace_roots_caller
            )
            if catalogue is None and action in ("register", "unregister", "republish", "update-writers", "set-own-agents-write"):
                catalogue = install_workspace_root_catalogue(
                    self.workspace_roots_authority,
                    operation_id=str(_uuid.uuid4()),
                    caller=self.workspace_roots_caller,
                )
        if catalogue is None:
            if action != "list" or set(request) != {"action"}:
                raise WorkspaceRootRefused("workspace-roots request is invalid")
            view = roots_view(self.workspace_roots_authority.store.revision, (), None, boot,
                              built_in=self.clean_workspace_root)
        else:
            if action in ("grant-private-root", "revoke-private-root", "set-own-agents-write"):
                from .private_root_grants import record_grant_event
                receipt_dir = self.private_root_grants.path.parent
                try:
                    self._clean_private_grant(request, action, admission)
                except Exception as exc:
                    record_grant_event("owner", "refused", "%s: %s" % (type(exc).__name__, exc),
                                       request, directory=receipt_dir)
                    raise
                record_grant_event("owner", "ok", self._last_private_grant_event.get("message", ""),
                                   request, directory=receipt_dir)
                request = {"action": "list"}
            if admission is None:
                admission = {"principal": "archhub-browser-workspace-settings"}
            signer_factory = fingerprint_of = change_verifier = None
            signing_key_id = None
            app_writes_here = (
                action in ("register", "unregister", "update-writers", "republish")
                and request.get("action") != "prepare"
                and request.get("signature") is None
                and not any(key in request for key in (
                    "public_blob", "key_check", "admission_ticket"))
            )
            if app_writes_here:
                signer_factory, fingerprint_of, change_verifier = app_signing_components()
                signing_key_id = APP_KEY_ID
            view = owner_change(
                self.workspace_roots_authority,
                catalogue,
                request,
                caller=self.workspace_roots_caller,
                admission=admission,
                operation_id=body.get("command_id") or str(_uuid.uuid4()),
                lock=self._mutation_lock,
                built_in=self.clean_workspace_root,
                signer_factory=signer_factory,
                fingerprint_of=fingerprint_of,
                verifier=change_verifier,
                signing_key_id=signing_key_id or KEY_ID,
                pin_mode=APP_WRITTEN,
                allow_key_migration=True,
            )
            if "prepared" in view:
                return view
            if action != "list":
                self.workspace_roots_boot = view["projection"]
        grant_store = getattr(self, "private_root_grants", None)
        from .workspace_roots_catalogue import private_grant_settings_view, current_registry_state
        settings_context = {}
        if getattr(self, "_workspace_roots_binding", None) is not None:
            settings_context = {
                "registry_state": current_registry_state(self.workspace_roots_authority,
                                                         caller=self.workspace_roots_caller),
                "session_reader": self._private_root_grant_sessions,
            }
        import os
        view["built_in"]["available"] = os.path.isdir(view["built_in"]["path"])
        identities = {}
        if catalogue is not None:
            with self._mutation_lock:
                _revision, registered, _pin = read_state(self.workspace_roots_authority, catalogue,
                    caller=self.workspace_roots_caller)
            identities = {entry["root_id"]: tuple(entry.get("identity", ())) for entry in registered}
        for root in view["roots"]:
            root["available"] = folder_identity(root["path"]) == identities.get(root["root_id"])
        message = "Reading workspaces…"
        if self._workspace_roots_repair_error:
            message = {
                "archive": "ArchHub could not archive the previous workspace list. Nothing was replaced.",
                "install": "ArchHub could not confirm the workspace change. Checking the saved list…",
                "pin": "The workspace list is saved in the graph, but its local copy is not ready. ArchHub will try again.",
                "publish": "The workspace list is saved in the graph, but its local copy is not ready. ArchHub will try again.",
            }.get(getattr(self, "_workspace_roots_repair_stage", "read"),
                  "ArchHub could not read your workspace list. Your files are unchanged.")
        elif view["projection"] == "match":
            message = "Workspaces are ready."
        elif catalogue is None and view["projection"] == "missing":
            message = "No other workspaces yet."
        if self._workspace_roots_repair_error == "the app signing key is missing":
            message = _KEY_RECOVERY_MESSAGE
        with self._mutation_lock:
            recovery_notice = None
            if action == "list" and not self._workspace_roots_repair_error:
                recovery_notice = getattr(self, "_workspace_roots_recovery_notice", None)
                self._workspace_roots_recovery_notice = None
        return {**view, "boot": self.workspace_roots_boot,
                "health": {"state": "error" if self._workspace_roots_repair_error else (
                    "ready" if view["projection"] == "match" else (
                        "idle" if catalogue is None and view["projection"] == "missing" else "unverified")),
                    "message": message,
                    "detail": self._workspace_roots_repair_error,
                    "recovery": recovery_notice},
                **private_grant_settings_view(grant_store, **settings_context),
                "last_private_grant_event": getattr(self, "_last_private_grant_event", None)}

    def _clean_private_grant(self, request, action, admission):
        """Grant or revoke one private-root consent (Settings admission only)."""
        from .workspace_roots_catalogue import (
            SETTINGS_IDENTITY, WorkspaceRootRefused, root_bound_registration)
        if action == "set-own-agents-write":
            if set(request) != {"action", "enabled"} or type(request["enabled"]) is not bool:
                raise WorkspaceRootRefused("Own agents write without asking must be on or off")
            vendor, session = SETTINGS_IDENTITY
            expected = "agent-session.%s" % hashlib.sha256(
                (vendor.lower() + "\0" + session).encode("utf-8")).hexdigest()
            if not isinstance(admission, dict) or admission.get("principal") != expected:
                raise WorkspaceRootRefused("Only this instance owner's Settings can change this default.")
            self.private_root_grants.set_own_agents_write_without_asking(request["enabled"])
            self._last_private_grant_event = {"action": action,
                "message": "Own agents write without asking is " + ("on." if request["enabled"] else "off.")}
            return
        allowed = {"action", "id", "runtime", "session_id", "operations", "expires_at"}
        if set(request) - allowed or not {"id", "runtime", "session_id"} <= set(request):
            raise WorkspaceRootRefused("workspace-roots request is invalid")
        principal = admission.get("principal") if isinstance(admission, dict) else None
        vendor, session = SETTINGS_IDENTITY
        expected_principal = "agent-session.%s" % hashlib.sha256(
            (vendor.lower() + "\0" + session).encode("utf-8")
        ).hexdigest()
        if principal != expected_principal:
            raise WorkspaceRootRefused(
                "the authenticated workspace-roots settings admission is required; "
                "nothing was changed")
        root_id = str(request["id"]).strip()
        runtime = str(request["runtime"]).strip().lower()
        session_id = str(request["session_id"]).strip()
        try:
            context = {}
            if getattr(self, "_workspace_roots_binding", None) is not None:
                from .workspace_roots_catalogue import current_registry_state
                context["registry_state"] = current_registry_state(self.workspace_roots_authority,
                                                                   caller=self.workspace_roots_caller)
            _container, digest, registration = root_bound_registration(
                "workspace-roots/%s/__grant__" % root_id, runtime=runtime, **context)
        except InvalidCell as exc:
            raise WorkspaceRootRefused(str(exc)) from exc
        if registration.get("privacy") != "private":
            raise WorkspaceRootRefused("only a private workspace root uses local grants")
        with self._mutation_lock:
            event = {"action": action, "root_id": root_id, "runtime": runtime,
                     "session_id": session_id, "issued_at": time.time()}
            if action == "grant-private-root":
                grant_path = self.private_root_grants.path
                pattern = grant_path.stem + ".unverifiable-*.json"
                before = set(grant_path.parent.glob(pattern))
                previous_hash = hashlib.sha256(grant_path.read_bytes()).hexdigest() if grant_path.exists() else None
                grant = self.private_root_grants.grant(
                    root_id=root_id,
                    runtime=runtime,
                    session_id=session_id,
                    root_digest=digest,
                    operations=request.get("operations"),
                    expires_at=request.get("expires_at"),
                    replace_unverifiable=True,
                )
                event.update(issued_at=grant["issued_at"], expires_at=grant["expires_at"],
                             message="Agent access granted.")
                set_aside = set(grant_path.parent.glob(pattern)) - before
                matching = [path for path in set_aside
                            if hashlib.sha256(path.read_bytes()).hexdigest() == previous_hash]
                if matching:
                    event["message"] = "unverifiable document set aside as " + sorted(matching)[-1].name
            else:
                self.private_root_grants.revoke(
                    root_id=root_id, runtime=runtime, session_id=session_id)
                event["message"] = "Agent access revoked."
            self._last_private_grant_event = event
