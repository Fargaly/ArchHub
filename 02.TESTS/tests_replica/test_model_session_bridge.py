import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

PRODUCT = Path(__file__).resolve().parents[2]
from nodelang import model_session_bridge as bridge, model_router as router
from nodelang.model_execution_broker import local_cli_chat_command, ModelExecutionBroker

TOOL = {"type": "function", "function": {"name": "Read", "parameters": {"type": "object"}}}
SECRET = 'test-credential-material-123456789'


class BridgeTests(unittest.TestCase):
    def test_live_catalogue_uses_app_discovery(self):
        groups = {"groups": [{"items": [
            {"route": "vendor/tool:free", "tag": "BYO", "supported_parameters": ["tools"]},
            {"route": "vendor/no-tools:free", "tag": "BYO"},
            {"route": "ollama/tiny", "tag": "LOCAL"},
        ]}], "source_errors": {}}
        providers = [{"id": "openrouter", "state": "keyed"}, {"id": "copilot", "state": "installed"},
                     {"id": "antigravity", "state": "installed"}]
        with patch.object(bridge.catalogue, 'live_model_groups', return_value=groups), patch.object(router, 'provider_rows', return_value=providers):
            result = bridge.brains()
        names = {r['name']: r for r in result['brains']}
        self.assertIn('openrouter/vendor/tool:free', names)
        self.assertNotIn('openrouter/vendor/no-tools:free', names)
        self.assertIn('ollama/tiny', names)
        self.assertTrue(names['copilot']['callable'])
        self.assertFalse(names['antigravity']['callable'])

    def test_real_router_stubbed_fetch_text_and_ollama_tool_call(self):
        sent = []
        def fetch(request, **kwargs):
            body = json.loads(request.data)
            sent.append(body)
            self.assertEqual(body['tools'], [TOOL])
            return io.BytesIO(json.dumps({"model": "tiny", "done": True, "message": {"content": "Reading.", "tool_calls": [
                {"function": {"name": "Read", "arguments": {"file_path": "README.md"}}}
            ]}}).encode())
        def chat(route, messages, **kwargs):
            return router.route_chat(route, messages, opener=fetch, cloud_session=None, **kwargs)
        result = bridge.answer({'brain': 'ollama/tiny', 'messages': [{'role': 'user', 'content': 'read'}], 'tools': [TOOL]},
                               workspace=PRODUCT, chat=chat, secrets_loader=lambda _: '')
        self.assertEqual(result['text'], 'Reading.')
        self.assertEqual(result['tools'][0]['input'], {'file_path': 'README.md'})
        self.assertEqual(len(sent), 1)

    def test_keys_redacted_in_text_tool_arguments_and_model(self):
        def chat(*args, **kwargs):
            return {'text': SECRET, 'actual_model': SECRET, 'tool_calls': [{'id': 'x', 'name': 'Read', 'arguments': {'file_path': SECRET}}]}
        result = bridge.answer({'brain': 'ollama/tiny', 'messages': [{'role': 'user', 'content': 'hello'}], 'tools': [TOOL]},
                               workspace=PRODUCT, chat=chat, secrets_loader=lambda _: SECRET)
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertIn('[redacted]', json.dumps(result))

    def test_paid_route_refused_before_dispatch(self):
        for route in ('openai-api/gpt', 'openrouter/vendor/model'):
            with self.assertRaisesRegex(ValueError, '--paid'):
                bridge.answer({'brain': route}, workspace=PRODUCT, chat=lambda *_: self.fail('dispatched'))

    def test_invalid_or_unknown_tools_refused(self):
        for call in ({'id': 'x', 'name': 'Delete', 'arguments': {}}, {'id': 'x', 'name': 'Read', 'arguments': '[]'}):
            with self.assertRaises(ValueError):
                bridge.answer({'brain': 'ollama/tiny', 'messages': [], 'tools': [TOOL]}, workspace=PRODUCT,
                              chat=lambda *a, **k: {'text': '', 'tool_calls': [call]})

    def test_copilot_uses_same_broker_and_medium_effort(self):
        command = local_cli_chat_command('copilot', 'copilot.exe')
        self.assertIn('--silent', command)
        self.assertIn('medium', command)
        broker = ModelExecutionBroker(workspace_root=PRODUCT, executables={'local-cli:copilot': 'copilot.exe'})
        self.assertEqual(broker.local_cli_executable('copilot'), 'copilot.exe')

    def test_router_accepts_session_tool_count_but_stays_bounded(self):
        self.assertEqual(len(router._checked_tools([TOOL] * 100)), 100)
        with self.assertRaises(router.ModelRouteRefused):
            router._checked_tools([TOOL] * 257)

    def test_unknown_free_model_is_not_tool_capable_when_catalogue_is_unavailable(self):
        with patch.object(router, '_openrouter_free_tool_catalogue_models', return_value=((), 'unavailable')):
            self.assertFalse(router._openrouter_free_pick_allowed(
                'vendor/unverified:free', None, require_tools=True))


    def test_model_duration_uses_typed_node_parameters_and_rejects_invalid_input(self):
        observed = []
        def chat(*args, **kwargs):
            observed.append(kwargs)
            return {'text': 'Answer', 'tool_calls': []}
        request = {'brain': 'ollama/tiny', 'messages': [], 'parameters': {'model_request_ms': 12345}}
        bridge.answer(request, workspace=PRODUCT, chat=chat, secrets_loader=lambda _: '')
        self.assertEqual(observed[-1]['timeout'], 12.345)
        for invalid in (True, 0, -1, '12345', 3600001):
            with self.assertRaises(ValueError):
                bridge.answer({**request, 'parameters': {'model_request_ms': invalid}},
                    workspace=PRODUCT, chat=chat, secrets_loader=lambda _: '')
        self.assertEqual(len(observed), 1)
        bridge.answer({'brain': 'local-cli/codex', 'messages': [], 'session': {'access': 'read'}},
            workspace=PRODUCT, chat=chat, secrets_loader=lambda _: '')
        self.assertEqual(observed[-1]['timeout'], 240)


if __name__ == '__main__':
    unittest.main(verbosity=2)
