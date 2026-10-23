"""Sphinx configuration for educelab-globus."""
from __future__ import annotations

import os
import sys
from importlib.metadata import PackageNotFoundError, version as _pkg_version

# Make the src/ layout importable for autodoc when building locally.
sys.path.insert(0, os.path.abspath('../src'))

project = 'educelab-globus'
author = 'Seth Parker'
copyright = '2026, EduceLab'

try:
    release = _pkg_version('educelab-globus')
except PackageNotFoundError:
    release = '1.1.0'
version = '.'.join(release.split('.')[:2])

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.viewcode',
    'sphinx.ext.intersphinx',
    'sphinx.ext.autosummary',
]

autosummary_generate = True
autodoc_default_options = {
    'members': True,
    'undoc-members': True,
    'show-inheritance': True,
}
autodoc_typehints = 'description'
napoleon_google_docstring = True
napoleon_numpy_docstring = True

intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
    'globus-sdk': ('https://globus-sdk-python.readthedocs.io/en/stable/', None),
}

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']
