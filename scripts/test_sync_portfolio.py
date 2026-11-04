import base64
import copy
import unittest
from urllib.error import HTTPError

from sync_portfolio import (SOURCE, TARGET, BEGIN, END, WORKFLOW, GitHub,
                            project_directory, replace_directory, require_success, synchronize)

SHA = "a" * 40
SOURCE_TEXT = "## Project directory\n\n| Capability | Project evidence |\n| --- | --- |\n| APIs | [API & Tests](<API & Tests/README.md>) |\n\n## Other\nprivate-looking text must not propagate\n"
PROFILE = "Personal biography unchanged\n" + BEGIN + "\nold\n" + END + "\nContact unchanged\n"


def file_data(text):
    return {"type": "file", "encoding": "base64", "sha": "old-blob",
            "content": base64.b64encode(text.encode()).decode()}


def good_run():
    return {"head_sha": SHA, "head_branch": "main", "path": WORKFLOW,
            "event": "push", "run_number": 10, "run_attempt": 1,
            "status": "completed", "conclusion": "success"}


class FakeAPI:
    def __init__(self):
        self.profile = PROFILE
        self.runs = [good_run()]
        self.source_heads = [SHA, SHA]
        self.writes = []
        self.private = False
        self.conflict = False

    def __call__(self, path, payload=None):
        if payload is not None:
            if self.conflict:
                raise HTTPError("https://api.github.com/", 409, "Conflict", {}, None)
            self.writes.append(copy.deepcopy(payload))
            self.profile = base64.b64decode(payload["content"]).decode()
            return {"commit": {"sha": "b" * 40}}
        if path in (f"/repos/{SOURCE}", f"/repos/{TARGET}"):
            return {"private": self.private, "default_branch": "main"}
        if path.endswith("/branches/main"):
            return {"commit": {"sha": self.source_heads.pop(0) if self.source_heads else SHA}}
        if "/actions/" in path:
            return {"workflow_runs": self.runs}
        if path.startswith(f"/repos/{SOURCE}/contents/"):
            return file_data(SOURCE_TEXT)
        if path.startswith(f"/repos/{TARGET}/contents/"):
            return file_data(self.profile)
        raise AssertionError(path)


class SyncTests(unittest.TestCase):
    def test_public_links_and_selected_section_only(self):
        rendered = project_directory(SOURCE_TEXT)
        self.assertIn("API%20%26%20Tests/README.md", rendered)
        self.assertNotIn("private-looking", rendered)

    def test_preserves_every_byte_outside_markers(self):
        rendered = replace_directory(PROFILE, project_directory(SOURCE_TEXT))
        self.assertEqual(rendered.split(BEGIN)[0], PROFILE.split(BEGIN)[0])
        self.assertEqual(rendered.split(END)[1], PROFILE.split(END)[1])

    def test_repeated_update_is_noop(self):
        api = FakeAPI()
        self.assertEqual(synchronize(api, True)["status"], "UPDATED")
        self.assertEqual(synchronize(api, True)["status"], "UNCHANGED")
        self.assertEqual(len(api.writes), 1)
        self.assertEqual(api.writes[0]["sha"], "old-blob")
        self.assertEqual(api.writes[0]["branch"], "main")

    def test_dry_run_does_not_write(self):
        api = FakeAPI()
        self.assertEqual(synchronize(api)["status"], "WOULD_UPDATE")
        self.assertEqual(api.writes, [])

    def test_bad_or_missing_markers_stop(self):
        for profile in ("none", BEGIN + END + END, END + BEGIN, BEGIN + BEGIN + END):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                replace_directory(profile, "new")

    def test_invalid_source_rejected(self):
        for source in ("", SOURCE_TEXT + SOURCE_TEXT,
                       SOURCE_TEXT.replace("API & Tests/README.md", "../secret/README.md"),
                       SOURCE_TEXT.replace("API & Tests/README.md", "https://evil/README.md"),
                       SOURCE_TEXT.replace("API & Tests/README.md", "C:\\secret/README.md"),
                       SOURCE_TEXT.replace("| APIs |", "| <script> |")):
            with self.subTest(source=source), self.assertRaises(ValueError):
                project_directory(source)

    def test_latest_failed_pending_or_cancelled_ci_blocks_older_success(self):
        for status, conclusion in (("completed", "failure"), ("in_progress", None),
                                   ("completed", "cancelled"), ("completed", "skipped")):
            api = FakeAPI()
            new = good_run()
            new.update(run_number=11, status=status, conclusion=conclusion)
            api.runs.append(new)
            with self.subTest(conclusion=conclusion), self.assertRaises(ValueError):
                synchronize(api, True)
            self.assertEqual(api.writes, [])

    def test_ci_must_match_commit_main_and_workflow(self):
        for key, value in (("head_sha", "c" * 40), ("head_branch", "other"),
                           ("path", "other.yml"), ("event", "pull_request")):
            run = good_run()
            run[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                require_success({"workflow_runs": [run]}, SHA)

    def test_failed_rerun_blocks_old_success(self):
        run = good_run()
        run.update(run_attempt=2, conclusion="failure")
        with self.assertRaises(ValueError):
            require_success({"workflow_runs": [good_run(), run]}, SHA)

    def test_source_movement_stops_without_write(self):
        api = FakeAPI()
        api.source_heads[1] = "c" * 40
        with self.assertRaises(ValueError):
            synchronize(api, True)
        self.assertEqual(api.writes, [])

    def test_private_repository_stops_cost_gate(self):
        api = FakeAPI()
        api.private = True
        with self.assertRaises(ValueError):
            synchronize(api, True)
        self.assertEqual(api.writes, [])

    def test_concurrent_edit_is_not_retried_or_overwritten(self):
        api = FakeAPI()
        api.conflict = True
        with self.assertRaises(HTTPError):
            synchronize(api, True)
        self.assertEqual(api.profile, PROFILE)
        self.assertEqual(api.writes, [])

    def test_write_scope_and_external_hosts_refused_before_network(self):
        api = GitHub("synthetic-not-a-real-token")
        for path, payload in (("https://evil.example", None),
                              (f"/repos/{SOURCE}/contents/README.md", {}),
                              (f"/repos/{TARGET}/contents/other.md", {})):
            with self.subTest(path=path), self.assertRaises(ValueError):
                api(path, payload)


if __name__ == "__main__":
    unittest.main()
