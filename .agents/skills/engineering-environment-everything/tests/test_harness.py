"""Behavioral regressions for evidence, bounded execution and crash recovery."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
import init_harness
import runtime


ADAPTER = '''import json, sys, time
from pathlib import Path
mode = sys.argv[1]
if mode == "fixture":
    value = sys.argv[2]
elif mode == "sleep":
    time.sleep(2)
    value = "good"
else:
    value = Path(sys.argv[2]).read_text().strip()
passed = value == "good"
print(json.dumps({"status": "PASS" if passed else "FAIL", "tests_run": 1,
                  "passed": int(passed), "failed": int(not passed), "skipped": 0}))
sys.exit(0 if passed else 1)
'''


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="eee-test-")
        self.root = Path(self.temp.name)
        self.old_cwd = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(os.chdir, self.old_cwd)
        self.folder = self.root / "harness"
        self.source = self.root / "product.txt"
        self.source.write_text("good", encoding="utf-8")
        self.profile = self.root / "profile.md"
        self.profile.write_text("# PROFILE\n\n" + "\n\n".join(
            f"## {index}. Axis\n\nActual task axis {index}." for index in range(1, 12)), encoding="utf-8")
        self.check = {"criterion": "Product contains the expected result", "work": "Implement product",
                      "verify": "Run behavioral adapter", "pass_when": "One assertion passes", "requires": [],
                      "executable": {"command": ["{python}", "harness/checks/check.py", "file", "product.txt"],
                                     "checker_files": ["harness/checks/check.py"],
                                     "self_tests": [
                                         {"command": ["{python}", "harness/checks/check.py", "fixture", "good"], "expected": "PASS"},
                                         {"command": ["{python}", "harness/checks/check.py", "fixture", "bad"], "expected": "FAIL"}]}}
        self.intake = {"what": "Produce a verified artifact", "skeleton": self.check,
                       "done_when": [self.check], "sources": ["product.txt"],
                       "research": "Verified local input contract.", "plan": "Prepare then implement and check.",
                       "constraints": [{"description": "No fabricated output", "checks": ["V02"]}]}
        self.files = init_harness.render_harness(init_harness.parse_profile(self.profile.read_text()), self.intake, {})

    def build(self, approve=True):
        init_harness.create_harness(self.profile, self.profile.read_bytes(), self.files)
        (self.folder / "checks/check.py").write_text(ADAPTER, encoding="utf-8")
        harness = runtime.Harness(self.folder)
        if approve:
            harness.approve()
            harness.start()
            harness.begin(["T01"], "environment")
        return harness

    def evidence(self, harness, age=0, value="good"):
        artifact = self.folder / "evidence/measurement.txt"
        artifact.write_text(value, encoding="utf-8")
        metadata_path = self.folder / "evidence/measurement.json"
        metadata = {"artifact_sha256": runtime.digest(artifact), "sources": harness.sources(harness.manifest()),
                    "collected_at": datetime.fromtimestamp(time.time() - age, timezone.utc).isoformat(),
                    "producer": "test device", "target": "board A", "settings": {"mode": "normal"}}
        runtime.write(metadata_path, metadata)
        return {"path": "harness/evidence/measurement.txt", "metadata": "harness/evidence/measurement.json",
                "max_age_seconds": 60, "producer": "test device", "target": "board A", "settings": {"mode": "normal"}}


class RuntimeTests(Fixture):
    def test_full_cli_handoff_in_generated_folder(self):
        self.build(approve=False)
        for arguments in (["approve"], ["start"], ["begin", "--tasks", "T01"], ["check", "--final"], ["record"]):
            result = subprocess.run([sys.executable, "-B", "harness/runtime.py", *arguments],
                                    capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
        state = runtime.load(self.folder / "STATE.json")
        self.assertEqual(state["status"], "complete")
        self.assertEqual(state["last_completed_loop"], 1)
        self.assertIsNone(state["active_loop"])

    def test_failure_then_improvement_and_final_pass(self):
        harness = self.build()
        self.source.write_text("bad")
        self.assertEqual(harness.check(final=True)["status"], "INCOMPLETE")
        harness.record()
        harness.begin(["T01"], "implement")
        self.source.write_text("good")
        self.assertEqual(harness.check(final=True)["status"], "PASS")

    def test_missing_required_constraint_mapping_rejected(self):
        harness = self.build(False)
        manifest = runtime.load(self.folder / "CHECKS.json")
        manifest["requirements"][-1]["checks"] = []
        runtime.write(self.folder / "CHECKS.json", manifest)
        with self.assertRaisesRegex(ValueError, "missing or unknown"):
            harness.approve()

    def test_constant_success_checker_rejected(self):
        harness = self.build(False)
        (self.folder / "checks/check.py").write_text(ADAPTER.replace('passed = value == "good"', 'passed = True'))
        with self.assertRaisesRegex(ValueError, "Calibration failed"):
            harness.approve()

    def test_failed_reapproval_clears_prior_completion(self):
        harness = self.build()
        self.assertEqual(harness.check(final=True)["status"], "PASS")
        harness.record()
        checker = self.folder / "checks/check.py"
        checker.write_text(ADAPTER.replace('passed = value == "good"', 'passed = True'))
        with self.assertRaisesRegex(ValueError, "Calibration failed"):
            harness.approve()
        state = runtime.Harness(self.folder).state
        self.assertEqual(state["status"], "awaiting_approval")
        self.assertEqual(state["results"], {})
        with self.assertRaisesRegex(ValueError, "approval"):
            harness.start()
        self.assertEqual(runtime.load(self.folder / "LATEST.json")["status"], "PASS")

    def test_status_revalidates_completed_sources_and_baseline(self):
        harness = self.build()
        self.assertEqual(harness.check(final=True)["status"], "PASS")
        harness.record()
        harness.refresh_status()
        self.assertEqual(harness.state["status"], "complete")
        self.source.write_text("bad")
        harness.refresh_status()
        self.assertEqual(harness.state["status"], "ready")
        self.assertEqual(harness.state["results"], {})

    def test_zero_skip_invalid_counts_and_exit_status(self):
        for total, passed, failed, skipped, code, expected in [
            (0, 0, 0, 0, 0, "UNVERIFIED"), (1, 0, 0, 1, 0, "UNVERIFIED"),
            (1, 1, 0, 0, 2, "ERROR"), (1, 0, 1, 0, 0, "FAIL")]:
            payload = json.dumps(dict(status="PASS", tests_run=total, passed=passed, failed=failed, skipped=skipped))
            self.assertEqual(runtime.parse_result(payload, code, 1)["status"], expected)
        with self.assertRaises(ValueError):
            runtime.parse_result('{"status":"PASS","tests_run":1,"passed":2,"failed":0,"skipped":0}', 0, 1)

    def test_checker_and_spec_changes_invalidate_approval(self):
        harness = self.build()
        (self.folder / "CONSTRAINTS.md").write_text("Weakened constraint")
        with self.assertRaisesRegex(ValueError, "changed"):
            harness.check(final=True)
        self.assertEqual(harness.state["status"], "blocked")

    def test_spec_completion_marks_do_not_invalidate_approval(self):
        harness = self.build()
        spec = self.folder / "SPEC.md"
        spec.write_text(spec.read_text(encoding="utf-8").replace("- [ ]", "- [x]"), encoding="utf-8")
        self.assertEqual(harness.check(final=True)["status"], "PASS")

    def test_missing_sources_never_complete(self):
        harness = self.build()
        self.source.unlink()
        self.assertEqual(harness.check(final=True)["status"], "INCOMPLETE")

    def test_external_evidence_staleness_and_tampering(self):
        harness = self.build(False)
        manifest = runtime.load(self.folder / "CHECKS.json")
        manifest["checks"][0]["evidence"] = [self.evidence(harness)]
        manifest["checks"][0]["command"][-1] = "harness/evidence/measurement.txt"
        runtime.write(self.folder / "CHECKS.json", manifest)
        harness.approve()
        harness.start()
        harness.begin(["T01"], "environment")
        self.evidence(harness, age=120)
        self.assertEqual(harness.check(final=True)["status"], "INCOMPLETE")
        self.evidence(harness)
        (self.folder / "evidence/measurement.txt").write_text("bad")
        self.assertEqual(harness.check(final=True)["status"], "INCOMPLETE")
        self.evidence(harness, value="bad")
        result = harness.check(final=True)
        self.assertEqual(result["results"]["V01"]["status"], "FAIL")
        self.evidence(harness)
        self.assertEqual(harness.check(final=True)["status"], "PASS")

    def test_later_checker_cannot_invalidate_earlier_evidence_and_still_pass(self):
        harness = self.build(False)
        manifest = runtime.load(self.folder / "CHECKS.json")
        manifest["checks"][0]["evidence"] = [self.evidence(harness)]
        runtime.write(self.folder / "CHECKS.json", manifest)
        harness.approve()
        harness.start()
        harness.begin(["T01"], "environment")
        execute = harness.execute
        calls = []
        def change_evidence(*args):
            result = execute(*args)
            calls.append(True)
            if len(calls) == 2:
                (self.folder / "evidence/measurement.txt").write_text("bad")
            return result
        with patch.object(harness, "execute", change_evidence):
            self.assertEqual(harness.check(final=True)["status"], "INCOMPLETE")

    def test_timeout_and_explicit_resume_preserve_active_loop(self):
        harness = self.build()
        harness.state["run"]["started_at"] -= 3601
        self.assertEqual(harness.remaining(), 0)
        self.assertEqual(harness.state["status"], "timed_out")
        harness.start()
        self.assertEqual(harness.state["active_loop"], 1)
        self.assertGreater(harness.remaining(), 3500)
        with self.assertRaisesRegex(ValueError, "active"):
            harness.start()

    def test_configurable_time_and_command_timeout(self):
        harness = self.build()
        config = harness.control()
        config["timeout_minutes"] = 120
        runtime.write(self.folder / "CONTROL.json", config)
        self.assertGreater(harness.remaining(), 7100)
        result = harness.execute(["{python}", "harness/checks/check.py", "sleep"], ".", .05, 1, "timeout")
        self.assertEqual(result["status"], "ERROR")
        self.assertEqual(result["reason"], "Command timeout")

    def test_completed_verification_is_not_revoked_by_delayed_report(self):
        harness = self.build()
        self.assertEqual(harness.check(final=True)["status"], "PASS")
        harness.state["run"]["started_at"] -= 3601
        harness.record()
        self.assertEqual(harness.state["status"], "complete")

    def test_no_progress_requires_replan_then_stops(self):
        harness = self.build()
        self.source.write_text("bad")
        for index in range(3):
            if index:
                harness.begin(["T01"], "implement")
            harness.check()
            harness.record()
        self.assertEqual(harness.state["status"], "replan_required")
        harness.state["run"].update(replanned=True, no_progress=0)
        harness.state["status"] = "running"
        for _ in range(2):
            harness.begin(["T01"], "implement")
            harness.check()
            harness.record()
        self.assertEqual(harness.state["status"], "blocked")

    def test_high_actual_token_consumption_without_progress_stops(self):
        harness = self.build()
        self.source.write_text("bad")
        harness.state["run"]["history"] = [{"tokens": 10, "seconds": 1}] * 3
        for index in range(2):
            if index:
                harness.begin(["T01"], "implement")
            harness.check()
            harness.record({"source": "test host telemetry", "input_tokens": 25, "output_tokens": 5})
        self.assertEqual(harness.state["status"], "blocked")
        self.assertIn("high consumption", harness.state["blocked_on"])

    def test_completed_loop_journal_recovers_failed_state_write(self):
        harness = self.build()
        harness.check()
        write = runtime.write
        def fail_state(path, value):
            if path.name == "STATE.json":
                raise OSError("Injected state write failure")
            write(path, value)
        with patch.object(runtime, "write", fail_state):
            with self.assertRaises(OSError):
                harness.record()
        restarted = runtime.Harness(self.folder)
        self.assertEqual(restarted.state["active_loop"], 1)
        restarted.recover()
        self.assertEqual(restarted.state["last_completed_loop"], 1)
        self.assertIsNone(restarted.state["active_loop"])

    def test_timeout_journal_failure_does_not_double_count(self):
        harness = self.build()
        harness.state["run"]["started_at"] -= 3601
        harness.save()
        write = runtime.write
        def fail_journal(path, value):
            if path.parent.name == "loops":
                raise OSError("Injected journal write failure")
            write(path, value)
        with patch.object(runtime, "write", fail_journal):
            with self.assertRaises(OSError):
                harness.record()
        restarted = runtime.Harness(self.folder)
        self.assertEqual(restarted.state["run"]["history"], [])
        restarted.record()
        self.assertEqual(len(restarted.state["run"]["history"]), 1)
        self.assertEqual(restarted.state["status"], "timed_out")

    def test_approval_paths_are_portable(self):
        harness = self.build()
        baseline = runtime.load(self.folder / "BASELINE.json")
        self.assertIn("harness/SPEC.md", baseline["files"])
        self.assertTrue(all("\\" not in key for key in baseline["files"]))

    def test_environment_activity_is_bounded_and_cannot_report_pass(self):
        harness = self.build()
        self.assertEqual(harness.activity(["{python}", "-c", "print('ready')"], ".", 5)["status"], "OK")
        slow = harness.activity(["{python}", "-c", "import time; time.sleep(2)"], ".", .05)
        self.assertEqual(slow["status"], "ERROR")
        self.assertEqual(slow["reason"], "Command timeout")
        self.assertEqual(len(list((self.folder / "activities").glob("*.json"))), 2)
        self.assertEqual(harness.state["results"], {})

    def test_subset_rechecks_prerequisites_after_source_change(self):
        harness = self.build()
        harness.check(["V01"])
        harness.record()
        harness.begin(["T02"], "implement")
        self.source.write_text("good\n")
        result = harness.check(["V02"])
        self.assertEqual(set(result["results"]), {"V01", "V02"})
        self.assertEqual(harness.completed_tasks(harness.manifest()), {"T01", "T02"})

    def test_environment_attempt_limit_survives_replan(self):
        harness = self.build()
        self.source.write_text("bad")
        for attempt in range(3):
            if attempt:
                harness.begin(["T01"], "environment")
            harness.check(["V01"])
            harness.record()
        command = [sys.executable, "-B", "harness/runtime.py", "replan", "--reason", "Inspect runner setup"]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        harness = runtime.Harness(self.folder)
        with self.assertRaisesRegex(ValueError, "Environment attempt limit"):
            harness.begin(["T01"], "environment")
        self.assertEqual(harness.state["status"], "blocked")

    def test_legacy_running_state_requires_recovery(self):
        self.folder.mkdir()
        runtime.write(self.folder / "STATE.json", {"loop": 4, "status": "running", "current_task": ["T02"]})
        harness = runtime.Harness(self.folder)
        harness.migrate()
        self.assertTrue(harness.state["recovery_required"])
        self.assertEqual(harness.state["active_loop"], 5)
        self.assertEqual(runtime.load(self.folder / "STATE.v1.json")["loop"], 4)


class InitializationTests(Fixture):
    def test_interrupted_publication_resumes_without_overwriting(self):
        rename = Path.rename
        def fail(path, target):
            if Path(target).name == "CONSTRAINTS.md":
                raise OSError("Injected publication failure")
            return rename(path, target)
        with patch.object(Path, "rename", fail):
            with self.assertRaises(OSError):
                init_harness.create_harness(self.profile, self.profile.read_bytes(), self.files)
        self.assertTrue((self.folder / ".init-journal.json").exists())
        init_harness.create_harness(self.profile, self.profile.read_bytes(), self.files)
        self.assertFalse((self.folder / ".init-journal.json").exists())
        with self.assertRaises(init_harness.ExistingHarnessError):
            init_harness.create_harness(self.profile, self.profile.read_bytes(), self.files)

    def test_partial_journal_write_is_not_published(self):
        def fail(value, stream, **kwargs):
            stream.write("{")
            raise OSError("Injected journal failure")
        with patch.object(init_harness.json, "dump", fail):
            with self.assertRaises(OSError):
                init_harness.create_harness(self.profile, self.profile.read_bytes(), self.files)
        self.assertFalse((self.folder / ".init-journal.json").exists())
        init_harness.create_harness(self.profile, self.profile.read_bytes(), self.files)
        self.assertTrue((self.folder / "STATE.json").exists())

    def test_user_modified_partial_file_is_preserved(self):
        rename = Path.rename
        def fail(path, target):
            if Path(target).name == "CONSTRAINTS.md":
                raise OSError("Injected publication failure")
            return rename(path, target)
        with patch.object(Path, "rename", fail):
            with self.assertRaises(OSError):
                init_harness.create_harness(self.profile, self.profile.read_bytes(), self.files)
        (self.folder / "AGENT.md").write_text("User edit")
        with self.assertRaises(init_harness.ExistingHarnessError):
            init_harness.create_harness(self.profile, self.profile.read_bytes(), self.files)
        self.assertEqual((self.folder / "AGENT.md").read_text(), "User edit")


if __name__ == "__main__":
    unittest.main()
