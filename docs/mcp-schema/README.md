# MCP Schema Snapshots

These files are generated reference snapshots for the local NetHunt MCP server.

Regenerate them after any tool or resource change:

```powershell
.\.venv\Scripts\python.exe .\scripts\export_mcp_schema.py
```

Generated files:

- `tools-list.json`: aggregate `tools/list` response from the live server
- `resources-list.json`: aggregate `resources/list` response from the live server
- `tools/*.json`: one JSON schema file per MCP tool
- `resources/*.json`: one JSON descriptor file per listed MCP resource

The exporter launches the real stdio server from `.venv`, so the snapshots reflect the protocol surface that Cursor and other MCP clients see.
