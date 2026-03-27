from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import json
import re
from string import Formatter
from typing import Any

from .automation import (
    AutomationKind,
    AutomationRegistry,
    extract_response_payload,
    get_path_value,
    normalize_automation,
    render_template,
)
from .automation_client import NetHuntAutomationClient
from .client import NetHuntClient
from .config import Settings
from .errors import ConfigError, NethuntMCPError, ValidationError


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

DEFAULT_AUTOMATION_STEP_LIST_OPTIONS = {
    "sortBy": [{"key": "updatedAt", "asc": False}],
    "limit": 25,
}
FIELD_TOKEN_PATTERN = re.compile(r"\{\{nh:([^}]+)\}\}")
FIELD_NAME_KEYS = ("name", "label", "title", "fieldName")
FIELD_ID_KEYS = ("fieldId", "id", "_id")
FIELD_TYPE_KEYS = ("fieldType", "type", "valueType", "dataType", "kind")
FIELD_OPTION_KEYS = ("options", "selectOptions", "choices", "values", "allowedValues")


class NetHuntService:
    def __init__(
        self,
        client: NetHuntClient,
        settings: Settings,
        *,
        automation_client: NetHuntAutomationClient | None = None,
    ) -> None:
        self.client = client
        self.automation_client = automation_client
        self.settings = settings
        self._cache: dict[str, Any] = {}
        self._automation_registry: AutomationRegistry | None = None

    async def close(self) -> None:
        await self.client.close()
        if self.automation_client is not None and self.automation_client is not self.client:
            await self.automation_client.close()

    async def auth_test(self) -> list[dict[str, Any]]:
        return await self.client.get_json("/triggers/auth-test", retryable=True)

    async def list_readable_folders(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        return await self._cached(
            "readable_folders",
            refresh,
            lambda: self._load_folder_catalog("/triggers/readable-folder", access="read"),
        )

    async def list_writable_folders(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        return await self._cached(
            "writable_folders",
            refresh,
            lambda: self._load_folder_catalog("/triggers/writable-folder", access="write"),
        )

    async def list_folder_fields(self, folder_id: str, *, refresh: bool = False) -> list[dict[str, Any]]:
        self._require_string(folder_id, "folder_id")
        return await self._cached(
            f"folder_fields:{folder_id}",
            refresh,
            lambda: self._load_folder_fields(folder_id, refresh=refresh),
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
        records = await self.client.get_json(f"/searches/find-record/{folder_id}", query=params, retryable=True)
        return await self._enrich_record_collection(folder_id, records)

    async def list_new_records(
        self,
        folder_id: str,
        *,
        since: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        self._require_string(folder_id, "folder_id")
        params = self._build_since_limit_query(since=since, limit=limit)
        records = await self.client.get_json(f"/triggers/new-record/{folder_id}", query=params, retryable=True)
        return await self._enrich_record_collection(folder_id, records)

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
        records = await self.client.get_json(f"/triggers/updated-record/{folder_id}", query=query, retryable=True)
        return await self._enrich_record_collection(folder_id, records)

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
        records = await self.client.get_json(f"/triggers/record-change/{folder_id}", query=query, retryable=True)
        return await self._enrich_record_collection(folder_id, records)

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

    async def list_automation_kinds(self) -> list[dict[str, Any]]:
        registry = self._require_automation_registry()
        return registry.capabilities()

    async def list_automations(self, *, kind: str | None = None) -> list[dict[str, Any]]:
        registry = self._require_automation_registry()
        automations: list[dict[str, Any]] = []
        for spec in registry.kinds_for_listing(kind):
            response = await self._execute_automation_operation(spec, "list")
            if not isinstance(response, list):
                raise NethuntMCPError(
                    code="invalid_response",
                    message="Automation list operation must return a JSON array.",
                    details={"kind": spec.kind},
                )
            for raw_item in response:
                automations.append(self._enrich_automation_summary(normalize_automation(spec, raw_item)))
        return automations

    async def list_automation_field_references(
        self,
        folder_id: str,
        *,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        self._require_string(folder_id, "folder_id")
        references: dict[str, dict[str, Any]] = {}
        try:
            raw_fields = await self._fetch_raw_folder_fields(folder_id)
        except (KeyError, NethuntMCPError):
            raw_fields = []
        raw_field_catalog = self._build_raw_field_catalog(folder_id, raw_fields)
        for automation in await self.list_automations(kind=kind):
            for item in self._extract_automation_field_references(automation):
                if item.get("folderId") != folder_id or item.get("fieldId") is None:
                    continue
                normalized_field_id = str(item["fieldId"])
                reference = references.setdefault(
                    normalized_field_id,
                    {
                        "folderId": folder_id,
                        "fieldId": normalized_field_id,
                        "referenceCount": 0,
                        "referencedBy": [],
                    },
                )
                reference["referenceCount"] += 1
                if item.get("fieldPath") is not None:
                    reference.setdefault("referencePaths", []).append(item["fieldPath"])
                reference["referencedBy"].append(
                    {
                        "kind": automation["kind"],
                        "automationId": automation["automationId"],
                        "name": automation.get("name"),
                    }
                )
        for reference in references.values():
            reference["referencedBy"].sort(
                key=lambda item: (
                    item.get("name") or "",
                    item["automationId"],
                )
            )
            reference["referencePaths"] = sorted(set(reference.get("referencePaths", [])))
            raw_field = raw_field_catalog.get(reference["fieldId"])
            if raw_field is not None:
                reference["fieldName"] = raw_field.get("fieldName")
                reference["fieldType"] = raw_field.get("fieldType")
                reference["fieldOptions"] = raw_field.get("fieldOptions")
                reference["metadataSource"] = {
                    "fieldId": "automation_imports",
                    "fieldName": raw_field.get("metadataSource", {}).get("fieldName"),
                    "fieldType": raw_field.get("metadataSource", {}).get("fieldType"),
                    "fieldOptions": raw_field.get("metadataSource", {}).get("fieldOptions"),
                }
            else:
                reference["fieldName"] = None
                reference["fieldType"] = None
                reference["fieldOptions"] = None
                reference["metadataSource"] = {
                    "fieldId": "automation_imports",
                    "fieldName": None,
                    "fieldType": None,
                    "fieldOptions": None,
                }
        return sorted(references.values(), key=lambda item: item["fieldId"])

    async def get_automation(
        self,
        kind: str,
        automation_id: str,
        *,
        include_branches: bool = False,
    ) -> dict[str, Any]:
        spec = self._require_automation_registry().require_kind(kind)
        self._require_string(automation_id, "automation_id")
        if not include_branches:
            response = await self._execute_automation_operation(spec, "get", automation_id=automation_id)
            return self._enrich_automation_summary(normalize_automation(spec, response, fallback_id=automation_id))
        request = self._build_automation_request(spec, "get", automation_id=automation_id)
        response, operation = await self._request_automation_response(spec, request, retryable=True)
        payload = extract_response_payload(response, operation.response_path)
        normalized = self._enrich_automation_summary(normalize_automation(spec, payload, fallback_id=automation_id))
        branches = get_path_value(response, "result.branches")
        normalized_branches = self._normalize_automation_branches(branches if isinstance(branches, list) else [])
        normalized["branches"] = normalized_branches
        normalized["branchGraph"] = self._build_branch_graph(normalized_branches)
        normalized["fieldReferences"] = self._merge_field_references(
            normalized.get("fieldReferences"),
            self._extract_branch_field_references(normalized_branches),
        )
        normalized["referenceCount"] = len(normalized["fieldReferences"])
        return normalized

    async def create_automation(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        confirm_write: bool = False,
    ) -> dict[str, Any]:
        spec = self._require_automation_registry().require_kind(kind)
        request = self._build_automation_request(spec, "create", payload=payload)
        if not confirm_write:
            return {"preview": request, "executed": False}
        response = await self._request_automation(spec, request, retryable=False, allow_missing_response_path=True)
        fallback_name = self._extract_automation_name(spec, payload)
        fallback_enabled = self._extract_automation_enabled(spec, payload)
        return {
            "executed": True,
            "result": await self._resolve_automation_write_result(
                spec,
                response,
                fallback_name=fallback_name,
                fallback_enabled=fallback_enabled,
            ),
        }

    async def update_automation(
        self,
        kind: str,
        automation_id: str,
        payload: dict[str, Any],
        *,
        confirm_write: bool = False,
    ) -> dict[str, Any]:
        spec = self._require_automation_registry().require_kind(kind)
        request = self._build_automation_request(spec, "update", automation_id=automation_id, payload=payload)
        if not confirm_write:
            return {"preview": request, "executed": False}
        response = await self._request_automation(spec, request, retryable=False, allow_missing_response_path=True)
        fallback_name = self._extract_automation_name(spec, payload)
        fallback_enabled = self._extract_automation_enabled(spec, payload)
        return {
            "executed": True,
            "result": await self._resolve_automation_write_result(
                spec,
                response,
                automation_id=automation_id,
                fallback_name=fallback_name,
                fallback_enabled=fallback_enabled,
            ),
        }

    async def delete_automation(
        self,
        kind: str,
        automation_id: str,
        *,
        confirm: bool = False,
        preview_only: bool = False,
    ) -> dict[str, Any]:
        spec = self._require_automation_registry().require_kind(kind)
        self._require_string(automation_id, "automation_id")
        preview = {
            "kind": spec.kind,
            "automationId": automation_id,
            "automation": await self.get_automation(spec.kind, automation_id),
            "request": self._build_automation_request(spec, "delete", automation_id=automation_id),
        }
        if preview_only or not confirm:
            return {"preview": preview, "deleted": False}
        request = dict(preview["request"])
        result = await self._request_automation(spec, request, retryable=False)
        return {
            "preview": preview,
            "deleted": True,
            "kind": spec.kind,
            "automationId": automation_id,
            "result": result,
        }

    async def set_automation_enabled(
        self,
        kind: str,
        automation_id: str,
        enabled: bool,
        *,
        confirm_write: bool = False,
    ) -> dict[str, Any]:
        spec = self._require_automation_registry().require_kind(kind)
        request = self._build_automation_request(spec, "set_enabled", automation_id=automation_id, enabled=enabled)
        if not confirm_write:
            return {"preview": request, "executed": False}
        response = await self._request_automation(spec, request, retryable=False, allow_missing_response_path=True)
        return {
            "executed": True,
            "result": await self._resolve_automation_write_result(
                spec,
                response,
                automation_id=automation_id,
                fallback_enabled=enabled,
            ),
        }

    async def activate_automation(
        self,
        kind: str,
        automation_id: str,
        *,
        confirm_write: bool = False,
    ) -> dict[str, Any]:
        spec = self._require_automation_registry().require_kind(kind)
        return await self._execute_automation_editor_write(
            spec,
            "activate",
            automation_id=automation_id,
            confirm_write=confirm_write,
            result_fields={"enabled": True},
        )

    async def deactivate_automation(
        self,
        kind: str,
        automation_id: str,
        *,
        confirm_write: bool = False,
    ) -> dict[str, Any]:
        spec = self._require_automation_registry().require_kind(kind)
        return await self._execute_automation_editor_write(
            spec,
            "deactivate",
            automation_id=automation_id,
            confirm_write=confirm_write,
            result_fields={"enabled": False},
        )

    async def rename_automation(
        self,
        kind: str,
        automation_id: str,
        name: str,
        *,
        confirm_write: bool = False,
    ) -> dict[str, Any]:
        spec = self._require_automation_registry().require_kind(kind)
        self._require_string(name, "name")
        payload = {"name": name}
        return await self._execute_automation_editor_write(
            spec,
            "rename",
            automation_id=automation_id,
            payload=payload,
            context={"name": name},
            confirm_write=confirm_write,
            require_payload=True,
            result_fields={"name": name},
        )

    async def get_automation_step_details(
        self,
        kind: str,
        automation_id: str,
        step_num: int,
        *,
        list_options: dict[str, Any] | None = None,
    ) -> Any:
        spec = self._require_automation_registry().require_kind(kind)
        self._require_string(automation_id, "automation_id")
        resolved_step_num = self._require_int(step_num, "step_num", minimum=0)
        resolved_list_options = self._require_object(list_options, "list_options", allow_none=True)
        if resolved_list_options is None:
            resolved_list_options = dict(DEFAULT_AUTOMATION_STEP_LIST_OPTIONS)
        result = await self._execute_automation_editor_operation(
            spec,
            "get_step_details",
            automation_id=automation_id,
            retryable=True,
            context={
                "step_num": resolved_step_num,
                "list_options": resolved_list_options,
            },
        )
        if not isinstance(result, dict):
            return result
        enriched = dict(result)
        enriched.setdefault("kind", spec.kind)
        enriched.setdefault("automationId", automation_id)
        enriched.setdefault("stepNum", resolved_step_num)
        enriched.setdefault("listOptions", resolved_list_options)
        try:
            automation = await self.get_automation(kind, automation_id, include_branches=True)
        except (KeyError, NethuntMCPError):
            return enriched
        step = self._find_automation_step(automation.get("branches"), resolved_step_num)
        if step is not None:
            enriched.setdefault("branchId", step.get("branchId"))
            enriched.setdefault("branchNum", step.get("branchNum"))
            enriched.setdefault("stepId", step.get("stepId"))
            enriched.setdefault("role", step.get("role"))
            enriched.setdefault("type", step.get("type"))
            enriched.setdefault("fieldReferences", step.get("fieldReferences", []))
        return enriched

    async def add_automation_step(
        self,
        kind: str,
        automation_id: str,
        step_type: str,
        payload: dict[str, Any],
        *,
        branch_id: int,
        role: str,
        confirm_write: bool = False,
    ) -> dict[str, Any]:
        spec = self._require_automation_registry().require_kind(kind)
        self._require_string(step_type, "step_type")
        resolved_branch_id = self._require_int(branch_id, "branch_id", minimum=1)
        self._require_string(role, "role")
        return await self._execute_automation_editor_write(
            spec,
            "add_step",
            automation_id=automation_id,
            payload=payload,
            context={
                "step_type": step_type,
                "branch_id": resolved_branch_id,
                "role": role,
            },
            confirm_write=confirm_write,
            require_payload=True,
            result_fields={"stepType": step_type, "branchId": resolved_branch_id, "role": role},
        )

    async def update_automation_step(
        self,
        kind: str,
        automation_id: str,
        step_num: int,
        payload: dict[str, Any],
        *,
        branch_id: int,
        step_id: int | None = None,
        confirm_write: bool = False,
    ) -> dict[str, Any]:
        spec = self._require_automation_registry().require_kind(kind)
        resolved_step_num = self._require_int(step_num, "step_num", minimum=0)
        resolved_branch_id = self._require_int(branch_id, "branch_id", minimum=1)
        resolved_step_id = resolved_step_num if step_id is None else self._require_int(step_id, "step_id", minimum=1)
        return await self._execute_automation_editor_write(
            spec,
            "update_step",
            automation_id=automation_id,
            payload=payload,
            context={
                "step_num": resolved_step_num,
                "branch_id": resolved_branch_id,
                "step_id": resolved_step_id,
            },
            confirm_write=confirm_write,
            require_payload=True,
            result_fields={
                "stepNum": resolved_step_num,
                "branchId": resolved_branch_id,
                "stepId": resolved_step_id,
            },
        )

    async def delete_automation_step(
        self,
        kind: str,
        automation_id: str,
        step_num: int,
        *,
        child_branch_num: int | None = None,
        payload: dict[str, Any] | None = None,
        confirm_write: bool = False,
    ) -> dict[str, Any]:
        spec = self._require_automation_registry().require_kind(kind)
        resolved_step_num = self._require_int(step_num, "step_num", minimum=0)
        resolved_child_branch_num = None
        if child_branch_num is not None:
            resolved_child_branch_num = self._require_int(child_branch_num, "child_branch_num", minimum=0)
        return await self._execute_automation_editor_write(
            spec,
            "delete_step",
            automation_id=automation_id,
            payload=payload,
            context={
                "step_num": resolved_step_num,
                "child_branch_num": resolved_child_branch_num,
            },
            confirm_write=confirm_write,
            result_fields={
                "stepNum": resolved_step_num,
                "childBranchNum": resolved_child_branch_num,
            },
        )

    async def add_automation_split(
        self,
        kind: str,
        automation_id: str,
        step_num: int,
        payload: dict[str, Any] | None = None,
        *,
        confirm_write: bool = False,
    ) -> dict[str, Any]:
        spec = self._require_automation_registry().require_kind(kind)
        resolved_step_num = self._require_int(step_num, "step_num", minimum=0)
        return await self._execute_automation_editor_write(
            spec,
            "add_split",
            automation_id=automation_id,
            payload=payload,
            context={"step_num": resolved_step_num},
            confirm_write=confirm_write,
            result_fields={"stepNum": resolved_step_num},
        )

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

    async def _load_folder_catalog(self, path: str, *, access: str) -> list[dict[str, Any]]:
        folders = await self.client.get_json(path, retryable=True)
        if not isinstance(folders, list):
            return folders
        return [self._normalize_folder_entry(item, access=access) for item in folders]

    def _normalize_folder_entry(self, raw_folder: Any, *, access: str) -> dict[str, Any]:
        if isinstance(raw_folder, dict):
            folder = dict(raw_folder)
        else:
            folder = {"name": raw_folder}
        folder_id = self._coerce_identifier(self._extract_first_value(folder, FIELD_ID_KEYS))
        folder_name = self._extract_first_string(folder, FIELD_NAME_KEYS)
        folder["folderId"] = folder_id
        folder["folderName"] = folder_name
        folder["access"] = access
        folder["metadataSource"] = {
            "folderId": "raw" if folder_id is not None else None,
            "folderName": "raw" if folder_name is not None else None,
        }
        return folder

    async def _fetch_raw_folder_fields(self, folder_id: str, *, refresh: bool = False) -> list[dict[str, Any]]:
        return await self._cached(
            f"folder_fields_raw:{folder_id}",
            refresh,
            lambda: self.client.get_json(f"/triggers/folder-field/{folder_id}", retryable=True),
        )

    async def _load_folder_fields(self, folder_id: str, *, refresh: bool) -> list[dict[str, Any]]:
        raw_fields = await self._fetch_raw_folder_fields(folder_id, refresh=refresh)
        references_by_id: dict[str, dict[str, Any]] = {}
        if self.settings.automation_configured:
            try:
                references_by_id = {
                    item["fieldId"]: item
                    for item in await self.list_automation_field_references(folder_id)
                    if isinstance(item, dict) and item.get("fieldId") is not None
                }
            except ConfigError:
                references_by_id = {}
        normalized_fields: list[dict[str, Any]] = []
        if not isinstance(raw_fields, list):
            return raw_fields
        for raw_field in raw_fields:
            normalized = self._normalize_field_entry(folder_id, raw_field)
            field_id = normalized.get("fieldId")
            if field_id is not None and field_id in references_by_id:
                reference = references_by_id[field_id]
                normalized["referenceCount"] = reference.get("referenceCount", 0)
                normalized["referencedBy"] = list(reference.get("referencedBy", []))
                normalized["referencePaths"] = list(reference.get("referencePaths", []))
            else:
                normalized.setdefault("referenceCount", 0)
                normalized.setdefault("referencedBy", [])
                normalized.setdefault("referencePaths", [])
            normalized_fields.append(normalized)
        return normalized_fields

    def _build_raw_field_catalog(self, folder_id: str, raw_fields: Any) -> dict[str, dict[str, Any]]:
        if not isinstance(raw_fields, list):
            return {}
        catalog: dict[str, dict[str, Any]] = {}
        for raw_field in raw_fields:
            normalized = self._normalize_field_entry(folder_id, raw_field)
            field_id = normalized.get("fieldId")
            if field_id is None:
                continue
            catalog[field_id] = normalized
        return catalog

    def _normalize_field_entry(self, folder_id: str, raw_field: Any) -> dict[str, Any]:
        if isinstance(raw_field, dict):
            field = dict(raw_field)
        else:
            field = {"name": raw_field}
        field_name = self._extract_first_string(field, FIELD_NAME_KEYS)
        field_id = self._coerce_identifier(self._extract_first_value(field, FIELD_ID_KEYS))
        field_type = self._extract_first_string(field, FIELD_TYPE_KEYS)
        field_options = self._normalize_field_options(field)
        field["folderId"] = folder_id
        field["fieldName"] = field_name
        field["fieldId"] = field_id
        field["fieldType"] = field_type
        field["fieldOptions"] = field_options
        field["metadataSource"] = {
            "fieldName": "raw" if field_name is not None else None,
            "fieldId": "raw" if field_id is not None else None,
            "fieldType": "raw" if field_type is not None else None,
            "fieldOptions": "raw" if field_options is not None else None,
        }
        return field

    def _normalize_field_options(self, field: dict[str, Any]) -> list[dict[str, Any]] | None:
        for key in FIELD_OPTION_KEYS:
            options = field.get(key)
            normalized = self._normalize_option_list(options)
            if normalized is not None:
                return normalized
        return None

    def _normalize_option_list(self, options: Any) -> list[dict[str, Any]] | None:
        if not isinstance(options, list):
            return None
        normalized: list[dict[str, Any]] = []
        for item in options:
            normalized_item = self._normalize_option_item(item)
            if normalized_item is not None:
                normalized.append(normalized_item)
        return normalized

    def _normalize_option_item(self, option: Any) -> dict[str, Any] | None:
        if isinstance(option, dict):
            raw_option = dict(option)
            option_id = self._coerce_identifier(
                self._extract_first_value(raw_option, ("id", "optionId", "key", "value", "code"))
            )
            label = self._extract_first_string(raw_option, ("label", "name", "title", "displayName"))
            value = raw_option.get("value")
            if label is None and isinstance(value, (int, float, str)):
                label = str(value)
            if option_id is None and label is not None:
                option_id = label
            return {
                "id": option_id,
                "label": label,
                "value": value if value is not None else raw_option.get("name", raw_option.get("label")),
                "raw": raw_option,
            }
        if isinstance(option, (bool, int, float, str)):
            label = str(option)
            return {"id": label, "label": label, "value": option, "raw": option}
        return None

    async def _enrich_record_collection(self, folder_id: str, records: Any) -> Any:
        if not isinstance(records, list):
            return records
        try:
            fields = await self.list_folder_fields(folder_id)
        except (ConfigError, KeyError, NethuntMCPError):
            return records
        field_catalog = {
            field["fieldName"].casefold(): field
            for field in fields
            if isinstance(field, dict) and isinstance(field.get("fieldName"), str)
        }
        return [self._enrich_record_item(folder_id, item, field_catalog) for item in records]

    def _enrich_record_item(
        self,
        folder_id: str,
        record: Any,
        field_catalog: dict[str, dict[str, Any]],
    ) -> Any:
        if not isinstance(record, dict):
            return record
        enriched = dict(record)
        record_id = self._coerce_identifier(
            self._extract_first_value(enriched, ("recordId", "id", "_id", "record_id"))
        )
        enriched["folderId"] = self._coerce_identifier(enriched.get("folderId")) or folder_id
        if record_id is not None:
            enriched["recordId"] = record_id
        fields = enriched.get("fields")
        if isinstance(fields, dict):
            field_metadata: dict[str, dict[str, Any]] = {}
            field_ids: dict[str, str | None] = {}
            for field_name in fields:
                normalized_name = field_name.casefold()
                field_definition = field_catalog.get(normalized_name)
                field_metadata[field_name] = {
                    "fieldId": field_definition.get("fieldId") if field_definition else None,
                    "fieldType": field_definition.get("fieldType") if field_definition else None,
                    "fieldOptions": field_definition.get("fieldOptions") if field_definition else None,
                    "metadataSource": field_definition.get("metadataSource") if field_definition else {
                        "fieldId": None,
                        "fieldType": None,
                        "fieldOptions": None,
                    },
                }
                field_ids[field_name] = field_metadata[field_name]["fieldId"]
            enriched["fieldMetadata"] = field_metadata
            enriched["fieldIds"] = field_ids
            enriched["fieldNames"] = sorted(fields)
        field_name = enriched.get("fieldName")
        if isinstance(field_name, str):
            field_definition = field_catalog.get(field_name.casefold())
            if field_definition is not None:
                enriched.setdefault("fieldId", field_definition.get("fieldId"))
                enriched.setdefault("fieldType", field_definition.get("fieldType"))
                enriched.setdefault("fieldOptions", field_definition.get("fieldOptions"))
                enriched.setdefault("metadataSource", field_definition.get("metadataSource"))
        return enriched

    def _enrich_automation_summary(self, automation: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(automation)
        imports = self._normalize_automation_imports(enriched.get("raw", {}).get("imports"))
        enriched["imports"] = imports
        enriched["fieldReferences"] = self._extract_automation_field_references(enriched)
        enriched["referenceCount"] = len(enriched["fieldReferences"])
        return enriched

    def _normalize_automation_imports(self, imports: Any) -> list[dict[str, Any]]:
        if not isinstance(imports, list):
            return []
        normalized_imports: list[dict[str, Any]] = []
        for index, item in enumerate(imports):
            if not isinstance(item, dict):
                continue
            normalized = dict(item)
            normalized["folderId"] = self._coerce_identifier(item.get("folderId"))
            normalized["fieldId"] = self._coerce_identifier(item.get("fieldId"))
            normalized["stepId"] = self._coerce_identifier(item.get("stepId"))
            normalized["stepNum"] = item.get("stepNum")
            normalized["fieldPath"] = f"imports[{index}]"
            normalized_imports.append(normalized)
        return normalized_imports

    def _extract_automation_field_references(self, automation: dict[str, Any]) -> list[dict[str, Any]]:
        references = self._references_from_imports(automation.get("imports"))
        references = self._merge_field_references(references, automation.get("fieldReferences"))
        references = self._merge_field_references(references, self._extract_branch_field_references(automation.get("branches")))
        return references

    def _references_from_imports(self, imports: Any) -> list[dict[str, Any]]:
        if not isinstance(imports, list):
            return []
        references: list[dict[str, Any]] = []
        for item in imports:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "FIELD" or item.get("fieldId") is None:
                continue
            references.append(
                {
                    "source": "automation_imports",
                    "fieldPath": item.get("fieldPath"),
                    "folderId": item.get("folderId"),
                    "fieldId": item.get("fieldId"),
                    "stepId": item.get("stepId"),
                    "stepNum": item.get("stepNum"),
                    "relation": None,
                }
            )
        return references

    def _normalize_automation_branches(self, branches: Any) -> list[dict[str, Any]]:
        if not isinstance(branches, list):
            return []
        normalized_branches: list[dict[str, Any]] = []
        for branch_index, raw_branch in enumerate(branches, start=1):
            branch = dict(raw_branch) if isinstance(raw_branch, dict) else {"raw": raw_branch}
            raw_branch_num = branch.get("branchNum")
            branch_num = raw_branch_num if isinstance(raw_branch_num, int) else branch_index
            branch["branchNum"] = branch_num
            branch["branchId"] = self._coerce_identifier(branch.get("branchId")) or str(branch_num)
            raw_steps = branch.get("steps")
            normalized_steps: list[dict[str, Any]] = []
            if isinstance(raw_steps, list):
                for step_index, raw_step in enumerate(raw_steps, start=1):
                    normalized_steps.append(
                        self._normalize_automation_step(
                            branch_id=branch["branchId"],
                            branch_num=branch_num,
                            raw_step=raw_step,
                            step_index=step_index,
                        )
                    )
            branch["steps"] = normalized_steps
            branch["stepCount"] = len(normalized_steps)
            branch["fieldReferences"] = self._extract_branch_field_references([branch])
            normalized_branches.append(branch)
        return normalized_branches

    def _normalize_automation_step(
        self,
        *,
        branch_id: str,
        branch_num: int,
        raw_step: Any,
        step_index: int,
    ) -> dict[str, Any]:
        step = dict(raw_step) if isinstance(raw_step, dict) else {"raw": raw_step}
        raw_step_num = step.get("stepNum")
        step_num = raw_step_num if isinstance(raw_step_num, int) else step_index
        step_id = self._coerce_identifier(step.get("stepId")) or str(step_num)
        step["branchId"] = branch_id
        step["branchNum"] = branch_num
        step["stepNum"] = step_num
        step["stepId"] = step_id
        step["role"] = step.get("role")
        step["type"] = step.get("type")
        step["targetFolderId"] = self._coerce_identifier(step.get("options", {}).get("folderId")) if isinstance(step.get("options"), dict) else None
        step["fieldReferences"] = self._extract_field_references_from_value(
            step.get("options"),
            field_path=f"branches[{branch_num}].steps[{step_num}].options",
            branch_id=branch_id,
            branch_num=branch_num,
            step_id=step_id,
            step_num=step_num,
        )
        return step

    def _extract_branch_field_references(self, branches: Any) -> list[dict[str, Any]]:
        if not isinstance(branches, list):
            return []
        references: list[dict[str, Any]] = []
        for branch in branches:
            if not isinstance(branch, dict):
                continue
            for step in branch.get("steps", []):
                if not isinstance(step, dict):
                    continue
                references = self._merge_field_references(references, step.get("fieldReferences"))
        return references

    def _build_branch_graph(self, branches: list[dict[str, Any]]) -> dict[str, Any]:
        graph_steps: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        for branch in branches:
            previous_step_id: str | None = None
            previous_step_num: int | None = None
            for step in branch.get("steps", []):
                graph_steps.append(
                    {
                        "branchId": branch.get("branchId"),
                        "branchNum": branch.get("branchNum"),
                        "stepId": step.get("stepId"),
                        "stepNum": step.get("stepNum"),
                        "role": step.get("role"),
                        "type": step.get("type"),
                    }
                )
                if previous_step_id is not None:
                    edges.append(
                        {
                            "branchId": branch.get("branchId"),
                            "fromStepId": previous_step_id,
                            "fromStepNum": previous_step_num,
                            "toStepId": step.get("stepId"),
                            "toStepNum": step.get("stepNum"),
                        }
                    )
                previous_step_id = step.get("stepId")
                previous_step_num = step.get("stepNum")
        return {
            "branchCount": len(branches),
            "stepCount": len(graph_steps),
            "branches": [
                {
                    "branchId": branch.get("branchId"),
                    "branchNum": branch.get("branchNum"),
                    "stepCount": branch.get("stepCount", 0),
                }
                for branch in branches
            ],
            "steps": graph_steps,
            "edges": edges,
        }

    def _find_automation_step(self, branches: Any, step_num: int) -> dict[str, Any] | None:
        if not isinstance(branches, list):
            return None
        for branch in branches:
            if not isinstance(branch, dict):
                continue
            for step in branch.get("steps", []):
                if isinstance(step, dict) and step.get("stepNum") == step_num:
                    return step
        return None

    def _extract_field_references_from_value(
        self,
        value: Any,
        *,
        field_path: str,
        branch_id: str,
        branch_num: int,
        step_id: str,
        step_num: int,
    ) -> list[dict[str, Any]]:
        references: list[dict[str, Any]] = []
        if isinstance(value, dict):
            direct_reference = self._make_reference(
                source="step_options",
                field_path=field_path,
                folder_id=value.get("folderId"),
                field_id=value.get("fieldId"),
                branch_id=branch_id,
                branch_num=branch_num,
                step_id=step_id,
                step_num=step_num,
                relation=None,
            )
            if direct_reference is not None:
                references.append(direct_reference)
            rel = value.get("rel")
            if isinstance(rel, dict):
                relation_reference = self._make_reference(
                    source="step_options_rel",
                    field_path=f"{field_path}.rel",
                    folder_id=rel.get("folderId"),
                    field_id=rel.get("fieldId"),
                    branch_id=branch_id,
                    branch_num=branch_num,
                    step_id=step_id,
                    step_num=step_num,
                    relation="rel",
                )
                if relation_reference is not None:
                    references.append(relation_reference)
            for key, nested_value in value.items():
                references = self._merge_field_references(
                    references,
                    self._extract_field_references_from_value(
                        nested_value,
                        field_path=f"{field_path}.{key}",
                        branch_id=branch_id,
                        branch_num=branch_num,
                        step_id=step_id,
                        step_num=step_num,
                    ),
                )
            return references
        if isinstance(value, list):
            for index, item in enumerate(value):
                references = self._merge_field_references(
                    references,
                    self._extract_field_references_from_value(
                        item,
                        field_path=f"{field_path}[{index}]",
                        branch_id=branch_id,
                        branch_num=branch_num,
                        step_id=step_id,
                        step_num=step_num,
                    ),
                )
            return references
        if isinstance(value, str):
            for token in FIELD_TOKEN_PATTERN.findall(value):
                decoded = self._decode_nethunt_token(token)
                if not isinstance(decoded, dict):
                    continue
                token_reference = self._make_reference(
                    source="template_token",
                    field_path=field_path,
                    folder_id=decoded.get("folderId"),
                    field_id=decoded.get("fieldId"),
                    branch_id=branch_id,
                    branch_num=branch_num,
                    step_id=step_id,
                    step_num=step_num,
                    relation=None,
                )
                if token_reference is not None:
                    references.append(token_reference)
                rel = decoded.get("rel")
                if isinstance(rel, dict):
                    relation_reference = self._make_reference(
                        source="template_token_rel",
                        field_path=f"{field_path}.rel",
                        folder_id=rel.get("folderId"),
                        field_id=rel.get("fieldId"),
                        branch_id=branch_id,
                        branch_num=branch_num,
                        step_id=step_id,
                        step_num=step_num,
                        relation="rel",
                    )
                    if relation_reference is not None:
                        references.append(relation_reference)
            return references
        return references

    def _make_reference(
        self,
        *,
        source: str,
        field_path: str,
        folder_id: Any,
        field_id: Any,
        branch_id: str,
        branch_num: int,
        step_id: str,
        step_num: int,
        relation: str | None,
    ) -> dict[str, Any] | None:
        normalized_field_id = self._coerce_identifier(field_id)
        if normalized_field_id is None:
            return None
        return {
            "source": source,
            "fieldPath": field_path,
            "folderId": self._coerce_identifier(folder_id),
            "fieldId": normalized_field_id,
            "branchId": branch_id,
            "branchNum": branch_num,
            "stepId": step_id,
            "stepNum": step_num,
            "relation": relation,
        }

    def _merge_field_references(self, *groups: Any) -> list[dict[str, Any]]:
        merged: dict[tuple[Any, ...], dict[str, Any]] = {}
        for group in groups:
            if not isinstance(group, list):
                continue
            for item in group:
                if not isinstance(item, dict):
                    continue
                key = (
                    item.get("source"),
                    item.get("fieldPath"),
                    item.get("folderId"),
                    item.get("fieldId"),
                    item.get("branchId"),
                    item.get("stepId"),
                    item.get("relation"),
                )
                merged[key] = dict(item)
        return sorted(
            merged.values(),
            key=lambda item: (
                item.get("branchNum") or 0,
                item.get("stepNum") or 0,
                item.get("fieldPath") or "",
                item.get("fieldId") or "",
            ),
        )

    def _decode_nethunt_token(self, token: str) -> Any:
        try:
            padded = token + ("=" * (-len(token) % 4))
            decoded = base64.b64decode(padded.encode("utf-8"))
            return json.loads(decoded.decode("utf-8"))
        except (ValueError, TypeError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError):
            return None

    def _extract_first_string(self, payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
        value = self._extract_first_value(payload, keys)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _extract_first_value(self, payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
        for key in keys:
            value = get_path_value(payload, key)
            if value is not None:
                return value
        return None

    def _coerce_identifier(self, value: Any) -> str | None:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, (int, str)):
            normalized = str(value).strip()
            return normalized or None
        return None

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

    async def _execute_automation_operation(
        self,
        spec: AutomationKind,
        operation_name: str,
        *,
        automation_id: str | None = None,
        payload: dict[str, Any] | None = None,
        enabled: bool | None = None,
        retryable: bool = True,
    ) -> Any:
        request = self._build_automation_request(
            spec,
            operation_name,
            automation_id=automation_id,
            payload=payload,
            enabled=enabled,
            operation_source="lifecycle",
        )
        return await self._request_automation(spec, request, retryable=retryable)

    async def _execute_automation_editor_operation(
        self,
        spec: AutomationKind,
        operation_name: str,
        *,
        automation_id: str | None = None,
        payload: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> Any:
        request = self._build_automation_request(
            spec,
            operation_name,
            automation_id=automation_id,
            payload=payload,
            context=context,
            operation_source="editor",
        )
        return await self._request_automation(spec, request, retryable=retryable)

    async def _execute_automation_editor_write(
        self,
        spec: AutomationKind,
        operation_name: str,
        *,
        automation_id: str,
        payload: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        confirm_write: bool,
        require_payload: bool = False,
        result_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request = self._build_automation_request(
            spec,
            operation_name,
            automation_id=automation_id,
            payload=payload,
            context=context,
            operation_source="editor",
            require_payload=require_payload,
        )
        if not confirm_write:
            return {"preview": request, "executed": False}
        response = await self._request_automation(spec, request, retryable=False)
        return {
            "executed": True,
            "result": self._wrap_automation_editor_result(
                spec,
                automation_id,
                response,
                **(result_fields or {}),
            ),
        }

    async def _request_automation(
        self,
        spec: AutomationKind,
        request: dict[str, Any],
        *,
        retryable: bool,
        allow_missing_response_path: bool = False,
    ) -> Any:
        response, operation = await self._request_automation_response(spec, request, retryable=retryable)
        try:
            return extract_response_payload(response, operation.response_path)
        except NethuntMCPError:
            if allow_missing_response_path:
                return response
            raise

    async def _request_automation_response(
        self,
        spec: AutomationKind,
        request: dict[str, Any],
        *,
        retryable: bool,
    ) -> tuple[Any, Any]:
        if self.automation_client is None:
            raise ConfigError(code="config_error", message="Automation client is not configured.")
        json_payload = request.get("json")
        if json_payload is not None and not isinstance(json_payload, (dict, list)):
            raise ValidationError(code="validation_error", message="Automation request JSON must be an object or array.")
        response = await self.automation_client.request_json(
            request["method"],
            request["path"],
            query=request.get("query"),
            json_body=json_payload,
            retryable=retryable,
        )
        self._raise_for_automation_response_error(response)
        resolved_operation = spec.resolve_operation(
            request["operation"],
            editor=request.get("operationSource") == "editor",
        )
        return response, resolved_operation

    def _build_automation_request(
        self,
        spec: AutomationKind,
        operation_name: str,
        *,
        automation_id: str | None = None,
        payload: dict[str, Any] | None = None,
        enabled: bool | None = None,
        context: dict[str, Any] | None = None,
        operation_source: str = "lifecycle",
        require_payload: bool = False,
    ) -> dict[str, Any]:
        if automation_id is not None:
            self._require_string(automation_id, "automation_id")
        if payload is not None and not isinstance(payload, dict):
            raise ValidationError(code="validation_error", message="payload must be an object.")
        if context is not None and not isinstance(context, dict):
            raise ValidationError(code="validation_error", message="context must be an object.")
        if operation_source not in {"editor", "lifecycle"}:
            raise ValidationError(code="validation_error", message="operation_source is invalid.")
        if operation_source == "lifecycle" and operation_name in {"create", "update"}:
            require_payload = True
        if require_payload and not payload:
            raise ValidationError(code="validation_error", message="payload must not be empty.")
        operation = spec.resolve_operation(operation_name, editor=operation_source == "editor")
        render_context = {
            "kind": spec.kind,
            "automation_id": automation_id,
            "enabled": enabled,
            "enabled_command": self._automation_enabled_command(enabled),
            "operation_name": operation_name,
            "payload": payload,
        }
        if context:
            render_context.update(context)
        path = render_template(operation.path, render_context)
        if not isinstance(path, str) or not path:
            raise ValidationError(code="validation_error", message="Automation operation path must resolve to a string.")
        query = render_template(operation.query, render_context) if operation.query is not None else None
        if query is not None and not isinstance(query, dict):
            raise ValidationError(code="validation_error", message="Automation operation query must resolve to an object.")
        json_payload = payload
        if operation.json is not None:
            json_payload = render_template(operation.json, render_context)
        if operation_source == "lifecycle" and operation_name == "set_enabled" and json_payload is None:
            json_payload = {"enabled": enabled}
        return {
            "kind": spec.kind,
            "operation": operation_name,
            "operationSource": operation_source,
            "automationId": automation_id,
            "method": operation.method,
            "path": path,
            "query": query,
            "json": json_payload,
        }

    def _raise_for_automation_response_error(self, response: Any) -> None:
        if not isinstance(response, dict) or response.get("status") != "ERROR":
            return
        error = response.get("error")
        if not isinstance(error, dict):
            return
        raw_code = error.get("code")
        raw_message = error.get("message")
        normalized_code = self._normalize_automation_error_code(raw_code)
        details = {
            "automation_error_code": raw_code,
            "automation_error": error,
        }
        raise NethuntMCPError(
            code=normalized_code,
            message=raw_message if isinstance(raw_message, str) and raw_message else "Automation endpoint returned an error.",
            details=details,
        )

    def _normalize_automation_error_code(self, raw_code: Any) -> str:
        if raw_code == "NotFoundError":
            return "not_found"
        if raw_code in {"InvalidArgumentError", "ValidationError"}:
            return "validation_error"
        if raw_code in {"UnauthorizedError", "AuthenticationError", "ForbiddenError"}:
            return "auth_error"
        return "automation_error"

    def _extract_automation_enabled(self, spec: AutomationKind, payload: dict[str, Any]) -> bool | None:
        if spec.enabled_path is None:
            return None
        resolved = get_path_value(payload, spec.enabled_path)
        if isinstance(resolved, bool):
            return resolved
        return None

    def _extract_automation_name(self, spec: AutomationKind, payload: dict[str, Any]) -> str | None:
        current: Any = payload
        for segment in spec.name_path.split("."):
            if isinstance(current, dict) and segment in current:
                current = current[segment]
                continue
            return None
        return current if isinstance(current, str) else None

    async def _resolve_automation_write_result(
        self,
        spec: AutomationKind,
        response: Any,
        *,
        automation_id: str | None = None,
        fallback_name: str | None = None,
        fallback_enabled: bool | None = None,
    ) -> dict[str, Any]:
        try:
            return self._enrich_automation_summary(
                normalize_automation(
                    spec,
                    response,
                    fallback_id=automation_id,
                    fallback_name=fallback_name,
                    fallback_enabled=fallback_enabled,
                )
            )
        except NethuntMCPError:
            resolved_automation_id = automation_id or self._extract_automation_id_hint(response)
            if resolved_automation_id is not None:
                refreshed = await self.get_automation(spec.kind, resolved_automation_id)
                if fallback_enabled is not None and refreshed.get("enabled") is None:
                    refreshed["enabled"] = fallback_enabled
                return refreshed
            if fallback_name:
                refreshed = await self._find_latest_automation_by_name(spec.kind, fallback_name)
                if refreshed is not None:
                    if fallback_enabled is not None and refreshed.get("enabled") is None:
                        refreshed["enabled"] = fallback_enabled
                    return refreshed
            raise

    async def _find_latest_automation_by_name(self, kind: str, name: str) -> dict[str, Any] | None:
        matches = [item for item in await self.list_automations(kind=kind) if item.get("name") == name]
        if not matches:
            return None
        return max(
            matches,
            key=lambda item: (
                item.get("raw", {}).get("createdAt", 0),
                item.get("raw", {}).get("updatedAt", 0),
            ),
        )

    def _extract_automation_id_hint(self, payload: Any) -> str | None:
        candidates = (
            "id",
            "automationId",
            "result.id",
            "result.automationId",
            "result.automation.id",
        )
        for path in candidates:
            value = get_path_value(payload, path)
            if value is None:
                continue
            if isinstance(value, (int, str)):
                return str(value)
        return None

    def _wrap_automation_editor_result(
        self,
        spec: AutomationKind,
        automation_id: str,
        response: Any,
        **fields: Any,
    ) -> dict[str, Any]:
        result = {
            "kind": spec.kind,
            "automationId": automation_id,
            "raw": response,
        }
        result.update({key: value for key, value in fields.items() if value is not None})
        return result

    def _require_automation_registry(self) -> AutomationRegistry:
        if not self.settings.nethunt_automation_cookie:
            raise ConfigError(
                code="config_error",
                message="NETHUNT_AUTOMATION_COOKIE is required for automation tools.",
            )
        if self._automation_registry is None:
            self._automation_registry = AutomationRegistry.from_manifest(self.settings.nethunt_automation_manifest)
        if not self._automation_registry.kinds:
            raise ConfigError(
                code="config_error",
                message="No supported automation kinds are configured. Set NETHUNT_AUTOMATION_MANIFEST_JSON with full lifecycle operation specs.",
            )
        return self._automation_registry

    def _extract_placeholders(self, path_template: str) -> list[str]:
        return [field_name for _, field_name, _, _ in Formatter().parse(path_template) if field_name]

    def _normalize_limit(self, value: int) -> int:
        if value < 1:
            raise ValidationError(code="validation_error", message="limit must be greater than 0.")
        return value

    def _automation_enabled_command(self, enabled: bool | None) -> str | None:
        if enabled is True:
            return "activateAutomation"
        if enabled is False:
            return "deactivateAutomation"
        return None

    def _require_int(self, value: int, field_name: str, *, minimum: int | None = None) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError(code="validation_error", message=f"{field_name} must be an integer.")
        if minimum is not None and value < minimum:
            raise ValidationError(code="validation_error", message=f"{field_name} must be at least {minimum}.")
        return value

    def _require_object(
        self,
        value: dict[str, Any] | None,
        field_name: str,
        *,
        allow_none: bool = False,
    ) -> dict[str, Any] | None:
        if value is None and allow_none:
            return None
        if not isinstance(value, dict):
            raise ValidationError(code="validation_error", message=f"{field_name} must be an object.")
        return value

    def _require_string(self, value: str, field_name: str) -> None:
        if not value or not value.strip():
            raise ValidationError(code="validation_error", message=f"{field_name} is required.")
