# EduceLab Globus

`educelab-globus` is a Python module for logging into and interacting with
Globus endpoints.

## Requirements
- Python 3.10+
- globus-sdk 4.0+
- prompt-toolkit

## Installation
This project is available on PyPI:

```shell
python3 -m pip install educelab-globus
```

## Usage

### Configuration

Named Globus endpoints are stored in `~/.globuscp/config.toml`:

```toml
[endpoint-name]
uuid = "16fd2706-8baf-433b-82eb-8c7fada847da"
basedir = "/absolute/path/to/default/directory/"  # optional, defaults to /
```

`basedir` is optional. When omitted, absolute paths must be given explicitly
on the command line and relative paths are not allowed.

### Utilities

```bash
# List configured endpoints
el-globus-config

# Interactively add, edit, or delete endpoints
el-globus-config --edit

# Login to Globus and cache access tokens (~/.globuscp/tokenstore.json)
el-globus-login

# Login for specific endpoints only
el-globus-login --endpoints endpoint-name-or-uuid [...]

# Transfer a file or directory between two endpoints
#   Paths may be absolute or relative to the endpoint's basedir
el-globus-cp src-endpoint:/path/to/source dst-endpoint:/path/to/dest

# Examples
el-globus-cp lab-server:data/experiment-01 archive:backups/2024/experiment-01
el-globus-cp lab-server:/mnt/scratch/run42 archive:/cold/run42

# Background mode: exit immediately after submitting the transfer
el-globus-cp --background src-endpoint:data/ dst-endpoint:data/
```
