from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated, Any, TypeAlias

from .automation_client import NetHuntAutomationClient
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .client import NetHuntClient
from .config import Settings
from .errors import ConfigError, NethuntMCPError
from .service import NetHuntService

RefreshFlag: TypeAlias = Annotated[
    bool,
    Field(description="Refresh cached discovery metadata instead of reusing the last cached response."),
]
FolderId: TypeAlias = Annotated[
    str,
    Field(description="NetHunt folder identifier. Discover valid values with `list_readable_folders` or `list_writable_folders`."),
]
RecordId: TypeAlias = Annotated[
    str,
    Field(description="NetHunt record identifier returned by record feeds, search, or create operations."),
]
OptionalRecordId: TypeAlias = Annotated[
    str | None,
    Field(description="Optional record identifier to narrow a record-change feed to one record."),
]
RecordQuery: TypeAlias = Annotated[
    str | None,
    Field(description="Free-text query string passed to NetHunt record search."),
]
SearchLimit: TypeAlias = Annotated[
    int,
    Field(description="Maximum number of records to return.", ge=1),
]
OptionalLimit: TypeAlias = Annotated[
    int | None,
    Field(description="Optional maximum number of items to return when the endpoint supports limiting.", ge=1),
]
SinceValue: TypeAlias = Annotated[
    str | None,
    Field(description="Optional feed cursor or timestamp accepted by the underlying NetHunt trigger endpoint."),
]
FieldNamesFilter: TypeAlias = Annotated[
    list[str] | None,
    Field(description="Optional list of exact field names to filter update or change feeds by."),
]
TimeZoneName: TypeAlias = Annotated[
    str | None,
    Field(description="Optional IANA time zone name such as `Europe/Kiev` used when creating records."),
]
OverwriteDefaultFlag: TypeAlias = Annotated[
    bool,
    Field(description="When true, update actions overwrite fields by default unless an individual action says otherwise."),
]
CommentText: TypeAlias = Annotated[
    str,
    Field(description="Plain-text content to store in the comment or call-log body."),
]
OptionalTimestamp: TypeAlias = Annotated[
    str | None,
    Field(description="Optional ISO-style timestamp string to attach to the call log."),
]
OptionalDuration: TypeAlias = Annotated[
    float | None,
    Field(description="Optional call duration in seconds."),
]
ConfirmFlag: TypeAlias = Annotated[
    bool,
    Field(description="Explicit confirmation flag required for destructive delete operations."),
]
PreviewOnlyFlag: TypeAlias = Annotated[
    bool,
    Field(description="When true, only compute the delete preview and do not execute the delete."),
]
ConfirmWriteFlag: TypeAlias = Annotated[
    bool,
    Field(description="Explicit confirmation flag required for mutating write operations."),
]
RawOperationName: TypeAlias = Annotated[
    str,
    Field(description="Name of an allowlisted raw operation defined by this MCP server."),
]
AutomationKind: TypeAlias = Annotated[
    str,
    Field(description="Configured automation kind, for example `workflow`. Discover supported values with `list_automation_kinds`."),
]
OptionalAutomationKind: TypeAlias = Annotated[
    str | None,
    Field(description="Optional automation kind filter. Use `null` to list all configured automation kinds."),
]
AutomationId: TypeAlias = Annotated[
    str,
    Field(description="Automation identifier returned by `list_automations`, `get_automation`, or automation write previews."),
]
IncludeBranchesFlag: TypeAlias = Annotated[
    bool,
    Field(description="When true, include the normalized branch and step graph with stable IDs in the automation response."),
]
EnabledFlag: TypeAlias = Annotated[
    bool,
    Field(description="Target enabled state for the automation."),
]
AutomationName: TypeAlias = Annotated[
    str,
    Field(description="Human-readable automation name."),
]
StepNum: TypeAlias = Annotated[
    int,
    Field(description="Automation step number within the branch.", ge=0),
]
OptionalStepId: TypeAlias = Annotated[
    int | None,
    Field(description="Optional stable step identifier. Pass it when NetHunt requires both `stepNum` and `stepId`."),
]
BranchId: TypeAlias = Annotated[
    int,
    Field(description="Target branch identifier required by NetHunt editor RPC calls."),
]
OptionalChildBranchNum: TypeAlias = Annotated[
    int | None,
    Field(description="Optional child branch number used when deleting split branches."),
]
StepRole: TypeAlias = Annotated[
    str,
    Field(description="NetHunt step role such as `TRIGGER`, `ACTION`, or `SPLIT`."),
]
StepType: TypeAlias = Annotated[
    str,
    Field(description="NetHunt automation step type such as `CREATE_TASK`, `UPDATE_RECORD2`, or `FILTER_RECORD`."),
]

TOOL_DESCRIPTIONS: dict[str, str] = {
    "auth_test": "Validate the configured NetHunt API credentials and return the upstream auth-test payload.",
    "list_readable_folders": "List NetHunt folders the current user can read. Use this before field, record, or automation authoring work.",
    "list_writable_folders": "List NetHunt folders the current user can write to when creating records or authoring actions.",
    "list_folder_fields": "List fields for a folder and enrich them with stable IDs, option metadata, reference counts, and provenance when available.",
    "list_automation_field_references": "Infer stable field IDs for a folder by scanning existing automation imports and returning who references each field.",
    "get_record": "Fetch a single NetHunt record by folder and record ID, with additive field metadata when available.",
    "search_records": "Search records in a folder by text query or record ID and return additive record metadata for authoring and debugging.",
    "list_new_records": "Read the NetHunt new-record feed for a folder, preserving feed entries while adding normalized record metadata when possible.",
    "list_updated_records": "Read the NetHunt updated-record feed for a folder, optionally filtered by field names.",
    "list_record_changes": "Read record-change events for a folder or a single record, optionally filtered by field names.",
    "create_record": "Create a new record in a folder from a field-name to value mapping.",
    "update_record": "Update an existing record using set/add/remove field actions expressed by field name.",
    "create_record_comment": "Attach a plain-text comment to an existing NetHunt record.",
    "create_call_log": "Attach a call-log entry to an existing NetHunt record.",
    "delete_record": "Delete a record. This tool always requires explicit `confirm=true` and returns a preview before execution.",
    "raw_get": "Execute an allowlisted raw GET helper for gaps not yet covered by higher-level MCP tools.",
    "raw_post": "Execute an allowlisted raw POST helper. This always requires `confirm_write=true` to perform the mutation.",
    "list_automation_kinds": "List configured automation kinds, lifecycle operations, editor operations, and sample payloads. Always call this before create_automation or update_automation to discover the expected payload format from the `samples` field.",
    "list_automations": "List automations for one configured kind or for all kinds, including normalized imports and field reference summaries.",
    "get_automation": "Fetch one automation by ID. Optionally include a normalized branch graph with stable branch and step IDs.",
    "create_automation": "Create a new automation. The payload format is manifest-specific — call `list_automation_kinds` first and use the `samples.create` example for the chosen kind. Requires confirmation.",
    "update_automation": "Update an existing automation. The payload format is manifest-specific — call `list_automation_kinds` first and use the `samples.update` example for the chosen kind. Requires confirmation.",
    "delete_automation": "Delete an automation. This tool requires explicit `confirm=true` and returns a preview before execution.",
    "set_automation_enabled": "Set the enabled state of an automation through its configured lifecycle operation. Requires confirmation.",
    "activate_automation": "Activate an automation through the NetHunt editor RPC wrapper. Requires confirmation.",
    "deactivate_automation": "Deactivate an automation through the NetHunt editor RPC wrapper. Requires confirmation.",
    "rename_automation": "Rename an automation through the NetHunt editor RPC wrapper. Requires confirmation.",
    "get_automation_step_details": "Read detailed information for one automation step and enrich the response with branch IDs, step IDs, and detected field references when available.",
    "add_automation_step": "Add a step to an automation branch through the NetHunt editor RPC wrapper. Requires confirmation.",
    "update_automation_step": "Update one automation step through the NetHunt editor RPC wrapper. Requires confirmation.",
    "delete_automation_step": "Delete one automation step or split branch through the NetHunt editor RPC wrapper. Requires confirmation.",
    "add_automation_split": "Add a split node after an automation step through the NetHunt editor RPC wrapper. Requires confirmation.",
}

RESOURCE_DESCRIPTIONS: dict[str, str] = {
    "nethunt://folders/readable": "JSON snapshot of the readable folder catalog, equivalent to `list_readable_folders(refresh=false)`.",
    "nethunt://folders/{folder_id}/fields": "JSON snapshot of folder fields with additive metadata, equivalent to `list_folder_fields(folder_id, refresh=false)`.",
    "nethunt://automations/capabilities": "JSON snapshot of configured automation kinds and capabilities, equivalent to `list_automation_kinds()`.",
}


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(levelname)s %(name)s %(message)s",
    )


class StaticTokenVerifier:
    def __init__(self, token: str) -> None:
        self._token = token

    async def verify_token(self, token: str) -> AccessToken | None:
        if token == self._token:
            return AccessToken(token=token, client_id="static", scopes=[])
        return None


class NetHuntMCPApplication:
    def __init__(self, service: NetHuntService, settings: Settings) -> None:
        self.service = service
        self.settings = settings
        auth_kwargs: dict[str, Any] = {}
        if settings.auth_configured:
            auth_kwargs["token_verifier"] = StaticTokenVerifier(settings.mcp_api_key)
            auth_kwargs["auth"] = AuthSettings(
                issuer_url=settings.mcp_server_url,
                resource_server_url=None,
            )
        self.server = FastMCP(
            "NetHunt CRM",
            instructions=(
                "Use discovery tools first to inspect folders and fields. "
                "Delete operations require explicit confirmation. "
                "Automation write operations require preview plus confirmation."
            ),
            host=settings.mcp_host,
            port=settings.mcp_port,
            json_response=True,
            **auth_kwargs,
        )
        self._register_tools()
        self._register_resources()

    async def auth_test(self) -> dict[str, Any]:
        return await self._execute("auth_test", self.service.auth_test)

    async def list_readable_folders(self, refresh: RefreshFlag = False) -> dict[str, Any]:
        return await self._execute(
            "list_readable_folders",
            lambda: self.service.list_readable_folders(refresh=refresh),
            refresh=refresh,
        )

    async def list_writable_folders(self, refresh: RefreshFlag = False) -> dict[str, Any]:
        return await self._execute(
            "list_writable_folders",
            lambda: self.service.list_writable_folders(refresh=refresh),
            refresh=refresh,
        )

    async def list_folder_fields(self, folder_id: FolderId, refresh: RefreshFlag = False) -> dict[str, Any]:
        return await self._execute(
            "list_folder_fields",
            lambda: self.service.list_folder_fields(folder_id, refresh=refresh),
            folder_id=folder_id,
            refresh=refresh,
        )

    async def list_automation_field_references(
        self,
        folder_id: FolderId,
        kind: OptionalAutomationKind = None,
    ) -> dict[str, Any]:
        return await self._execute(
            "list_automation_field_references",
            lambda: self.service.list_automation_field_references(folder_id, kind=kind),
            folder_id=folder_id,
            kind=kind,
        )

    async def get_record(self, folder_id: FolderId, record_id: RecordId) -> dict[str, Any]:
        return await self._execute(
            "get_record",
            lambda: self.service.get_record(folder_id, record_id),
            folder_id=folder_id,
            record_id=record_id,
        )

    async def search_records(
        self,
        folder_id: FolderId,
        query: RecordQuery = None,
        record_id: Annotated[
            str | None,
            Field(description="Optional record identifier to look up directly through the search endpoint."),
        ] = None,
        limit: SearchLimit = 10,
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
        folder_id: FolderId,
        since: SinceValue = None,
        limit: OptionalLimit = None,
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
        folder_id: FolderId,
        field_names: FieldNamesFilter = None,
        since: SinceValue = None,
        limit: OptionalLimit = None,
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
        folder_id: FolderId,
        record_id: OptionalRecordId = None,
        field_names: FieldNamesFilter = None,
        since: SinceValue = None,
        limit: OptionalLimit = None,
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
        folder_id: FolderId,
        fields: Annotated[
            dict[str, Any],
            Field(description="Mapping of NetHunt field names to values for the new record."),
        ],
        time_zone: TimeZoneName = None,
    ) -> dict[str, Any]:
        return await self._execute(
            "create_record",
            lambda: self.service.create_record(folder_id, fields=fields, time_zone=time_zone),
            folder_id=folder_id,
        )

    async def update_record(
        self,
        record_id: RecordId,
        set_fields: Annotated[
            dict[str, Any] | None,
            Field(description="Field-name to value mapping for overwrite-style updates."),
        ] = None,
        add_fields: Annotated[
            dict[str, Any] | None,
            Field(description="Field-name to value mapping for additive updates."),
        ] = None,
        remove_fields: Annotated[
            dict[str, Any] | None,
            Field(description="Field-name to value mapping for remove actions."),
        ] = None,
        overwrite_default: OverwriteDefaultFlag = False,
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

    async def create_record_comment(self, record_id: RecordId, text: CommentText) -> dict[str, Any]:
        return await self._execute(
            "create_record_comment",
            lambda: self.service.create_record_comment(record_id, text=text),
            record_id=record_id,
        )

    async def create_call_log(
        self,
        record_id: RecordId,
        text: CommentText,
        time: OptionalTimestamp = None,
        duration: OptionalDuration = None,
    ) -> dict[str, Any]:
        return await self._execute(
            "create_call_log",
            lambda: self.service.create_call_log(record_id, text=text, time=time, duration=duration),
            record_id=record_id,
        )

    async def delete_record(
        self,
        folder_id: FolderId,
        record_id: RecordId,
        confirm: ConfirmFlag = False,
        preview_only: PreviewOnlyFlag = False,
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

    async def raw_get(
        self,
        operation: RawOperationName,
        params: Annotated[
            dict[str, Any] | None,
            Field(description="Optional raw parameter object, including path placeholders and query values."),
        ] = None,
    ) -> dict[str, Any]:
        return await self._execute(
            "raw_get",
            lambda: self.service.raw_get(operation, params=params),
            raw_operation=operation,
        )

    async def raw_post(
        self,
        operation: RawOperationName,
        body: Annotated[
            dict[str, Any] | None,
            Field(description="Optional raw request body object for the allowlisted POST operation."),
        ] = None,
        confirm_write: ConfirmWriteFlag = False,
    ) -> dict[str, Any]:
        if not confirm_write:
            preview = await self._execute(
                "raw_post",
                lambda: self.service.raw_post(operation, body=body, confirm_write=False),
                raw_operation=operation,
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
                    raw_operation=operation,
                    confirm_write=confirm_write,
                )
            return preview
        return await self._execute(
            "raw_post",
            lambda: self.service.raw_post(operation, body=body, confirm_write=True),
            raw_operation=operation,
            confirm_write=confirm_write,
        )

    async def list_automation_kinds(self) -> dict[str, Any]:
        return await self._execute("list_automation_kinds", self.service.list_automation_kinds)

    async def list_automations(self, kind: OptionalAutomationKind = None) -> dict[str, Any]:
        return await self._execute(
            "list_automations",
            lambda: self.service.list_automations(kind=kind),
            kind=kind,
        )

    async def get_automation(
        self,
        kind: AutomationKind,
        automation_id: AutomationId,
        include_branches: IncludeBranchesFlag = False,
    ) -> dict[str, Any]:
        return await self._execute(
            "get_automation",
            lambda: self.service.get_automation(kind, automation_id, include_branches=include_branches),
            kind=kind,
            automation_id=automation_id,
            include_branches=include_branches,
        )

    async def create_automation(
        self,
        kind: AutomationKind,
        payload: Annotated[
            dict[str, Any],
            Field(description="Manifest-specific payload for the automation create operation. Call list_automation_kinds first and use the samples.create example for the chosen kind."),
        ],
        confirm_write: ConfirmWriteFlag = False,
    ) -> dict[str, Any]:
        return await self._execute_confirmable_write(
            "create_automation",
            lambda: self.service.create_automation(kind, payload, confirm_write=False),
            lambda: self.service.create_automation(kind, payload, confirm_write=True),
            message="Set confirm_write=true to create an automation.",
            kind=kind,
            confirm_write=confirm_write,
        )

    async def update_automation(
        self,
        kind: AutomationKind,
        automation_id: AutomationId,
        payload: Annotated[
            dict[str, Any],
            Field(description="Manifest-specific payload for the automation update operation. Call list_automation_kinds first and use the samples.update example for the chosen kind."),
        ],
        confirm_write: ConfirmWriteFlag = False,
    ) -> dict[str, Any]:
        return await self._execute_confirmable_write(
            "update_automation",
            lambda: self.service.update_automation(kind, automation_id, payload, confirm_write=False),
            lambda: self.service.update_automation(kind, automation_id, payload, confirm_write=True),
            message="Set confirm_write=true to update an automation.",
            kind=kind,
            automation_id=automation_id,
            confirm_write=confirm_write,
        )

    async def delete_automation(
        self,
        kind: AutomationKind,
        automation_id: AutomationId,
        confirm: ConfirmFlag = False,
        preview_only: PreviewOnlyFlag = False,
    ) -> dict[str, Any]:
        if not confirm:
            preview = await self._execute(
                "delete_automation",
                lambda: self.service.delete_automation(kind, automation_id, confirm=False, preview_only=True),
                kind=kind,
                automation_id=automation_id,
                confirm=confirm,
                preview_only=preview_only,
            )
            if preview["ok"]:
                return self._error_response(
                    NethuntMCPError(
                        code="confirmation_required",
                        message="Set confirm=true to delete the automation.",
                        details=preview["data"],
                    ),
                    "delete_automation",
                    kind=kind,
                    automation_id=automation_id,
                    confirm=confirm,
                    preview_only=preview_only,
                )
            return preview
        return await self._execute(
            "delete_automation",
            lambda: self.service.delete_automation(kind, automation_id, confirm=True, preview_only=preview_only),
            kind=kind,
            automation_id=automation_id,
            confirm=confirm,
            preview_only=preview_only,
        )

    async def set_automation_enabled(
        self,
        kind: AutomationKind,
        automation_id: AutomationId,
        enabled: EnabledFlag,
        confirm_write: ConfirmWriteFlag = False,
    ) -> dict[str, Any]:
        if not confirm_write:
            preview = await self._execute(
                "set_automation_enabled",
                lambda: self.service.set_automation_enabled(kind, automation_id, enabled, confirm_write=False),
                kind=kind,
                automation_id=automation_id,
                enabled=enabled,
                confirm_write=confirm_write,
            )
            if preview["ok"]:
                return self._error_response(
                    NethuntMCPError(
                        code="confirmation_required",
                        message="Set confirm_write=true to change automation enabled state.",
                        details=preview["data"],
                    ),
                    "set_automation_enabled",
                    kind=kind,
                    automation_id=automation_id,
                    enabled=enabled,
                    confirm_write=confirm_write,
                )
            return preview
        return await self._execute(
            "set_automation_enabled",
            lambda: self.service.set_automation_enabled(kind, automation_id, enabled, confirm_write=True),
            kind=kind,
            automation_id=automation_id,
            enabled=enabled,
            confirm_write=confirm_write,
        )

    async def activate_automation(
        self,
        kind: AutomationKind,
        automation_id: AutomationId,
        confirm_write: ConfirmWriteFlag = False,
    ) -> dict[str, Any]:
        return await self._execute_confirmable_write(
            "activate_automation",
            lambda: self.service.activate_automation(kind, automation_id, confirm_write=False),
            lambda: self.service.activate_automation(kind, automation_id, confirm_write=True),
            message="Set confirm_write=true to activate the automation.",
            kind=kind,
            automation_id=automation_id,
            confirm_write=confirm_write,
        )

    async def deactivate_automation(
        self,
        kind: AutomationKind,
        automation_id: AutomationId,
        confirm_write: ConfirmWriteFlag = False,
    ) -> dict[str, Any]:
        return await self._execute_confirmable_write(
            "deactivate_automation",
            lambda: self.service.deactivate_automation(kind, automation_id, confirm_write=False),
            lambda: self.service.deactivate_automation(kind, automation_id, confirm_write=True),
            message="Set confirm_write=true to deactivate the automation.",
            kind=kind,
            automation_id=automation_id,
            confirm_write=confirm_write,
        )

    async def rename_automation(
        self,
        kind: AutomationKind,
        automation_id: AutomationId,
        name: AutomationName,
        confirm_write: ConfirmWriteFlag = False,
    ) -> dict[str, Any]:
        return await self._execute_confirmable_write(
            "rename_automation",
            lambda: self.service.rename_automation(kind, automation_id, name, confirm_write=False),
            lambda: self.service.rename_automation(kind, automation_id, name, confirm_write=True),
            message="Set confirm_write=true to rename the automation.",
            kind=kind,
            automation_id=automation_id,
            name=name,
            confirm_write=confirm_write,
        )

    async def get_automation_step_details(
        self,
        kind: AutomationKind,
        automation_id: AutomationId,
        step_num: StepNum,
        list_options: Annotated[
            dict[str, Any] | None,
            Field(description="Optional NetHunt list-options object passed through to the step-details RPC."),
        ] = None,
    ) -> dict[str, Any]:
        return await self._execute(
            "get_automation_step_details",
            lambda: self.service.get_automation_step_details(
                kind,
                automation_id,
                step_num,
                list_options=list_options,
            ),
            kind=kind,
            automation_id=automation_id,
            step_num=step_num,
        )

    async def add_automation_step(
        self,
        kind: AutomationKind,
        automation_id: AutomationId,
        step_type: StepType,
        payload: Annotated[
            dict[str, Any],
            Field(description="NetHunt editor payload for the new automation step."),
        ],
        branch_id: BranchId,
        role: StepRole,
        confirm_write: ConfirmWriteFlag = False,
    ) -> dict[str, Any]:
        return await self._execute_confirmable_write(
            "add_automation_step",
            lambda: self.service.add_automation_step(
                kind,
                automation_id,
                step_type,
                payload,
                branch_id=branch_id,
                role=role,
                confirm_write=False,
            ),
            lambda: self.service.add_automation_step(
                kind,
                automation_id,
                step_type,
                payload,
                branch_id=branch_id,
                role=role,
                confirm_write=True,
            ),
            message="Set confirm_write=true to add an automation step.",
            kind=kind,
            automation_id=automation_id,
            step_type=step_type,
            branch_id=branch_id,
            role=role,
            confirm_write=confirm_write,
        )

    async def update_automation_step(
        self,
        kind: AutomationKind,
        automation_id: AutomationId,
        step_num: StepNum,
        payload: Annotated[
            dict[str, Any],
            Field(description="NetHunt editor payload with the step option changes to apply."),
        ],
        branch_id: BranchId,
        step_id: OptionalStepId = None,
        confirm_write: ConfirmWriteFlag = False,
    ) -> dict[str, Any]:
        return await self._execute_confirmable_write(
            "update_automation_step",
            lambda: self.service.update_automation_step(
                kind,
                automation_id,
                step_num,
                payload,
                branch_id=branch_id,
                step_id=step_id,
                confirm_write=False,
            ),
            lambda: self.service.update_automation_step(
                kind,
                automation_id,
                step_num,
                payload,
                branch_id=branch_id,
                step_id=step_id,
                confirm_write=True,
            ),
            message="Set confirm_write=true to update the automation step.",
            kind=kind,
            automation_id=automation_id,
            step_num=step_num,
            branch_id=branch_id,
            step_id=step_id,
            confirm_write=confirm_write,
        )

    async def delete_automation_step(
        self,
        kind: AutomationKind,
        automation_id: AutomationId,
        step_num: StepNum,
        child_branch_num: OptionalChildBranchNum = None,
        payload: Annotated[
            dict[str, Any] | None,
            Field(description="Optional NetHunt delete-step payload for advanced editor cases."),
        ] = None,
        confirm_write: ConfirmWriteFlag = False,
    ) -> dict[str, Any]:
        return await self._execute_confirmable_write(
            "delete_automation_step",
            lambda: self.service.delete_automation_step(
                kind,
                automation_id,
                step_num,
                child_branch_num=child_branch_num,
                payload=payload,
                confirm_write=False,
            ),
            lambda: self.service.delete_automation_step(
                kind,
                automation_id,
                step_num,
                child_branch_num=child_branch_num,
                payload=payload,
                confirm_write=True,
            ),
            message="Set confirm_write=true to delete the automation step.",
            kind=kind,
            automation_id=automation_id,
            step_num=step_num,
            child_branch_num=child_branch_num,
            confirm_write=confirm_write,
        )

    async def add_automation_split(
        self,
        kind: AutomationKind,
        automation_id: AutomationId,
        step_num: StepNum,
        payload: Annotated[
            dict[str, Any] | None,
            Field(description="Optional NetHunt editor payload used when adding a split node."),
        ] = None,
        confirm_write: ConfirmWriteFlag = False,
    ) -> dict[str, Any]:
        return await self._execute_confirmable_write(
            "add_automation_split",
            lambda: self.service.add_automation_split(kind, automation_id, step_num, payload, confirm_write=False),
            lambda: self.service.add_automation_split(kind, automation_id, step_num, payload, confirm_write=True),
            message="Set confirm_write=true to add an automation split.",
            kind=kind,
            automation_id=automation_id,
            step_num=step_num,
            confirm_write=confirm_write,
        )

    async def readable_folders_resource(self) -> str:
        payload = await self.list_readable_folders(refresh=False)
        return json.dumps(payload, ensure_ascii=True, indent=2)

    async def folder_fields_resource(self, folder_id: FolderId) -> str:
        payload = await self.list_folder_fields(folder_id, refresh=False)
        return json.dumps(payload, ensure_ascii=True, indent=2)

    async def automation_capabilities_resource(self) -> str:
        payload = await self.list_automation_kinds()
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

    async def _execute_confirmable_write(
        self,
        operation: str,
        preview_fn: Any,
        execute_fn: Any,
        *,
        message: str,
        **meta: Any,
    ) -> dict[str, Any]:
        confirm_write = bool(meta.get("confirm_write"))
        if not confirm_write:
            preview = await self._execute(operation, preview_fn, **meta)
            if preview["ok"]:
                return self._error_response(
                    NethuntMCPError(
                        code="confirmation_required",
                        message=message,
                        details=preview["data"],
                    ),
                    operation,
                    **meta,
                )
            return preview
        return await self._execute(operation, execute_fn, **meta)

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

    def _register_tool(self, name: str, fn: Any) -> None:
        self.server.tool(name=name, description=TOOL_DESCRIPTIONS[name])(fn)

    def _register_resource(self, uri: str, fn: Any) -> None:
        self.server.resource(uri, description=RESOURCE_DESCRIPTIONS[uri])(fn)

    def _register_tools(self) -> None:
        self._register_tool("auth_test", self.auth_test)
        self._register_tool("list_readable_folders", self.list_readable_folders)
        self._register_tool("list_writable_folders", self.list_writable_folders)
        self._register_tool("list_folder_fields", self.list_folder_fields)
        self._register_tool("list_automation_field_references", self.list_automation_field_references)
        self._register_tool("get_record", self.get_record)
        self._register_tool("search_records", self.search_records)
        self._register_tool("list_new_records", self.list_new_records)
        self._register_tool("list_updated_records", self.list_updated_records)
        self._register_tool("list_record_changes", self.list_record_changes)
        self._register_tool("create_record", self.create_record)
        self._register_tool("update_record", self.update_record)
        self._register_tool("create_record_comment", self.create_record_comment)
        self._register_tool("create_call_log", self.create_call_log)
        self._register_tool("delete_record", self.delete_record)
        self._register_tool("raw_get", self.raw_get)
        self._register_tool("raw_post", self.raw_post)
        self._register_tool("list_automation_kinds", self.list_automation_kinds)
        self._register_tool("list_automations", self.list_automations)
        self._register_tool("get_automation", self.get_automation)
        self._register_tool("create_automation", self.create_automation)
        self._register_tool("update_automation", self.update_automation)
        self._register_tool("delete_automation", self.delete_automation)
        self._register_tool("set_automation_enabled", self.set_automation_enabled)
        self._register_tool("activate_automation", self.activate_automation)
        self._register_tool("deactivate_automation", self.deactivate_automation)
        self._register_tool("rename_automation", self.rename_automation)
        self._register_tool("get_automation_step_details", self.get_automation_step_details)
        self._register_tool("add_automation_step", self.add_automation_step)
        self._register_tool("update_automation_step", self.update_automation_step)
        self._register_tool("delete_automation_step", self.delete_automation_step)
        self._register_tool("add_automation_split", self.add_automation_split)

    def _register_resources(self) -> None:
        self._register_resource("nethunt://folders/readable", self.readable_folders_resource)
        self._register_resource("nethunt://folders/{folder_id}/fields", self.folder_fields_resource)
        self._register_resource("nethunt://automations/capabilities", self.automation_capabilities_resource)


def build_application(settings: Settings | None = None) -> NetHuntMCPApplication:
    resolved_settings = settings or Settings.from_env()
    configure_logging(resolved_settings.nethunt_log_level)
    client = NetHuntClient(resolved_settings)
    automation_client = NetHuntAutomationClient(resolved_settings)
    service = NetHuntService(client, resolved_settings, automation_client=automation_client)
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
