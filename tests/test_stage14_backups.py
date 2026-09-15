from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from portal.backups import BackupError, BackupService, TRUSTED_BACKUP_PLANS
from portal.management import DenyByDefaultAuthorizer, Principal
from portal.resources import InMemoryResourceAdapter, ResourceService

VALUES = {
    "verification": "1248312846857666704",
    "payannounce": "1303323145020768306",
    "banlogs": "1249445968211087584",
    "general": "1248307521119060033",
}


def setup(
    tmp_path,
    permissions=frozenset({"backups.view", "backups.create", "backups.restore"}),
    bots=frozenset({"cda-admin"}),
    **kwargs,
):
    adapter = InMemoryResourceAdapter({"cda-admin-server": VALUES})
    auth = DenyByDefaultAuthorizer()
    resources = ResourceService(adapter, auth)
    events = []
    service = BackupService(
        tmp_path / "backups", resources, auth, audit_sink=events.append, **kwargs
    )
    return service, adapter, Principal("operator", permissions, bots), events


def test_closed_plan_and_distinct_exact_bot_permissions(tmp_path):
    service, _, actor, _ = setup(tmp_path, frozenset({"backups.view"}))
    assert service.list_backup_plans(actor, "cda-admin") == (
        TRUSTED_BACKUP_PLANS[("cda-admin", "cda-admin-configuration")],
    )
    with pytest.raises(BackupError) as denied:
        service.create_backup(actor, "cda-admin", "cda-admin-configuration", "r")
    assert denied.value.code == "permission_denied"
    with pytest.raises(BackupError):
        service.list_backups(actor, "unbot")


@pytest.mark.parametrize("value", ["../x", "/tmp/x", "C:\\x", "x;rm", "x\ny", "\0"])
def test_ids_are_not_paths(tmp_path, value):
    service, _, actor, _ = setup(tmp_path)
    with pytest.raises(BackupError):
        service.create_backup(actor, "cda-admin", value, "r")
    with pytest.raises(BackupError):
        service.get_backup(actor, "cda-admin", value)


def test_create_manifest_integrity_catalog_and_redacted_audit(tmp_path):
    service, _, actor, events = setup(tmp_path)
    item = service.create_backup(actor, "cda-admin", "cda-admin-configuration", "request-1")
    assert len(item.backup_id) == 32 and item.integrity_status == "verified"
    assert service.list_backups(actor, "cda-admin") == (item,)
    manifest = json.loads(
        (tmp_path / "backups" / "cda-admin" / item.backup_id / "manifest.json").read_text()
    )
    assert manifest["backup_format_version"] == 1
    assert (
        manifest["resources"][0]["sha256"]
        and manifest["resources"][0]["resource_id"] == "channel-routing"
    )
    assert not any(value in repr(events) for value in VALUES.values())


def test_changed_payload_and_future_format_fail_integrity(tmp_path):
    service, _, actor, _ = setup(tmp_path)
    item = service.create_backup(actor, "cda-admin", "cda-admin-configuration", "r")
    root = tmp_path / "backups" / "cda-admin" / item.backup_id
    (root / "payload" / "channel-routing.json").write_text("{}")
    with pytest.raises(BackupError) as error:
        service.preview_restore(actor, "cda-admin", item.backup_id, "r")
    assert error.value.code == "backup_integrity_failed"
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["backup_format_version"] = 2
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(BackupError):
        service.preview_restore(actor, "cda-admin", item.backup_id, "r")


def test_restore_preview_stale_then_success_with_safety_snapshot(tmp_path):
    service, adapter, actor, events = setup(tmp_path)
    item = service.create_backup(actor, "cda-admin", "cda-admin-configuration", "r")
    preview = service.preview_restore(actor, "cda-admin", item.backup_id, "r")
    adapter.configs["cda-admin-server"] = {**VALUES, "general": "1248307521119060999"}
    with pytest.raises(BackupError) as stale:
        service.restore_backup(actor, "cda-admin", item.backup_id, preview.preview_id, "r")
    assert stale.value.code == "stale_restore_preview"
    preview = service.preview_restore(actor, "cda-admin", item.backup_id, "r")
    service.restore_backup(actor, "cda-admin", item.backup_id, preview.preview_id, "r")
    assert adapter.configs["cda-admin-server"] == VALUES
    assert len(json.loads((tmp_path / "backups" / "cda-admin" / "catalog.json").read_text())) == 2
    assert any(event.name == "restore.succeeded" for event in events)


def test_process_instance_change_invalidates_preview(tmp_path):
    instance = ["a"]
    service, _, actor, _ = setup(tmp_path, process_instance=lambda _bot: instance[0])
    item = service.create_backup(actor, "cda-admin", "cda-admin-configuration", "r")
    preview = service.preview_restore(actor, "cda-admin", item.backup_id, "r")
    instance[0] = "b"
    with pytest.raises(BackupError) as error:
        service.restore_backup(actor, "cda-admin", item.backup_id, preview.preview_id, "r")
    assert error.value.code == "stale_restore_preview"


def test_retention_is_bounded_and_unknown_files_are_not_catalogued(tmp_path):
    service, _, actor, _ = setup(tmp_path)
    plan = TRUSTED_BACKUP_PLANS[("cda-admin", "cda-admin-configuration")]
    object.__setattr__(plan, "retention", 2)
    try:
        ids = [
            service.create_backup(actor, "cda-admin", plan.plan_id, str(i)).backup_id
            for i in range(3)
        ]
        assert len(service.list_backups(actor, "cda-admin")) == 2
        assert not (tmp_path / "backups" / "cda-admin" / ids[0]).exists()
        (tmp_path / "backups" / "cda-admin" / ("f" * 32)).mkdir()
        assert len(service.list_backups(actor, "cda-admin")) == 2
    finally:
        object.__setattr__(plan, "retention", 10)


def test_same_bot_concurrency_is_serialized(tmp_path):
    service, _, actor, _ = setup(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = []
        for future in [
            pool.submit(
                service.create_backup, actor, "cda-admin", "cda-admin-configuration", str(i)
            )
            for i in range(2)
        ]:
            try:
                results.append(future.result().status)
            except BackupError as exc:
                results.append(exc.code)
    assert set(results) <= {"completed", "backup_in_progress"} and "completed" in results
