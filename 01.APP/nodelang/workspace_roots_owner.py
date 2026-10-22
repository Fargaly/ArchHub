"""Workspaces routes shared by the desktop and the historical clean consumer."""
from __future__ import annotations

import hashlib
import time

from .universal_cell import InvalidCell


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
        from .workspace_roots_catalogue import (
            boot_check,
            find_workspace_root_catalogue,
        )
        try:
            catalogue = find_workspace_root_catalogue(
                self.workspace_roots_authority, caller=self.workspace_roots_caller
            )
            self.workspace_roots_boot = boot_check(
                self.workspace_roots_authority, catalogue, caller=self.workspace_roots_caller
            )
        except Exception as exc:  # noqa: BLE001 - a failed check is never a match
            self.workspace_roots_boot = "unverifiable: " + type(exc).__name__

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
        boot = self.workspace_roots_boot
        if action == "prepare":
            # The change the desktop window will ask the owner to approve.
            change = request.get("change")
            action = change.get("action") if type(change) is dict else None
            if action not in ("register", "unregister", "republish", "update-writers"):
                raise WorkspaceRootRefused("only a change can be prepared for approval")
        if action in ("register", "unregister", "update-writers") and boot not in ("match", "missing"):
            raise WorkspaceRootRefused(
                "the workspace-roots registry does not match the graph (%s); "
                "republish it before changing roots" % boot
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
        return {**view, "boot": self.workspace_roots_boot,
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
