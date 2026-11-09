import base64
import copy
import unittest
from urllib.error import HTTPError

from sync_portfolio import (SOURCE, TARGET, BEGIN, END, WORKFLOW, GitHub,
                            project_directory, replace_directory, require_success, synchronize,
                            BRANCH, BOT, PROFILE_WORKFLOW)

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
    """Model branch, PR and CI state without network or credential access."""
    def __init__(self):
        self.profile = PROFILE
        self.proposed = None
        self.runs = [good_run()]
        self.source_heads = [SHA, SHA]
        self.source_sha = SHA
        self.main_sha = "b" * 40
        self.head_sha = "c" * 40
        self.merge_sha = "d" * 40
        self.writes = []
        self.private = False
        self.conflict = False
        self.branch = None
        self.pr = None
        self.closed = []
        self.profile_runs = []
        self.changed_files = [{"filename": "README.md", "status": "modified"}]
        self.merge_state = "clean"
        self.merge_result = True

    def __call__(self, path, payload=None, method=None):
        """Apply allowed fake API transitions and retain a complete write ledger."""
        method = method or ("PUT" if payload is not None else "GET")
        prefix = f"/repos/{TARGET}"
        if payload is not None:
            if self.conflict and path.endswith("/contents/README.md"):
                raise HTTPError("https://api.github.com/", 409, "Conflict", {}, None)
            self.writes.append({"path": path, "method": method, **copy.deepcopy(payload)})
            if path.endswith("/git/refs") or "/git/refs/heads/" in path:
                self.branch = payload["sha"]
                return {}
            if path.endswith("/contents/README.md"):
                if payload["branch"] != BRANCH or payload["sha"] != "old-blob":
                    raise AssertionError("Unsafe README write")
                self.proposed = base64.b64decode(payload["content"]).decode()
                self.branch = self.head_sha
                return {"commit": {"sha": self.head_sha}}
            if path.endswith("/pulls"):
                self.pr = {"number": 1, "state": "open", "draft": False,
                           "user": {"login": BOT}, "body": payload["body"],
                           "head": {"sha": self.head_sha, "ref": BRANCH,
                                    "repo": {"full_name": TARGET}},
                           "base": {"ref": "main", "sha": self.main_sha},
                           "mergeable": True, "mergeable_state": self.merge_state}
                return copy.deepcopy(self.pr)
            if path.endswith("/dispatches"):
                return {}
            if path.endswith("/merge"):
                if self.merge_result:
                    self.profile = self.proposed
                    self.main_sha = self.merge_sha
                    self.pr["merged_at"] = "2026-11-09T00:00:00Z"
                    self.closed.append(copy.deepcopy(self.pr))
                    self.pr = None
                return {"merged": self.merge_result, "sha": self.merge_sha}
            raise AssertionError(path)
        if path in (f"/repos/{SOURCE}", prefix):
            return {"private": self.private, "default_branch": "main"}
        if path == f"/repos/{SOURCE}/branches/main":
            return {"commit": {"sha": self.source_heads.pop(0) if self.source_heads else self.source_sha}}
        if path == prefix + "/branches/main":
            return {"commit": {"sha": self.main_sha}}
        if "/actions/workflows/portfolio-ci.yml/runs?" in path:
            return {"workflow_runs": self.runs}
        if "/actions/workflows/profile-ci.yml/runs?" in path:
            return {"workflow_runs": self.profile_runs}
        if path.startswith(f"/repos/{SOURCE}/contents/"):
            return file_data(SOURCE_TEXT)
        if path.startswith(prefix + "/contents/"):
            ref = path.rsplit("=", 1)[1]
            return file_data(self.proposed if ref == self.head_sha else self.profile)
        if path == prefix + "/git/ref/heads/" + BRANCH:
            if self.branch is None:
                raise HTTPError("https://api.github.com/", 404, "Not found", {}, None)
            return {"object": {"sha": self.branch}}
        if "/pulls?state=open" in path:
            return [copy.deepcopy(self.pr)] if self.pr else []
        if "/pulls?state=closed" in path:
            return copy.deepcopy(self.closed)
        if path.endswith("/pulls/1/files?per_page=100"):
            return copy.deepcopy(self.changed_files)
        if path.endswith("/pulls/1"):
            pr = copy.deepcopy(self.pr)
            pr["mergeable_state"] = self.merge_state
            return pr
        raise AssertionError(path)

    def passed_profile_ci(self):
        """Publish native PR evidence for the exact proposed commit and base."""
        self.profile_runs = [{"head_sha": self.head_sha, "head_branch": BRANCH,
                              "path": PROFILE_WORKFLOW, "event": "pull_request",
                              "head_repository": {"full_name": TARGET},
                              "pull_requests": [{"number": 1,
                                                 "head": {"sha": self.head_sha},
                                                 "base": {"sha": self.main_sha}}],
                              "run_number": 1, "run_attempt": 1,
                              "status": "completed", "conclusion": "success"}]


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
        """A checked PR merges once; repeated polling never rewrites main."""
        api = FakeAPI()
        self.assertEqual(synchronize(api, True)["status"], "PR_OPENED")
        self.assertEqual(api.profile, PROFILE)
        api.passed_profile_ci()
        self.assertEqual(synchronize(api, True)["status"], "MERGED")
        count = len(api.writes)
        self.assertEqual(synchronize(api, True)["status"], "UNCHANGED")
        self.assertEqual(len(api.writes), count)
        readme_writes = [w for w in api.writes if w["path"].endswith("/contents/README.md")]
        self.assertEqual(len(readme_writes), 1)
        self.assertEqual(readme_writes[0]["branch"], BRANCH)
        self.assertFalse(any(w.get("branch") == "main" for w in api.writes))
        self.assertEqual(api.writes[-1]["ref"], "main")

    def test_dry_run_does_not_write(self):
        api = FakeAPI()
        self.assertEqual(synchronize(api)["status"], "WOULD_PROPOSE")
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
        self.assertFalse(any(w["path"].endswith("/contents/README.md") for w in api.writes))

    def test_write_scope_and_external_hosts_refused_before_network(self):
        api = GitHub("synthetic-not-a-real-token")
        for path, payload in (("https://evil.example", None),
                              (f"/repos/{SOURCE}/contents/README.md", {}),
                              (f"/repos/{TARGET}/contents/other.md", {})):
            with self.subTest(path=path), self.assertRaises(ValueError):
                api(path, payload)

    def test_pending_profile_ci_cannot_merge(self):
        """A pending result never changes the published profile."""
        api = FakeAPI()
        synchronize(api, True)
        api.passed_profile_ci()
        api.profile_runs[0].update(status="in_progress", conclusion=None)
        self.assertEqual(synchronize(api, True)["status"], "WAITING_FOR_CHECKS")
        self.assertEqual(api.profile, PROFILE)

    def test_dispatch_cannot_authorize_managed_pr_merge(self):
        """A green branch dispatch cannot substitute for native PR checks."""
        api = FakeAPI()
        synchronize(api, True)
        api.passed_profile_ci()
        api.profile_runs[0]["event"] = "workflow_dispatch"
        count = len(api.writes)
        self.assertEqual(synchronize(api, True)["status"], "WAITING_FOR_NATIVE_PR_CHECKS")
        self.assertEqual(api.profile, PROFILE)
        self.assertEqual(len(api.writes), count)

    def test_native_ci_must_belong_to_current_pr_head_and_base(self):
        """Unrelated or stale run associations cannot authorize a merge."""
        mutations = [
            lambda run: run.update(pull_requests=[]),
            lambda run: run["pull_requests"][0].update(number=2),
            lambda run: run["pull_requests"][0]["head"].update(sha="e" * 40),
            lambda run: run["pull_requests"][0]["base"].update(sha="e" * 40),
            lambda run: run["head_repository"].update(full_name="other/repo"),
        ]
        for mutate in mutations:
            api = FakeAPI()
            synchronize(api, True)
            api.passed_profile_ci()
            mutate(api.profile_runs[0])
            count = len(api.writes)
            with self.subTest(mutate=mutate):
                self.assertEqual(synchronize(api, True)["status"], "WAITING_FOR_NATIVE_PR_CHECKS")
            self.assertEqual(api.profile, PROFILE)
            self.assertEqual(len(api.writes), count)

    def test_approval_is_left_to_the_native_maintainer_control(self):
        """Approval-required CI waits without dispatching or approving itself."""
        api = FakeAPI()
        synchronize(api, True)
        count = len(api.writes)
        self.assertEqual(synchronize(api, True)["status"], "WAITING_FOR_NATIVE_PR_CHECKS")
        api.passed_profile_ci()
        api.profile_runs[0].update(status="completed", conclusion="action_required")
        self.assertEqual(synchronize(api, True)["status"], "WAITING_FOR_CHECK_APPROVAL")
        self.assertEqual(len(api.writes), count)
        self.assertEqual(api.profile, PROFILE)

    def test_failed_latest_profile_attempt_blocks_old_success(self):
        """A failed rerun cannot borrow an earlier passing result."""
        api = FakeAPI()
        synchronize(api, True)
        api.passed_profile_ci()
        bad = copy.deepcopy(api.profile_runs[0])
        bad.update(run_attempt=2, conclusion="failure")
        api.profile_runs.append(bad)
        with self.assertRaises(ValueError):
            synchronize(api, True)
        self.assertEqual(api.profile, PROFILE)

    def test_unknown_branch_is_preserved(self):
        """An existing branch without an owned merge receipt is not overwritten."""
        api = FakeAPI()
        api.branch = "e" * 40
        with self.assertRaises(ValueError):
            synchronize(api, True)
        self.assertEqual(api.writes, [])

    def test_changed_pr_identity_scope_or_content_cannot_merge(self):
        """Even green checks cannot authorize foreign, stale or expanded changes."""
        mutations = [
            lambda api: api.pr["user"].update(login="someone-else"),
            lambda api: api.pr["head"]["repo"].update(full_name="other/repo"),
            lambda api: api.pr.update(body="unmanaged"),
            lambda api: api.pr["base"].update(sha="e" * 40),
            lambda api: api.changed_files.append({"filename": "other.py", "status": "added"}),
            lambda api: setattr(api, "proposed", api.proposed + "unexpected"),
        ]
        for mutate in mutations:
            api = FakeAPI()
            synchronize(api, True)
            api.passed_profile_ci()
            mutate(api)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                synchronize(api, True)
            self.assertEqual(api.profile, PROFILE)
            self.assertFalse(any(w["path"].endswith("/merge") for w in api.writes))

    def test_native_merge_requirements_remain_authoritative(self):
        """Blocked reviews, conflicts or native rules are never bypassed."""
        api = FakeAPI()
        synchronize(api, True)
        api.passed_profile_ci()
        api.merge_state = "blocked"
        self.assertEqual(synchronize(api, True)["status"], "WAITING_FOR_MERGE_REQUIREMENTS")
        self.assertEqual(api.profile, PROFILE)

    def test_unconfirmed_merge_stops_without_postmerge_dispatch(self):
        """An uncertain merge response is preserved for inspection, not retried."""
        api = FakeAPI()
        synchronize(api, True)
        api.passed_profile_ci()
        api.merge_result = False
        with self.assertRaises(ValueError):
            synchronize(api, True)
        self.assertEqual(api.profile, PROFILE)
        self.assertEqual(api.writes[-1]["method"], "PUT")

    def test_no_main_or_force_write_can_reach_network(self):
        """The transport independently rejects bypasses of the managed PR route."""
        api = GitHub("synthetic-not-a-real-token")
        cases = [
            (f"/repos/{TARGET}/contents/README.md", {"branch": "main"}, "PUT"),
            (f"/repos/{TARGET}/git/refs/heads/main", {"sha": SHA, "force": False}, "PATCH"),
            (f"/repos/{TARGET}/git/refs/heads/{BRANCH}", {"sha": SHA, "force": True}, "PATCH"),
            (f"/repos/{TARGET}/pulls", {"head": "unknown", "base": "main"}, "POST"),
            (f"/repos/{SOURCE}/pulls/1/merge", {"sha": SHA, "merge_method": "merge"}, "PUT"),
            (f"/repos/{TARGET}/actions/workflows/profile-ci.yml/dispatches", {"ref": BRANCH}, "POST"),
            (f"/repos/{TARGET}/actions/runs/1/approve", {}, "POST"),
        ]
        for path, payload, method in cases:
            with self.subTest(path=path), self.assertRaises(ValueError):
                api(path, payload, method)


if __name__ == "__main__":
    unittest.main()

