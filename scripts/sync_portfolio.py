"""Refresh only the marked project directory from a successful Portfolio main build."""
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


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Redirect refused")


class GitHub:
    def __init__(self, token):
        self.token = token
        self.opener = build_opener(NoRedirect())

    def __call__(self, path, payload=None):
        if path not in (f"/repos/{SOURCE}", f"/repos/{TARGET}") and not path.startswith((f"/repos/{SOURCE}/", f"/repos/{TARGET}/")):
            raise ValueError("Repository outside sync scope")
        if payload is not None and path != f"/repos/{TARGET}/contents/README.md":
            raise ValueError("Only the profile README can be updated")
        headers = {"Accept": "application/vnd.github+json", "Content-Type": "application/json", "User-Agent": "portfolio-profile-sync",
                   "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request("https://api.github.com" + path, headers=headers,
                          data=json.dumps(payload).encode() if payload is not None else None,
                          method="PUT" if payload is not None else "GET")
        with self.opener.open(request, timeout=30) as response:
            data = response.read(8_000_001)
        if len(data) > 8_000_000:
            raise ValueError("API response exceeds sync limit")
        return json.loads(data)


def decode_file(data):
    if data.get("type") != "file" or data.get("encoding") != "base64":
        raise ValueError("Expected a regular base64 file")
    text = base64.b64decode(data["content"]).decode("utf-8")
    if len(text) > 200_000:
        raise ValueError("Document exceeds sync limit")
    return text


def project_directory(source):
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
    if profile.count(BEGIN) != 1 or profile.count(END) != 1:
        raise ValueError("Expected exactly one managed block")
    before, rest = profile.split(BEGIN)
    old, after = rest.split(END)
    if END in before or BEGIN in after:
        raise ValueError("Reversed managed markers")
    return before + BEGIN + "\n" + directory + "\n" + END + after


def require_success(runs, sha):
    eligible = [r for r in runs["workflow_runs"] if r.get("head_sha") == sha
                and r.get("head_branch") == "main" and r.get("path") == WORKFLOW
                and r.get("event") in ("push", "workflow_dispatch")]
    if not eligible:
        raise ValueError("No Portfolio main CI evidence for this commit")
    latest = max(eligible, key=lambda r: (r["run_number"], r.get("run_attempt", 1)))
    if latest.get("status") != "completed" or latest.get("conclusion") != "success":
        raise ValueError("Latest Portfolio main CI has not succeeded")


def synchronize(api, apply=False):
    for repo in (SOURCE, TARGET):
        info = api(f"/repos/{repo}")
        if info.get("private") is not False or info.get("default_branch") != "main":
            raise ValueError("Cost/scope gate: both repositories must be public and use main")
    sha = api(f"/repos/{SOURCE}/branches/main")["commit"]["sha"]
    if not re.fullmatch("[0-9a-f]{40}", sha):
        raise ValueError("Invalid source revision")
    runs = api(f"/repos/{SOURCE}/actions/workflows/portfolio-ci.yml/runs?head_sha={sha}&branch=main&per_page=100")
    require_success(runs, sha)
    source = decode_file(api(f"/repos/{SOURCE}/contents/README.md?ref={sha}"))
    target = api(f"/repos/{TARGET}/contents/README.md?ref=main")
    old = decode_file(target)
    new = replace_directory(old, project_directory(source))
    if new == old:
        return {"status": "UNCHANGED", "source_sha": sha}
    if api(f"/repos/{SOURCE}/branches/main")["commit"]["sha"] != sha:
        raise ValueError("Source main moved; next scheduled run will reconcile")
    if not apply:
        return {"status": "WOULD_UPDATE", "source_sha": sha}
    result = api(f"/repos/{TARGET}/contents/README.md", {
        "message": f"docs: sync Portfolio project directory ({sha[:12]})",
        "content": base64.b64encode(new.encode()).decode(),
        "sha": target["sha"], "branch": "main"})
    # Verify the exact committed content, not a possibly concurrent main head.
    commit = result["commit"]["sha"]
    actual = decode_file(api(f"/repos/{TARGET}/contents/README.md?ref={commit}"))
    if actual != new:
        raise ValueError("Committed content verification failed; inspect before retrying")
    return {"status": "UPDATED", "source_sha": sha, "profile_commit": commit}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Update the managed block after checks")
    args = parser.parse_args()
    try:
        if args.apply and not os.environ.get("GH_TOKEN"):
            raise ValueError("GH_TOKEN is required for apply")
        print(json.dumps(synchronize(GitHub(os.environ.get("GH_TOKEN")), args.apply)))
    except (ValueError, KeyError, HTTPError, OSError) as error:
        # Do not emit response bodies, tokens or untrusted source content.
        print(f"Sync stopped: {type(error).__name__}: " +
              (f"HTTP {error.code}" if isinstance(error, HTTPError) else
               str(error) if isinstance(error, ValueError) else "check network/API schema"), file=sys.stderr)
        sys.exit(1)
