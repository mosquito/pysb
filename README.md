# `snak` — Python Standalone Build Management Tool

`snak` is a lightweight CLI utility to manage multiple **self-contained Python builds** and virtual environments,
without touching your system Python installation.

It downloads **prebuilt Python binaries**
(from [python-build-standalone](https://github.com/astral-sh/python-build-standalone)) directly, allowing you
to **install, update, switch, and create virtual environments** independently and safely.

---

## Features

* 📦 Install standalone Python builds easily
* 🔄 Create and manage multiple virtual environments
* 🔍 List and inspect installed versions and environments
* ⚙️ Minimal configuration with sane defaults
* 🛡️ System-safe: does not interfere with your system's Python
* 🖥️ Works on **Linux** and **macOS**

---

## Installation

You can install `snak` globally by running:

```bash
curl -L https://raw.githubusercontent.com/mosquito/snak/refs/heads/master/src/snak.py | sudo install -Dm 755 /dev/stdin /usr/local/bin/snak
```

Alternatively, you can save the script manually and place it somewhere in your `$PATH`.

```bash
pip install --user snak
```

---

## Usage

```bash
snak [COMMAND] [SUBCOMMAND] [OPTIONS...]
```

High-level command structure:

| Command    | Description                       |
| ---------- | --------------------------------- |
| `env`      | Manage virtual environments       |
| `versions` | Manage standalone Python versions |
| `config`   | Manage `snak` configuration       |

Run `snak --help` to view all available commands.

---

## Examples

### Install a new standalone Python version

```bash
snak versions list
snak versions install 3.12.2
```

### Create a new virtual environment

```bash
snak env create myenv
# (optionally install packages)
snak env create myenv -p requests flask
```

### Activate an environment

```bash
eval $(snak env activate myenv)
```

*(Note: use `eval` to source the activation in your current shell.)*

### List all environments

```bash
snak env list
```

### Remove a virtual environment

```bash
snak env remove myenv
```

### Show installed Python versions

```bash
snak versions list
```

---

## Configuration

`snak` uses a simple INI-style configuration file:

* **User mode**: `~/.local/share/snak/config.ini`
* **Root mode (sudo)**: `/etc/snak.ini`

You can show or edit the configuration:

```bash
snak config show
snak config set paths cache ~/.cache/snak/

# for reverting to default just set empty value
snak config set paths cache ""
```

---

## Requirements

`snak` uses only standard libraries and does not require external Python packages.

You need just a few things to run `snak`:

* Linux or macOS
* Python 3.8+

---

## Why `snak`?

* No need to compile Python from source.
* Fully isolated environments.
* Great for experimenting with different Python versions easily.

---

## License

MIT License.
