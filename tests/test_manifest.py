from pathlib import Path
import pytest
from shared.bot_core import StartupPolicy, ValidationError, load_manifest, validate_bot_id


def test_repository_manifests_are_valid():
    manifests = [load_manifest(path) for path in sorted(Path("bots").glob("*/bot.toml"))]
    assert [item.bot_id for item in manifests] == ["cda-admin", "cda-pay", "rpa-admin", "unbot"]
    assert all(
        not item.enabled and item.startup_policy is StartupPolicy.MANUAL for item in manifests
    )


@pytest.mark.parametrize(
    "value", ["", "CDA_ADMIN", "../cda-admin", "cda/admin", "-bot", "bot--two"]
)
def test_invalid_bot_ids(value):
    with pytest.raises(ValidationError):
        validate_bot_id(value)


def test_manifest_rejects_secret(tmp_path):
    folder = tmp_path / "safe-bot"
    folder.mkdir()
    path = folder / "bot.toml"
    path.write_text(
        '[bot]\nid="safe-bot"\ndisplay_name="Safe"\nentry_point="safe.main"\ntoken="oops"\n'
    )
    with pytest.raises(ValidationError, match="secrets"):
        load_manifest(path)
