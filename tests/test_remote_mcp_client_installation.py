import pytest

from nodelang.remote_mcp_client_installation import (
    MCP_URL,
    RemoteMcpClientRefused,
    install_target,
)


def test_remote_mcp_client_targets_are_https_and_include_private_mcp_url():
    notion = install_target("notion")
    gemini = install_target("gemini")

    assert notion["open_url"].startswith("https://www.notion.so/")
    assert gemini["open_url"].startswith("https://gemini.google.com/")
    assert notion["mcp_url"] == MCP_URL == gemini["mcp_url"]
    assert notion["prefill"] is False
    assert gemini["prefill"] is False


def test_remote_mcp_client_rejects_unknown_provider():
    with pytest.raises(RemoteMcpClientRefused):
        install_target("slack")
