import json
import logging


def test_env_empty_list(snak_cli, capsys):
    snak_cli("versions", "install", "3.12")
    snak_cli("env", "list")
    captured = capsys.readouterr().out.splitlines()
    assert len(captured) > 2  # header size is 2


def test_env_install(snak_cli, caplog):
    snak_cli("versions", "install", "3.12")

    with caplog.at_level(logging.INFO):
        snak_cli("env", "create", "-P", "3.12", "test_env")

    assert "Created environment test_env" in caplog.text


def test_env_list(snak_cli, capsys):
    snak_cli("versions", "install", "3.12")
    snak_cli("versions", "install", "3.13")
    snak_cli("env", "create", "-P", "3.12", "test_env312")
    snak_cli("env", "create", "-P", "3.13", "test_env313")

    snak_cli("env", "list")
    captured = capsys.readouterr().out
    assert len(captured.splitlines()) > 2  # header size is 2
    assert "test_env312" in captured
    assert "test_env313" in captured


def test_do_not_show_broken_versions(snak_cli, capsys, snak_tmp_path):
    snak_cli("versions", "install", "3.12")
    version_files = list((snak_tmp_path / "versions").glob("3.12*/version.json"))
    assert len(version_files)

    for version_file in version_files:
        version_file.unlink()

    snak_cli("-f", "json", "env", "list")
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    for version in result:
        if version["python"].startswith("3.12"):
            raise AssertionError(f"Version {version['python']} should not be shown in the list of versions")


def test_env_activate(snak_cli, caplog):
    snak_cli("versions", "install", "3.12")
    snak_cli("env", "create", "-P", "3.12", "test_env")

    with caplog.at_level(logging.INFO):
        snak_cli("env", "activate", "test_env")

    assert "Activated environment test_env" in caplog.text
