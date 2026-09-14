import pytest
from shared.bot_core import PathSecurityError, RuntimePaths, ValidationError
from shared.bot_core.jsonio import atomic_write_json
from shared.bot_core.secure_path import AuthorizedPath


def test_per_bot_paths_are_isolated(tmp_path):
    paths = RuntimePaths(tmp_path)
    assert paths.bot_data("cda-admin") != paths.bot_data("cda-pay")
    assert paths.bot_data("cda-admin", "guilds", "1.json").is_relative_to(
        tmp_path / "data" / "cda-admin"
    )


@pytest.mark.parametrize("part", ["../cda-pay/private.json", "../../outside", "/tmp/outside"])
def test_path_traversal_is_rejected(tmp_path, part):
    with pytest.raises(PathSecurityError):
        RuntimePaths(tmp_path).bot_data("cda-admin", part)


def test_invalid_id_cannot_select_directory(tmp_path):
    with pytest.raises(ValidationError):
        RuntimePaths(tmp_path).bot_data("../unbot")


@pytest.mark.parametrize("category", ["data", "logs"])
def test_runtime_category_symlink_cannot_escape_runtime_root(tmp_path, category):
    outside = tmp_path.parent / f"outside-{category}"
    outside.mkdir()
    (tmp_path / category).symlink_to(outside, target_is_directory=True)

    paths = RuntimePaths(tmp_path)
    with pytest.raises(PathSecurityError, match="runtime root"):
        paths.bot_data("cda-admin") if category == "data" else paths.bot_logs("cda-admin")


@pytest.mark.parametrize("category", ["data", "logs"])
def test_bot_directory_symlink_cannot_escape_category_root(tmp_path, category):
    category_root = tmp_path / category
    category_root.mkdir()
    outside = tmp_path.parent / f"outside-bot-{category}"
    outside.mkdir()
    (category_root / "cda-admin").symlink_to(outside, target_is_directory=True)

    paths = RuntimePaths(tmp_path)
    with pytest.raises(PathSecurityError, match=f"{category} root"):
        paths.bot_data("cda-admin") if category == "data" else paths.bot_logs("cda-admin")


def test_authorized_write_rejects_symlink_created_after_path_validation(tmp_path):
    authorized = RuntimePaths(tmp_path).bot_data("cda-admin", "guilds", "settings.json")
    bot_root = tmp_path / "data" / "cda-admin"
    bot_root.mkdir(parents=True)
    outside = tmp_path.parent / "race-destination"
    outside.mkdir()
    (bot_root / "guilds").symlink_to(outside, target_is_directory=True)

    with pytest.raises(PathSecurityError, match="unsafe component"):
        atomic_write_json(authorized, {"enabled": True})
    assert not (outside / "settings.json").exists()


def test_authorized_path_cannot_be_forged_with_traversal(tmp_path):
    with pytest.raises(PathSecurityError, match="invalid component"):
        AuthorizedPath(tmp_path.resolve(), ("data", "cda-admin", "..", "cda-pay", "state.json"))
