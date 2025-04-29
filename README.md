# `pysb` — Python Standalone Build Management Tool

`pysb` is a lightweight CLI utility to manage multiple **self-contained Python builds** and virtual environments,
without touching your system Python installation.

It downloads **prebuilt Python binaries** 
(from [python-build-standalone](https://github.com/astral-sh/python-build-standalone)) directly, allowing you 
to **install, update, switch, and create virtual environments** independently and safely.

---

## Features

- 📦 Install standalone Python builds easily
- 🔄 Create and manage multiple virtual environments
- 🔍 List and inspect installed versions and environments
- ⚙️ Minimal configuration with sane defaults
- 🛡️ System-safe: does not interfere with your system's Python
- 🖥️ Works on **Linux** and **macOS**

---

## Installation

You can install `pysb` globally by running:

```bash
curl -L https://raw.githubusercontent.com/mosquito/pysb/refs/heads/master/pysb.py | sudo install -Dm 755 /dev/stdin /usr/local/bin/pysb
```

Alternatively, you can save the script manually and place it somewhere in your `$PATH`.

---

## Usage

```bash
pysb [COMMAND] [SUBCOMMAND] [OPTIONS...]
```

High-level command structure:

| Command     | Description                        |
| ----------- | ---------------------------------- |
| `env`       | Manage virtual environments        |
| `versions`  | Manage standalone Python versions  |
| `config`    | Manage `pysb` configuration         |

Run `pysb --help` to view all available commands.

---

## Examples

### Install a new standalone Python version

```bash
pysb versions list
pysb versions install 3.12.2
```

### Create a new virtual environment

```bash
pysb env create myenv
# (optionally install packages)
pysb env create myenv -p requests flask
```

### Activate an environment

```bash
eval $(pysb env activate myenv)
```

*(Note: use `eval` to source the activation in your current shell.)*

### List all environments

```bash
pysb env list
```

### Remove a virtual environment

```bash
pysb env remove myenv
```

### Show installed Python versions

```bash
pysb versions list
```

---

## Configuration

`pysb` uses a simple INI-style configuration file:

- **User mode**: `~/.local/share/pysb/config.ini`
- **Root mode (sudo)**: `/etc/pysb.ini`

You can show or edit the configuration:

```bash
pysb config show
pysb config set paths cache ~/.cache/pysb/

# for reverting to default just set empty value
pysb config set paths cache ""
```

---

## Requirements

`pysb` uses only standard libraries and does not require external Python packages.

You need just a few things to run `pysb`:

- Linux or macOS
- Python 3.8+

---

## Why pysb?

- No need to compile Python from source.
- Fully isolated environments.
- Great for experimenting with different Python versions easily.

---

## License

MIT License.
