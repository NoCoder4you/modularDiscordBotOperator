import pytest
pytest.importorskip("discord", reason="CDA Admin runtime dependencies are not installed")
pytest.importorskip("apscheduler", reason="CDA Admin runtime dependencies are not installed")
import asyncio
from types import SimpleNamespace

from cda_admin.bot import discover_extensions, load_statuses, resolve_extension_name
from cda_admin.cogs.BotCheck import has_authorised_role
from cda_admin.cogs.VerifiedRoleAudit import _needs_action


def test_cog_discovery_uses_package_names_and_contains_every_cog():
    extensions = discover_extensions()
    assert "cda_admin.cogs.RoleUpdater" in extensions
    assert "cda_admin.cogs.ServerVerify" in extensions
    assert len(extensions) == 26
    assert resolve_extension_name("RoleUpdater") == "cda_admin.cogs.RoleUpdater"


def test_statuses_are_packaged_and_nonempty():
    assert "out for Version 1.3.0" in load_statuses()


def test_verified_role_audit_business_rule():
    role = lambda role_id, name: SimpleNamespace(id=role_id, name=name)
    member = SimpleNamespace(roles=[role(1, "Verified")])
    assert _needs_action(member, set(), {2}) is True
    member.roles.append(role(2, "Employee"))
    assert _needs_action(member, set(), {2}) is False


def test_authorised_check_requires_both_named_roles():
    decorator = has_authorised_role()
    predicate = decorator.predicate

    class Response:
        def __init__(self): self.messages = []
        async def send_message(self, message, **kwargs): self.messages.append((message, kwargs))

    denied = SimpleNamespace(
        user=SimpleNamespace(roles=[SimpleNamespace(name="Discord Admins")]), response=Response()
    )
    assert asyncio.run(predicate(denied)) is False
    assert denied.response.messages[0][1]["ephemeral"] is True
    allowed = SimpleNamespace(
        user=SimpleNamespace(roles=[SimpleNamespace(name="Discord Admins"), SimpleNamespace(name="Verified")]),
        response=Response(),
    )
    assert asyncio.run(predicate(allowed)) is True
