#!/usr/bin/env python3
import argparse
import json
import logging
import os
import platform
import re
import shutil
import ssl
import sys
import tarfile
import time
import urllib.request
import uuid
from collections import Counter
from configparser import ConfigParser
from io import StringIO
from pathlib import Path
from shutil import rmtree
from subprocess import run
from tempfile import TemporaryDirectory
from types import MappingProxyType
from typing import IO, AbstractSet, Any


##################################################
# Python standalone build (pysb) managenent tool #
##################################################

# RUNTIME VARIABLES

SHELL = Path(os.getenv("SHELL", "/bin/bash")).resolve()

# CONFIGURATION

CONFIG_PATH = Path("~/.local/share/pysb/config.ini").expanduser()
if os.geteuid() == 0:
    CONFIG_PATH = Path("/etc/pysb.ini").expanduser()

CONFIG = ConfigParser()
CONFIG.read(CONFIG_PATH)

def set_default(section: str, key: str, value: str):
    if not CONFIG.has_section(section):
        CONFIG.add_section(section)

    if not CONFIG.has_option(section, key):
        CONFIG.set(section, key, value)

set_default("releases", "url", "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest")

DEFAULT_BASE_PATH = "/opt/python" if os.geteuid() == 0 else "~/.local/share/pysb"
if os.geteuid() == 0:
    set_default("paths", "cache", "/var/cache/pysb/")
else:
    set_default("paths", "cache", "~/.cache/pysb/")

set_default("paths", "venvs", str(Path(DEFAULT_BASE_PATH) / "envs"))
set_default("paths", "versions", str(Path(DEFAULT_BASE_PATH) / "versions"))

# Global variables from configuration

RELEASES_URL = CONFIG.get("releases", "url")
CACHE_PATH = Path(CONFIG.get("paths", "cache"))
CACHE_PATH.mkdir(parents=True, exist_ok=True)

VENVS_PATH = Path(CONFIG.get("paths", "venvs")).expanduser()
VERSIONS_PATH = Path(CONFIG.get("paths", "versions")).expanduser()


class Table:
    UNICODE_SUPPORT = sys.stdout.encoding.lower().startswith("utf")
    BOOL_MARKS = MappingProxyType({True: "✅ ", False: "❌ "} if UNICODE_SUPPORT else {True: "yes", False: "no"})
    TABLE_HEADER_SEPARATOR = "═" if UNICODE_SUPPORT else "="

    def __init__(self, *header: str):
        hdr = []
        cols = []
        for col in header:
            if ":" in col:
                h, fmt = col.split(":", 1)
                cols.append(f"{{:{fmt}}}")
                hdr.append(h)
            else:
                hdr.append(col)
                cols.append(f"{{:<{len(col) + 2}}}")

        self.format = " ".join(cols)
        self.header = tuple(hdr)
        self.rows = []

    def add(self, *row: Any):
        if len(row) != len(self.header):
            raise ValueError(f"Row length {len(row)} does not match header length {len(self.header)}")
        self.rows.append(tuple(row))

    def _convert(self, value) -> str:
        match value:
            case bool():
                return self.BOOL_MARKS[value]
            case float():
                return f"{value:.2f}"
            case _:
                return str(value)

    def write(self, fp: IO[str]) -> None:
        header = self.format.format(*self.header)
        fp.write(header + "\n")
        fp.write(self.TABLE_HEADER_SEPARATOR * len(header) + "\n")
        for row in self.rows:
            fp.write(self.format.format(*map(self._convert, row)))
            fp.write("\n")

    def __str__(self):
        fp = StringIO()
        self.write(fp)
        return fp.getvalue()


def subparser(
    name: str, help: str, subparsers: Any, *arguments: dict[str, Any],
):
    subparser = subparsers.add_parser(
        name,
        help=help,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    for arg in map(dict, arguments):
        names = list(map(lambda x: x.strip(), arg.pop("names").split(",")))
        subparser.add_argument(*names, **arg)

    def decorator(func):
        subparser.set_defaults(func=func)
        return func

    return decorator

PARSER = argparse.ArgumentParser()
SUBPARSERS = PARSER.add_subparsers()

ENV_PARSER = SUBPARSERS.add_parser("env", help="Virtual environment management")
ENV_PARSER.set_defaults(func=lambda _: ENV_PARSER.print_help())
ENV_SUBPARSERS = ENV_PARSER.add_subparsers()


@subparser("list", "List all available environments", ENV_SUBPARSERS)
def env_list_parser(_: argparse.Namespace) -> int:
    versions = sorted(
        VERSIONS_PATH.glob("3.*/bin/python"),
        key=lambda f: f.parent.parent.name.split("."),
        reverse=True,
    )
    venvs = VENVS_PATH.glob("*/bin/python")

    venv_counter = Counter()
    table_data = []

    for venv in venvs:
        pybin = venv.resolve()
        version_file = pybin.parent.parent / "version.json"
        if not version_file.exists():
            continue

        table_data.append([venv, pybin, json.loads(version_file.read_text())])
        venv_counter[pybin] += 1

    for version in versions:
        version = version.resolve()
        version_file = version.parent.parent / "version.json"

        if not version_file.exists():
            continue

        table_data.append([version, version, json.loads(version_file.read_text())])

    table_data.sort(key=lambda x: (x[1], x[0]), reverse=True)

    table = Table("#:<3", "Python version:>20", "venv:^4", "Used", "Name:<30")
    for idx, (pybin, _, version) in enumerate(table_data):
        is_venv = pybin.is_relative_to(VENVS_PATH)
        name = pybin.parent.parent.name if is_venv else ""
        table.add(idx + 1, version["version"], is_venv, " " if is_venv else venv_counter[pybin], name)
    table.write(sys.stdout)

    return 0


@subparser(
    "create", "Create a new virtual environment", ENV_SUBPARSERS,
    dict(names="name", help="Name of the environment to create"),
    dict(names="-p,--packages", nargs="+", help="Packages to install after creation"),
)
def env_create_parser(args: argparse.Namespace) -> int:
    target_path = VENVS_PATH / args.name
    if target_path.exists():
        logging.error(f"Environment %s already exists %s", args.name, target_path)
        return 1

    versions = sorted(
        VERSIONS_PATH.glob("3.*/bin/python"),
        key=lambda f: f.parent.parent.name.split("."),
        reverse=True,
    )

    versions_map = {}

    table = Table("#:<3", "Python version")
    for idx, version in enumerate(versions):
        version_file = version.parent.parent / "version.json"
        if not version_file.exists():
            continue

        version_meta = json.loads(version_file.read_text())
        table.add(idx + 1, version_meta["version"])
        versions_map[str(idx + 1)] = version

    table.write(sys.stdout)
    selected = input("Select Python version number: ")
    while selected not in versions_map:
        selected = input("Invalid version number, select again: ")

    run([versions_map[selected], "-m", "venv", str(target_path)], check=True)
    logging.info(f"Created environment %s: %s", args.name, target_path)

    if args.packages:
        pip = target_path / "bin" / "pip"
        run([pip, "install", "-U", "pip", "certifi"], check=True)
        run([pip, "install", "-U", *args.packages], check=True)
        logging.info(f"Installed packages %s", args.packages)

    return 0


@subparser(
    "remove", "Remove virtual environment", ENV_SUBPARSERS,
    dict(names="env", help="Name of the environment to create"),
)
def env_remove_parser(args: argparse.Namespace) -> int:
    target_path = VENVS_PATH / args.env
    if not target_path.exists():
        logging.error(f"Environment %s does not exist %s", args.env, target_path)
        return 1

    rmtree(str(target_path))
    logging.info(f"Removed environment %s: %s", args.env, target_path)
    return 0

@subparser(
    "activate", "Remove virtual environment", ENV_SUBPARSERS,
    dict(names="env", help="Name of the environment to create"),
)
def env_activate_parser(args: argparse.Namespace) -> int:
    target_path = VENVS_PATH / args.env
    if not target_path.exists():
        logging.error(f"Environment %s does not exist %s", args.env, target_path)
        return 1

    match SHELL.name:
        case "fish":
            activate_script = target_path / "bin" / "activate.fish"
        case "csh":
            activate_script = target_path / "bin" / "activate.csh"
        case _:
            activate_script = target_path / "bin" / "activate"

    if sys.stdout.isatty():
        logging.warning("For activating environment in current shell use eval expression")
    else:
        logging.info(f"Activated environment %s: %s", args.env, target_path)

    print(f"source {activate_script}")

    return 0


VERSIONS_PARSER = SUBPARSERS.add_parser("versions", help="Python version management")
VERSIONS_PARSER.set_defaults(func=lambda _: VERSIONS_PARSER.print_help())

VERSIONS_SUBPARSERS = VERSIONS_PARSER.add_subparsers()


SSL_CONTEXT = ssl.create_default_context()
if not Path("/etc/ssl/certs/ca-certificates.crt").resolve().exists():
    SSL_CONTEXT.check_hostname = False
    SSL_CONTEXT.verify_mode = ssl.CERT_NONE


def fetch(url, cache=3600 * 4) -> IO[bytes]:
    obj = str(uuid.uuid3(uuid.NAMESPACE_URL, url))
    cache_path = CACHE_PATH / "cache" / obj[:2] / obj[2:4] / obj
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    if not (cache_path.exists() and cache_path.stat().st_mtime > (time.time() - cache)):
        logging.info("Downloading %s...", url)
        response = urllib.request.urlopen(url, context=SSL_CONTEXT)
        with cache_path.open("wb") as fp:
            shutil.copyfileobj(response, fp)
    return cache_path.open("rb")


def get_versions(
    libc: AbstractSet[str] = frozenset({platform.libc_ver()[0]}),
    system: AbstractSet[str] = frozenset({platform.system().lower()}),
    machine: AbstractSet[str] = frozenset({platform.machine()}),
    stripped: bool = True,
):
    release = json.load(fetch(RELEASES_URL))
    assets = release["assets"]
    machine_map = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "arm64": "aarch64",
        "aarch64": "aarch64",
    }
    libc_map = {"glibc": "gnu", "": None, "native": None}
    libc = frozenset(libc_map.get(x, x) for x in libc)
    if libc == frozenset({None}):
        libc = None

    system_map = {
        "linux": "linux",
        "darwin": "darwin",
    }
    system = frozenset(system_map.get(x, x) for x in system)
    machine = frozenset(machine_map.get(x, x) for x in machine)

    exp = re.compile(
        r"^cpython-(?P<version>\d+\.\d+\.\d+)\+(?P<date>\d+)-"
        r"(?P<arch>[^-]+)-(?P<vendor>[^-]+)-(?P<os>[^-]+)-(?P<tail>.*)$",
    )
    variant_exp = re.compile(r"^((?P<libc>[^-]+)-)?(?P<variant>[^-]+)\.tar\.gz$")

    versions = []

    for asset in assets:
        match = exp.match(asset["name"])
        if match is None:
            continue
        release_info = match.groupdict()
        if release_info["arch"] not in machine:
            continue
        if release_info["os"] not in system:
            continue
        tail = release_info.pop("tail")
        tail_match = variant_exp.match(tail)
        if tail_match is None:
            continue
        release_info.update(tail_match.groupdict())
        if libc is not None and release_info["libc"] not in libc:
            continue

        release_info["variant"] = release_info["variant"].replace("_", " ")

        if stripped and "stripped" not in release_info["variant"]:
            continue
        if not stripped and "stripped" in release_info["variant"]:
            continue

        release_info["libc"] = release_info["libc"] or "native"
        for key in release_info:
            if release_info[key] is None:
                release_info[key] = "N/A"
        release_info["url"] = asset["browser_download_url"]
        release_info["install_name"] = (
            f"{release_info['version']}-{release_info['arch']}-"
            f"{release_info['vendor']}-{release_info['os']}-"
            f"{release_info['libc']}-{release_info['variant'].replace(' ', '_')}"
        )
        versions.append(release_info)

    versions = sorted(versions, key=lambda item: list(map(int, item["version"].split("."))))

    return versions


@subparser(
    "list", "List all available Python versions", VERSIONS_SUBPARSERS,
    dict(names="--non-stripped", action="store_true", help="Install non stripped version"),
    dict(
        names="--arch", nargs="+", help="Show specific architectures", choices=["x86_64", "arm64", "armv7"],
        default=[platform.machine()],
    ),
    dict(
        names="--libc", nargs="+", help="Show specific libc versions",
        choices=["native", "musl", "gnu", "gnueabihf", "gnueabi"],
        default=["native", "gnu", "musl"],
    ),
)
def python_list_parser(args: argparse.Namespace) -> int:
    versions = get_versions(machine=frozenset(args.arch), libc=frozenset(args.libc), stripped=not args.non_stripped)

    table = Table(
        "#:<3", "Version:<10", "Arch:>8", "OS:>10", "Platform:>10", "Libc:>10", "Stripped:^8", "Installed:^8",
    )

    for idx, version in enumerate(versions):
        installed = (VERSIONS_PATH / version["install_name"]).is_dir()
        table.add(
            idx + 1, version["version"], version["arch"], version["os"], version["vendor"],
            version["libc"], "stripped" in version["variant"], installed,
        )

    table.write(sys.stdout)
    return 0


@subparser(
    "install", "Install Python version", VERSIONS_SUBPARSERS,
    dict(names="--non-stripped", action="store_true", help="Install non stripped version"),
    dict(names="--arch",help="Install specific architecture", default=platform.machine()),
    dict(
        names="--libc", help="Show specific libc versions",
        choices=["N/A", "musl", "gnu", "gnueabihf", "gnueabi"],
        default=platform.libc_ver()[0],
    ),
    dict(names="version", help="Version to install"),
)
def python_install_parser(args: argparse.Namespace) -> int:
    versions = list(
        filter(
            lambda item: item["version"] == args.version,
            get_versions(
                machine=frozenset([args.arch]),
                stripped=not args.non_stripped,
                libc=frozenset([args.libc]),
            ),
        ),
    )

    if not versions:
        logging.error("No versions found matching your criteria")
        return 1

    if len(versions) > 1:
        logging.error("Multiple versions found matching your criteria:\n%s", "\n".join(v["url"] for v in versions))
        return 1

    ver = versions[0]
    install_path = VERSIONS_PATH / ver["install_name"]

    if install_path.exists():
        logging.error("Version %s already installed at %s", ver["version"], install_path)
        return 1

    install_path.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(dir=CACHE_PATH, suffix=".download") as tmpdir:
        tmp_path = Path(tmpdir)
        extract_path = tmp_path / "extract"
        extract_path.mkdir(parents=True, exist_ok=True)

        with tarfile.open(fileobj=fetch(versions[0]["url"])) as archive:
            logging.info("Extracting...")
            archive.extractall(extract_path)

        logging.info("Installing...")
        for path in (extract_path / "python").iterdir():
            shutil.move(path, install_path / path.name)

        with (install_path / "version.json").open("w") as fp:
            json.dump(ver, fp, indent=1)

    logging.info("Installed Python %s to %s", ver["version"], install_path)
    return 0

CONFIG_PARSER = SUBPARSERS.add_parser("config", help="Configuration management")
CONFIG_PARSER.set_defaults(func=lambda _: CONFIG_PARSER.print_help())

CONFIG_SUBPARSERS = CONFIG_PARSER.add_subparsers()

@subparser(
    "show", "Show configuration", CONFIG_SUBPARSERS,
)
def config_show_parser(_: argparse.Namespace) -> int:
    table = Table("Section:8", "Key:20", "Value:52")
    for section in CONFIG.sections():
        for key, value in CONFIG.items(section):
            table.add(section, key, value)
    table.write(sys.stdout)
    return 0


@subparser(
    "set", "Set or unset configuration option. Pass empty value for use default.",
    CONFIG_SUBPARSERS,
    dict(names="section", help="Configuration section"),
    dict(names="key", help="Configuration key"),
    dict(names="value", help="Configuration value"),
)
def config_show_parser(args: argparse.Namespace) -> int:
    if not CONFIG.has_section(args.section):
        CONFIG.add_section(args.section)

    if not args.value:
        if not CONFIG.has_option(args.section, args.key):
            logging.error("Key %s.%s does not exist", args.section, args.key)
            return 1
        logging.info("Unsetting %s.%s", args.section, args.key)
        CONFIG.remove_option(args.section, args.key)
    else:
        logging.info("Setting %s.%s = %s", args.section, args.key, args.value)
        CONFIG.set(args.section, args.key, args.value)

    with CONFIG_PATH.open("w") as fp:
        CONFIG.write(fp)

    return 0



def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    args = PARSER.parse_args()
    if not hasattr(args, "func"):
        PARSER.print_help()
        return 1
    try:
        return args.func(args)
    except Exception as e:
        logging.error(f"Error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    main()
