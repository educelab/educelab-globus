# EduceLab Globus

`educelab-globus` is a Python module for logging into and interacting with 
Globus endpoints.

## Requirements
- Python 3.10+
- globus-sdk 3.46+ 
- prompt-toolkit

## Installation
This project is available on PyPI:

```shell
python3 -m pip install educelab-globus
```

## Usage

### Configuration files
Named Globus endpoints are specified in `~/.globuscp/config.toml`. The config 
file has a simple format which is similar to that of `rclone`:
```toml
[endpoint-name]
uuid = "16fd2706-8baf-433b-82eb-8c7fada847da"
basedir = "/absolute/path/to/default/directory/"
```

**Note:** At the moment, `el-globus-cp` only supports transfers between the 
`basedir` of two endpoints. This is expected to change in future releases.

### Utilities

```bash
# List the endpoints stored in configuration file
el-globus-config

# Login to Globus and get access tokens for endpoints
# Tokens are stored in ~/.globuscp/tokenstore.json
el-globus-login

# Initiate a transfer between the base directories of two Globus endpoints
el-globus-cp
```