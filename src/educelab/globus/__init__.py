"""EduceLab Globus: configuration and helpers for Globus endpoint transfers."""

from .login import login
from .config import endpoints, endpoint_names, endpoint_uuids, get_endpoint

__all__ = [
    'login',
    'endpoints',
    'endpoint_names',
    'endpoint_uuids',
    'get_endpoint',
]
