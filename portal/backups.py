"""Closed, per-bot Stage 14 backup and recovery boundary.

The on-disk format is deliberately a directory, not an archive: manifest members
are fixed catalog names and are never extracted or mapped to live paths.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from shared.bot_core.jsonio import atomic_write_json
from .resources import ConfigurationResource, ResourceError, ResourceService

FORMAT_VERSION = 1
BACKUP_ID = re.compile(r"^[0-9a-f]{32}$")
PLAN_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
MAX_RESOURCE_BYTES = 2 * 1024 * 1024
MAX_BACKUP_BYTES = 10 * 1024 * 1024
MAX_RESOURCES = 16
DEFAULT_RETENTION = 10


class BackupError(Exception):
    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code, self.safe_message, self.status = code, message, status


@dataclass(frozen=True, slots=True)
class BackupResource:
    resource_id: str
    kind: str = "configuration"
    schema_version: int = 1
    restart_required: bool = True


@dataclass(frozen=True, slots=True)
class BackupPlan:
    plan_id: str
    bot_id: str
    display_name: str
    resources: tuple[BackupResource, ...]
    retention: int = DEFAULT_RETENTION


# Stage 13 has established safe ownership and restoration semantics only for this
# typed configuration resource. Deferred bot state is intentionally not inferred.
TRUSTED_BACKUP_PLANS: Mapping[tuple[str, str], BackupPlan] = {
    ("cda-admin", "cda-admin-configuration"): BackupPlan(
        "cda-admin-configuration",
        "cda-admin",
        "CDA Admin typed configuration",
        (BackupResource("channel-routing"),),
    )
}


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    resource_id: str
    kind: str
    schema_version: int
    revision: str
    sha256: str
    size: int
    restart_required: bool


@dataclass(frozen=True, slots=True)
class BackupRecord:
    backup_id: str
    bot_id: str
    plan_id: str
    created_at: datetime
    creator: str
    status: str
    total_bytes: int
    format_version: int
    integrity_status: str
    resources: tuple[ManifestEntry, ...]
    operation_id: str
    safety_snapshot: bool = False


@dataclass(frozen=True, slots=True)
class RestoreChange:
    resource_id: str
    current_revision: str
    backup_revision: str
    summary: str
    restart_required: bool


@dataclass(frozen=True, slots=True)
class RestorePreview:
    preview_id: str
    backup_id: str
    bot_id: str
    changes: tuple[RestoreChange, ...]
    process_instance_id: str | None = None


@dataclass(frozen=True, slots=True)
class BackupAuditEvent:
    name: str
    actor: str
    bot_id: str
    request_id: str
    operation_id: str
    result: str
    backup_id: str | None = None
    plan_id: str | None = None
    resource_ids: tuple[str, ...] = ()
    revisions_before: tuple[str, ...] = ()
    revisions_after: tuple[str, ...] = ()
    rollback_result: str | None = None


class BackupService:
    """Synchronous bounded operations serialized per bot.

    Resource I/O is delegated to the Stage 13 typed adapter. No caller provides a
    path, filename, member name, resource set, or restore destination.
    """

    def __init__(
        self,
        storage_root: Path,
        resources: ResourceService,
        authorizer,
        *,
        audit_sink: Callable[[BackupAuditEvent], None] | None = None,
        max_total_bytes_per_bot: int = 100 * 1024 * 1024,
        process_instance: Callable[[str], str | None] | None = None,
    ) -> None:
        root = storage_root.resolve()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if root.is_symlink():
            raise ValueError("backup root must not be a symlink")
        self._root = root
        self._resources = resources
        self._authorizer = authorizer
        self._audit_sink = audit_sink
        self._max_total = max_total_bytes_per_bot
        self._process_instance = process_instance or (lambda _bot: None)
        self._locks = {bot: threading.Lock() for bot in {key[0] for key in TRUSTED_BACKUP_PLANS}}
        self._previews: dict[str, tuple[str, str, str, dict[str, str], str | None]] = {}
        self._active_restore: set[str] = set()

    def _require(self, actor, permission: str, bot_id: str) -> None:
        if not self._authorizer.can(actor, permission, bot_id=bot_id):
            raise BackupError("permission_denied", "Permission is denied.", 403)

    @staticmethod
    def _valid_id(value: str) -> bool:
        return len(value) == 32 and BACKUP_ID.fullmatch(value) is not None

    def _plan(self, bot_id: str, plan_id: str) -> BackupPlan:
        if len(plan_id) > 64 or PLAN_ID.fullmatch(plan_id) is None:
            raise BackupError("backup_plan_not_supported", "Backup plan is not supported.", 404)
        plan = TRUSTED_BACKUP_PLANS.get((bot_id, plan_id))
        if plan is None:
            raise BackupError("backup_plan_not_supported", "Backup plan is not supported.", 404)
        return plan

    def _bot_root(self, bot_id: str) -> Path:
        if bot_id not in {key[0] for key in TRUSTED_BACKUP_PLANS}:
            raise BackupError("backup_plan_not_supported", "Backup plan is not supported.", 404)
        path = self._root / bot_id
        path.mkdir(mode=0o700, exist_ok=True)
        if path.is_symlink() or not path.resolve().is_relative_to(self._root):
            raise BackupError("persistence_failed", "Backup storage is unavailable.", 503)
        return path

    def _backup_path(self, bot_id: str, backup_id: str) -> Path:
        if not self._valid_id(backup_id):
            raise BackupError("backup_not_found", "Backup was not found.", 404)
        result = self._bot_root(bot_id) / backup_id
        if result.is_symlink() or not result.resolve().is_relative_to(self._bot_root(bot_id)):
            raise BackupError("backup_not_found", "Backup was not found.", 404)
        return result

    def list_backup_plans(self, actor, bot_id: str) -> tuple[BackupPlan, ...]:
        self._require(actor, "backups.view", bot_id)
        return tuple(plan for (owner, _), plan in TRUSTED_BACKUP_PLANS.items() if owner == bot_id)

    def list_backups(self, actor, bot_id: str) -> tuple[BackupRecord, ...]:
        self._require(actor, "backups.view", bot_id)
        records = self._catalog(bot_id)
        return tuple(
            sorted(
                (x for x in records if not x.safety_snapshot),
                key=lambda x: x.created_at,
                reverse=True,
            )
        )

    def get_backup(self, actor, bot_id: str, backup_id: str) -> BackupRecord:
        self._require(actor, "backups.view", bot_id)
        return self._record(bot_id, backup_id, expose_safety=False)

    def create_backup(self, actor, bot_id: str, plan_id: str, request_id: str) -> BackupRecord:
        self._require(actor, "backups.create", bot_id)
        return self._create(
            actor.principal_id, bot_id, self._plan(bot_id, plan_id), request_id, False
        )

    def _create(
        self, actor: str, bot_id: str, plan: BackupPlan, request_id: str, safety: bool
    ) -> BackupRecord:
        lock = self._locks[bot_id]
        if not lock.acquire(blocking=False):
            raise BackupError("backup_in_progress", "A backup or restore is already in progress.")
        try:
            return self._create_locked(actor, bot_id, plan, request_id, safety)
        finally:
            lock.release()

    def _create_locked(
        self, actor: str, bot_id: str, plan: BackupPlan, request_id: str, safety: bool
    ) -> BackupRecord:
        backup_id, operation_id = uuid.uuid4().hex, str(uuid.uuid4())
        bot_root = self._bot_root(bot_id)
        stage = bot_root / f".{backup_id}.tmp"
        final = bot_root / backup_id
        self._audit(
            "backup.requested",
            actor,
            bot_id,
            request_id,
            operation_id,
            "requested",
            backup_id,
            plan,
        )
        try:
            stage.mkdir(mode=0o700)
            payload = stage / "payload"
            payload.mkdir(mode=0o700)
            entries: list[ManifestEntry] = []
            total = 0
            for declared in plan.resources:
                resource = self._config(bot_id, declared.resource_id)
                snapshot = self._resources.adapter.read_config(resource)
                encoded = json.dumps(
                    snapshot.values, sort_keys=True, separators=(",", ":")
                ).encode()
                if len(encoded) > MAX_RESOURCE_BYTES or total + len(encoded) > MAX_BACKUP_BYTES:
                    raise BackupError(
                        "backup_storage_full", "Backup size limit would be exceeded.", 507
                    )
                member = payload / f"{declared.resource_id}.json"
                self._write_bytes(member, encoded)
                entries.append(
                    ManifestEntry(
                        declared.resource_id,
                        declared.kind,
                        declared.schema_version,
                        snapshot.revision,
                        hashlib.sha256(encoded).hexdigest(),
                        len(encoded),
                        declared.restart_required,
                    )
                )
                total += len(encoded)
            if len(entries) > MAX_RESOURCES:
                raise BackupError(
                    "backup_storage_full", "Backup resource limit would be exceeded.", 507
                )
            created = datetime.now(timezone.utc)
            manifest = self._manifest(
                backup_id,
                bot_id,
                plan.plan_id,
                created,
                actor,
                entries,
                total,
                operation_id,
                safety,
            )
            self._write_bytes(
                stage / "manifest.json",
                json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode(),
            )
            self._parse_manifest(stage, bot_id, backup_id, plan)
            if sum(x.total_bytes for x in self._catalog(bot_id)) + total > self._max_total:
                self._retention(bot_id, plan, reserve=1)
                if sum(x.total_bytes for x in self._catalog(bot_id)) + total > self._max_total:
                    raise BackupError(
                        "backup_storage_full", "Backup storage limit would be exceeded.", 507
                    )
            os.replace(stage, final)
            record = self._parse_manifest(final, bot_id, backup_id, plan)
            self._save_catalog(bot_id, [*self._catalog(bot_id), record])
            self._retention(bot_id, plan)
            self._audit(
                "backup.succeeded",
                actor,
                bot_id,
                request_id,
                operation_id,
                "succeeded",
                backup_id,
                plan,
            )
            return record
        except BackupError:
            self._audit(
                "backup.failed", actor, bot_id, request_id, operation_id, "failed", backup_id, plan
            )
            raise
        except (OSError, ValueError, ResourceError) as exc:
            self._audit(
                "backup.failed", actor, bot_id, request_id, operation_id, "failed", backup_id, plan
            )
            raise BackupError("persistence_failed", "Backup could not be created.", 503) from exc
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def preview_restore(
        self, actor, bot_id: str, backup_id: str, request_id: str
    ) -> RestorePreview:
        self._require(actor, "backups.restore", bot_id)
        record = self._record(bot_id, backup_id, expose_safety=False)
        path = self._backup_path(bot_id, backup_id)
        plan = self._plan(bot_id, record.plan_id)
        verified = self._parse_manifest(path, bot_id, backup_id, plan)
        revisions: dict[str, str] = {}
        changes = []
        for entry in verified.resources:
            current = self._resources.adapter.read_config(self._config(bot_id, entry.resource_id))
            revisions[entry.resource_id] = current.revision
            changes.append(
                RestoreChange(
                    entry.resource_id,
                    current.revision,
                    entry.revision,
                    "will change" if current.revision != entry.revision else "unchanged",
                    entry.restart_required,
                )
            )
        preview_id = uuid.uuid4().hex
        instance = self._process_instance(bot_id)
        self._previews[preview_id] = (actor.principal_id, bot_id, backup_id, revisions, instance)
        self._audit(
            "restore.previewed",
            actor.principal_id,
            bot_id,
            request_id,
            str(uuid.uuid4()),
            "succeeded",
            backup_id,
            plan,
        )
        return RestorePreview(preview_id, backup_id, bot_id, tuple(changes), instance)

    def restore_backup(
        self, actor, bot_id: str, backup_id: str, preview_id: str, request_id: str
    ) -> BackupRecord:
        self._require(actor, "backups.restore", bot_id)
        preview = self._previews.pop(preview_id, None) if self._valid_id(preview_id) else None
        if preview is None or preview[:3] != (actor.principal_id, bot_id, backup_id):
            raise BackupError(
                "stale_restore_preview", "Restore preview is stale; create a new preview."
            )
        record = self._record(bot_id, backup_id, expose_safety=False)
        plan = self._plan(bot_id, record.plan_id)
        lock = self._locks[bot_id]
        if not lock.acquire(blocking=False):
            raise BackupError("restore_in_progress", "A backup or restore is already in progress.")
        operation_id = str(uuid.uuid4())
        before = preview[3]
        self._active_restore.add(backup_id)
        try:
            verified = self._parse_manifest(
                self._backup_path(bot_id, backup_id), bot_id, backup_id, plan
            )
            if preview[4] != self._process_instance(bot_id):
                raise BackupError(
                    "stale_restore_preview", "Restore preview is stale; create a new preview."
                )
            for entry in verified.resources:
                current = self._resources.adapter.read_config(
                    self._config(bot_id, entry.resource_id)
                )
                if current.revision != before[entry.resource_id]:
                    raise BackupError(
                        "stale_restore_preview", "Restore preview is stale; create a new preview."
                    )
            safety = self._create_locked(actor.principal_id, bot_id, plan, request_id, True)
            applied: list[ManifestEntry] = []
            try:
                for entry in verified.resources:
                    values = json.loads(
                        (
                            self._backup_path(bot_id, backup_id)
                            / "payload"
                            / f"{entry.resource_id}.json"
                        ).read_bytes()
                    )
                    result = self._resources.adapter.write_config(
                        self._config(bot_id, entry.resource_id), values, before[entry.resource_id]
                    )
                    applied.append(entry)
                    if result.revision != entry.revision:
                        raise BackupError("restore_failed", "Restore verification failed.", 503)
            except Exception as exc:
                try:
                    self._restore_snapshot(bot_id, safety, applied)
                except Exception as rollback_exc:
                    self._audit(
                        "restore.failed",
                        actor.principal_id,
                        bot_id,
                        request_id,
                        operation_id,
                        "manual_recovery_required",
                        backup_id,
                        plan,
                        "failed",
                    )
                    raise BackupError(
                        "manual_recovery_required",
                        "Restore failed; operator recovery is required.",
                        503,
                    ) from rollback_exc
                self._audit(
                    "restore.failed",
                    actor.principal_id,
                    bot_id,
                    request_id,
                    operation_id,
                    "restore_failed_rolled_back",
                    backup_id,
                    plan,
                    "succeeded",
                )
                raise BackupError(
                    "restore_failed_rolled_back", "Restore failed and was rolled back.", 503
                ) from exc
            self._audit(
                "restore.succeeded",
                actor.principal_id,
                bot_id,
                request_id,
                operation_id,
                "succeeded",
                backup_id,
                plan,
                resource_ids=tuple(x.resource_id for x in verified.resources),
                before=tuple(before.values()),
                after=tuple(x.revision for x in verified.resources),
            )
            return verified
        finally:
            self._active_restore.discard(backup_id)
            lock.release()

    def _restore_snapshot(
        self, bot_id: str, snapshot: BackupRecord, applied: list[ManifestEntry]
    ) -> None:
        entries = {x.resource_id: x for x in snapshot.resources}
        for changed in reversed(applied):
            resource = self._config(bot_id, changed.resource_id)
            current = self._resources.adapter.read_config(resource)
            entry = entries[changed.resource_id]
            values = json.loads(
                (
                    self._backup_path(bot_id, snapshot.backup_id)
                    / "payload"
                    / f"{entry.resource_id}.json"
                ).read_bytes()
            )
            self._resources.adapter.write_config(resource, values, current.revision)

    @staticmethod
    def _config(bot_id: str, resource_id: str) -> ConfigurationResource:
        try:
            return ResourceService._config(bot_id, resource_id)
        except ResourceError as exc:
            raise BackupError("backup_incompatible", "Backup is not compatible.") from exc

    @staticmethod
    def _write_bytes(path: Path, value: bytes) -> None:
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _manifest(
        backup_id, bot_id, plan_id, created, creator, entries, total, operation_id, safety
    ):
        return {
            "backup_format_version": FORMAT_VERSION,
            "backup_id": backup_id,
            "bot_id": bot_id,
            "plan_id": plan_id,
            "created_at": created.isoformat(),
            "creator": creator,
            "status": "completed",
            "total_bytes": total,
            "operation_id": operation_id,
            "safety_snapshot": safety,
            "resources": [asdict(x) for x in entries],
        }

    def _parse_manifest(
        self, directory: Path, bot_id: str, backup_id: str, plan: BackupPlan
    ) -> BackupRecord:
        try:
            if directory.is_symlink() or not directory.resolve().is_relative_to(
                self._bot_root(bot_id)
            ):
                raise ValueError
            raw_bytes = (directory / "manifest.json").read_bytes()
            if len(raw_bytes) > 64 * 1024:
                raise ValueError
            raw = json.loads(raw_bytes)
            expected = {
                "backup_format_version",
                "backup_id",
                "bot_id",
                "plan_id",
                "created_at",
                "creator",
                "status",
                "total_bytes",
                "operation_id",
                "safety_snapshot",
                "resources",
            }
            if (
                not isinstance(raw, dict)
                or set(raw) != expected
                or raw["backup_format_version"] != FORMAT_VERSION
                or raw["backup_id"] != backup_id
                or raw["bot_id"] != bot_id
                or raw["plan_id"] != plan.plan_id
                or raw["status"] != "completed"
            ):
                raise ValueError
            declared = {x.resource_id: x for x in plan.resources}
            if (
                not isinstance(raw["resources"], list)
                or len(raw["resources"]) != len(declared)
                or len(raw["resources"]) > MAX_RESOURCES
            ):
                raise ValueError
            entries = []
            seen = set()
            for item in raw["resources"]:
                keys = {
                    "resource_id",
                    "kind",
                    "schema_version",
                    "revision",
                    "sha256",
                    "size",
                    "restart_required",
                }
                if (
                    not isinstance(item, dict)
                    or set(item) != keys
                    or item["resource_id"] in seen
                    or item["resource_id"] not in declared
                ):
                    raise ValueError
                definition = declared[item["resource_id"]]
                if (
                    item["kind"] != definition.kind
                    or item["schema_version"] != definition.schema_version
                    or type(item["size"]) is not int
                    or not 0 <= item["size"] <= MAX_RESOURCE_BYTES
                ):
                    raise ValueError
                member = directory / "payload" / f"{item['resource_id']}.json"
                if member.is_symlink() or not member.resolve().is_relative_to(directory.resolve()):
                    raise ValueError
                content = member.read_bytes()
                if (
                    len(content) != item["size"]
                    or hashlib.sha256(content).hexdigest() != item["sha256"]
                ):
                    raise ValueError
                json.loads(content)
                entries.append(ManifestEntry(**item))
                seen.add(item["resource_id"])
            actual = {x.name for x in (directory / "payload").iterdir() if x.is_file()}
            if (
                actual != {f"{x.resource_id}.json" for x in entries}
                or sum(x.size for x in entries) != raw["total_bytes"]
                or raw["total_bytes"] > MAX_BACKUP_BYTES
            ):
                raise ValueError
            return BackupRecord(
                backup_id,
                bot_id,
                plan.plan_id,
                datetime.fromisoformat(raw["created_at"]),
                str(raw["creator"]),
                "completed",
                raw["total_bytes"],
                FORMAT_VERSION,
                "verified",
                tuple(entries),
                str(raw["operation_id"]),
                bool(raw["safety_snapshot"]),
            )
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise BackupError(
                "backup_integrity_failed", "Backup integrity verification failed."
            ) from exc

    def _catalog(self, bot_id: str) -> list[BackupRecord]:
        catalog = self._bot_root(bot_id) / "catalog.json"
        if not catalog.exists():
            return []
        try:
            raw = json.loads(catalog.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise ValueError
            records = []
            for item in raw:
                if not isinstance(item, dict) or set(item) != {"backup_id"}:
                    raise ValueError
                try:
                    records.append(self._record_from_manifest(bot_id, item["backup_id"]))
                except BackupError:
                    continue
            return records
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return []

    def _record_from_manifest(self, bot_id: str, backup_id: str) -> BackupRecord:
        path = self._backup_path(bot_id, backup_id)
        try:
            raw = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
            plan = self._plan(bot_id, raw["plan_id"])
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise BackupError("backup_corrupt", "Backup is corrupt.") from exc
        return self._parse_manifest(path, bot_id, backup_id, plan)

    def _record(self, bot_id: str, backup_id: str, *, expose_safety: bool) -> BackupRecord:
        if not self._valid_id(backup_id):
            raise BackupError("backup_not_found", "Backup was not found.", 404)
        catalog = self._bot_root(bot_id) / "catalog.json"
        try:
            indexed = json.loads(catalog.read_text(encoding="utf-8"))
            ids = {item["backup_id"] for item in indexed if isinstance(item, dict)}
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            ids = set()
        if backup_id not in ids:
            raise BackupError("backup_not_found", "Backup was not found.", 404)
        record = self._record_from_manifest(bot_id, backup_id)
        if record.safety_snapshot and not expose_safety:
            raise BackupError("backup_not_found", "Backup was not found.", 404)
        return record

    def _save_catalog(self, bot_id: str, records: list[BackupRecord]) -> None:
        atomic_write_json(
            self._bot_root(bot_id) / "catalog.json", [{"backup_id": x.backup_id} for x in records]
        )

    def _retention(self, bot_id: str, plan: BackupPlan, reserve: int = 0) -> None:
        records = self._catalog(bot_id)
        matching = sorted(
            (x for x in records if x.plan_id == plan.plan_id), key=lambda x: x.created_at
        )
        remove = matching[: max(0, len(matching) + reserve - plan.retention)]
        protected = set(self._active_restore)
        removed = {x.backup_id for x in remove if x.backup_id not in protected}
        for backup_id in removed:
            shutil.rmtree(self._backup_path(bot_id, backup_id))
        if removed:
            self._save_catalog(bot_id, [x for x in records if x.backup_id not in removed])

    def _audit(
        self,
        name,
        actor,
        bot_id,
        request_id,
        operation_id,
        result,
        backup_id,
        plan,
        rollback=None,
        *,
        resource_ids=(),
        before=(),
        after=(),
    ):
        if callable(self._audit_sink):
            self._audit_sink(
                BackupAuditEvent(
                    name,
                    actor,
                    bot_id,
                    request_id,
                    operation_id,
                    result,
                    backup_id,
                    plan.plan_id,
                    resource_ids or tuple(x.resource_id for x in plan.resources),
                    before,
                    after,
                    rollback,
                )
            )
