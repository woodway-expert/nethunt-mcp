# NetHunt CRM MCP Server

Local MCP server for NetHunt CRM, built with Python and the official MCP Python SDK.

## Features

- `stdio` by default for local Codex/CLI integrations
- Optional `streamable-http` transport for Docker smoke tests and MCP Inspector
- Universal folder discovery across the current NetHunt workspace
- Curated tools for auth, discovery, search, reads, comments, call logs, create, update, and delete
- Two discovery resources:
  - `nethunt://folders/readable`
  - `nethunt://folders/{folder_id}/fields`
- Structured JSON responses for every tool call:
  - Success: `ok`, `data`, `meta`
  - Error: `ok=false`, `error.code`, `error.message`, `error.details`

## Requirements

- Python 3.12+
- NetHunt CRM email
- NetHunt CRM API key

NetHunt API authentication uses the combination `email:api_key`, not the API key by itself.

Official references:

- NetHunt API docs: https://nethunt.com/integration-api
- API key help: https://help.nethunt.com/en/articles/4260105-where-to-get-nethunt-api-key
- MCP Python SDK: https://py.sdk.modelcontextprotocol.io/

## Environment

Copy `.env.example` or export the variables directly:

```powershell
$env:NETHUNT_EMAIL = "you@example.com"
$env:NETHUNT_API_KEY = "replace-me"
```

Available variables:

- `NETHUNT_EMAIL` required
- `NETHUNT_API_KEY` required
- `NETHUNT_BASE_URL` default `https://nethunt.com`
- `NETHUNT_TIMEZONE` default `Europe/Kiev`
- `NETHUNT_LOG_LEVEL` default `INFO`
- `MCP_TRANSPORT` default `stdio`
- `MCP_HOST` default `127.0.0.1`
- `MCP_PORT` default `8000`

## Native Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -e .[dev]
```

Run locally:

```powershell
.\.venv\Scripts\nethunt-mcp
```

## Codex Integration

Native `stdio` setup:

```powershell
codex mcp add nethunt-crm-local `
  --env NETHUNT_EMAIL=you@example.com `
  --env NETHUNT_API_KEY=replace-me `
  -- .\.venv\Scripts\nethunt-mcp.exe
```

Docker `stdio` setup:

```powershell
codex mcp add nethunt-crm-local-docker `
  --env NETHUNT_EMAIL=you@example.com `
  --env NETHUNT_API_KEY=replace-me `
  -- docker run --rm -i `
       -e NETHUNT_EMAIL `
       -e NETHUNT_API_KEY `
       nethunt-mcp:latest
```

This project does not modify the existing remote `nethunt-crm` entry in `~/.codex/config.toml`.

## Docker

Build the image:

```powershell
docker build -t nethunt-mcp:latest .
```

Run in `stdio` mode:

```powershell
docker run --rm -i `
  -e NETHUNT_EMAIL=you@example.com `
  -e NETHUNT_API_KEY=replace-me `
  nethunt-mcp:latest
```

Run in `streamable-http` mode for Inspector or reverse proxy testing:

```powershell
docker compose up --build
```

The compose service listens on `http://127.0.0.1:8000/mcp`.

## Tools

- `auth_test`
- `list_readable_folders`
- `list_writable_folders`
- `list_folder_fields`
- `get_record`
- `search_records`
- `list_new_records`
- `list_updated_records`
- `list_record_changes`
- `create_record`
- `update_record`
- `create_record_comment`
- `create_call_log`
- `delete_record`
- `raw_get`
- `raw_post`

### Delete Safety

`delete_record` requires `confirm=true`. Without confirmation, the tool returns a guard response with a preview payload and no deletion.

### Raw Escape Hatch

- `raw_get(operation, params)` supports only documented allowlisted GET operations.
- `raw_post(operation, body, confirm_write)` supports only documented allowlisted POST operations.
- `raw_post` returns a preview unless `confirm_write=true`.

For raw operations, path placeholders can be passed directly in the input object. Example:

```json
{
  "folder_id": "folder-123",
  "fields": {
    "Name": "Ada Lovelace"
  },
  "timeZone": "Europe/Kiev"
}
```

## Tests

```powershell
.\.venv\Scripts\python -m pytest
```
