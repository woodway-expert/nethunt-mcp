from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from .client import NetHuntClient
from .config import Settings
from .errors import ConfigError, NethuntMCPError
from .service import NetHuntService


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(levelname)s %(name)s %(message)s",
    )


class NetHuntMCPApplication:
    def __init__(self, service: NetHuntService, settings: Settings) -> None:
        self.service = service
        self.settings = settings
        self.server = FastMCP(
            "NetHunt CRM",
            instructions=(
                "Use discovery tools first to inspect folders and fields. "
                "Delete operations require explicit confirmation."
            ),
            host=settings.mcp_host,
            port=settings.mcp_port,
            json_response=True,
        )
        self._register_tools()
        self._register_resources()

    async def auth_test(self) -> dict[str, Any]:
        return await self._execute("auth_test", self.service.auth_test)

    async def list_readable_folders(self, refresh: bool = False) -> dict[str, Any]:
        return await self._execute(
            "list_readable_folders",
            lambda: self.service.list_readable_folders(refresh=refresh),
            refresh=refresh,
        )

    async def list_writable_folders(self, refresh: bool = False) -> dict[str, Any]:
        return await self._execute(
            "list_writable_folders",
            lambda: self.service.list_writable_folders(refresh=refresh),
            refresh=refresh,
        )

    async def list_folder_fields(self, folder_id: str, refresh: bool = False) -> dict[str, Any]:
        return await self._execute(
            "list_folder_fields",
            lambda: self.service.list_folder_fields(folder_id, refresh=refresh),
            folder_id=folder_id,
            refresh=refresh,
        )

    async def get_record(self, folder_id: str, record_id: str) -> dict[str, Any]:
        return await self._execute(
            "get_record",
            lambda: self.service.get_record(folder_id, record_id),
            folder_id=folder_id,
            record_id=record_id,
        )

    async def search_records(
        self,
        folder_id: str,
        query: str | None = None,
        record_id: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        return await self._execute(
            "search_records",
            lambda: self.service.search_records(folder_id, query=query, record_id=record_id, limit=limit),
            folder_id=folder_id,
            query=query,
            record_id=record_id,
            limit=limit,
        )

    async def list_new_records(
        self,
        folder_id: str,
        since: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        return await self._execute(
            "list_new_records",
            lambda: self.service.list_new_records(folder_id, since=since, limit=limit),
            folder_id=folder_id,
            since=since,
            limit=limit,
        )

    async def list_updated_records(
        self,
        folder_id: str,
        field_names: list[str] | None = None,
        since: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        return await self._execute(
            "list_updated_records",
            lambda: self.service.list_updated_records(folder_id, field_names=field_names, since=since, limit=limit),
            folder_id=folder_id,
            field_names=field_names,
            since=since,
            limit=limit,
        )

    async def list_record_changes(
        self,
        folder_id: str,
        record_id: str | None = None,
        field_names: list[str] | None = None,
        since: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        return await self._execute(
            "list_record_changes",
            lambda: self.service.list_record_changes(
                folder_id,
                record_id=record_id,
                field_names=field_names,
                since=since,
                limit=limit,
            ),
            folder_id=folder_id,
            record_id=record_id,
            field_names=field_names,
            since=since,
            limit=limit,
        )

    async def create_record(
        self,
        folder_id: str,
        fields: dict[str, Any],
        time_zone: str | None = None,
    ) -> dict[str, Any]:
        return await self._execute(
            "create_record",
            lambda: self.service.create_record(folder_id, fields=fields, time_zone=time_zone),
            folder_id=folder_id,
        )

    async def update_record(
        self,
        record_id: str,
        set_fields: dict[str, Any] | None = None,
        add_fields: dict[str, Any] | None = None,
        remove_fields: dict[str, Any] | None = None,
        overwrite_default: bool = False,
    ) -> dict[str, Any]:
        return await self._execute(
            "update_record",
            lambda: self.service.update_record(
                record_id,
                set_fields=set_fields,
                add_fields=add_fields,
                remove_fields=remove_fields,
                overwrite_default=overwrite_default,
            ),
            record_id=record_id,
        )

    async def create_record_comment(self, record_id: str, text: str) -> dict[str, Any]:
        return await self._execute(
            "create_record_comment",
            lambda: self.service.create_record_comment(record_id, text=text),
            record_id=record_id,
        )

    async def create_call_log(
        self,
        record_id: str,
        text: str,
        time: str | None = None,
        duration: float | None = None,
    ) -> dict[str, Any]:
        return await self._execute(
            "create_call_log",
            lambda: self.service.create_call_log(record_id, text=text, time=time, duration=duration),
            record_id=record_id,
        )

    async def delete_record(
        self,
        folder_id: str,
        record_id: str,
        confirm: bool = False,
        preview_only: bool = False,
    ) -> dict[str, Any]:
        if not confirm:
            preview = await self._execute(
                "delete_record",
                lambda: self.service.delete_record(folder_id, record_id, confirm=False, preview_only=True),
                folder_id=folder_id,
                record_id=record_id,
                confirm=confirm,
                preview_only=preview_only,
            )
            if preview["ok"]:
                return self._error_response(
                    NethuntMCPError(
                        code="confirmation_required",
                        message="Set confirm=true to delete the record.",
                        details=preview["data"],
                    ),
                    "delete_record",
                    folder_id=folder_id,
                    record_id=record_id,
                    confirm=confirm,
                    preview_only=preview_only,
                )
            return preview
        return await self._execute(
            "delete_record",
            lambda: self.service.delete_record(folder_id, record_id, confirm=True, preview_only=preview_only),
            folder_id=folder_id,
            record_id=record_id,
            confirm=confirm,
            preview_only=preview_only,
        )

    async def raw_get(self, operation: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._execute(
            "raw_get",
            lambda: self.service.raw_get(operation, params=params),
            operation=operation,
        )

    async def raw_post(
        self,
        operation: str,
        body: dict[str, Any] | None = None,
        confirm_write: bool = False,
    ) -> dict[str, Any]:
        if not confirm_write:
            preview = await self._execute(
                "raw_post",
                lambda: self.service.raw_post(operation, body=body, confirm_write=False),
                operation=operation,
                confirm_write=confirm_write,
            )
            if preview["ok"]:
                return self._error_response(
                    NethuntMCPError(
                        code="confirmation_required",
                        message="Set confirm_write=true to execute raw POST operations.",
                        details=preview["data"],
                    ),
                    "raw_post",
                    operation=operation,
                    confirm_write=confirm_write,
                )
            return preview
        return await self._execute(
            "raw_post",
            lambda: self.service.raw_post(operation, body=body, confirm_write=True),
            operation=operation,
            confirm_write=confirm_write,
        )

    async def readable_folders_resource(self) -> str:
        payload = await self.list_readable_folders(refresh=False)
        return json.dumps(payload, ensure_ascii=True, indent=2)

    async def folder_fields_resource(self, folder_id: str) -> str:
        payload = await self.list_folder_fields(folder_id, refresh=False)
        return json.dumps(payload, ensure_ascii=True, indent=2)

    def run(self) -> None:
        if self.settings.mcp_transport == "stdio":
            self.server.run(transport="stdio")
            return
        self.server.run(
            transport="streamable-http",
        )

    async def _execute(self, operation: str, fn: Any, **meta: Any) -> dict[str, Any]:
        try:
            data = await fn()
        except Exception as exc:  # noqa: BLE001
            return self._error_response(exc, operation, **meta)
        return {"ok": True, "data": data, "meta": self._meta(operation, **meta)}

    def _error_response(self, exc: Exception, operation: str, **meta: Any) -> dict[str, Any]:
        normalized = exc if isinstance(exc, NethuntMCPError) else NethuntMCPError(
            code="internal_error",
            message="Unexpected internal server error.",
            details={"reason": str(exc)},
        )
        return {
            "ok": False,
            "data": None,
            "meta": self._meta(operation, **meta),
            "error": {
                "code": normalized.code,
                "message": normalized.message,
                "details": normalized.details,
            },
        }

    def _meta(self, operation: str, **meta: Any) -> dict[str, Any]:
        payload = {
            "operation": operation,
            "transport": self.settings.mcp_transport,
            "source": "nethunt",
        }
        payload.update({key: value for key, value in meta.items() if value is not None})
        return payload

    def _register_tools(self) -> None:
        self.server.tool(name="auth_test")(self.auth_test)
        self.server.tool(name="list_readable_folders")(self.list_readable_folders)
        self.server.tool(name="list_writable_folders")(self.list_writable_folders)
        self.server.tool(name="list_folder_fields")(self.list_folder_fields)
        self.server.tool(name="get_record")(self.get_record)
        self.server.tool(name="search_records")(self.search_records)
        self.server.tool(name="list_new_records")(self.list_new_records)
        self.server.tool(name="list_updated_records")(self.list_updated_records)
        self.server.tool(name="list_record_changes")(self.list_record_changes)
        self.server.tool(name="create_record")(self.create_record)
        self.server.tool(name="update_record")(self.update_record)
        self.server.tool(name="create_record_comment")(self.create_record_comment)
        self.server.tool(name="create_call_log")(self.create_call_log)
        self.server.tool(name="delete_record")(self.delete_record)
        self.server.tool(name="raw_get")(self.raw_get)
        self.server.tool(name="raw_post")(self.raw_post)

    def _register_resources(self) -> None:
        self.server.resource("nethunt://folders/readable")(self.readable_folders_resource)
        self.server.resource("nethunt://folders/{folder_id}/fields")(self.folder_fields_resource)


def build_application(settings: Settings | None = None) -> NetHuntMCPApplication:
    resolved_settings = settings or Settings.from_env()
    configure_logging(resolved_settings.nethunt_log_level)
    client = NetHuntClient(resolved_settings)
    service = NetHuntService(client, resolved_settings)
    return NetHuntMCPApplication(service, resolved_settings)


def run_application() -> None:
    try:
        application = build_application()
    except ConfigError as exc:
        raise SystemExit(exc.message) from exc
    try:
        application.run()
    finally:
        asyncio.run(application.service.close())
