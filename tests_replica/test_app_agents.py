"""Area adapter checks; no real client configuration or agent request is written."""
import unittest
from unittest.mock import Mock
from types import SimpleNamespace
from nodelang.app_agents import AgentsAPI, dispatch

class AgentsTests(unittest.TestCase):
    def setUp(self):
        self.registration = Mock()
        self.registration.register.return_value={"state":"registered"}
        self.registration.repair_hooks.return_value={"state":"configured","activation_pending":True}
        self.registration.readiness.return_value = {"clients": [{"client":"codex", "state":"registered",
            "entry":{"env":{"TOKEN":"private"}}, "config":"private-path", "hooks":{"available":True,
            "state":"configured", "events":[{"event":"Stop", "state":"on", "command":"private"}]}}]}
        self.transport = Mock()
        self.transport.discover.return_value = {"status":"ok","recipients":[{"app":"codex", "id":"session-1", "title":"Builder",
            "socket":"private", "token":"private"}], "providers":{"codex":{"status":"live"}},"truncated":False,"complete_apps":["codex"]}
        self.api = AgentsAPI(transport=self.transport, registration=self.registration, environment={"HOME":"server-owned"})

    def test_readiness_projects_only_public_state_and_never_claims_connected(self):
        row = self.api.getAgentChannel("codex")
        self.assertEqual(row["state"], "registered")
        self.assertNotIn("entry", row)
        self.assertNotIn("config", row)
        self.assertNotIn("command", row["hooks"]["events"][0])
        self.assertEqual(row["connection"], "not_checked")

    def test_install_uses_existing_owner_and_server_environment_then_rereads(self):
        result = dispatch(self.api,{"action":"agent-channel","function":"installAgentChannel","args":["codex"]},guard=Mock())
        self.registration.register.assert_called_once_with("codex",consent=True,environment={"HOME":"server-owned"})
        self.assertEqual(result["result"]["state"], "registered")
        self.assertTrue(result["result"]["activationPending"])

    def test_registration_conflict_never_claims_settings_were_saved(self):
        self.registration.register.return_value={"state":"conflict"}
        self.registration.readiness.return_value={"clients":[{"client":"codex","state":"conflict"}]}
        self.assertFalse(self.api.installAgentChannel("codex")["activationPending"])

    def test_unknown_client_or_browser_environment_never_installs(self):
        with self.assertRaises(ValueError): self.api.installAgentChannel("shell-command")
        with self.assertRaises(ValueError):
            dispatch(self.api,{"action":"agent-channel","function":"installAgentChannel","args":["codex"],"environment":{}},guard=Mock())
        self.registration.register.assert_not_called()

    def test_native_discovery_does_not_expose_private_transport(self):
        result=self.api.listAgentSessions()
        self.assertEqual(result["sessions"],[{"app":"codex","id":"session-1","title":"Builder"}])
        self.assertNotIn("private",str(result))
        self.transport.request.assert_not_called()

    def test_discovery_failure_is_not_an_empty_success(self):
        self.transport.discover.side_effect=RuntimeError("owner unavailable")
        with self.assertRaises(RuntimeError): self.api.listAgentSessions()

    def test_incomplete_discovery_is_an_error_and_truncation_is_preserved(self):
        self.transport.discover.return_value={"status":"not_sent", "reason":"transport_busy"}
        with self.assertRaises(RuntimeError):self.api.listAgentSessions()
        self.transport.discover.return_value={"status":"ok", "recipients":[], "truncated":True}
        self.assertTrue(self.api.listAgentSessions()["truncated"])

    def test_guard_failure_prevents_install_and_bad_arity_is_refused(self):
        guard=Mock(side_effect=PermissionError("changed owner"))
        with self.assertRaises(PermissionError):
            dispatch(self.api,{"action":"agent-channel","function":"installAgentChannel","args":["codex"]},guard=guard)
        self.registration.register.assert_not_called()
        with self.assertRaises(ValueError):
            dispatch(self.api,{"action":"agent-channel","function":"installAgentChannel","args":["codex",True]},guard=Mock())

    def test_hook_repair_passes_reviewed_digest_to_existing_owner(self):
        self.registration.preview_hooks.return_value={"plan_digest":"a"*64,"changed":True,"events":["Stop"],"text":"private"}
        preview=self.api.previewAgentChannel("codex")
        self.assertNotIn("text",preview)
        self.api.repairAgentChannel("codex","a"*64)
        self.registration.repair_hooks.assert_called_once_with("codex",consent=True,plan_digest="a"*64,environment={"HOME":"server-owned"})
        with self.assertRaises(ValueError):self.api.repairAgentChannel("codex","forged")

    def test_native_snapshot_is_read_only_and_expired_frame_is_visible(self):
        host=SimpleNamespace(running=True,connection_state="connected",latest_snapshot=SimpleNamespace(
            revision=7,presence_expires_at=120,frame_expires_at=110,directive={"motion":"idle","compact_message":"Ready"}))
        self.api.companion=host
        report=self.api.getDesktopCompanion(now=100)
        self.assertEqual(report["status"],"current")
        self.assertEqual(report["message"],"Ready")
        self.assertEqual(self.api.getDesktopCompanion(now=111)["status"],"expired")
        self.api.companion=None
        with self.assertRaises(RuntimeError): self.api.getDesktopCompanion(now=100)
        self.api.companion=SimpleNamespace(running=False)
        self.assertEqual(self.api.getDesktopCompanion(now=100)["status"],"not_running")

if __name__ == "__main__": unittest.main()
