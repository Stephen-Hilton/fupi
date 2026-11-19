#!/usr/bin/env bash
# Build and upload fupi to PyPI. Run from anywhere; it works from the repo root.
set -euo pipefail
cd "$(dirname "$0")"

echo "Remember to update the version in pyproject.toml (and __version__ in src/fupi/__init__.py)."
echo "Press enter when ready."
read -r _

rm -rf dist src/*.egg-info
python3 -m pip install --upgrade pip build twine
python3 -m build

# check before we upload:
twine check dist/*

# upload
twine upload -r pypi dist/*
# twine upload -r testpypi dist/*
