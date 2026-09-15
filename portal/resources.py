"""Closed, typed Stage 13 configuration and data-resource boundary.

Resource IDs are catalog keys, never paths.  The portal depends only on these
contracts and does not import a bot package.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Mapping, Protocol

from shared.bot_core.jsonio import atomic_write_json
from shared.bot_core.secure_path import AuthorizedPath

RESOURCE_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
DISCORD_ID = re.compile(r"^[1-9][0-9]{16,19}$")


class FieldType(StrEnum):
    BOOLEAN = "boolean"
    INTEGER = "integer"
    STRING = "string"
    ENUM = "enum"
    DISCORD_CHANNEL_ID = "discord-channel-id"


class RuntimeAction(StrEnum):
    NONE = "none"
    RESTART = "restart"


@dataclass(frozen=True, slots=True)
class ConfigField:
    field_id: str
    label: str
    description: str
    field_type: FieldType
    required: bool = True
    minimum: int | None = None
    maximum: int | None = None
    maximum_length: int | None = None
    choices: tuple[str, ...] = ()
    sensitive: bool = False
    read_only: bool = False
    restart_required: bool = False


@dataclass(frozen=True, slots=True)
class ConfigurationResource:
    resource_id: str
    bot_id: str
    display_name: str
    category: str
    description: str
    fields: tuple[ConfigField, ...]
    read_permission: str = "config.view"
    edit_permission: str | None = "config.edit"
    persistence_owner: str = "bot process"
    location_key: str = ""
    revision_strategy: str = "sha256-canonical-content"
    write_strategy: str = "atomic-replace"
    runtime_action: RuntimeAction = RuntimeAction.RESTART
    sensitivity: str = "internal"
    backup_importance: str = "high"
    exposure_policy: str = "declared-fields-only"
    validator: Callable[[Mapping[str, object]], None] | None = None


@dataclass(frozen=True, slots=True)
class DataResource:
    resource_id: str
    bot_id: str
    display_name: str
    category: str
    description: str
    fields: tuple[str, ...]
    read_permission: str = "data.view"
    persistence_owner: str = "bot process"
    location_key: str = ""
    revision_strategy: str = "sha256-canonical-content"
    sensitivity: str = "restricted"
    default_page_size: int = 25
    maximum_page_size: int = 100
    sort_key: str = "user_id"


CHANNEL_FIELDS = tuple(
    ConfigField(
        name,
        label,
        "Discord channel snowflake; changing routing requires a process restart.",
        FieldType.DISCORD_CHANNEL_ID,
        restart_required=True,
    )
    for name, label in (
        ("verification", "Verification channel"),
        ("payannounce", "Pay announcement channel"),
        ("banlogs", "Ban log channel"),
        ("general", "General channel"),
    )
)

# Audited from cda_admin/defaults/server.json.  Other bot files combine unclear,
# bot-written state with configuration and are intentionally deferred.
TRUSTED_CONFIGURATION_CATALOG: Mapping[tuple[str, str], ConfigurationResource] = {
    ("cda-admin", "channel-routing"): ConfigurationResource(
        "channel-routing",
        "cda-admin",
        "Channel routing",
        "Discord",
        "Channels used by verification, announcements, audit, and general workflows.",
        CHANNEL_FIELDS,
        location_key="cda-admin-server",
    )
}

TRUSTED_DATA_CATALOG: Mapping[tuple[str, str], DataResource] = {
    ("cda-admin", "verified-users"): DataResource(
        "verified-users",
        "cda-admin",
        "Verified users",
        "Verification",
        "A bounded view of verified Discord user identifiers.",
        ("user_id",),
        location_key="cda-admin-server",
    )
}


class ResourceError(Exception):
    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code, self.safe_message, self.status = code, message, status


@dataclass(frozen=True, slots=True)
class ConfigSnapshot:
    values: Mapping[str, object]
    revision: str


@dataclass(frozen=True, slots=True)
class ConfigChange:
    field_id: str
    old_value: object
    new_value: object
    restart_required: bool
    reload_required: bool = False


@dataclass(frozen=True, slots=True)
class ConfigPreview:
    resource: ConfigurationResource
    expected_revision: str
    proposed_revision: str
    values: Mapping[str, object]
    changes: tuple[ConfigChange, ...]


@dataclass(frozen=True, slots=True)
class DataPage:
    resource: DataResource
    records: tuple[Mapping[str, object], ...]
    next_cursor: str | None
    revision: str


class ResourceAdapter(Protocol):
    def read_config(self, resource: ConfigurationResource) -> ConfigSnapshot: ...
    def write_config(
        self, resource: ConfigurationResource, values: Mapping[str, object], expected_revision: str
    ) -> ConfigSnapshot: ...
    def read_data(self, resource: DataResource) -> tuple[tuple[Mapping[str, object], ...], str]: ...


class ResourceAuthorizer(Protocol):
    def can(
        self, actor, permission: str, *, bot_id: str | None = None, resource_id: str | None = None
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class ResourceAuditEvent:
    name: str
    actor: str
    bot_id: str
    resource_id: str
    request_id: str
    result: str
    revision_before: str | None = None
    revision_after: str | None = None
    changed_fields: tuple[str, ...] = ()


def _revision(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_values(
    resource: ConfigurationResource, submitted: Mapping[str, object]
) -> dict[str, object]:
    fields = {item.field_id: item for item in resource.fields}
    if set(submitted) - set(fields):
        raise ResourceError("validation_failed", "Configuration contains an unknown field.", 422)
    result: dict[str, object] = {}
    for name, definition in fields.items():
        if definition.read_only and name in submitted:
            raise ResourceError("validation_failed", "A read-only field cannot be changed.", 422)
        if name not in submitted:
            if definition.required:
                raise ResourceError("validation_failed", "A required field is missing.", 422)
            continue
        value = submitted[name]
        valid = True
        if definition.field_type is FieldType.BOOLEAN:
            valid = type(value) is bool
        elif definition.field_type is FieldType.INTEGER:
            valid = type(value) is int
        elif definition.field_type is FieldType.STRING:
            valid = isinstance(value, str)
        elif definition.field_type is FieldType.ENUM:
            valid = isinstance(value, str) and value in definition.choices
        elif definition.field_type is FieldType.DISCORD_CHANNEL_ID:
            valid = isinstance(value, str) and DISCORD_ID.fullmatch(value) is not None
        if not valid:
            raise ResourceError("validation_failed", f"Field {name} has an invalid value.", 422)
        if isinstance(value, int) and (
            (definition.minimum is not None and value < definition.minimum)
            or (definition.maximum is not None and value > definition.maximum)
        ):
            raise ResourceError(
                "validation_failed", f"Field {name} is outside its allowed range.", 422
            )
        if (
            isinstance(value, str)
            and definition.maximum_length is not None
            and len(value) > definition.maximum_length
        ):
            raise ResourceError("validation_failed", f"Field {name} is too long.", 422)
        result[name] = value
    if resource.validator:
        resource.validator(result)
    return result


class ResourceService:
    def __init__(
        self, adapter: ResourceAdapter, authorizer: ResourceAuthorizer, audit_sink=None
    ) -> None:
        self.adapter, self.authorizer, self.audit_sink = adapter, authorizer, audit_sink

    def _require(self, actor, permission: str, bot_id: str, resource_id: str) -> None:
        if not self.authorizer.can(actor, permission, bot_id=bot_id, resource_id=resource_id):
            raise ResourceError("permission_denied", "Permission is denied.", 403)

    @staticmethod
    def _config(bot_id: str, resource_id: str) -> ConfigurationResource:
        if len(resource_id) > 64 or not RESOURCE_ID.fullmatch(resource_id):
            raise ResourceError("resource_not_found", "Resource was not found.", 404)
        item = TRUSTED_CONFIGURATION_CATALOG.get((bot_id, resource_id))
        if item is None:
            raise ResourceError("resource_not_found", "Resource was not found.", 404)
        return item

    def list_config(self, actor, bot_id: str) -> tuple[ConfigurationResource, ...]:
        return tuple(
            item
            for (owner, _), item in TRUSTED_CONFIGURATION_CATALOG.items()
            if owner == bot_id
            and self.authorizer.can(
                actor, item.read_permission, bot_id=bot_id, resource_id=item.resource_id
            )
        )

    def list_data(self, actor, bot_id: str) -> tuple[DataResource, ...]:
        return tuple(
            item
            for (owner, _), item in TRUSTED_DATA_CATALOG.items()
            if owner == bot_id
            and self.authorizer.can(
                actor,
                item.read_permission,
                bot_id=bot_id,
                resource_id=item.resource_id,
            )
        )

    def get_config(
        self, actor, bot_id: str, resource_id: str, request_id: str
    ) -> tuple[ConfigurationResource, ConfigSnapshot]:
        item = self._config(bot_id, resource_id)
        self._require(actor, item.read_permission, bot_id, resource_id)
        snapshot = self.adapter.read_config(item)
        self._audit("config.viewed", actor, item, request_id, "succeeded", after=snapshot.revision)
        return item, snapshot

    def preview(
        self,
        actor,
        bot_id: str,
        resource_id: str,
        submitted: Mapping[str, object],
        expected_revision: str,
        request_id: str,
    ) -> ConfigPreview:
        item = self._config(bot_id, resource_id)
        if item.edit_permission is None:
            raise ResourceError("resource_read_only", "Resource is read-only.", 409)
        self._require(actor, item.edit_permission, bot_id, resource_id)
        values = validate_values(item, submitted)
        current = self.adapter.read_config(item)
        if current.revision != expected_revision:
            raise ResourceError(
                "stale_revision", "Configuration changed; review the latest values.", 409
            )
        definitions = {field.field_id: field for field in item.fields}
        changes = tuple(
            ConfigChange(
                name,
                "changed" if definitions[name].sensitive else current.values.get(name),
                "changed" if definitions[name].sensitive else value,
                definitions[name].restart_required,
            )
            for name, value in values.items()
            if current.values.get(name) != value
        )
        preview = ConfigPreview(item, expected_revision, _revision(values), values, changes)
        self._audit(
            "config.previewed",
            actor,
            item,
            request_id,
            "succeeded",
            before=current.revision,
            after=preview.proposed_revision,
            fields=tuple(change.field_id for change in changes),
        )
        return preview

    def commit(
        self,
        actor,
        bot_id: str,
        resource_id: str,
        submitted: Mapping[str, object],
        expected_revision: str,
        request_id: str,
    ) -> ConfigSnapshot:
        preview = self.preview(actor, bot_id, resource_id, submitted, expected_revision, request_id)
        try:
            result = self.adapter.write_config(preview.resource, preview.values, expected_revision)
        except ResourceError:
            self._audit(
                "config.change_failed",
                actor,
                preview.resource,
                request_id,
                "failed",
                before=expected_revision,
            )
            raise
        self._audit(
            "config.changed",
            actor,
            preview.resource,
            request_id,
            "succeeded",
            before=expected_revision,
            after=result.revision,
            fields=tuple(change.field_id for change in preview.changes),
        )
        return result

    def data_page(
        self,
        actor,
        bot_id: str,
        resource_id: str,
        request_id: str,
        *,
        limit: int = 25,
        cursor: str | None = None,
    ) -> DataPage:
        if len(resource_id) > 64 or not RESOURCE_ID.fullmatch(resource_id):
            raise ResourceError("resource_not_found", "Resource was not found.", 404)
        item = TRUSTED_DATA_CATALOG.get((bot_id, resource_id))
        if item is None:
            raise ResourceError("resource_not_found", "Resource was not found.", 404)
        self._require(actor, item.read_permission, bot_id, resource_id)
        if limit < 1 or limit > item.maximum_page_size:
            raise ResourceError("validation_failed", "Page size is outside its allowed range.", 422)
        start = 0
        if cursor:
            try:
                start = int(base64.urlsafe_b64decode(cursor.encode() + b"===").decode())
            except (ValueError, UnicodeError):
                raise ResourceError(
                    "validation_failed", "Pagination cursor is invalid.", 422
                ) from None
            if start < 0:
                raise ResourceError("validation_failed", "Pagination cursor is invalid.", 422)
        records, revision = self.adapter.read_data(item)
        safe = tuple(
            {field: record[field] for field in item.fields if field in record}
            for record in sorted(records, key=lambda row: str(row[item.sort_key]))
        )
        page = safe[start : start + limit]
        next_cursor = (
            base64.urlsafe_b64encode(str(start + limit).encode()).decode().rstrip("=")
            if start + limit < len(safe)
            else None
        )
        result = DataPage(item, page, next_cursor, revision)
        self._audit("data.viewed", actor, item, request_id, "succeeded", after=revision)
        return result

    def _audit(
        self, name, actor, resource, request_id, result, *, before=None, after=None, fields=()
    ):
        if callable(self.audit_sink):
            self.audit_sink(
                ResourceAuditEvent(
                    name,
                    actor.principal_id,
                    resource.bot_id,
                    resource.resource_id,
                    request_id,
                    result,
                    before,
                    after,
                    fields,
                )
            )


class InMemoryResourceAdapter:
    """Deterministic fake used by portal composition and tests; never production data."""

    def __init__(self, configs=None, data=None) -> None:
        self.configs = dict(configs or {})
        self.data = dict(data or {})
        self._lock = threading.RLock()
        self.fail_write = False

    def read_config(self, resource):
        with self._lock:
            values = dict(self.configs[resource.location_key])
            return ConfigSnapshot(values, _revision(values))

    def write_config(self, resource, values, expected_revision):
        with self._lock:
            current = self.read_config(resource)
            if current.revision != expected_revision:
                raise ResourceError(
                    "stale_revision", "Configuration changed; review the latest values.", 409
                )
            if self.fail_write:
                raise ResourceError("persistence_failed", "Configuration could not be saved.", 503)
            self.configs[resource.location_key] = dict(values)
            return self.read_config(resource)

    def read_data(self, resource):
        with self._lock:
            rows = tuple(dict(row) for row in self.data.get(resource.location_key, ()))
            return rows, _revision(rows)


class AtomicJsonResourceAdapter:
    """Explicit adapter for the single audited file; callers supply a trusted capability."""

    def __init__(self, locations: Mapping[str, AuthorizedPath]) -> None:
        self._locations = dict(locations)
        self._locks = {key: threading.RLock() for key in locations}

    def _load(self, key: str) -> dict[str, object]:
        location = self._locations[key]
        try:
            descriptor = os.open(location.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, ValueError, TypeError) as exc:
            raise ResourceError(
                "resource_temporarily_unavailable", "Resource is unavailable.", 503
            ) from exc
        if not isinstance(value, dict):
            raise ResourceError("resource_temporarily_unavailable", "Resource is unavailable.", 503)
        return value

    def read_config(self, resource):
        with self._locks[resource.location_key]:
            document = self._load(resource.location_key)
            channels = document.get("channels")
            if not isinstance(channels, dict):
                raise ResourceError(
                    "resource_temporarily_unavailable", "Resource is unavailable.", 503
                )
            values = {field.field_id: str(channels[field.field_id]) for field in resource.fields}
            validate_values(resource, values)
            return ConfigSnapshot(values, _revision(document))

    def write_config(self, resource, values, expected_revision):
        with self._locks[resource.location_key]:
            document = self._load(resource.location_key)
            if _revision(document) != expected_revision:
                raise ResourceError(
                    "stale_revision", "Configuration changed; review the latest values.", 409
                )
            updated = dict(document)
            updated["channels"] = {name: int(value) for name, value in values.items()}
            try:
                atomic_write_json(self._locations[resource.location_key], updated)
            except OSError as exc:
                raise ResourceError(
                    "persistence_failed", "Configuration could not be saved.", 503
                ) from exc
            return ConfigSnapshot(dict(values), _revision(updated))

    def read_data(self, resource):
        with self._locks[resource.location_key]:
            document = self._load(resource.location_key)
            raw = document.get("verified_users", [])
            if not isinstance(raw, list):
                raise ResourceError(
                    "resource_temporarily_unavailable", "Resource is unavailable.", 503
                )
            records = tuple({"user_id": str(item)} for item in raw if isinstance(item, (str, int)))
            return records, _revision(document)
