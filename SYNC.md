# Portfolio profile synchronization

Source: `MirceaStefanescu/Portfolio`, `main`, the `Project directory` section of `README.md`.
Destination: the `PORTFOLIO_PROJECTS` block of this repository's `README.md`.
The biography, contact details, services and screenshots outside the block stay unchanged.

GitHub Actions checks hourly at minute 37 UTC, when sync code changes on main,
or using **Actions → Sync Portfolio project directory → Run workflow**.
GitHub can delay scheduled runs and disables scheduled workflows in public
repositories after 60 days without repository activity; re-enable using Actions.
This is eventual synchronization of published Portfolio content, not local files.
Saving a file on a computer does not publish it: commit/push and successful
Portfolio CI for that exact main revision are required first.

The job uses a standard Ubuntu GitHub-hosted runner in this public repository.
Standard runners for public repositories are free. There are no paid services,
personal access tokens, artifact storage, external AI calls or new Git branches.
The job refuses private repository metadata; do not change the runner to a larger
runner. The built-in token can update only this repository and is supplied only
to the sync step. Checkout does not persist credentials.

Every run executes the regression tests, checks the latest matching Portfolio CI
run, reads the source by immutable commit SHA and checks for source movement.
It writes only when the rendered directory changes, with the README blob SHA
as a concurrency condition. A conflict, malformed source, missing/duplicate
markers, missing CI success or unknown API result stops the run without retries.
Inspect the run before retrying an uncertain write. The committed README is read
back using the returned commit SHA. No timestamp-only commits are generated.

Local tests: `python -m unittest discover -s scripts -p 'test_*.py' -v`.
Dry-run: `python scripts/sync_portfolio.py`. Applying requires `--apply` and
`GH_TOKEN`; use the existing workflow rather than putting credentials in files.
Test fixtures exercise write/no-op behavior, preservation, malformed content,
failed/pending/cancelled CI, reruns, source movement, concurrent updates and cost
gates. They do not certify long-term scheduler reliability.

Stop with **Disable workflow** in Actions. To undo a content change, disable the
workflow first, then revert the relevant commit using a new commit on main.
Do not force-push or remove the managed markers while the job remains active.

References: [GitHub Actions billing](https://docs.github.com/en/actions/concepts/billing-and-usage),
[GITHUB_TOKEN](https://docs.github.com/en/actions/concepts/security/github_token),
[Disable/enable workflows](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows).
