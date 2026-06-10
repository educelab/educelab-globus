# EduceLab Globus

[![PyPI version](https://img.shields.io/pypi/v/educelab-globus.svg)](https://pypi.org/project/educelab-globus/)
[![Python versions](https://img.shields.io/pypi/pyversions/educelab-globus.svg)](https://pypi.org/project/educelab-globus/)
[![Tests](https://github.com/educelab/educelab-globus/actions/workflows/test.yml/badge.svg)](https://github.com/educelab/educelab-globus/actions/workflows/test.yml)
[![Documentation Status](https://readthedocs.org/projects/educelab-globus/badge/?version=latest)](https://educelab-globus.readthedocs.io/en/latest/?badge=latest)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPLv3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)

`educelab-globus` is a Python module and command-line toolkit for logging into
and transferring data between [Globus](https://www.globus.org/) endpoints. It
wraps `globus-sdk` with a small configuration file, named endpoints, and three
ergonomic CLI commands that make scripted transfers between lab and archive
systems straightforward.

## Features
- A simple TOML-based config of named Globus endpoints with optional default
  base directories
- A login command that acquires and caches tokens, prompts for any required
  consents (including `data_access` and session/MFA requirements), and falls
  back automatically to a headless flow on remote shells
- A `cp`-style command for copying files and directories between endpoints,
  with progress reporting, sync modes, optional checksum verification, and a
  background submit mode
- A small Python API for use from other tools and pipelines

## Requirements
- Python 3.10+
- [`globus-sdk`](https://pypi.org/project/globus-sdk/) 4.0+
- [`prompt-toolkit`](https://pypi.org/project/prompt-toolkit/)

## Installation
This project is available on PyPI:

```shell
python3 -m pip install educelab-globus
```

## Quick start

### 1. Configure your endpoints

Named Globus endpoints are stored in `~/.globuscp/config.toml`:

```toml
[lab-server]
uuid = "16fd2706-8baf-433b-82eb-8c7fada847da"
basedir = "/mnt/scratch/"  # optional, defaults to /

[archive]
uuid = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
basedir = "/cold/"
```

`basedir` is optional. When omitted, absolute paths must be given explicitly
on the command line and relative paths are not allowed.

You can also use the interactive editor:

```shell
el-globus-config --edit
```

### 2. Log in

```shell
el-globus-login
```

Tokens are cached in `~/.globuscp/tokenstore.json`. Subsequent commands reuse
them until they expire or an endpoint requires new consents.

### 3. Transfer data

```shell
el-globus-cp lab-server:data/experiment-01 archive:backups/2024/experiment-01
```

## CLI reference

```bash
# List configured endpoints
el-globus-config

# Interactively add, edit, or delete endpoints
el-globus-config --edit

# Login to Globus and cache access tokens
el-globus-login

# Login for specific endpoints only
el-globus-login --endpoints endpoint-name-or-uuid [...]

# Force a new login, even if cached tokens are valid
el-globus-login --force

# Print the auth URL instead of opening a browser (useful over SSH)
el-globus-login --no-browser

# Transfer a file or directory between two endpoints.
# Paths may be absolute or relative to the endpoint's basedir.
el-globus-cp src-endpoint:/path/to/source dst-endpoint:/path/to/dest

# Examples
el-globus-cp lab-server:data/experiment-01 archive:backups/2024/experiment-01
el-globus-cp lab-server:/mnt/scratch/run42 archive:/cold/run42

# Only transfer files that have changed (other choices: exists, size, checksum)
el-globus-cp --sync-level mtime src:data/ dst:data/

# Enable checksum verification
el-globus-cp --verify src:data/ dst:data/

# Background mode: exit immediately after submitting the transfer
el-globus-cp --background src:data/ dst:data/
```

All commands accept `--verbose`/`-v` and `--quiet`/`-q` to control log output.

## Python API

```python
from educelab.globus import login, endpoints, get_endpoint

# List configured endpoints
print(endpoints())

# Look up a single endpoint by name
ep = get_endpoint('lab-server')

# Log in and obtain a globus_sdk.TransferClient
tc = login([ep['uuid']])
```

See the [full API documentation](https://educelab-globus.readthedocs.io) for
details.

## Documentation
Full documentation is hosted on Read the Docs:
<https://educelab-globus.readthedocs.io>

## License
This project is licensed under the GNU Affero General Public License v3.0. See
[LICENSE](LICENSE) and [NOTICE](NOTICE) for details.
