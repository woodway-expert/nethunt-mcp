# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dev dependencies
python -m venv .venv
.venv/bin/python -m pip install -e .[dev]

# Run the server (stdio mode)
.venv/bin/nethunt-mcp

# Run the server (HTTP mode for local inspection)
MCP_TRANSPORT=streamable-http .venv/bin/nethunt-mcp
# Then connect to http://127.0.0.1:18044/mcp

# Run all tests
.venv/bin/python -m pytest

# Run a single test file
.venv/bin/python -m pytest tests/test_service.py

# Run a single test
.venv/bin/python -m pytest tests/test_service.py::test_name

# Export MCP schema snapshots
.venv/bin/python scripts/export_mcp_schema.py

# Docker (HTTP smoke tests)
docker compose up --build
```

Required env vars: `NETHUNT_EMAIL`, `NETHUNT_API_KEY`. Copy `.env.example` to `.env`.

## Architecture

The server is a [FastMCP](https://py.sdk.modelcontextprotocol.io/) application in `src/nethunt_mcp/` with these layers:

- **`server.py`** — FastMCP tool and resource registration; thin wiring only. All tool parameters use `TypeAlias` annotated types defined at the top of the file.
- **`service.py`** — NetHunt business logic: discovery caching, metadata enrichment, confirmation guards, record/field operations.
- **`client.py`** — HTTP client wrapping the NetHunt public API (`/api/v1/zapier`). Auth is HTTP Basic with `email:api_key` base64-encoded.
- **`automation_client.py`** — Separate cookie-auth HTTP client for NetHunt's internal web API. Disabled unless both `NETHUNT_AUTOMATION_COOKIE` and `NETHUNT_AUTOMATION_MANIFEST_JSON` env vars are set.
- **`automation.py`** — Automation tool implementations driven by the manifest.
- **`config.py`** — Frozen `Settings` dataclass loaded from environment via `Settings.from_env()`.
- **`errors.py`** — Normalized error types used across all layers.

### Response Contract

All tool responses follow a uniform JSON envelope:
- Success: `{"ok": true, "data": ..., "meta": ...}`
- Error: `{"ok": false, "error": {"code": ..., "message": ..., "details": ...}}`

### Confirmation Guards

Destructive and mutating operations are gated:
- `delete_record` requires `confirm=true`; without it, returns a preview payload.
- `raw_post` requires `confirm_write=true`; without it, returns a preview.
- All automation write tools require `confirm_write=true`.
- `delete_automation` requires `confirm=true`.

Never remove or weaken these guards.

### Automation Tools

Automation tools are manifest-driven: `NETHUNT_AUTOMATION_MANIFEST_JSON` describes which kinds exist and the HTTP operations for each. `NETHUNT_AUTOMATION_COOKIE` holds the browser session cookie. Both must be set for automation tools to activate. The manifest supports both REST-style (`GET`/`PUT`) and RPC command-style (`POST /api/command`) patterns.

### Testing

Tests use `pytest` + `pytest-asyncio` with `asyncio_mode = "auto"` (no need to mark individual tests with `@pytest.mark.asyncio`). Use fake/mock clients (`respx` for HTTP mocking) rather than live API calls. Each test file mirrors a source module: `test_service.py`, `test_server.py`, `test_client.py`, `test_config.py`, `test_automation.py`.

### Style

- Python 3.12+, 4-space indent, explicit type hints, `snake_case` functions/variables, `PascalCase` classes, `UPPER_CASE` constants.
- No formatter or linter is configured — follow the style of surrounding code.
- LF line endings (except Windows `.ps1` scripts which use CRLF per `.gitattributes`).
- Regenerate `docs/mcp-schema/` snapshots after adding, removing, or renaming tools or resources.
