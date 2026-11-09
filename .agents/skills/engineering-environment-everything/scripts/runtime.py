"""Portable, standard-library execution and evidence harness (Python 3.9+)."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import statistics
import subprocess
import sys
import tempfile
import time
import uuid


CONTROL = {"timeout_minutes": 60, "check_timeout_seconds": 300,
           "environment_attempts": 3, "no_progress_limit": 3,
           "after_replan_limit": 2, "consumption_ratio": 2,
           "high_consumption_streak": 2, "monitor_every": 2}
SEALED = ["PROFILE.md", "SPEC.md", "CONSTRAINTS.md", "PLAN.md", "RESEARCH.md",
          "VERIFICATION.md", "CHECKS.json", "AGENT.md", "PROTOCOL.md",
          "REPORT_FORMAT.md", "runtime.py"]


def load(path):
    with path.open(encoding="utf-8-sig") as stream:
        return json.load(stream)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".write-", delete=False) as stream:
            temp = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def digest(path):
    hash_value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hash_value.update(block)
    return hash_value.hexdigest()


def within(root, relative):
    if not isinstance(relative, str) or not relative:
        raise ValueError("Expected a relative project path")
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"Path must stay in the project: {relative}")
    resolved = (root / candidate).resolve()
    resolved.relative_to(root.resolve())
    return resolved


def number(value, name, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    if not math.isfinite(value) or value < minimum:
        raise ValueError(f"Invalid {name}")
    return value


def text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must contain text")
    return value


def command(value):
    if not isinstance(value, list) or not value:
        raise ValueError("command must be a nonempty argument array")
    for part in value:
        text(part, "command argument")
    return [sys.executable if part == "{python}" else part for part in value]


@contextmanager
def lock(folder):
    """OS-released advisory lock; an abandoned process cannot leave a stale lock."""
    with (folder / ".runtime.lock").open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def terminate_tree(process):
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=10)


def parse_result(payload, returncode, minimum):
    result = json.loads(payload)
    if not isinstance(result, dict):
        raise ValueError("Checker output must be a JSON object")
    counts = [result.get(key) for key in ("tests_run", "passed", "failed", "skipped")]
    if any(type(value) is not int or value < 0 for value in counts):
        raise ValueError("Checker counts must be nonnegative integers")
    total, passed, failed, skipped = counts
    if total != passed + failed + skipped:
        raise ValueError("Inconsistent checker counts")
    if result.get("status") not in ("PASS", "FAIL", "UNVERIFIED", "ERROR"):
        raise ValueError("Invalid checker status")
    metrics = result.get("metrics", {})
    if not isinstance(metrics, dict):
        raise ValueError("Checker metrics must be an object")
    for name, value in metrics.items():
        number(value, name, -sys.float_info.max)
    status = result["status"]
    if total < minimum or skipped or status == "UNVERIFIED":
        status = "UNVERIFIED"
    elif returncode not in (0, 1) or status == "ERROR":
        status = "ERROR"
    elif failed or status == "FAIL":
        status = "FAIL"
    elif returncode != 0:
        status = "ERROR"
    result["status"] = status
    return {key: result[key] for key in ("status", "tests_run", "passed", "failed", "skipped", "metrics", "details") if key in result}


class Harness:
    def __init__(self, folder):
        self.folder = Path(folder).resolve()
        self.root = self.folder.parent
        self.state = load(self.folder / "STATE.json")

    def save(self):
        write(self.folder / "STATE.json", self.state)

    def control(self):
        control = load(self.folder / "CONTROL.json")
        for key in CONTROL:
            number(control.get(key), key, 0.001)
        for key in ("environment_attempts", "no_progress_limit", "after_replan_limit",
                    "high_consumption_streak", "monitor_every"):
            if type(control[key]) is not int:
                raise ValueError(f"{key} must be an integer")
        return control

    def manifest(self):
        manifest = load(self.folder / "CHECKS.json")
        if manifest.get("schema_version") != 2:
            raise ValueError("CHECKS.json requires schema_version 2")
        checks = manifest.get("checks", [])
        requirements = manifest.get("requirements", [])
        if not checks or not requirements or not manifest.get("sources"):
            raise ValueError("Checks, requirements and source patterns must be defined")
        ids = set()
        for check in checks:
            check_id = text(check.get("id"), "check ID")
            if check_id in ids:
                raise ValueError("Duplicate check ID")
            ids.add(check_id)
            command(check.get("command"))
            within(self.root, check.get("cwd", "."))
            if type(check.get("min_tests")) is not int or check["min_tests"] < 1:
                raise ValueError("min_tests must be a positive integer")
            number(check.get("timeout_seconds", 300), "check timeout", 0.001)
            if not check.get("checker_files"):
                raise ValueError(f"{check_id} requires checker_files")
            for path in check["checker_files"]:
                if not within(self.root, path).is_file():
                    raise ValueError(f"Missing checker file: {path}")
            examples = check.get("self_tests", [])
            if not {"PASS", "FAIL"}.issubset({example.get("expected") for example in examples}):
                raise ValueError(f"{check_id} requires positive and negative self-tests")
            for example in examples:
                command(example.get("command"))
                if example["command"][:2] != check["command"][:2]:
                    raise ValueError("Self-tests must exercise the same checker entry point")
                if example.get("expected") not in ("PASS", "FAIL"):
                    raise ValueError("Self-test expected result must be PASS or FAIL")
            for direction in check.get("metrics", {}).values():
                if direction not in ("min", "max"):
                    raise ValueError("Metric direction must be min or max")
        requirement_ids = set()
        kinds = set()
        for requirement in requirements:
            identity = text(requirement.get("id"), "requirement ID")
            if identity in requirement_ids:
                raise ValueError("Duplicate requirement ID")
            requirement_ids.add(identity)
            kinds.add(requirement.get("kind"))
            text(requirement.get("description"), "requirement description")
            linked = requirement.get("checks", [])
            if not linked or not set(linked).issubset(ids):
                raise ValueError(f"{identity} has missing or unknown checks")
        if kinds != {"goal", "constraint"}:
            raise ValueError("Both goals and constraints must be covered")
        tasks = manifest.get("tasks", [])
        task_ids = {item.get("id") for item in tasks}
        if not tasks or None in task_ids or len(task_ids) != len(tasks):
            raise ValueError("Unique tasks are required")
        for task in tasks:
            if not task.get("checks") or not set(task["checks"]).issubset(ids):
                raise ValueError("Task checks must exist")
            if not set(task.get("depends_on", [])).issubset(task_ids - {task["id"]}):
                raise ValueError("Invalid task dependencies")
        unresolved = {task["id"]: set(task.get("depends_on", [])) for task in tasks}
        resolved = set()
        while unresolved:
            ready = {identity for identity, dependencies in unresolved.items() if dependencies.issubset(resolved)}
            if not ready:
                raise ValueError("Cyclic task dependencies")
            resolved.update(ready)
            unresolved = {identity: dependencies for identity, dependencies in unresolved.items() if identity not in ready}
        for pattern in manifest["sources"]:
            within(self.root, pattern)
        if "environment" in manifest:
            steps = manifest["environment"]
            if not isinstance(steps, list):
                raise ValueError("environment must be an ordered array")
            step_ids = set()
            for step in steps:
                if not isinstance(step, dict):
                    raise ValueError("Environment steps must be objects")
                identity = text(step.get("id"), "environment step ID")
                if identity in step_ids:
                    raise ValueError("Duplicate environment step ID")
                step_ids.add(identity)
                within(self.root, step.get("cwd", "."))
                number(step.get("timeout_seconds", 300), "environment timeout", 0.001)
                command(step.get("probe"))
                if "setup" in step:
                    command(step["setup"])
                files = step.get("files", [])
                if not isinstance(files, list):
                    raise ValueError("Environment files must be an array")
                for path in files:
                    if not within(self.root, path).is_file():
                        raise ValueError(f"Missing environment file: {path}")
        return manifest

    def sources(self, manifest):
        result = {}
        for pattern in manifest["sources"]:
            for path in sorted(self.root.glob(pattern)):
                if path.is_file():
                    resolved = within(self.root, str(path.relative_to(self.root)))
                    result[path.relative_to(self.root).as_posix()] = digest(resolved)
        return result

    def sealed(self, manifest):
        paths = {(self.folder / name).relative_to(self.root).as_posix() for name in SEALED}
        for check in manifest["checks"]:
            paths.update(check["checker_files"])
        for step in manifest.get("environment", []):
            paths.update(step.get("files", []))
        hashes = {}
        for path in sorted(paths):
            resolved = within(self.root, path)
            key = resolved.relative_to(self.root).as_posix()
            if resolved == self.folder / "SPEC.md":
                content = resolved.read_text(encoding="utf-8-sig")
                content = re.sub(r"(?m)^- \[[xX]\] ", "- [ ] ", content)
                hashes[key] = hashlib.sha256(content.encode("utf-8")).hexdigest()
            else:
                hashes[key] = digest(resolved)
        return hashes

    def integrity(self, manifest):
        baseline = load(self.folder / "BASELINE.json")
        if baseline["files"] != self.sealed(manifest):
            self.state.update(status="blocked", blocked_on="Approved specification or checker changed; review and approve again")
            self.save()
            raise ValueError(self.state["blocked_on"])

    def remaining(self, *, save_timeout=True):
        run = self.state.get("run")
        if not run:
            raise ValueError("Start an authorized run first")
        deadline = run["started_at"] + self.control()["timeout_minutes"] * 60
        run["deadline"] = deadline
        remaining = deadline - time.time()
        if remaining <= 0:
            self.state.update(status="timed_out", blocked_on="Run deadline reached; report progress and ask whether to continue")
            if save_timeout:
                self.save()
        return max(0, remaining)

    def execute(self, arguments, cwd, timeout, minimum, log_name):
        logs = self.folder / "logs"
        logs.mkdir(exist_ok=True)
        stdout_path = logs / f"{log_name}.stdout"
        stderr_path = logs / f"{log_name}.stderr"
        record = {"command": arguments, "cwd": cwd, "started_at": time.time(),
                  "stdout": str(stdout_path.relative_to(self.folder)),
                  "stderr": str(stderr_path.relative_to(self.folder))}
        if timeout <= 0:
            return {**record, "status": "UNVERIFIED", "reason": "Run deadline reached"}
        try:
            with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
                process = subprocess.Popen(command(arguments), cwd=within(self.root, cwd),
                                           stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                           start_new_session=os.name != "nt",
                                           creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
                try:
                    record["exit_code"] = process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    terminate_tree(process)
                    return {**record, "status": "ERROR", "reason": "Command timeout", "ended_at": time.time()}
                except BaseException:
                    terminate_tree(process)
                    raise
            if minimum is None:
                return {**record, "status": "OK" if record["exit_code"] == 0 else "ERROR", "ended_at": time.time()}
            if stdout_path.stat().st_size > 1024 * 1024:
                raise ValueError("Checker JSON exceeds 1 MiB; put verbose output on stderr")
            result = parse_result(stdout_path.read_text(encoding="utf-8-sig"), record["exit_code"], minimum)
            return {**record, **result, "ended_at": time.time()}
        except FileNotFoundError as error:
            return {**record, "status": "UNVERIFIED", "reason": str(error)}
        except (OSError, ValueError) as error:
            return {**record, "status": "ERROR", "reason": str(error)}

    def approve(self):
        if self.state.get("status") in ("running", "preparing"):
            raise ValueError("Pause and review changes before reapproval")
        if self.state.get("recovery_required"):
            raise ValueError("Legacy interrupted state requires recover first")
        self.state.update(status="awaiting_approval", phase="review", blocked_on=None,
                          results={}, preparation=None, run=None)
        self.save()
        manifest = self.manifest()
        before = self.sealed(manifest)
        if "environment" in manifest:
            write(self.folder / "BASELINE.json", {"approved_at": time.time(), "files": before})
            self.state.update(status="preparing", phase="environment", run=self.new_run(),
                              preparation={"attempts": {}, "steps": {}, "calibrated": False})
            self.remaining()
            self.save()
            return

        # Manifests created before separate preparation retain their original entry point.
        deadline = time.time() + self.control()["timeout_minutes"] * 60
        self.run_calibration(manifest, before, lambda: max(0, deadline - time.time()))
        write(self.folder / "BASELINE.json", {"approved_at": time.time(), "files": before})
        self.state.update(status="ready")
        self.save()

    def preparation_manifest(self):
        if self.state.get("status") != "preparing" or not self.state.get("preparation"):
            raise ValueError("An approved preparation run is required")
        if not self.remaining():
            raise ValueError("Run deadline reached")
        manifest = self.manifest()
        self.integrity(manifest)
        return manifest

    def prepare(self, identity):
        manifest = self.preparation_manifest()
        progress = self.state["preparation"]
        steps = manifest["environment"]
        pending = next((step for step in steps if progress["steps"].get(step["id"], {}).get("status") != "OK"), None)
        if pending is None or pending["id"] != identity:
            raise ValueError("Prepare the next pending environment step in approved order")

        attempts = progress["attempts"]
        limit = self.control()["environment_attempts"]
        if attempts.get(identity, 0) >= limit:
            self.state.update(status="blocked", blocked_on=f"Environment attempt limit for {identity}")
            self.save()
            raise ValueError(self.state["blocked_on"])
        attempts[identity] = attempts.get(identity, 0) + 1
        self.save()

        def execute_step(key):
            timeout = min(pending.get("timeout_seconds", 300), self.remaining())
            return self.execute(pending[key], pending.get("cwd", "."), timeout, None, uuid.uuid4().hex)

        result = {"step": identity, "attempt": attempts[identity], "probe": execute_step("probe")}
        self.integrity(manifest)
        result["status"] = result["probe"]["status"]
        if result["probe"]["status"] != "OK" and "setup" in pending and self.remaining():
            result["setup"] = execute_step("setup")
            self.integrity(manifest)
            result["status"] = result["setup"]["status"]
            if result["setup"]["status"] == "OK":
                result["initial_probe"] = result["probe"]
                result["probe"] = execute_step("probe")
                self.integrity(manifest)
                result["status"] = result["probe"]["status"]
        write(self.folder / "activities" / f"{uuid.uuid4().hex}.json",
              {**result, "run_id": self.state["run"]["id"], "phase": "environment"})
        progress["steps"][identity] = result
        if self.remaining():
            self.state["blocked_on"] = None if result["status"] == "OK" else f"Readiness check failed for {identity}"
            if result["status"] != "OK" and attempts[identity] >= limit:
                self.state.update(status="blocked", blocked_on=f"Environment attempt limit for {identity}")
        self.save()
        return result

    def calibrate(self):
        manifest = self.preparation_manifest()
        progress = self.state["preparation"]
        if any(progress["steps"].get(step["id"], {}).get("status") != "OK"
               for step in manifest["environment"]):
            raise ValueError("All environment readiness probes must succeed before calibration")
        before = self.sealed(manifest)
        try:
            self.run_calibration(manifest, before, self.remaining)
        except ValueError as error:
            if self.remaining():
                self.state.update(status="blocked", phase="calibration", blocked_on=str(error))
                self.save()
            raise
        if not self.remaining():
            raise ValueError("Run deadline reached")
        progress["calibrated"] = True
        self.state.update(status="ready", phase="calibration", blocked_on=None)
        self.save()

    def run_calibration(self, manifest, before, remaining):
        initial_sources = self.sources(manifest)
        results = []
        for check in manifest["checks"]:
            for example in check["self_tests"]:
                result = self.execute(example["command"], check.get("cwd", "."),
                                      min(check.get("timeout_seconds", 300), self.control()["check_timeout_seconds"],
                                          remaining()), check["min_tests"], uuid.uuid4().hex)
                results.append({"check": check["id"], "expected": example["expected"], **result})
                if result["status"] != example["expected"]:
                    write(self.folder / "CALIBRATION.json", results)
                    raise ValueError(f"Calibration failed for {check['id']}")
        if before != self.sealed(manifest) or initial_sources != self.sources(manifest):
            raise ValueError("Checker, specification or sources changed during calibration")
        write(self.folder / "CALIBRATION.json", results)

    def new_run(self):
        return {"id": uuid.uuid4().hex, "started_at": time.time(), "history": [],
                "no_progress": 0, "high_streak": 0, "replanned": False,
                "environment_attempts": {}, "best_passed": [], "best_metrics": {}}

    def start(self):
        if self.state.get("status") == "awaiting_approval":
            raise ValueError("Successful calibration and approval are required before starting")
        manifest = self.manifest()
        self.integrity(manifest)
        preparation = self.state.get("preparation") or {}
        if "environment" in manifest and not preparation.get("calibrated"):
            raise ValueError("Environment preparation and calibration are required before implementation")
        if self.state.get("recovery_required"):
            raise ValueError("Legacy interrupted state requires recover first")
        if self.state.get("status") == "running":
            raise ValueError("A run is active; start cannot reset its deadline")
        if self.state["status"] == "ready" and self.state.get("phase") == "calibration":
            if not self.remaining():
                raise ValueError("Run deadline reached")
        else:
            self.state["run"] = self.new_run()
        self.state.update(status="running", phase="implement", blocked_on=None)
        if self.state.get("active_loop") is not None:
            self.state["active_started_at"] = time.time()
        self.remaining()
        self.save()

    def ensure_running(self):
        if self.state.get("schema_version") != 2:
            raise ValueError("Legacy state requires migrate")
        if self.state.get("status") != "running":
            raise ValueError(f"Run is {self.state.get('status')}; follow PROTOCOL.md")
        if not self.remaining():
            raise ValueError("Run deadline reached")

    def begin(self, tasks, phase):
        self.ensure_running()
        manifest = self.manifest()
        self.integrity(manifest)
        if phase == "environment" and "environment" in manifest:
            raise ValueError("Use the separate preparation stage for environment setup")
        if self.state.get("active_loop") is not None:
            raise ValueError("Continue the active loop; do not allocate another number")
        known = {task["id"]: task for task in manifest["tasks"]}
        if not tasks or len(tasks) > 2 or not set(tasks).issubset(known):
            raise ValueError("Select one or two known task IDs")
        if self.state.get("last_completed_loop", 0) == 0 and tasks != [manifest["tasks"][0]["id"]]:
            raise ValueError("First loop must select only the minimum execution-path task")
        completed = self.completed_tasks(manifest)
        for task in tasks:
            if not set(known[task].get("depends_on", [])).issubset(completed):
                raise ValueError(f"Dependencies incomplete for {task}")
            if phase == "environment":
                attempts = self.state["run"]["environment_attempts"]
                attempts[task] = attempts.get(task, 0) + 1
                if attempts[task] > self.control()["environment_attempts"]:
                    self.state.update(status="blocked", blocked_on=f"Environment attempt limit for {task}")
                    self.save()
                    raise ValueError(self.state["blocked_on"])
        self.state.update(active_loop=self.state.get("last_completed_loop", 0) + 1,
                          current_task=tasks, phase=phase, active_started_at=time.time())
        self.save()

    def evidence(self, check, source_hashes):
        evidence_hashes = {}
        for item in check.get("evidence", []):
            artifact = within(self.root, item["path"])
            metadata_path = within(self.root, item["metadata"])
            metadata = load(metadata_path)
            if metadata.get("artifact_sha256") != digest(artifact):
                raise ValueError("Evidence hash mismatch")
            if metadata.get("sources") != source_hashes:
                raise ValueError("Evidence belongs to different source files")
            for field in ("producer", "target", "settings"):
                if field not in item or metadata.get(field) != item[field]:
                    raise ValueError(f"Evidence {field} mismatch")
            stamp = datetime.fromisoformat(metadata["collected_at"].replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError("Evidence timestamp requires a timezone")
            age = time.time() - stamp.timestamp()
            if age < -60 or age > number(item["max_age_seconds"], "evidence age", 1):
                raise ValueError("Evidence is stale or dated in the future")
            evidence_hashes[item["path"]] = digest(artifact)
            evidence_hashes[item["metadata"]] = digest(metadata_path)
        return evidence_hashes

    def activity(self, arguments, cwd, timeout):
        self.ensure_running()
        self.integrity(self.manifest())
        if self.state.get("active_loop") is None:
            raise ValueError("Begin a loop before running a project command")
        identity = uuid.uuid4().hex
        limit = min(number(timeout, "command timeout", 0.001), self.remaining())
        result = self.execute(arguments, cwd, limit, None, identity)
        result.update(run_id=self.state["run"]["id"], loop=self.state["active_loop"])
        write(self.folder / "activities" / f"{identity}.json", result)
        self.remaining()
        self.save()
        return result

    def check(self, selected=None, final=False):
        self.ensure_running()
        manifest = self.manifest()
        self.integrity(manifest)
        if self.state.get("active_loop") is None:
            raise ValueError("Begin a loop before checking")
        checks = {check["id"]: check for check in manifest["checks"]}
        if final and selected:
            raise ValueError("Final validation must run all checks")
        chosen = list(checks) if final or not selected else selected
        if not set(chosen).issubset(checks):
            raise ValueError("Unknown check ID")
        if selected:
            tasks = {task["id"]: task for task in manifest["tasks"]}
            pending = list(self.state["current_task"])
            prerequisites = set()
            while pending:
                for dependency in tasks[pending.pop()].get("depends_on", []):
                    if dependency not in prerequisites:
                        prerequisites.add(dependency)
                        pending.append(dependency)
            required = {identity for task in prerequisites for identity in tasks[task]["checks"]}
            chosen = list(dict.fromkeys([*chosen, *sorted(required)]))
        before = self.sources(manifest)
        results = {}
        self.state["phase"] = "verify"
        self.save()
        for identity in chosen:
            check = checks[identity]
            try:
                inputs = self.evidence(check, before)
                result = self.execute(check["command"], check.get("cwd", "."),
                                      min(check.get("timeout_seconds", 300), self.control()["check_timeout_seconds"], self.remaining()),
                                      check["min_tests"], uuid.uuid4().hex)
                if inputs != self.evidence(check, before):
                    result.update(status="ERROR", reason="Evidence changed during validation")
                result["evidence"] = inputs
            except (OSError, ValueError, KeyError, TypeError) as error:
                result = {"status": "UNVERIFIED", "reason": str(error)}
            result["sources"] = before
            results[identity] = result
        if before != self.sources(manifest):
            for result in results.values():
                result.update(status="ERROR", reason="Sources changed during validation")
        for identity, result in results.items():
            if result["status"] == "PASS":
                try:
                    if result.get("evidence", {}) != self.evidence(checks[identity], before):
                        result.update(status="UNVERIFIED", reason="Evidence changed before completion")
                except (OSError, ValueError, KeyError, TypeError) as error:
                    result.update(status="UNVERIFIED", reason=str(error))
        self.integrity(manifest)
        self.state.setdefault("results", {}).update(results)
        within_budget = self.remaining() > 0
        passed = bool(before) and within_budget and all(result["status"] == "PASS" for result in results.values())
        report = {"run_id": self.state["run"]["id"], "loop": self.state["active_loop"],
                  "final": final, "status": "PASS" if final and passed else "INCOMPLETE",
                  "results": results, "created_at": time.time()}
        if final:
            report["requirements"] = {
                item["id"]: "PASS" if all(results[identity]["status"] == "PASS" for identity in item["checks"])
                else "INCOMPLETE" for item in manifest["requirements"]
            }
            if not before:
                report["reason"] = "No project artifact matched the approved source patterns"
            elif not within_budget:
                report["reason"] = "Run deadline reached"
        write(self.folder / "results" / f"{uuid.uuid4().hex}.json", report)
        write(self.folder / "LATEST.json", report)
        if final and passed:
            self.state.update(status="complete", phase="report", blocked_on=None)
        self.save()
        return report

    def fresh_passes(self, manifest, sources=None):
        if sources is None:
            sources = self.sources(manifest)
        passed = set()
        checks = {check["id"]: check for check in manifest["checks"]}
        for identity, result in self.state.get("results", {}).items():
            if identity not in checks or result.get("status") != "PASS" or result.get("sources") != sources:
                continue
            try:
                if result.get("evidence", {}) == self.evidence(checks[identity], sources):
                    passed.add(identity)
            except (OSError, ValueError, KeyError, TypeError):
                pass
        return passed

    def completed_tasks(self, manifest):
        passed = self.fresh_passes(manifest)
        return {task["id"] for task in manifest["tasks"] if set(task["checks"]).issubset(passed)}

    def record(self, usage=None):
        if self.state.get("active_loop") is None:
            raise ValueError("No active loop to record")
        manifest = self.manifest()
        self.integrity(manifest)
        if "environment" in manifest and not (self.state.get("preparation") or {}).get("calibrated"):
            raise ValueError("Calibrate before recording implementation work")
        control = self.control()
        run = self.state["run"]
        source_hashes = self.sources(manifest)
        passed = self.fresh_passes(manifest, source_hashes)
        progress = bool(passed - set(run["best_passed"]))
        run["best_passed"] = sorted(set(run["best_passed"]) | passed)
        for check in manifest["checks"]:
            result = self.state.get("results", {}).get(check["id"], {})
            if result.get("sources") != source_hashes:
                continue
            for name, direction in check.get("metrics", {}).items():
                value = result.get("metrics", {}).get(name)
                if value is None:
                    continue
                number(value, name, -sys.float_info.max)
                key = f"{check['id']}.{name}"
                old = run["best_metrics"].get(key)
                improved = old is None or (value < old if direction == "min" else value > old)
                if improved:
                    run["best_metrics"][key] = value
                    progress = True
        entry = {"loop": self.state["active_loop"], "tasks": self.state["current_task"],
                 "phase": self.state["phase"], "passed": sorted(passed), "progress": progress,
                 "seconds": time.time() - self.state["active_started_at"], "tokens": None}
        if usage:
            text(usage.get("source"), "usage source")
            entry["tokens"] = sum(number(usage.get(key), key) for key in ("input_tokens", "output_tokens"))
            entry["usage"] = usage
        measure = "tokens" if entry["tokens"] is not None else "seconds"
        previous = [item[measure] for item in run["history"] if item.get(measure) is not None][-3:]
        high = len(previous) == 3 and entry[measure] > statistics.median(previous) * control["consumption_ratio"]
        run["no_progress"] = 0 if progress else run["no_progress"] + 1
        run["high_streak"] = run["high_streak"] + 1 if high and not progress else 0
        entry.update(high_consumption=high, consumption_measure=measure)
        run["history"].append(entry)
        timed_out = self.state["status"] != "complete" and not self.remaining(save_timeout=False)
        if self.state["status"] not in ("complete", "blocked", "paused", "timed_out") and not timed_out:
            if run["high_streak"] >= control["high_consumption_streak"]:
                self.state.update(status="blocked", blocked_on="Repeated high consumption without progress")
            elif run["replanned"] and run["no_progress"] >= control["after_replan_limit"]:
                self.state.update(status="blocked", blocked_on="No progress after approach change")
            elif run["no_progress"] >= control["no_progress_limit"]:
                self.state.update(status="replan_required", blocked_on="Record one concrete approach change")
        if high or self.state["status"] == "replan_required" or len(run["history"]) % control["monitor_every"] == 0:
            recent = [{key: item[key] for key in ("loop", "seconds", "tokens", "progress", "high_consumption")
                       if key in item} for item in run["history"][-3:]]
            write(self.folder / "MONITOR_REQUEST.json", {"run_id": run["id"], "loop": entry["loop"],
                  "state": self.state["status"], "recent": recent,
                  "reason": self.state.get("blocked_on"), "allowed": ["continue", "replan", "stop"],
                  "latest_evidence": "LATEST.json" if (self.folder / "LATEST.json").exists() else None,
                  "input_token_limit": 2000, "output_token_limit": 300})
        # The completed-loop record is the recovery journal if saving STATE is interrupted.
        self.state.update(last_completed_loop=entry["loop"], active_loop=None, current_task=[], phase="report")
        write(self.folder / "loops" / f"{entry['loop']:02d}.json", {"entry": entry, "state_after": self.state})
        self.save()
        return entry

    def recover(self):
        active = self.state.get("active_loop")
        if active is not None:
            path = self.folder / "loops" / f"{active:02d}.json"
            if path.exists():
                journal = load(path)
                if journal["state_after"].get("run", {}).get("id") != self.state.get("run", {}).get("id"):
                    raise ValueError("Loop journal belongs to a different run")
                self.state = journal["state_after"]
        self.state["recovery_required"] = False
        self.save()

    def migrate(self):
        if not (self.folder / "CONTROL.json").exists():
            write(self.folder / "CONTROL.json", CONTROL)
        if self.state.get("schema_version") == 2:
            return
        backup = self.folder / "STATE.v1.json"
        if not backup.exists():
            write(backup, self.state)
        interrupted = self.state.get("status") == "running"
        completed = self.state.get("loop", 0)
        self.state.update(schema_version=2, last_completed_loop=completed,
                          active_loop=completed + 1 if interrupted else None,
                          status="awaiting_approval", phase="review", run=None, results={},
                          recovery_required=interrupted)
        self.save()

    def summary(self):
        fields = ("status", "phase", "last_completed_loop", "active_loop", "current_task", "blocked_on", "recovery_required")
        summary = {key: self.state.get(key) for key in fields}
        run = self.state.get("run") or {}
        summary["run"] = {key: run.get(key) for key in ("id", "deadline", "no_progress", "high_streak")}
        summary["checks"] = {key: value["status"] for key, value in self.state.get("results", {}).items()}
        if preparation := self.state.get("preparation"):
            summary["preparation"] = {"calibrated": preparation["calibrated"],
                                      "attempts": preparation["attempts"],
                                      "steps": {key: value["status"] for key, value in preparation["steps"].items()}}
        return summary

    def refresh_status(self):
        if self.state.get("run") and (self.state["status"] in ("running", "preparing")
                                        or (self.state["status"] == "ready" and self.state["phase"] == "calibration")):
            self.remaining()
            self.save()
        elif self.state["status"] == "complete":
            try:
                manifest = self.manifest()
                approved = load(self.folder / "BASELINE.json")["files"]
                if approved != self.sealed(manifest):
                    raise ValueError("Approved specification or checker changed")
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.state.update(status="awaiting_approval", phase="review", results={}, blocked_on=str(error))
                self.save()
                return
            if self.fresh_passes(manifest) != {check["id"] for check in manifest["checks"]}:
                self.state.update(status="ready", phase="verify", results={},
                                  blocked_on="Sources or evidence changed; repeat final validation")
                self.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harness", type=Path, default=Path(__file__).resolve().parent)
    commands = parser.add_subparsers(dest="action", required=True)
    for name in ("approve", "calibrate", "start", "status", "recover", "migrate"):
        commands.add_parser(name)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("step")
    begin = commands.add_parser("begin")
    begin.add_argument("--tasks", nargs="+", required=True)
    begin.add_argument("--phase", choices=["environment", "implement"], default="implement")
    check = commands.add_parser("check")
    check.add_argument("--ids", nargs="+")
    check.add_argument("--final", action="store_true")
    activity = commands.add_parser("exec")
    activity.add_argument("--cwd", default=".")
    activity.add_argument("--timeout-seconds", type=float, default=300)
    activity.add_argument("arguments", nargs=argparse.REMAINDER)
    record = commands.add_parser("record")
    record.add_argument("--usage", type=Path)
    for name in ("replan", "pause", "block"):
        item = commands.add_parser(name)
        item.add_argument("--reason", required=True)
    monitor = commands.add_parser("monitor")
    monitor.add_argument("--decision", choices=["continue", "replan", "stop"], required=True)
    monitor.add_argument("--reason", required=True)
    monitor.add_argument("--loop", type=int, required=True)
    args = parser.parse_args()
    try:
        with lock(args.harness.resolve()):
            harness = Harness(args.harness)
            output = None
            if args.action in ("approve", "calibrate", "start", "recover", "migrate"):
                getattr(harness, args.action)()
            elif args.action == "prepare":
                output = harness.prepare(args.step)
            elif args.action == "begin":
                harness.begin(args.tasks, args.phase)
            elif args.action == "check":
                output = harness.check(args.ids, args.final)
                output["results"] = {identity: {key: result[key] for key in ("status", "reason", "stdout", "stderr", "metrics")
                                                if key in result} for identity, result in output["results"].items()}
            elif args.action == "exec":
                arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
                output = harness.activity(arguments, args.cwd, args.timeout_seconds)
            elif args.action == "record":
                output = harness.record(load(args.usage) if args.usage else None)
            elif args.action == "status":
                harness.refresh_status()
            elif args.action == "replan":
                if harness.state["status"] not in ("running", "replan_required") or harness.state["run"]["replanned"]:
                    raise ValueError("One automatic approach change is allowed per run")
                harness.state["run"].update(replanned=True, no_progress=0, approach=args.reason)
                harness.state.update(status="running", blocked_on=None)
                harness.save()
            elif args.action == "monitor":
                request = load(harness.folder / "MONITOR_REQUEST.json")
                if request["loop"] != args.loop or request["run_id"] != harness.state["run"]["id"] or args.loop != harness.state["last_completed_loop"]:
                    raise ValueError("Stale monitor response")
                write(harness.folder / "MONITOR_RESPONSE.json", {"loop": args.loop, "decision": args.decision, "reason": args.reason})
                if harness.state["status"] == "running" and args.decision != "continue":
                    stop = args.decision == "stop" or harness.state["run"]["replanned"]
                    harness.state.update(status="blocked" if stop else "replan_required", blocked_on=args.reason)
                    harness.save()
            else:
                harness.state.update(status="paused" if args.action == "pause" else "blocked", blocked_on=args.reason)
                harness.save()
            print(json.dumps(output if output is not None else harness.summary(), ensure_ascii=True))
            if output and output.get("final") and output["status"] != "PASS":
                return 1
            if args.action in ("exec", "prepare") and output["status"] != "OK":
                return 1
            return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "ERROR", "reason": str(error)}, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
