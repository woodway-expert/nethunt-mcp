# NetHunt CRM MCP Server

Local MCP server for NetHunt CRM, built with Python and the official MCP Python SDK.

## Features

- `stdio` by default for local Codex/CLI integrations
- Optional `streamable-http` transport for Docker smoke tests and MCP Inspector
- Universal folder discovery across the current NetHunt workspace
- Curated tools for auth, discovery, search, reads, comments, call logs, create, update, and delete
- Optional automation tools for internal NetHunt workflow APIs via a separate cookie-auth client
- Granular automation editor tools for activation, renaming, steps, and splits
- Additive metadata enrichment for folders, fields, records, and automation graphs with stable IDs and provenance
- Generated MCP schema snapshots under `docs/mcp-schema/`
- Two discovery resources:
  - `nethunt://folders/readable`
  - `nethunt://folders/{folder_id}/fields`
  - `nethunt://automations/capabilities`
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
- `NETHUNT_AUTOMATION_BASE_URL` default `https://nethunt.com`
- `NETHUNT_AUTOMATION_COOKIE` optional unless you use automation tools
- `NETHUNT_AUTOMATION_EXTRA_HEADERS_JSON` optional JSON object of extra headers for automation requests
- `NETHUNT_AUTOMATION_MANIFEST_JSON` optional JSON object describing supported automation kinds and endpoints
- `NETHUNT_TIMEZONE` default `Europe/Kiev`
- `NETHUNT_LOG_LEVEL` default `INFO`
- `MCP_TRANSPORT` default `stdio`
- `MCP_HOST` default `127.0.0.1`
- `MCP_PORT` default `18044`

Automation support uses a separate, thin wrapper over NetHunt's internal web API. It is disabled unless both `NETHUNT_AUTOMATION_COOKIE` and `NETHUNT_AUTOMATION_MANIFEST_JSON` are set.

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

## Cursor Integration

The repository includes `scripts/run_cursor_mcp.ps1`, which:

- loads local values from `.env`
- sets `PYTHONPATH` to `src`
- launches the server from `.venv`

That lets Cursor use local credentials without copying secrets into the global MCP config.

Add this entry to `C:\Users\system_administrator\.cursor\mcp.json`:

```json
{
  "mcpServers": {
    "nethunt-crm-local": {
      "command": "powershell",
      "args": [
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "C:\\Users\\system_administrator\\Documents\\Repos\\NetHunt-Configuration\\scripts\\run_cursor_mcp.ps1"
      ]
    }
  }
}
```

If you already have other global MCP servers, merge the new `nethunt-crm-local` entry into the existing `mcpServers` object instead of replacing it.

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

The compose service listens on `http://127.0.0.1:18044/mcp`.

## Tools

- `auth_test`
- `list_readable_folders`
- `list_writable_folders`
- `list_folder_fields`
- `list_automation_field_references`
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
- `list_automation_kinds`
- `list_automations`
- `get_automation`
- `create_automation`
- `update_automation`
- `delete_automation`
- `set_automation_enabled`
- `activate_automation`
- `deactivate_automation`
- `rename_automation`
- `get_automation_step_details`
- `add_automation_step`
- `update_automation_step`
- `delete_automation_step`
- `add_automation_split`

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

### Discovery Metadata

- `list_readable_folders` and `list_writable_folders` keep the raw folder objects but also add `folderId`, `folderName`, `access`, and `metadataSource`.
- `list_folder_fields(folder_id)` keeps the raw field objects but also adds `folderId`, `fieldName`, `fieldId`, `fieldType`, `fieldOptions`, `referenceCount`, `referencedBy`, `referencePaths`, and `metadataSource`.
- Record read/search tools (`get_record`, `search_records`, `list_new_records`, `list_updated_records`, `list_record_changes`) now enrich record-like payloads with `folderId`, `fieldIds`, `fieldMetadata`, and `fieldNames` when folder metadata is available. If field enrichment fails, the original record payload is still returned.
- `metadataSource` shows whether a value came directly from the folder metadata or was inferred from automation imports.

### Automation Tools

- Lifecycle automation tools remain manifest-driven: `list_automations`, `get_automation`, `create_automation`, `update_automation`, `delete_automation`, and `set_automation_enabled`.
- `list_automations` and automation write results now include normalized `imports`, top-level `fieldReferences`, and `referenceCount` in addition to the raw NetHunt payload.
- `get_automation(include_branches=true)` returns a normalized branch/step graph with stable `branchId`, `branchNum`, `stepId`, `stepNum`, `role`, `type`, per-step `fieldReferences`, and a summarized `branchGraph`.
- `get_automation_step_details` still returns the raw step-detail payload, but now also adds `kind`, `automationId`, `stepNum`, `listOptions`, and, when available, `branchId`, `stepId`, `role`, `type`, and `fieldReferences`.
- `list_automation_field_references(folder_id)` shows which `fieldId` values are already referenced by existing automations for a folder, plus `referencePaths`, best-effort `fieldName` / `fieldType` / `fieldOptions`, and `metadataSource`.
- Editor automation tools expose the captured NetHunt RPC model directly: activation, deactivation, rename, step detail reads, step add/update/delete, and split add.
- All mutating automation tools use `preview -> confirm` semantics.
- `delete_automation` requires `confirm=true`.
- Every other automation write tool requires `confirm_write=true`.
- `list_automation_kinds` returns only manifest entries that define the full lifecycle, and now also reports optional `editorOperations`.
- Automation error envelopes such as `status: ERROR` are normalized into MCP error codes like `not_found` and `validation_error` instead of surfacing as generic `invalid_response`.
- Manifest templates can reference `kind`, `automation_id`, `enabled`, `enabled_command`, `payload`, and `operation_name`, plus tool-specific context such as `name`, `step_num`, `step_type`, `list_options`, `branch_id`, `role`, `step_id`, and `child_branch_num`.

#### Getting Automation Cookies

`NETHUNT_AUTOMATION_COOKIE` is not an API key. It is the browser session `Cookie` header from an authenticated NetHunt web session.

Use this workflow:

1. Log in to NetHunt in Chrome, Edge, or another Chromium-based browser.
2. Open DevTools with `F12`.
3. Open the `Network` tab and filter by `Fetch/XHR`.
4. In NetHunt, open the page that uses the automation feature you want to reverse-engineer, for example Workflows.
5. Click one of the internal API requests for that page, for example a request like `/api/workflows`.
6. In `Headers`, copy the full `Cookie` request header value into `NETHUNT_AUTOMATION_COOKIE`.
7. If the same request includes additional auth headers such as `Authorization`, `X-CSRF-Token`, or similar custom headers, copy them into `NETHUNT_AUTOMATION_EXTRA_HEADERS_JSON`.

Example:

```powershell
$env:NETHUNT_AUTOMATION_COOKIE = "session=...; other_cookie=..."
$env:NETHUNT_AUTOMATION_EXTRA_HEADERS_JSON = '{"Authorization":"Basic ...","X-CSRF-Token":"..."}'
```

Notes:

- Treat the cookie like a password. Do not commit it to git or paste it into `README.md`.
- Session cookies expire. If automation calls start returning `401` or `403`, capture a fresh value from the browser.
- Some NetHunt internal endpoints send both `Cookie` and `Authorization`. If the captured request has both, copy both. Do not assume the cookie alone is sufficient.
- The cookie alone is not enough to discover endpoints. You still need `NETHUNT_AUTOMATION_MANIFEST_JSON` with the exact method, path, and response shape for each supported automation kind.

Minimal manifest example:

```json
{
  "workflow": {
    "label": "Workflows",
    "name_path": "attributes.name",
    "enabled_path": "attributes.enabled",
    "operations": {
      "list": {
        "method": "GET",
        "path": "/api/workflows",
        "response_path": "items"
      },
      "get": {
        "method": "GET",
        "path": "/api/workflows/{automation_id}",
        "response_path": "item"
      },
      "create": {
        "method": "POST",
        "path": "/api/workflows",
        "json": "$payload",
        "response_path": "item"
      },
      "update": {
        "method": "PUT",
        "path": "/api/workflows/{automation_id}",
        "json": "$payload",
        "response_path": "item"
      },
      "delete": {
        "method": "DELETE",
        "path": "/api/workflows/{automation_id}"
      },
      "set_enabled": {
        "method": "PATCH",
        "path": "/api/workflows/{automation_id}/state",
        "json": {
          "enabled": "$enabled"
        },
        "response_path": "item"
      }
    }
  }
}
```

Command-based editor example:

```json
{
  "workflow": {
    "label": "Workflows",
    "name_path": "result.automation.name",
    "enabled_path": "result.automation.enabled",
    "operations": {
      "list": {
        "method": "POST",
        "path": "/api/commands",
        "json": [
          {
            "service": "automation",
            "name": "getAutomations",
            "data": {
              "workspaceId": "workspace-id"
            },
            "id": "1"
          }
        ],
        "response_path": "0.result.automations"
      },
      "get": {
        "method": "POST",
        "path": "/api/command",
        "json": {
          "service": "automation",
          "name": "getAutomationDetails",
          "data": {
            "workspaceId": "workspace-id",
            "automationId": "{automation_id}"
          }
        },
        "response_path": "result.automation"
      },
      "create": {
        "method": "POST",
        "path": "/api/command",
        "json": "$payload"
      },
      "update": {
        "method": "POST",
        "path": "/api/command",
        "json": "$payload"
      },
      "delete": {
        "method": "POST",
        "path": "/api/command",
        "json": {
          "service": "automation",
          "name": "deleteAutomation",
          "data": {
            "workspaceId": "workspace-id",
            "automationId": "{automation_id}"
          }
        }
      },
      "set_enabled": {
        "method": "POST",
        "path": "/api/command",
        "json": {
          "service": "automation",
          "name": "{enabled_command}",
          "data": {
            "workspaceId": "workspace-id",
            "automationId": "{automation_id}"
          }
        }
      }
    },
    "editor_operations": {
      "rename": {
        "method": "POST",
        "path": "/api/command",
        "json": {
          "service": "automation",
          "name": "updateAutomationName",
          "data": {
            "workspaceId": "workspace-id",
            "automationId": "{automation_id}",
            "name": "{name}"
          }
        }
      },
      "get_step_details": {
        "method": "POST",
        "path": "/api/commands",
        "json": [
          {
            "service": "automation",
            "name": "getStepDetails",
            "data": {
              "workspaceId": "workspace-id",
              "automationId": "{automation_id}",
              "stepNum": "$step_num",
              "listOptions": "$list_options"
            },
            "id": "90"
          }
        ],
        "response_path": "0.result"
      },
      "add_step": {
        "method": "POST",
        "path": "/api/command",
        "json": {
          "service": "automation",
          "name": "addStep",
          "data": {
            "workspaceId": "workspace-id",
            "automationId": "{automation_id}",
            "branchId": "$branch_id",
            "role": "$role",
            "type": "$step_type",
            "options": "$payload"
          }
        }
      }
    }
  }
}
```

## Schema Export

Export the current MCP protocol surface into local reference files:

```powershell
.\.venv\Scripts\python.exe .\scripts\export_mcp_schema.py
```

This writes:

- `docs/mcp-schema/tools-list.json`
- `docs/mcp-schema/resources-list.json`
- `docs/mcp-schema/tools/*.json`
- `docs/mcp-schema/resources/*.json`

Regenerate these snapshots any time you add, remove, or rename MCP tools or resources.

## Tests

```powershell
.\.venv\Scripts\python -m pytest
```
