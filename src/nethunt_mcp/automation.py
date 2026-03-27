from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .errors import ConfigError, NethuntMCPError, ValidationError

REQUIRED_AUTOMATION_OPERATIONS = ("list", "get", "create", "update", "delete", "set_enabled")
SUPPORTED_HTTP_METHODS = {"DELETE", "GET", "PATCH", "POST", "PUT"}
TOKEN_PREFIX = "$"
ENABLED_TRUE_STRINGS = {"1", "active", "enabled", "on", "true", "yes"}
ENABLED_FALSE_STRINGS = {"0", "disabled", "draft", "inactive", "initial", "off", "paused", "stopped", "false", "no"}


@dataclass(frozen=True, slots=True)
class AutomationOperation:
    method: str
    path: str
    query: Mapping[str, Any] | None = None
    json: Any = None
    response_path: str | None = None


@dataclass(frozen=True, slots=True)
class AutomationKind:
    kind: str
    label: str
    operations: Mapping[str, AutomationOperation]
    editor_operations: Mapping[str, AutomationOperation] = field(default_factory=dict)
    id_path: str = "id"
    name_path: str = "name"
    enabled_path: str | None = "enabled"
    samples: Mapping[str, Any] = field(default_factory=dict)

    def capabilities(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "operations": sorted(self.operations),
            "editorOperations": sorted(self.editor_operations),
            "idPath": self.id_path,
            "namePath": self.name_path,
            "enabledPath": self.enabled_path,
            "samples": dict(self.samples),
        }

    def resolve_operation(self, operation_name: str, *, editor: bool = False) -> AutomationOperation:
        operations = self.editor_operations if editor else self.operations
        resolved = operations.get(operation_name)
        if resolved is None:
            operation_type = "editor" if editor else "lifecycle"
            raise ValidationError(
                code="validation_error",
                message=f"Unsupported {operation_type} automation operation: {operation_name}",
                details={
                    "kind": self.kind,
                    "operation": operation_name,
                    "allowed_operations": sorted(operations),
                },
            )
        return resolved


@dataclass(frozen=True, slots=True)
class AutomationRegistry:
    kinds: Mapping[str, AutomationKind]

    @classmethod
    def from_manifest(cls, manifest: Mapping[str, Any]) -> "AutomationRegistry":
        if not manifest:
            return cls(kinds={})
        parsed: dict[str, AutomationKind] = {}
        for raw_kind, raw_spec in manifest.items():
            kind = _require_non_empty_string(raw_kind, "kind")
            if not isinstance(raw_spec, Mapping):
                raise ConfigError(
                    code="config_error",
                    message="Automation kind definitions must be objects.",
                    details={"kind": kind},
                )
            operations = _parse_operations(kind, raw_spec.get("operations"))
            if operations is None:
                continue
            editor_operations = _parse_operations(
                kind,
                raw_spec.get("editor_operations"),
                required_operations=None,
                field_name="editor_operations",
                optional=True,
            )
            label = str(raw_spec.get("label") or kind)
            id_path = str(raw_spec.get("id_path") or "id")
            name_path = str(raw_spec.get("name_path") or "name")
            enabled_path = raw_spec.get("enabled_path", "enabled")
            if enabled_path is not None and not isinstance(enabled_path, str):
                raise ConfigError(
                    code="config_error",
                    message="enabled_path must be a string or null.",
                    details={"kind": kind},
                )
            samples = raw_spec.get("samples") or {}
            if not isinstance(samples, Mapping):
                raise ConfigError(
                    code="config_error",
                    message="Automation samples must be an object.",
                    details={"kind": kind},
                )
            parsed[kind] = AutomationKind(
                kind=kind,
                label=label,
                operations=operations,
                editor_operations=editor_operations,
                id_path=id_path,
                name_path=name_path,
                enabled_path=enabled_path,
                samples=dict(samples),
            )
        return cls(kinds=parsed)

    def capabilities(self) -> list[dict[str, Any]]:
        return [self.kinds[kind].capabilities() for kind in sorted(self.kinds)]

    def supported_kinds(self) -> list[str]:
        return sorted(self.kinds)

    def require_kind(self, kind: str) -> AutomationKind:
        normalized = _require_runtime_string(kind, "kind")
        if normalized == "all":
            raise ValidationError(
                code="validation_error",
                message='Specify a concrete kind; "all" is allowed only for list_automations.',
                details={"allowed_kinds": self.supported_kinds()},
            )
        spec = self.kinds.get(normalized)
        if spec is None:
            raise ValidationError(
                code="validation_error",
                message=f"Unsupported automation kind: {normalized}",
                details={"kind": normalized, "allowed_kinds": self.supported_kinds()},
            )
        return spec

    def kinds_for_listing(self, kind: str | None) -> list[AutomationKind]:
        if kind is None:
            return [self.kinds[name] for name in self.supported_kinds()]
        normalized = _require_runtime_string(kind, "kind")
        if normalized.lower() == "all":
            return [self.kinds[name] for name in self.supported_kinds()]
        return [self.require_kind(normalized)]


def extract_response_payload(response: Any, response_path: str | None) -> Any:
    if response_path is None:
        return response
    value = get_path_value(response, response_path)
    if value is None:
        raise NethuntMCPError(
            code="invalid_response",
            message="Automation endpoint response did not include the configured response_path.",
            details={"response_path": response_path},
        )
    return value


def normalize_automation(
    spec: AutomationKind,
    raw: Any,
    *,
    fallback_id: str | None = None,
    fallback_name: str | None = None,
    fallback_enabled: bool | None = None,
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise NethuntMCPError(
            code="invalid_response",
            message="Automation endpoint returned an unexpected JSON shape.",
            details={"kind": spec.kind, "expected": "object"},
        )
    automation_id = get_path_value(raw, spec.id_path) or fallback_id
    if automation_id is None:
        raise NethuntMCPError(
            code="invalid_response",
            message="Automation payload did not include an identifier.",
            details={"kind": spec.kind, "id_path": spec.id_path},
        )
    name = get_path_value(raw, spec.name_path)
    if name is None:
        name = fallback_name
    enabled = fallback_enabled
    if spec.enabled_path is not None:
        resolved_enabled = get_path_value(raw, spec.enabled_path)
        enabled = _coerce_enabled_value(resolved_enabled, default=enabled)
    return {
        "kind": spec.kind,
        "automationId": str(automation_id),
        "name": name if isinstance(name, str) else None,
        "enabled": enabled,
        "raw": dict(raw),
    }


def render_template(template: Any, context: Mapping[str, Any]) -> Any:
    if isinstance(template, Mapping):
        return {key: render_template(value, context) for key, value in template.items()}
    if isinstance(template, list):
        return [render_template(value, context) for value in template]
    if isinstance(template, str):
        if template.startswith(TOKEN_PREFIX) and template.count("{") == 0:
            return context.get(template[1:])
        format_context = {key: value for key, value in context.items() if _is_format_safe(value)}
        payload = context.get("payload")
        if isinstance(payload, Mapping):
            for k, v in payload.items():
                if _is_format_safe(v) and k not in format_context:
                    format_context[k] = v
        try:
            return template.format(**format_context)
        except KeyError as exc:
            missing = str(exc).strip("'")
            raise ValidationError(
                code="validation_error",
                message=f"Template variable '{{{missing}}}' is not available. "
                        "Use $variable for whole-value substitution or pass the value inside the payload.",
                details={"missing": missing, "available": sorted(format_context)},
            ) from exc
    return template


def get_path_value(payload: Any, path: str | None) -> Any:
    if path is None:
        return None
    current = payload
    for segment in path.split("."):
        if isinstance(current, list):
            if not segment.isdigit():
                return None
            index = int(segment)
            if not 0 <= index < len(current):
                return None
            current = current[index]
            continue
        if isinstance(current, Mapping) and segment in current:
            current = current[segment]
            continue
        return None
    return current


def _parse_operations(
    kind: str,
    raw_operations: Any,
    *,
    required_operations: tuple[str, ...] | None = REQUIRED_AUTOMATION_OPERATIONS,
    field_name: str = "operations",
    optional: bool = False,
) -> dict[str, AutomationOperation] | None:
    if raw_operations is None:
        return {} if optional else None
    if not isinstance(raw_operations, Mapping):
        raise ConfigError(
            code="config_error",
            message=f"Automation {field_name} must be an object.",
            details={"kind": kind, "field": field_name},
        )
    if required_operations is not None and any(name not in raw_operations for name in required_operations):
        return None
    operation_names = tuple(raw_operations) if required_operations is None else required_operations
    operations: dict[str, AutomationOperation] = {}
    for operation_name in operation_names:
        raw_spec = raw_operations[operation_name]
        if not isinstance(raw_spec, Mapping):
            raise ConfigError(
                code="config_error",
                message=f"Each automation {field_name} entry must be an object.",
                details={"kind": kind, "operation": operation_name, "field": field_name},
            )
        method = _require_non_empty_string(raw_spec.get("method"), "method").upper()
        if method not in SUPPORTED_HTTP_METHODS:
            raise ConfigError(
                code="config_error",
                message="Unsupported HTTP method in automation manifest.",
                details={"kind": kind, "operation": operation_name, "method": method, "field": field_name},
            )
        path = _require_non_empty_string(raw_spec.get("path"), "path")
        query = raw_spec.get("query")
        if query is not None and not isinstance(query, Mapping):
            raise ConfigError(
                code="config_error",
                message="Automation operation query must be an object.",
                details={"kind": kind, "operation": operation_name, "field": field_name},
            )
        response_path = raw_spec.get("response_path")
        if response_path is not None and not isinstance(response_path, str):
            raise ConfigError(
                code="config_error",
                message="Automation operation response_path must be a string.",
                details={"kind": kind, "operation": operation_name, "field": field_name},
            )
        operations[operation_name] = AutomationOperation(
            method=method,
            path=path,
            query=dict(query) if isinstance(query, Mapping) else None,
            json=raw_spec.get("json"),
            response_path=response_path,
        )
    return operations


def _is_format_safe(value: Any) -> bool:
    return isinstance(value, (bool, float, int, str))


def _coerce_enabled_value(value: Any, *, default: bool | None) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ENABLED_TRUE_STRINGS:
            return True
        if normalized in ENABLED_FALSE_STRINGS:
            return False
        return default
    if value is None:
        return default
    return bool(value)


def _require_non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(code="config_error", message=f"{field_name} must be a non-empty string.")
    return value.strip()


def _require_runtime_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(code="validation_error", message=f"{field_name} is required.")
    return value.strip()
