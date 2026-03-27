from __future__ import annotations

from pathlib import Path


def test_compose_uses_shared_env_and_bot_sidecar() -> None:
    compose_text = Path("compose.yaml").read_text(encoding="utf-8")

    assert "nethunt-telegram-bot" in compose_text
    assert "path: .env" in compose_text
    assert "TELEGRAM_MCP_URL: http://nethunt-mcp-http:18044/mcp" in compose_text
    assert "entrypoint:" in compose_text
    assert "- nethunt-telegram-bot" in compose_text
