from functools import partial
from pathlib import Path
from typing import Callable

import pytest

import snak


@pytest.fixture(params=[True, False])
def unicode_support_toggle(request) -> None:
    snak.UNICODE_SUPPORT = request.param


@pytest.fixture()
def snak_cli(tmp_path: Path) -> Callable[..., None]:
    return partial(snak.main, "--config", str(tmp_path / "test_config.ini"))


@pytest.fixture(autouse=True)
def snak_tmp_path(snak_cli, tmp_path: Path) -> Path:
    snak_cli("config", "set", "paths", "venvs", str(tmp_path / "venvs"))
    snak_cli("config", "set", "paths", "versions", str(tmp_path / "versions"))
    return tmp_path
