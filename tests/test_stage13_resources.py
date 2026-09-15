from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import json
import os
import pytest
from portal.management import DenyByDefaultAuthorizer, Principal
from portal.resources import (
    AtomicJsonResourceAdapter,
    InMemoryResourceAdapter,
    ResourceError,
    ResourceService,
    TRUSTED_CONFIGURATION_CATALOG,
    TRUSTED_DATA_CATALOG,
)
from shared.bot_core.secure_path import AuthorizedPath

VALUES = {
    "verification": "1248312846857666704",
    "payannounce": "1303323145020768306",
    "banlogs": "1249445968211087584",
    "general": "1248307521119060033",
}


def service(
    permissions=frozenset({"config.view", "config.edit", "data.view"}),
    bots=frozenset({"cda-admin"}),
):
    adapter = InMemoryResourceAdapter(
        {"cda-admin-server": VALUES},
        {"cda-admin-server": ({"user_id": "3", "secret": "x"}, {"user_id": "1"}, {"user_id": "2"})},
    )
    return (
        ResourceService(adapter, DenyByDefaultAuthorizer()),
        adapter,
        Principal("operator", permissions, bots),
    )


def test_catalog_is_closed_and_has_complete_safe_metadata():
    resource = TRUSTED_CONFIGURATION_CATALOG[("cda-admin", "channel-routing")]
    assert (
        resource.bot_id == "cda-admin"
        and resource.location_key
        and resource.write_strategy == "atomic-replace"
    )
    assert {f.field_id for f in resource.fields} == set(VALUES)
    assert TRUSTED_DATA_CATALOG[("cda-admin", "verified-users")].maximum_page_size == 100


@pytest.mark.parametrize(
    "resource_id", ["../x", "/etc/passwd", "C:\\x", "file:///x", "x;rm", "x\ny", "x" * 100, "／"]
)
def test_resource_ids_never_become_paths(resource_id):
    resources, _, actor = service()
    with pytest.raises(ResourceError) as error:
        resources.get_config(actor, "cda-admin", resource_id, "request")
    assert error.value.code == "resource_not_found"


def test_exact_bot_authorization_and_view_does_not_grant_edit():
    resources, _, actor = service(frozenset({"config.view"}), frozenset({"unbot"}))
    with pytest.raises(ResourceError) as error:
        resources.get_config(actor, "cda-admin", "channel-routing", "request")
    assert error.value.code == "permission_denied"
    resources, _, actor = service(frozenset({"config.view"}))
    _, current = resources.get_config(actor, "cda-admin", "channel-routing", "request")
    with pytest.raises(ResourceError) as error:
        resources.preview(
            actor, "cda-admin", "channel-routing", VALUES, current.revision, "request"
        )
    assert error.value.code == "permission_denied"


@pytest.mark.parametrize(
    "change", [{"unknown": "1"}, {"verification": "bad"}, {"verification": 1248312846857666704}]
)
def test_schema_rejects_unknown_and_invalid_fields(change):
    resources, _, actor = service()
    _, current = resources.get_config(actor, "cda-admin", "channel-routing", "request")
    submitted = {**VALUES, **change}
    with pytest.raises(ResourceError) as error:
        resources.preview(
            actor, "cda-admin", "channel-routing", submitted, current.revision, "request"
        )
    assert error.value.code == "validation_failed"


def test_preview_diff_commit_restart_and_stale_revision():
    resources, _, actor = service()
    _, current = resources.get_config(actor, "cda-admin", "channel-routing", "request")
    changed = {**VALUES, "general": "1248307521119060999"}
    preview = resources.preview(
        actor, "cda-admin", "channel-routing", changed, current.revision, "request"
    )
    assert [(x.field_id, x.restart_required) for x in preview.changes] == [("general", True)]
    assert (
        resources.commit(
            actor, "cda-admin", "channel-routing", changed, current.revision, "request"
        ).revision
        != current.revision
    )
    with pytest.raises(ResourceError) as error:
        resources.commit(actor, "cda-admin", "channel-routing", VALUES, current.revision, "request")
    assert error.value.code == "stale_revision"


def test_failed_write_does_not_advance_revision_or_mutate():
    resources, adapter, actor = service()
    _, before = resources.get_config(actor, "cda-admin", "channel-routing", "request")
    adapter.fail_write = True
    with pytest.raises(ResourceError):
        resources.commit(
            actor,
            "cda-admin",
            "channel-routing",
            {**VALUES, "general": "1248307521119060999"},
            before.revision,
            "request",
        )
    assert resources.get_config(actor, "cda-admin", "channel-routing", "request")[1] == before


def test_concurrent_edit_has_one_winner_and_no_lost_update():
    resources, _, actor = service()
    _, before = resources.get_config(actor, "cda-admin", "channel-routing", "request")

    def update(value):
        try:
            resources.commit(
                actor,
                "cda-admin",
                "channel-routing",
                {**VALUES, "general": value},
                before.revision,
                value,
            )
            return "ok"
        except ResourceError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, ("1248307521119060111", "1248307521119060222")))
    assert sorted(results) == ["ok", "stale_revision"]


def test_data_pages_are_stable_bounded_and_allow_list_fields():
    resources, _, actor = service()
    first = resources.data_page(actor, "cda-admin", "verified-users", "request", limit=2)
    assert first.records == ({"user_id": "1"}, {"user_id": "2"})
    assert resources.data_page(
        actor, "cda-admin", "verified-users", "request", limit=2, cursor=first.next_cursor
    ).records == ({"user_id": "3"},)
    with pytest.raises(ResourceError):
        resources.data_page(actor, "cda-admin", "verified-users", "request", limit=101)
    with pytest.raises(ResourceError):
        resources.data_page(actor, "cda-admin", "verified-users", "request", cursor="bad")


def test_audits_contain_field_ids_not_values():
    events = []
    resources, _, actor = service()
    resources.audit_sink = events.append
    _, before = resources.get_config(actor, "cda-admin", "channel-routing", "request-1")
    resources.commit(
        actor,
        "cda-admin",
        "channel-routing",
        {**VALUES, "general": "1248307521119060999"},
        before.revision,
        "request-1",
    )
    assert events[-1].changed_fields == ("general",) and "1248307521119060999" not in repr(
        events[-1]
    )


def test_real_adapter_atomic_write_preserves_document_and_assigns_safe_mode(tmp_path):
    target = tmp_path / "server.json"
    target.write_text(
        json.dumps(
            {
                "channels": {name: int(value) for name, value in VALUES.items()},
                "balances": {"safe": 1},
            }
        ),
        encoding="utf-8",
    )
    os.chmod(target, 0o640)
    adapter = AtomicJsonResourceAdapter(
        {"cda-admin-server": AuthorizedPath(tmp_path.resolve(), ("server.json",))}
    )
    resource = TRUSTED_CONFIGURATION_CATALOG[("cda-admin", "channel-routing")]
    before = adapter.read_config(resource)
    adapter.write_config(resource, {**VALUES, "general": "1248307521119060999"}, before.revision)
    persisted = json.loads(target.read_text(encoding="utf-8"))
    assert persisted["balances"] == {"safe": 1}
    assert persisted["channels"]["general"] == 1248307521119060999
    assert target.stat().st_mode & 0o777 == 0o600


def test_real_adapter_refuses_symlink_target(tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    target = tmp_path / "server.json"
    target.symlink_to(outside)
    adapter = AtomicJsonResourceAdapter(
        {"cda-admin-server": AuthorizedPath(tmp_path.resolve(), ("server.json",))}
    )
    resource = TRUSTED_CONFIGURATION_CATALOG[("cda-admin", "channel-routing")]
    with pytest.raises(ResourceError) as error:
        adapter.read_config(resource)
    assert error.value.code == "resource_temporarily_unavailable"
