from __future__ import annotations

from dataclasses import dataclass
from string import Formatter
from typing import Any

from .client import NetHuntClient
from .config import Settings
from .errors import NethuntMCPError, ValidationError


@dataclass(frozen=True, slots=True)
class RawOperation:
    method: str
    path_template: str


RAW_GET_OPERATIONS = {
    "auth_test": RawOperation("GET", "/triggers/auth-test"),
    "list_readable_folders": RawOperation("GET", "/triggers/readable-folder"),
    "list_writable_folders": RawOperation("GET", "/triggers/writable-folder"),
    "list_folder_fields": RawOperation("GET", "/triggers/folder-field/{folder_id}"),
    "find_record": RawOperation("GET", "/searches/find-record/{folder_id}"),
    "new_record": RawOperation("GET", "/triggers/new-record/{folder_id}"),
    "updated_record": RawOperation("GET", "/triggers/updated-record/{folder_id}"),
    "record_change": RawOperation("GET", "/triggers/record-change/{folder_id}"),
}

RAW_POST_OPERATIONS = {
    "create_record": RawOperation("POST", "/actions/create-record/{folder_id}"),
    "create_comment": RawOperation("POST", "/actions/create-comment/{record_id}"),
    "create_call_log": RawOperation("POST", "/actions/create-call-log/{record_id}"),
    "update_record": RawOperation("POST", "/actions/update-record/{record_id}"),
    "delete_record": RawOperation("POST", "/actions/delete-record/{record_id}"),
    "link_gmail_thread": RawOperation("POST", "/actions/link-gmail-thread/{record_id}"),
}


class NetHuntService:
    def __init__(self, client: NetHuntClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings
        self._cache: dict[str, Any] = {}

    async def close(self) -> None:
        await self.client.close()

    async def auth_test(self) -> list[dict[str, Any]]:
        return await self.client.get_json("/triggers/auth-test", retryable=True)

    async def list_readable_folders(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        return await self._cached("readable_folders", refresh, lambda: self.client.get_json("/triggers/readable-folder"))

    async def list_writable_folders(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        return await self._cached("writable_folders", refresh, lambda: self.client.get_json("/triggers/writable-folder"))

    async def list_folder_fields(self, folder_id: str, *, refresh: bool = False) -> list[dict[str, Any]]:
        self._require_string(folder_id, "folder_id")
        return await self._cached(
            f"folder_fields:{folder_id}",
            refresh,
            lambda: self.client.get_json(f"/triggers/folder-field/{folder_id}"),
        )

    async def get_record(self, folder_id: str, record_id: str) -> dict[str, Any]:
        self._require_string(folder_id, "folder_id")
        self._require_string(record_id, "record_id")
        records = await self.search_records(folder_id, record_id=record_id, limit=1)
        if not records:
            raise NethuntMCPError(
                code="not_found",
                message="The requested NetHunt record was not found.",
                details={"folder_id": folder_id, "record_id": record_id},
            )
        return records[0]

    async def search_records(
        self,
        folder_id: str,
        *,
        query: str | None = None,
        record_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        self._require_string(folder_id, "folder_id")
        if not query and not record_id:
            raise ValidationError(code="validation_error", message="Either query or record_id must be provided.")
        params: dict[str, Any] = {"limit": self._normalize_limit(limit)}
        if query:
            params["query"] = query
        if record_id:
            params["recordId"] = record_id
        return await self.client.get_json(f"/searches/find-record/{folder_id}", query=params, retryable=True)

    async def list_new_records(
        self,
        folder_id: str,
        *,
        since: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        self._require_string(folder_id, "folder_id")
        params = self._build_since_limit_query(since=since, limit=limit)
        return await self.client.get_json(f"/triggers/new-record/{folder_id}", query=params, retryable=True)

    async def list_updated_records(
        self,
        folder_id: str,
        *,
        field_names: list[str] | None = None,
        since: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        self._require_string(folder_id, "folder_id")
        params = self._build_since_limit_query(since=since, limit=limit)
        query = self._merge_query_with_field_names(params, field_names)
        return await self.client.get_json(f"/triggers/updated-record/{folder_id}", query=query, retryable=True)

    async def list_record_changes(
        self,
        folder_id: str,
        *,
        record_id: str | None = None,
        field_names: list[str] | None = None,
        since: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        self._require_string(folder_id, "folder_id")
        params = self._build_since_limit_query(since=since, limit=limit)
        if record_id:
            params["recordId"] = record_id
        query = self._merge_query_with_field_names(params, field_names)
        return await self.client.get_json(f"/triggers/record-change/{folder_id}", query=query, retryable=True)

    async def create_record(
        self,
        folder_id: str,
        *,
        fields: dict[str, Any],
        time_zone: str | None = None,
    ) -> dict[str, Any]:
        self._require_string(folder_id, "folder_id")
        if not fields:
            raise ValidationError(code="validation_error", message="fields must not be empty.")
        payload = {
            "timeZone": time_zone or self.settings.nethunt_timezone,
            "fields": fields,
        }
        return await self.client.post_json(f"/actions/create-record/{folder_id}", json_body=payload, retryable=False)

    async def update_record(
        self,
        record_id: str,
        *,
        set_fields: dict[str, Any] | None = None,
        add_fields: dict[str, Any] | None = None,
        remove_fields: dict[str, Any] | None = None,
        overwrite_default: bool = False,
    ) -> dict[str, Any]:
        self._require_string(record_id, "record_id")
        field_actions = self._build_field_actions(
            set_fields=set_fields or {},
            add_fields=add_fields or {},
            remove_fields=remove_fields or {},
        )
        payload = {"fieldActions": field_actions}
        query = {"overwrite": str(overwrite_default).lower()}
        return await self.client.post_json(
            f"/actions/update-record/{record_id}",
            query=query,
            json_body=payload,
            retryable=False,
        )

    async def create_record_comment(self, record_id: str, *, text: str) -> dict[str, Any]:
        self._require_string(record_id, "record_id")
        self._require_string(text, "text")
        return await self.client.post_json(
            f"/actions/create-comment/{record_id}",
            json_body={"text": text},
            retryable=False,
        )

    async def create_call_log(
        self,
        record_id: str,
        *,
        text: str,
        time: str | None = None,
        duration: float | None = None,
    ) -> dict[str, Any]:
        self._require_string(record_id, "record_id")
        self._require_string(text, "text")
        payload: dict[str, Any] = {"text": text}
        if time:
            payload["time"] = time
        if duration is not None:
            payload["duration"] = duration
        return await self.client.post_json(
            f"/actions/create-call-log/{record_id}",
            json_body=payload,
            retryable=False,
        )

    async def delete_record(
        self,
        folder_id: str,
        record_id: str,
        *,
        confirm: bool = False,
        preview_only: bool = False,
    ) -> dict[str, Any]:
        self._require_string(folder_id, "folder_id")
        self._require_string(record_id, "record_id")
        preview = {
            "folderId": folder_id,
            "recordId": record_id,
            "record": await self.get_record(folder_id, record_id),
        }
        if preview_only or not confirm:
            return {"preview": preview, "deleted": False}
        await self.client.post_json(f"/actions/delete-record/{record_id}", retryable=False)
        return {"preview": preview, "deleted": True, "recordId": record_id}

    async def raw_get(self, operation: str, params: dict[str, Any] | None = None) -> Any:
        raw_operation = RAW_GET_OPERATIONS.get(operation)
        if raw_operation is None:
            raise ValidationError(
                code="validation_error",
                message=f"Unsupported raw GET operation: {operation}",
                details={"operation": operation, "allowed_operations": sorted(RAW_GET_OPERATIONS)},
            )
        path, query = self._resolve_operation(raw_operation, params or {})
        return await self.client.get_json(path, query=query, retryable=True)

    async def raw_post(
        self,
        operation: str,
        body: dict[str, Any] | None = None,
        *,
        confirm_write: bool = False,
    ) -> dict[str, Any]:
        raw_operation = RAW_POST_OPERATIONS.get(operation)
        if raw_operation is None:
            raise ValidationError(
                code="validation_error",
                message=f"Unsupported raw POST operation: {operation}",
                details={"operation": operation, "allowed_operations": sorted(RAW_POST_OPERATIONS)},
            )
        path, query, json_payload = self._resolve_post_operation(raw_operation, body or {})
        if not confirm_write:
            return {
                "preview": {
                    "operation": operation,
                    "method": raw_operation.method,
                    "path": path,
                    "query": query,
                    "json": json_payload,
                },
                "executed": False,
            }
        result = await self.client.post_json(path, query=query, json_body=json_payload, retryable=False)
        return {"executed": True, "result": result}

    async def _cached(self, key: str, refresh: bool, loader: Any) -> Any:
        if not refresh and key in self._cache:
            return self._cache[key]
        value = await loader()
        self._cache[key] = value
        return value

    def _build_since_limit_query(self, *, since: str | None, limit: int | None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if since:
            params["since"] = since
        if limit is not None:
            params["limit"] = self._normalize_limit(limit)
        return params

    def _merge_query_with_field_names(
        self,
        params: dict[str, Any],
        field_names: list[str] | None,
    ) -> dict[str, Any] | list[tuple[str, Any]]:
        if not field_names:
            return params
        query_items: list[tuple[str, Any]] = list(params.items())
        for field_name in field_names:
            self._require_string(field_name, "field_name")
            query_items.append(("fieldName", field_name))
        return query_items

    def _build_field_actions(
        self,
        *,
        set_fields: dict[str, Any],
        add_fields: dict[str, Any],
        remove_fields: dict[str, Any],
    ) -> dict[str, Any]:
        overlaps = (set(set_fields) & set(add_fields)) | (set(set_fields) & set(remove_fields))
        if overlaps:
            raise ValidationError(
                code="validation_error",
                message="set_fields cannot overlap with add_fields or remove_fields.",
                details={"overlapping_fields": sorted(overlaps)},
            )
        field_actions: dict[str, Any] = {}
        for name, value in set_fields.items():
            field_actions[name] = {"overwrite": True, "add": value}
        for name, value in add_fields.items():
            field_actions.setdefault(name, {})["add"] = value
        for name, value in remove_fields.items():
            field_actions.setdefault(name, {})["remove"] = value
        if not field_actions:
            raise ValidationError(code="validation_error", message="At least one field update must be provided.")
        return field_actions

    def _resolve_operation(self, operation: RawOperation, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        path, payload = self._resolve_path(operation.path_template, params)
        query = payload.pop("query", None)
        if query is not None:
            if not isinstance(query, dict):
                raise ValidationError(code="validation_error", message="query must be an object.")
            payload.update(query)
        return path, payload

    def _resolve_path(self, path_template: str, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        payload = dict(params)
        path_params = payload.pop("path_params", {})
        if path_params and not isinstance(path_params, dict):
            raise ValidationError(code="validation_error", message="path_params must be an object.")
        placeholders = self._extract_placeholders(path_template)
        resolved_params = dict(path_params)
        for name in placeholders:
            if name in payload and name not in resolved_params:
                resolved_params[name] = payload.pop(name)
        missing = [name for name in placeholders if name not in resolved_params]
        if missing:
            raise ValidationError(
                code="validation_error",
                message="Missing path parameters for raw operation.",
                details={"missing": missing, "operation": path_template},
            )
        return path_template.format(**resolved_params), payload

    def _resolve_post_operation(
        self,
        operation: RawOperation,
        body: dict[str, Any],
    ) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
        payload = dict(body)
        path, remaining = self._resolve_path(operation.path_template, payload)
        query = remaining.pop("query", None)
        if query is not None and not isinstance(query, dict):
            raise ValidationError(code="validation_error", message="query must be an object.")
        json_payload = remaining.pop("json", None)
        if json_payload is not None and not isinstance(json_payload, dict):
            raise ValidationError(code="validation_error", message="json must be an object.")
        if json_payload is None:
            json_payload = remaining or None
        return path, query, json_payload

    def _extract_placeholders(self, path_template: str) -> list[str]:
        return [field_name for _, field_name, _, _ in Formatter().parse(path_template) if field_name]

    def _normalize_limit(self, value: int) -> int:
        if value < 1:
            raise ValidationError(code="validation_error", message="limit must be greater than 0.")
        return value

    def _require_string(self, value: str, field_name: str) -> None:
        if not value or not value.strip():
            raise ValidationError(code="validation_error", message=f"{field_name} is required.")
