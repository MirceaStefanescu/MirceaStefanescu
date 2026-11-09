"""Refresh the managed profile directory through a verified pull request."""
import argparse
import base64
import json
import os
import re
import sys
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPRedirectHandler

SOURCE = "MirceaStefanescu/Portfolio"
TARGET = "MirceaStefanescu/MirceaStefanescu"
BEGIN = "<!-- PORTFOLIO_PROJECTS:BEGIN -->"
END = "<!-- PORTFOLIO_PROJECTS:END -->"
WORKFLOW = ".github/workflows/portfolio-ci.yml"
PROFILE_WORKFLOW = ".github/workflows/profile-ci.yml"
BRANCH = "automation/portfolio-sync"
BOT = "github-actions[bot]"
MARKER = "<!-- portfolio-profile-sync:v2 -->"


class NoRedirect(HTTPRedirectHandler):
    """Keep the built-in token on the GitHub API host."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Refuse redirects instead of forwarding authorization."""
        raise ValueError("Redirect refused")


class GitHub:
    """Read the two public repositories; write only the managed PR route."""
    def __init__(self, token):
        """Create a bounded client without persisted credentials."""
        self.token = token
        self.opener = build_opener(NoRedirect())

    def __call__(self, path, payload=None, method=None):
        """Enforce method, endpoint and branch allowlists before network access."""
        method = method or ("PUT" if payload is not None else "GET")
        prefix = f"/repos/{TARGET}"
        if path not in (f"/repos/{SOURCE}", prefix) and not path.startswith((f"/repos/{SOURCE}/", prefix + "/")):
            raise ValueError("Repository outside sync scope")
        if method != "GET":
            permitted = (
                method == "PUT" and path == prefix + "/contents/README.md"
                and payload.get("branch") == BRANCH
            ) or (
                method == "POST" and path == prefix + "/git/refs"
                and payload.get("ref") == "refs/heads/" + BRANCH
            ) or (
                method == "PATCH" and path == prefix + "/git/refs/heads/" + BRANCH
                and payload.get("force") is False
            ) or (
                method == "POST" and path == prefix + "/pulls"
                and payload.get("head") == BRANCH and payload.get("base") == "main"
            ) or (
                method == "PUT" and re.fullmatch(re.escape(prefix) + r"/pulls/[1-9][0-9]*/merge", path)
                and payload.get("merge_method") == "merge"
                and re.fullmatch("[0-9a-f]{40}", payload.get("sha", ""))
            ) or (
                method == "POST" and path == prefix + "/actions/workflows/profile-ci.yml/dispatches"
                and payload.get("ref") == "main"
            )
            if not permitted:
                raise ValueError("Write outside the managed PR route")
        headers = {"Accept": "application/vnd.github+json", "Content-Type": "application/json",
                   "User-Agent": "portfolio-profile-sync", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request("https://api.github.com" + path, headers=headers,
                          data=json.dumps(payload).encode() if payload is not None else None,
                          method=method)
        with self.opener.open(request, timeout=30) as response:
            data = response.read(8_000_001)
        if len(data) > 8_000_000:
            raise ValueError("API response exceeds sync limit")
        return json.loads(data) if data else {}


def decode_file(data):
    """Decode a bounded regular UTF-8 file returned by the Contents API."""
    if data.get("type") != "file" or data.get("encoding") != "base64":
        raise ValueError("Expected a regular base64 file")
    text = base64.b64decode(data["content"], validate=False).decode("utf-8")
    if len(text) > 200_000:
        raise ValueError("Document exceeds sync limit")
    return text


def project_directory(source):
    """Render only the validated project table with public Portfolio links."""
    sections = re.findall(r"^## Project directory\n(.*?)(?=^## |\Z)", source, re.M | re.S)
    if len(sections) != 1:
        raise ValueError("Expected one Portfolio project directory")
    rows = []
    paths = set()
    for line in sections[0].splitlines():
        if not line.startswith("|") or line in ("| Capability | Project evidence |", "| --- | --- |"):
            continue
        match = re.fullmatch(r"\| ([^|<>\[\]`]+) \| \[([^\[\]<>|`]+)\]\(<([^<>]+)>\) \|", line)
        if not match:
            raise ValueError("Unexpected project row format")
        capability, title, path = match.groups()
        if (not path.endswith("/README.md") or path.startswith("/") or
                any(p in ("", ".", "..") for p in path.split("/")) or
                any(c in path for c in "\\:#?\r\n") or path in paths):
            raise ValueError("Unsafe or duplicate project path")
        paths.add(path)
        url = f"https://github.com/{SOURCE}/blob/main/{quote(path, safe='/')}"
        rows.append(f"| {capability} | [{title}]({url}) |")
    if not 1 <= len(rows) <= 100:
        raise ValueError("Missing or excessive project directory")
    return "\n".join(["## Project directory", "",
                      f"Current projects from [Portfolio](https://github.com/{SOURCE}#project-directory).", "",
                      "| Capability | Project evidence |", "| --- | --- |", *rows])


def replace_directory(profile, directory):
    """Preserve every byte outside one correctly ordered managed block."""
    if profile.count(BEGIN) != 1 or profile.count(END) != 1:
        raise ValueError("Expected exactly one managed block")
    before, rest = profile.split(BEGIN)
    _, after = rest.split(END)
    if END in before or BEGIN in after:
        raise ValueError("Reversed managed markers")
    return before + BEGIN + "\n" + directory + "\n" + END + after


def latest_run(runs, sha, workflow=WORKFLOW, branch="main"):
    """Select the latest matching run and attempt, never an older green result."""
    eligible = [r for r in runs["workflow_runs"] if r.get("head_sha") == sha
                and r.get("head_branch") == branch and r.get("path") == workflow
                and r.get("event") in ("push", "workflow_dispatch")]
    return max(eligible, key=lambda r: (r["run_number"], r.get("run_attempt", 1))) if eligible else None


def require_success(runs, sha):
    """Require successful Portfolio main CI for the exact published revision."""
    latest = latest_run(runs, sha)
    if not latest or latest.get("status") != "completed" or latest.get("conclusion") != "success":
        raise ValueError("Latest Portfolio main CI has not succeeded for this commit")


def owned_pull(pr):
    """Recognize this automation's PR; preserve anything with uncertain ownership."""
    return (pr.get("user", {}).get("login") == BOT
            and (pr.get("body") or "").startswith(MARKER + "\n")
            and pr.get("head", {}).get("ref") == BRANCH
            and pr.get("head", {}).get("repo", {}).get("full_name") == TARGET
            and pr.get("base", {}).get("ref") == "main")


def main_head(api, repo):
    """Read and validate a complete commit identity."""
    sha = api(f"/repos/{repo}/branches/main")["commit"]["sha"]
    if not re.fullmatch("[0-9a-f]{40}", sha):
        raise ValueError("Invalid main revision")
    return sha


def dispatch_main(api):
    """Verify main after a bot merge; dispatch checks never authorize a PR."""
    api(f"/repos/{TARGET}/actions/workflows/profile-ci.yml/dispatches",
        {"ref": "main"}, method="POST")


def latest_pr_run(runs, pr):
    """Require native PR CI associated with this exact head, base and repository."""
    eligible = [r for r in runs["workflow_runs"]
                if r.get("event") == "pull_request"
                and r.get("path") == PROFILE_WORKFLOW
                and r.get("head_sha") == pr["head"]["sha"]
                and r.get("head_branch") == BRANCH
                and r.get("head_repository", {}).get("full_name") == TARGET
                and any(p.get("number") == pr["number"]
                        and p.get("head", {}).get("sha") == pr["head"]["sha"]
                        and p.get("base", {}).get("sha") == pr["base"]["sha"]
                        for p in r.get("pull_requests", []))]
    return max(eligible, key=lambda r: (r["run_number"], r.get("run_attempt", 1))) if eligible else None


def finish_pull(api, pr, source_sha, target_sha, expected):
    """Merge only a current, README-only, reviewed and successfully checked proposal."""
    if not owned_pull(pr):
        raise ValueError("Managed branch has a PR with uncertain ownership")
    number = pr["number"]
    pr = api(f"/repos/{TARGET}/pulls/{number}")
    if not owned_pull(pr) or pr.get("state") != "open" or pr.get("draft"):
        raise ValueError("Managed PR identity or state changed")
    head = pr["head"]["sha"]
    if not re.fullmatch("[0-9a-f]{40}", head):
        raise ValueError("Invalid PR revision")
    body = f"{MARKER}\nSource: {source_sha}\nBase: {target_sha}\n"
    if not (pr.get("body") or "").startswith(body) or pr["base"]["sha"] != target_sha:
        raise ValueError("Managed PR is stale; inspect it before another update")
    files = api(f"/repos/{TARGET}/pulls/{number}/files?per_page=100")
    if len(files) != 1 or files[0].get("filename") != "README.md" or files[0].get("status") != "modified":
        raise ValueError("Managed PR must change only the existing README")
    if decode_file(api(f"/repos/{TARGET}/contents/README.md?ref={head}")) != expected:
        raise ValueError("Managed PR content differs from the current source and profile")
    runs = api(f"/repos/{TARGET}/actions/workflows/profile-ci.yml/runs?head_sha={head}&per_page=100")
    latest = latest_pr_run(runs, pr)
    if not latest:
        return {"status": "WAITING_FOR_NATIVE_PR_CHECKS", "pull_request": number}
    if latest.get("conclusion") == "action_required" or latest.get("status") == "action_required":
        return {"status": "WAITING_FOR_CHECK_APPROVAL", "pull_request": number}
    if latest.get("status") != "completed":
        return {"status": "WAITING_FOR_CHECKS", "pull_request": number}
    if latest.get("conclusion") != "success":
        raise ValueError("Latest profile checks failed; inspect before retrying")
    if pr.get("mergeable") is not True or pr.get("mergeable_state") != "clean":
        return {"status": "WAITING_FOR_MERGE_REQUIREMENTS", "pull_request": number}
    if main_head(api, SOURCE) != source_sha or main_head(api, TARGET) != target_sha:
        raise ValueError("A main branch moved; no merge attempted")
    result = api(f"/repos/{TARGET}/pulls/{number}/merge",
                 {"sha": head, "merge_method": "merge"}, method="PUT")
    if result.get("merged") is not True:
        raise ValueError("Merge not confirmed; inspect before retrying")
    commit = result["sha"]
    if decode_file(api(f"/repos/{TARGET}/contents/README.md?ref={commit}")) != expected:
        raise ValueError("Merged content verification failed; inspect before retrying")
    receipt = {"status": "MERGED", "source_sha": source_sha, "profile_commit": commit,
               "pull_request": number}
    try:
        dispatch_main(api)
        receipt["main_ci_dispatch"] = "requested"
    except (HTTPError, OSError, ValueError) as error:
        # The merge and content readback already succeeded. Preserve that fact
        # without claiming main CI started or retrying an uncertain dispatch.
        receipt["main_ci_dispatch"] = "unconfirmed"
        receipt["dispatch_error"] = (f"HTTP {error.code}" if isinstance(error, HTTPError)
                                     else type(error).__name__)
    return receipt


def prepare_branch(api, target_sha):
    """Create the branch or fast-forward an exclusively owned, previously merged branch."""
    try:
        ref = api(f"/repos/{TARGET}/git/ref/heads/{BRANCH}")
    except HTTPError as error:
        if error.code != 404:
            raise
        api(f"/repos/{TARGET}/git/refs",
            {"ref": "refs/heads/" + BRANCH, "sha": target_sha}, method="POST")
        return
    previous = api(f"/repos/{TARGET}/pulls?state=closed&head=MirceaStefanescu:{BRANCH}&base=main&per_page=100")
    if not any(owned_pull(pr) and pr.get("merged_at") and pr["head"]["sha"] == ref["object"]["sha"]
               for pr in previous):
        raise ValueError("Existing branch is not a verified previously merged sync branch")
    api(f"/repos/{TARGET}/git/refs/heads/{BRANCH}",
        {"sha": target_sha, "force": False}, method="PATCH")


def synchronize(api, apply=False):
    """Plan, propose or normally merge a sync; never write directly to main."""
    for repo in (SOURCE, TARGET):
        info = api(f"/repos/{repo}")
        if info.get("private") is not False or info.get("default_branch") != "main":
            raise ValueError("Cost/scope gate: both repositories must be public and use main")
    source_sha = main_head(api, SOURCE)
    target_sha = main_head(api, TARGET)
    runs = api(f"/repos/{SOURCE}/actions/workflows/portfolio-ci.yml/runs?head_sha={source_sha}&branch=main&per_page=100")
    require_success(runs, source_sha)
    source = decode_file(api(f"/repos/{SOURCE}/contents/README.md?ref={source_sha}"))
    target = api(f"/repos/{TARGET}/contents/README.md?ref={target_sha}")
    old = decode_file(target)
    new = replace_directory(old, project_directory(source))
    if new == old:
        return {"status": "UNCHANGED", "source_sha": source_sha}
    if main_head(api, SOURCE) != source_sha or main_head(api, TARGET) != target_sha:
        raise ValueError("A main branch moved; no write attempted")
    if not apply:
        return {"status": "WOULD_PROPOSE", "source_sha": source_sha}
    pulls = api(f"/repos/{TARGET}/pulls?state=open&head=MirceaStefanescu:{BRANCH}&base=main&per_page=100")
    if len(pulls) > 1:
        raise ValueError("Multiple managed-branch PRs require inspection")
    if pulls:
        return finish_pull(api, pulls[0], source_sha, target_sha, new)
    prepare_branch(api, target_sha)
    result = api(f"/repos/{TARGET}/contents/README.md", {
        "message": f"docs: sync Portfolio project directory ({source_sha[:12]})",
        "content": base64.b64encode(new.encode()).decode(),
        "sha": target["sha"], "branch": BRANCH})
    head = result["commit"]["sha"]
    if decode_file(api(f"/repos/{TARGET}/contents/README.md?ref={head}")) != new:
        raise ValueError("Proposed content verification failed; inspect before retrying")
    pr = api(f"/repos/{TARGET}/pulls", {
        "title": "docs: sync verified Portfolio project directory",
        "head": BRANCH, "base": "main",
        "body": f"{MARKER}\nSource: {source_sha}\nBase: {target_sha}\n\n"
                "Updates only the managed project table after successful Portfolio main CI. "
                "Inspect the README-only diff, then use Approve workflows to run in this PR. "
                "Native PR checks and merge requirements must pass before the sync job can merge.",
        "maintainer_can_modify": False}, method="POST")
    return {"status": "PR_OPENED", "source_sha": source_sha, "profile_commit": head,
            "pull_request": pr["number"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Propose or merge through the checked PR route")
    args = parser.parse_args()
    try:
        if args.apply and not os.environ.get("GH_TOKEN"):
            raise ValueError("GH_TOKEN is required for apply")
        receipt = synchronize(GitHub(os.environ.get("GH_TOKEN")), args.apply)
        print(json.dumps(receipt))
        if receipt.get("dispatch_error"):
            sys.exit(1)
    except (ValueError, KeyError, HTTPError, OSError) as error:
        print(f"Sync stopped: {type(error).__name__}: " +
              (f"HTTP {error.code}" if isinstance(error, HTTPError) else
               str(error) if isinstance(error, ValueError) else "check network/API schema"), file=sys.stderr)
        sys.exit(1)

