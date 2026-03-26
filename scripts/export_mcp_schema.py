from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters, stdio_client

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "docs" / "mcp-schema"
TOOLS_DIR = OUTPUT_DIR / "tools"
RESOURCES_DIR = OUTPUT_DIR / "resources"


def _venv_python() -> Path:
    if os.name == "nt":
        return REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    return REPO_ROOT / ".venv" / "bin" / "python"


def _prepend_path(value: str, existing: str | None) -> str:
    if not existing:
        return value
    return os.pathsep.join([value, existing])


def _sanitize_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return cleaned or "item"


def _model_payload(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_split_files(directory: Path, items: list[Any], filename_builder: Any) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    written: set[Path] = set()
    for item in items:
        path = directory / filename_builder(item)
        _write_json(path, _model_payload(item))
        written.add(path.resolve())
    for existing in directory.glob("*.json"):
        if existing.resolve() not in written:
            existing.unlink()


def _resource_filename(resource: Any) -> str:
    name = getattr(resource, "name", None) or getattr(resource, "uri", "resource")
    return f"{_sanitize_name(str(name))}.json"


def _tool_filename(tool: Any) -> str:
    return f"{_sanitize_name(tool.name)}.json"


def _server_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = _prepend_path(str(REPO_ROOT / "src"), env.get("PYTHONPATH"))
    env["NETHUNT_EMAIL"] = env.get("NETHUNT_EMAIL") or "schema@example.com"
    env["NETHUNT_API_KEY"] = env.get("NETHUNT_API_KEY") or "schema-placeholder"
    env["MCP_TRANSPORT"] = "stdio"
    return env


async def export_schema() -> None:
    python_path = _venv_python()
    if not python_path.exists():
        raise SystemExit(f"Python executable not found: {python_path}")

    params = StdioServerParameters(
        command=str(python_path),
        args=["-m", "nethunt_mcp"],
        env=_server_env(),
        cwd=REPO_ROOT,
    )

    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools_result = await session.list_tools()
            resources_result = await session.list_resources()

    tools_payload = _model_payload(tools_result)
    resources_payload = _model_payload(resources_result)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_DIR / "tools-list.json", tools_payload)
    _write_json(OUTPUT_DIR / "resources-list.json", resources_payload)
    _write_split_files(TOOLS_DIR, tools_result.tools, _tool_filename)
    _write_split_files(RESOURCES_DIR, resources_result.resources, _resource_filename)


def main() -> None:
    asyncio.run(export_schema())


if __name__ == "__main__":
    main()
