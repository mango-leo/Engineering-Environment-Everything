"""Check the command names supplied by a project profile."""

import argparse
import json
import shutil
import subprocess
from pathlib import Path


def inspect_tool(name):
    path = shutil.which(name)
    result = {"found": path is not None, "path": path, "version": None}
    if path is None:
        return result

    try:
        probe = subprocess.run(
            [path, "--version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        result["version_error"] = str(error)
        return result

    version_output = probe.stdout.strip() or probe.stderr.strip()
    if probe.returncode == 0 and version_output:
        result["version"] = version_output.splitlines()[0]
    elif probe.returncode == 0:
        result["version_error"] = "--version produced no output"
    else:
        result["version_error"] = f"--version exited with code {probe.returncode}"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tools", nargs="*")
    parser.add_argument("--output", type=Path, help="Write UTF-8 JSON to this file")
    args = parser.parse_args()

    results = {name: inspect_tool(name) for name in dict.fromkeys(args.tools)}
    output = json.dumps(results, indent=2) + "\n"
    if args.output is None:
        print(output, end="")
    else:
        args.output.write_text(output, encoding="utf-8")


if __name__ == "__main__":
    main()
