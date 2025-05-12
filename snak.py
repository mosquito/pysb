#!/usr/bin/env python3
import argparse
import configparser
import csv
import enum
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
from dataclasses import dataclass
from functools import singledispatchmethod, cached_property
from io import StringIO
from pathlib import Path
from shutil import rmtree
from subprocess import run
from tempfile import TemporaryDirectory
from types import MappingProxyType
from typing import IO, AbstractSet, Any, Mapping, Optional, Literal

UNICODE_SUPPORT = sys.stdout.encoding.lower().startswith("utf") and sys.stdout.isatty()


######################################################
# snak is a python standalone builds management tool #
######################################################

class ConfigParser(configparser.ConfigParser):
    def __init__(self, set_defaults: Mapping[str, Mapping[str, Any]] = None, **kwargs):
        super().__init__(**kwargs)
        for section, options in set_defaults.items():
            self.set_default(section, **options)

    def set_default(self, section: str, **kwargs):
        for key, value in kwargs.items():
            if not self.has_section(section):
                self.add_section(section)

            if not self.has_option(section, key):
                self.set(section, key, str(value))


class Runtime:
    config = ConfigParser(
        set_defaults={
            "paths": {
                "cache": str(Path("/var/cache/snak/") if os.geteuid() == 0 else "~/.cache/snak/"),
                "venvs": str(Path("/opt/python/envs") if os.geteuid() == 0 else "~/.local/share/snak/envs"),
                "versions": str(Path("/opt/python/versions") if os.geteuid() == 0 else "~/.local/share/snak/versions"),
            },
            "releases": {
                "url": "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest",
            },
        }
    )

    @classmethod
    def get_venvs_path(cls) -> Path:
        return Path(cls.config.get("paths", "venvs")).expanduser()

    @classmethod
    def get_versions_path(cls) -> Path:
        return Path(cls.config.get("paths", "versions")).expanduser()


class Colors(str, enum.Enum):
    RESET = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    BLACK = "\033[30m"
    RED = "\033[91m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[94m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"


@dataclass(frozen=True)
class TableHeader:
    value: str
    format: str = ""
    color: Optional[Colors] = None

    @cached_property
    def text(self) -> str:
        fmt = "{:" + self.format + "}"
        return fmt.format(self.value)

    def __str__(self):
        if UNICODE_SUPPORT and self.color:
            return f"{self.color.value}{self.text}{Colors.RESET.value}"
        return self.text

    def bold(self) -> str:
        if UNICODE_SUPPORT:
            return Colors.BOLD.value + str(self)
        return str(self)

    def copy(self, value) -> "TableHeader":
        return TableHeader(value, self.format, self.color)


class Table:
    BOOL_MARKS = MappingProxyType(
        {True: "\U0001F518 ", False: "\U000026AA "} if UNICODE_SUPPORT else {True: "yes", False: "no"}
    )
    TABLE_HEADER_SEPARATOR = "═" if UNICODE_SUPPORT else "="

    def __init__(self, *header: TableHeader, format: Literal["table", "csv", "json"] = "table"):
        self.header = tuple(header)
        self.rows = []
        self.format = format

    def add(self, *row: Any):
        if len(row) != len(self.header):
            raise ValueError(f"Row length {len(row)} does not match header length {len(self.header)}")
        self.rows.append(tuple(row))

    @singledispatchmethod
    def _convert(self, value) -> str:
        return str(value)

    @_convert.register(bool)
    def _(self, value: Path) -> str:
        return self.BOOL_MARKS[value]

    @_convert.register(float)
    def _(self, value: float) -> str:
        return f"{value:.2f}"

    def format_table(self, fp: IO[str]) -> None:
        header_len = 0
        for hdr in self.header:
            header = f"{hdr.bold()} "
            header_len += len(hdr.text) + 1
            fp.write(header)

        fp.write("\n")
        if UNICODE_SUPPORT:
            fp.write(Colors.BOLD.value)
        fp.write((self.TABLE_HEADER_SEPARATOR * header_len + "\n"))
        if UNICODE_SUPPORT:
            fp.write(Colors.RESET.value)

        for row in self.rows:
            values = list(map(self._convert, row))
            for hdr, value in zip(self.header, values):
                fp.write(str(hdr.copy(value)))
                fp.write(" ")
            fp.write("\n")

    def write(self, fp: IO[str]) -> None:
        if self.format == "table":
            self.format_table(fp)
        elif self.format == "csv":
            csv_writer = csv.writer(fp)
            csv_writer.writerow([hdr.value for hdr in self.header])
            for row in self.rows:
                csv_writer.writerow(row)
        elif self.format == "json":
            result = []
            for hdr, row in zip(self.header, self.rows):
                result.append({hdr.value.lower(): value for hdr, value in zip(self.header, row)})
            json.dump(result, fp, indent=1)

    def __str__(self):
        with StringIO() as fp:
            self.write(fp)
            return fp.getvalue()


def subparser(name: str, help: str, subparsers: Any, *arguments: dict[str, Any]):
    parser = subparsers.add_parser(
        name,
        help=help,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    for arg in map(dict, arguments):
        names = list(map(lambda x: x.strip(), arg.pop("names").split(",")))
        parser.add_argument(*names, **arg)

    def decorator(func):
        parser.set_defaults(func=func)
        return func

    return decorator


PARSER = argparse.ArgumentParser()
PARSER.add_argument(
    "-c", "--config", help="Path to configuration file", type=Path, dest="config_file",
    default=Path("/etc/snak.ini" if os.geteuid() == 0 else "~/.local/share/snak/config.ini").expanduser(),
)
PARSER.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output")
PARSER.add_argument("-f", "--format", choices=["table", "csv", "json"], default="table", help="Output format")
SUBPARSERS = PARSER.add_subparsers()

ENV_PARSER = SUBPARSERS.add_parser("env", help="Virtual environment management")
ENV_PARSER.set_defaults(func=lambda _: ENV_PARSER.print_help())
ENV_SUBPARSERS = ENV_PARSER.add_subparsers()


@subparser("list", "List all available environments", ENV_SUBPARSERS)
def env_list_parser(args: argparse.Namespace) -> int:
    versions = sorted(
        Runtime.get_versions_path().glob("3.*/bin/python"),
        key=lambda f: f.parent.parent.name.split("."),
        reverse=True,
    )
    venvs = Runtime.get_venvs_path().glob("*/bin/python")

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

    table = Table(
        TableHeader(value="Python", format=">10", color=Colors.GREEN),
        TableHeader(value="venv", format="^4", color=Colors.CYAN),
        TableHeader(value="Used", format="^4", color=Colors.YELLOW),
        TableHeader(value="Name", format="<30", color=Colors.BOLD),
        format=args.format,
    )
    for pybin, _, version in table_data:
        is_venv = pybin.is_relative_to(Runtime.get_venvs_path())
        name = pybin.parent.parent.name if is_venv else ""
        table.add(version["version"], is_venv, " " if is_venv else venv_counter[pybin], name)
    table.write(sys.stdout)

    return 0


@subparser(
    "create", "Create a new virtual environment", ENV_SUBPARSERS,
    dict(names="name", help="Name of the environment to create"),
    dict(names="-p,--packages", nargs="+", help="Packages to install after creation"),
    dict(names="-P,--python", help="Python version to use"),
)
def env_create_parser(args: argparse.Namespace) -> int:
    target_path = Runtime.get_venvs_path() / args.name
    if target_path.exists():
        logging.error(f"Environment %s already exists %s", args.name, target_path)
        return 1

    versions = sorted(
        Runtime.get_versions_path().glob("3.*/bin/python"),
        key=lambda f: f.parent.parent.name.split("."),
        reverse=True,
    )

    versions_map: dict[Path, dict] = {}

    for version in versions:
        version_file = version.parent.parent / "version.json"
        if not version_file.exists():
            continue

        version_meta = json.loads(version_file.read_text())
        versions_map[version] = version_meta

    def find_suitable_version(version_string: str) -> Optional[Path]:
        candidates = []
        for version_path, meta in versions_map.items():
            if meta["version"].startswith(version_string):
                candidates.append(version_path)

        if not candidates:
            return None
        if len(candidates) > 1:
            logging.error("Multiple versions found matching your criteria:\n%s", "\n".join(candidates))
            return None
        return candidates[0]

    if args.python is None:
        selected = sorted(versions_map.keys(), reverse=True)[0]
        logging.info("Latest installed version will be used: %s", versions_map[selected]["version"])
    else:
        selected = find_suitable_version(args.python)
        if selected is None:
            logging.error("No versions found matching your criteria")
            return 1

    run([selected, "-m", "venv", str(target_path)], check=True)
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
    target_path = Runtime.get_venvs_path() / args.env
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
    target_path = Runtime.get_venvs_path() / args.env
    if not target_path.exists():
        logging.error(f"Environment %s does not exist %s", args.env, target_path)
        return 1

    shell_activate_scripts = {
        "bash": target_path / "bin" / "activate",
        "zsh": target_path / "bin" / "activate",
        "fish": target_path / "bin" / "activate.fish",
        "csh": target_path / "bin" / "activate.csh",
    }

    activate_script = shell_activate_scripts.get(
        Path(os.getenv("SHELL", "/bin/bash")).name, shell_activate_scripts["bash"]
    )

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
    cache_path = Path(Runtime.config.get("paths", "cache")) / "cache" / obj[:2] / obj[2:4] / obj
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
    release = json.load(fetch(Runtime.config.get("releases", "url")))
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
        TableHeader(value="Version", format=">10", color=Colors.GREEN),
        TableHeader(value="Arch", format=">8", color=Colors.MAGENTA),
        TableHeader(value="OS", format=">10", color=Colors.YELLOW),
        TableHeader(value="Vendor", format=">10", color=Colors.BLUE),
        TableHeader(value="Libc", format=">10", color=Colors.RED),
        TableHeader(value="Stripped", format="^8", color=Colors.CYAN),
        TableHeader(value="Installed", format="^8"),
        format=args.format,
    )

    for version in versions:
        installed = (Runtime.get_versions_path() / version["install_name"] / "version.json").exists()
        table.add(
            version["version"], version["arch"], version["os"], version["vendor"],
            version["libc"], "stripped" in version["variant"], installed,
        )

    table.write(sys.stdout)
    return 0


@subparser(
    "install", "Install Python version", VERSIONS_SUBPARSERS,
    dict(names="--non-stripped", action="store_true", help="Install non stripped version"),
    dict(names="--arch", help="Install specific architecture", default=platform.machine()),
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
            lambda item: item["version"].startswith(args.version),
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
    install_path = Runtime.get_versions_path() / ver["install_name"]

    if install_path.exists():
        logging.error("Version %s already installed at %s", ver["version"], install_path)
        return 1

    install_path.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(dir=Path(Runtime.config.get("paths", "cache")), suffix=".download") as tmpdir:
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


@subparser("show", "Show configuration", CONFIG_SUBPARSERS)
def config_show_parser(args: argparse.Namespace) -> int:
    table = Table(
        TableHeader(value="Section", format="8", color=Colors.MAGENTA),
        TableHeader(value="Key", format="20", color=Colors.GREEN),
        TableHeader(value="Value", format="52", color=Colors.CYAN),
        format=args.format,
    )

    for section in Runtime.config.sections():
        for key, value in Runtime.config.items(section):
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
    if not Runtime.config.has_section(args.section):
        Runtime.config.add_section(args.section)

    if not args.value:
        if not Runtime.config.has_option(args.section, args.key):
            logging.error("Key %s.%s does not exist", args.section, args.key)
            return 1
        logging.info("Unsetting %s.%s", args.section, args.key)
        Runtime.config.remove_option(args.section, args.key)
    else:
        logging.info("Setting %s.%s = %s", args.section, args.key, args.value)
        Runtime.config.set(args.section, args.key, args.value)

    with args.config_file.open("w") as fp:
        Runtime.config.write(fp)

    return 0


class UnicodeLoggingFormatter(logging.Formatter):
    LEVEL_MAPPING = MappingProxyType({
        logging.ERROR: "\U0000274C",
        logging.WARNING: "\U000026A0",
        logging.INFO: "\U00002705",
        logging.DEBUG: "\U0001F50E",
        logging.CRITICAL: "\U00002757",
    })

    def formatMessage(self, record):
        if UNICODE_SUPPORT:
            record.levelname = self.LEVEL_MAPPING.get(record.levelno, "➡")
        return self._style.format(record)


def main(*argv):
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(level=logging.INFO)

    formatter = UnicodeLoggingFormatter("%(levelname)s\t%(message)s")
    for handler in logging.getLogger().handlers:
        handler.setFormatter(formatter)

    args = PARSER.parse_args(argv) if argv else PARSER.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.debug("Verbose mode enabled")

    read_configs = Runtime.config.read(args.config_file)
    if read_configs:
        logging.debug("Using configuration files %s", ", ".join(read_configs))
    else:
        logging.debug("Configuration file %s not found, using defaults", args.config_file)
    Path(Runtime.config.get("paths", "cache")).mkdir(parents=True, exist_ok=True)
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
