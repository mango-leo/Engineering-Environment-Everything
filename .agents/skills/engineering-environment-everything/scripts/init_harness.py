"""Render a project harness from an approved profile, intake, and tool checks."""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from string import Template
from tempfile import TemporaryDirectory

from runtime import CONTROL, Harness, lock


TEMPLATES = Path(__file__).resolve().parent.parent / "assets" / "harness-template"
PROFILE_HEADING = re.compile(r"^##[ \t]+(\d+)\.[ \t]+[^\n]+$", re.MULTILINE)


class ExistingHarnessError(Exception):
    pass


def parse_profile(profile_text):
    headings = list(PROFILE_HEADING.finditer(profile_text))
    if [int(heading[1]) for heading in headings] != list(range(1, 12)):
        raise ValueError("PROFILE.md must contain sections 1 through 11 in order")

    sections = {}
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(profile_text)
        section = profile_text[heading.end():end].strip()
        if not section:
            raise ValueError(f"PROFILE.md section {heading[1]} is empty")
        sections[int(heading[1])] = section
    return sections


def load_object(path):
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return data


def require_text(record, field):
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must contain text")
    return value.strip()


def string_list(record, field):
    values = record.get(field, [])
    if not isinstance(values, list) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        raise ValueError(f"{field} must be an array of nonempty strings")
    return [value.strip() for value in values]


def markdown_items(items, checkbox=False):
    prefix = "- [ ] " if checkbox else "- "
    lines = [prefix + item.replace("\n", "\n" + " " * len(prefix)) for item in items]
    return "\n".join(lines) or "해당 사항 없음."


def tool_status(tool):
    if tool is None:
        return "미점검"
    if not tool["found"]:
        return "명령을 찾지 못함"
    if not tool.get("version"):
        reason = tool.get("version_error", "출력 없음")
        return f"경로 확인, 버전 미확인 ({reason})"
    return f"경로 및 버전 확인 ({tool['version']})"


def verification_section(check_id, criterion, check, tools):
    procedure = require_text(check, "verify")
    pass_when = require_text(check, "pass_when")
    requires = string_list(check, "requires")
    statuses = [f"{name}: {tool_status(tools.get(name))}" for name in requires]
    prerequisites = string_list(check, "prerequisites")
    fallback = require_text(check, "fallback") if "fallback" in check else ""
    if not fallback and any(not tools.get(name, {}).get("version") for name in requires):
        fallback = "필요한 도구를 사용할 수 있는 환경에서 검증 절차를 실행한다."

    heading = f"### {check_id} · {criterion}"
    details = [f"실행 절차\n\n{procedure}", f"통과 기준\n\n{pass_when}"]
    details.append("필요한 도구\n\n" + markdown_items(statuses))
    if prerequisites:
        details.append("실행 환경의 선행 조건\n\n" + markdown_items(prerequisites))
    if fallback:
        details.append(f"대안 또는 후속 실행\n\n{fallback}")
    return "\n\n".join([heading, *details])


def render_harness(profile, intake, tools):
    for name, tool in tools.items():
        if not isinstance(tool, dict) or not isinstance(tool.get("found"), bool):
            raise ValueError(f"Invalid tool result for {name!r}")

    done_when = intake.get("done_when")
    if not isinstance(done_when, list) or not done_when:
        raise ValueError("done_when must contain at least one completion condition")

    skeleton = intake.get("skeleton")
    if not isinstance(skeleton, dict):
        raise ValueError("skeleton must contain a verification object")
    skeleton = {**skeleton, "criterion": "최소 검증 경로", "work": profile[9]}

    criteria = []
    tasks = []
    checks = []
    manifest_checks = []
    manifest_tasks = []
    requirements = []
    for index, check in enumerate([skeleton, *done_when], start=1):
        if not isinstance(check, dict):
            raise ValueError(f"Verification item {index} must be an object")
        check_id = f"V{index:02d}"
        criterion = require_text(check, "criterion")
        work = " ".join(require_text(check, "work").splitlines()).replace("|", "\\|")
        tasks.append(f"| [ ] | T{index:02d} | {work} | {check_id} | todo |")
        checks.append(verification_section(check_id, criterion, check, tools))
        manifest_checks.append({"id": check_id, "command": [], "cwd": ".", "min_tests": 1,
                                "timeout_seconds": 300, "checker_files": [], "self_tests": [],
                                **check.get("executable", {})})
        manifest_checks[-1]["id"] = check_id
        manifest_tasks.append({"id": f"T{index:02d}", "work": work, "checks": [check_id],
                               "depends_on": check.get("depends_on", [] if index == 1 else ["T01"])})
        if index > 1:
            criteria.append(f"{criterion} ({check_id})")
            requirements.append({"id": f"R{index - 1:02d}", "kind": "goal",
                                 "description": criterion, "checks": [check_id]})

    constraint_items = intake.get("constraints")
    if constraint_items is None:
        constraint_items = [{"description": profile[5], "checks": []}]
        constraint_items.extend({"description": item, "checks": []} for item in string_list(intake, "never"))
    if not isinstance(constraint_items, list) or not constraint_items:
        raise ValueError("constraints must enumerate the project constraints")
    for index, constraint in enumerate(constraint_items, 1):
        requirements.append({"id": f"C{index:02d}", "kind": "constraint",
                             "description": require_text(constraint, "description"),
                             "checks": string_list(constraint, "checks")})
    extra_checks = intake.get("extra_checks", [])
    if not isinstance(extra_checks, list):
        raise ValueError("extra_checks must be an array")
    manifest_checks.extend(extra_checks)

    tool_checks = [
        f"{name}: {tool_status(tool)}" + (f" — `{tool['path']}`" if tool.get("path") else "")
        for name, tool in tools.items()
    ]
    values = {
        "goal": require_text(intake, "what"),
        "nature": profile[1],
        "deliverables": profile[2],
        "target": profile[3],
        "evidence": profile[4],
        "constraints": profile[5],
        "conventions": profile[6],
        "needed_tools": profile[7],
        "alternatives": profile[8],
        "first_loop": profile[9],
        "done_when": markdown_items(criteria, checkbox=True),
        "tasks": "\n".join(tasks),
        "checks": "\n\n".join(checks),
        "tool_checks": markdown_items(tool_checks),
        "research": intake.get("research", "조사 기록과 출처를 작성한 뒤 사용자 검토를 받는다."),
        "plan": intake.get("plan", "작업 의존성, 환경 준비, 검증 경로와 예상 시간을 작성한다."),
        "adjacent": profile[10],
        "confidence": profile[11],
    }
    for field in ("scope_in", "scope_out", "interfaces", "assumptions", "open_questions", "never"):
        values[field] = markdown_items(string_list(intake, field))

    files = {}
    for template in sorted(TEMPLATES.glob("*.md")):
        content = template.read_text(encoding="utf-8")
        files[template.name] = content if template.name in ("PROTOCOL.md", "REPORT_FORMAT.md") else Template(content).substitute(values)
    state = load_object(TEMPLATES / "STATE.json")
    state["tools"] = tools
    files["STATE.json"] = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    files["CONTROL.json"] = json.dumps(CONTROL, indent=2) + "\n"
    files["CHECKS.json"] = json.dumps({"schema_version": 2, "sources": string_list(intake, "sources"),
                                     "requirements": requirements, "tasks": manifest_tasks,
                                     "checks": manifest_checks}, ensure_ascii=False, indent=2) + "\n"
    files["runtime.py"] = (Path(__file__).parent / "runtime.py").read_text(encoding="utf-8")
    return files


def create_harness(profile_path, profile_bytes, files):
    target = Path.cwd() / "harness"
    if target.is_symlink() or target.resolve() != target:
        raise ExistingHarnessError("Harness must be a regular project directory")
    target.mkdir(exist_ok=True)
    with lock(target):
        return publish_harness(profile_bytes, files)


def publish_harness(profile_bytes, files):
    target = Path.cwd() / "harness"
    payloads = {name: content.encode("utf-8") for name, content in files.items()}
    payloads["PROFILE.md"] = profile_bytes
    hashes = {name: hashlib.sha256(content).hexdigest() for name, content in payloads.items()}
    journal = target / ".init-journal.json"
    directories = {"loops", "logs", "results", "checks", "evidence"}
    if target.exists() or target.is_symlink():
        if target.is_symlink() or target.resolve() != target or not target.is_dir():
            raise ExistingHarnessError("Harness must be a regular project directory")
        if journal.is_symlink():
            raise ExistingHarnessError("Unexpected initialization journal link")
        if journal.exists():
            if load_object(journal) != {"schema_version": 2, "files": hashes}:
                raise ExistingHarnessError("Incomplete initialization has different inputs; inspect before recovery")
            allowed = set(payloads) | directories | {journal.name, ".runtime.lock"}
        else:
            allowed = {"PROFILE.md", ".runtime.lock"}
        for path in target.iterdir():
            if path.name not in allowed or path.is_symlink():
                raise ExistingHarnessError("Existing harness requires resume or explicit upgrade")
            if path.name in payloads and (not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != hashes[path.name]):
                raise ExistingHarnessError(f"Preserving modified file: {path.name}")
            if path.name in directories and (not path.is_dir() or any(path.iterdir())):
                raise ExistingHarnessError(f"Preserving populated directory: {path.name}")

    # Stage complete files, then publish; the checksum journal permits interrupted retries.
    with TemporaryDirectory(prefix=".harness-stage-", dir=Path.cwd()) as temporary:
        staging = Path(temporary)
        for name, content in payloads.items():
            (staging / name).write_bytes(content)
        target.mkdir(exist_ok=True)
        if not journal.exists():
            staged_journal = staging / journal.name
            with staged_journal.open("x", encoding="utf-8") as output:
                json.dump({"schema_version": 2, "files": hashes}, output)
            staged_journal.rename(journal)
        for name in directories:
            (target / name).mkdir(exist_ok=True)
        for name in payloads:
            destination = target / name
            if not destination.exists():
                (staging / name).rename(destination)
        journal.unlink()
    return target


def upgrade_harness():
    target = Path.cwd() / "harness"
    if target.is_symlink() or target.resolve() != target or not target.is_dir():
        raise ExistingHarnessError("Harness must be a regular project directory")
    with lock(target):
        harness = Harness(target)
        for source in (TEMPLATES / "PROTOCOL.md", TEMPLATES / "REPORT_FORMAT.md", Path(__file__).parent / "runtime.py"):
            destination = target / source.name
            if not destination.exists():
                with destination.open("xb") as output:
                    output.write(source.read_bytes())
        harness.migrate()
    print("Migrated state and installed portable runtime. Complete PLAN, RESEARCH and CHECKS before approval.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upgrade", action="store_true")
    for name in ("profile", "intake", "tools"):
        parser.add_argument(f"--{name}", type=Path)
    args = parser.parse_args()

    try:
        if args.upgrade:
            upgrade_harness()
            return 0
        if any(value is None for value in (args.profile, args.intake, args.tools)):
            parser.error("--profile, --intake and --tools are required unless --upgrade is used")
        profile_bytes = args.profile.read_bytes()
        profile_text = profile_bytes.decode("utf-8-sig").replace("\r\n", "\n")
        files = render_harness(parse_profile(profile_text), load_object(args.intake), load_object(args.tools))
        target = create_harness(args.profile, profile_bytes, files)
    except (ExistingHarnessError, FileExistsError) as error:
        print(f"Existing harness: {error}", file=sys.stderr)
        return 3
    except (OSError, ValueError, KeyError) as error:
        print(f"Cannot initialize harness: {error}", file=sys.stderr)
        return 2

    print(f"Created {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
