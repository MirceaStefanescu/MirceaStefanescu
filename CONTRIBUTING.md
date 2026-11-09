# Profile maintenance checks

This repository publishes the GitHub profile README. Changes go through a pull
request, including updates proposed by the existing Portfolio directory sync.

## Required checks

Profile CI runs for every pull request to main, for main after a normal merge,
and through an explicit workflow dispatch. It checks profile links and images,
the sync regression suite, shared Markdown parser regressions, workflow syntax
and Python with CodeQL. Dependency Review checks introduced high/critical
vulnerabilities on pull-request events. Profile status requires both CI jobs to
succeed; failed, cancelled or skipped jobs cannot pass this gate.

The parser and its tests come from
[Portfolio at a fixed commit](https://github.com/MirceaStefanescu/Portfolio/tree/b70af4a7de4399433ae854ae115f510ab628184e).
Only those two files are checked out, and updates to this pin require a reviewed
PR. This avoids maintaining a second copy of the parsing implementation.

The link check covers README.md, SYNC.md and this guide. Local file and anchor
errors block CI. Approved public HTTPS destinations are checked with bounded
requests; an external 404/410 must be repeated before it blocks. Authentication,
throttling and temporary network failures are warnings. Other hosts require
review before the checker will contact them. This is not a full Markdown parser
or a guarantee about the content of third-party pages.

## Optional local verification

Use a POSIX environment, Python 3.9 or later, and Git. Symlink tests require a
filesystem that supports symbolic links. GitHub's standard Ubuntu runner already
provides these prerequisites. No administrator rights or API keys are needed.

Prepare the pinned helper in a new, empty .portfolio-checks directory:

```bash
git clone --no-checkout --filter=blob:none https://github.com/MirceaStefanescu/Portfolio.git .portfolio-checks
git -C .portfolio-checks sparse-checkout init --no-cone
git -C .portfolio-checks sparse-checkout set /scripts/check-presentation.py /tests/test-presentation.py
git -C .portfolio-checks checkout b70af4a7de4399433ae854ae115f510ab628184e
python3 -m unittest discover -s scripts -p 'test_*.py' -v
python3 .portfolio-checks/tests/test-presentation.py
python3 scripts/check_profile.py
```

Do not overwrite an existing helper checkout with unknown changes. Add
--external to the final command to check approved public URLs. The normal
offline test suite makes no network requests.

## Sync and recovery

See [SYNC.md](SYNC.md) for the automatic PR route, stop conditions and recovery.
A failed check is investigated before merging. Do not remove the required
checks, bypass branch protection or push directly to main.

The workflows use standard runners in this public repository, pinned actions,
the existing built-in GitHub token and open-source tools. No AI API or Codex
credits are required for these deterministic checks.
