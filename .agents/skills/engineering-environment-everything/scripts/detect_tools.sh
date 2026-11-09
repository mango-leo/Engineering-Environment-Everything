#!/usr/bin/env bash
set -eu

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if command -v python3 >/dev/null 2>&1; then
    exec python3 "$script_dir/detect_tools.py" "$@"
fi
exec python "$script_dir/detect_tools.py" "$@"
