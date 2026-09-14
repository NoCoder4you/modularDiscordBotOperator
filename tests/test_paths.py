import pytest
from shared.bot_core import PathSecurityError, RuntimePaths, ValidationError


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
