#!/usr/bin/env bash
# Build and upload fupi to PyPI. Run it (./publish.sh), don't source it. Needs uv.
(return 0 2>/dev/null) && { echo "Run ./publish.sh instead of sourcing it."; return 1; }
set -euo pipefail
cd "$(dirname "$0")"

version=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
echo "Publishing fupi $version (check pyproject.toml and __version__ in src/fupi/__init__.py)."
echo "Press enter when ready, or Ctrl-C to stop."
read -r _ || { echo "No input (not an interactive terminal); aborting without publishing."; exit 1; }

rm -rf dist build src/*.egg-info
uv build                       # builds sdist + wheel into dist/ in an isolated env
uvx twine check dist/*         # check before we upload
uvx twine upload -r pypi dist/*
# uvx twine upload -r testpypi dist/*
