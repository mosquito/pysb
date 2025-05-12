def test_config_show(snak_cli, unicode_support_toggle, capsys):
    """Test the `snak config show` command."""
    snak_cli("config", "show")
    captured = capsys.readouterr()
    assert "venvs" in captured.out
    assert "versions" in captured.out
    assert "snak" in captured.out


def test_config_set(snak_cli, unicode_support_toggle, capsys):
    """Test the `snak config set` command."""
    snak_cli("config", "set", "paths", "venvs", "/tmp/venvs")
    snak_cli("config", "set", "paths", "versions", "/tmp/versions")
    snak_cli("config", "show")
    captured = capsys.readouterr()
    assert "venvs" in captured.out
    assert "versions" in captured.out
    assert "/tmp/venvs" in captured.out
    assert "/tmp/versions" in captured.out
