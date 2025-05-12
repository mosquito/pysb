import json
import logging


def test_versions_list(snak_cli, capsys):
    """Test the `snak versions list` command."""
    snak_cli("versions", "list")
    captured = capsys.readouterr()
    stdout = captured.out
    assert len(stdout.splitlines()) > 2  # header is 2 lines


def test_versions_install(snak_cli, caplog):
    """Test the `snak versions install` command."""
    with caplog.at_level(logging.INFO):
        snak_cli("versions", "install", "3.12")
    captured = caplog.records
    assert len(captured) > 0
    assert "Installed Python 3.12" in captured[-1].message


def test_do_not_show_foreign_versions(snak_cli, capsys, snak_tmp_path):
    snak_cli("versions", "install", "3.12")
    version_files = list((snak_tmp_path / "versions").glob("3.12*/version.json"))
    assert len(version_files)

    for version_file in version_files:
        version_file.unlink()

    snak_cli("-f", "json", "versions", "list")
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    for version in result:
        if version["version"].startswith("3.12") and version["installed"]:
            raise AssertionError(f"Version {version['version']} should not be shown in the list of versions")
