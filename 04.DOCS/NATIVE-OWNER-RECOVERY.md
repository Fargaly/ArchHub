# Shared messages and governed Work

The general agent MCP connector no longer has an owner-status, rebind or recovery mode. It exposes `send(to, text)` and `read(since)` immediately. See [the shared mailbox contract](CLEAN-COORDINATION-ENDPOINT.md).

A restarted connector reads current public Workshop notes and continues with its server-recorded identity. It does not enroll a substitute owner or replay a task. Host session metadata gives a stable readable session label across connector restarts while the OS-observed identity key changes.

Governed Work and host/file effects remain separate capabilities. `NativeAgentSession`, `InstalledWorkshopInboxReader`, native Work recovery, write permits and completion receipts still protect those effects. The ordinary mailbox neither supplies a Work capability nor bypasses a failed Work/file gate. Private native hook compositions and selected-Work profiles must use their existing governed authority; a successful chat message does not prove they are active or a task is complete.

The retired owner-rebind tests described by earlier versions of this page were tests of the removed general coordination surface. The current message courts are `02.TESTS/tests/test_agentlink2.py` and `02.TESTS/tests/test_agentlink2_round3.py`. Installed acceptance belongs to the release integrator.
