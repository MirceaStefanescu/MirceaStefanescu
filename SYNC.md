# Portfolio profile synchronization

Source: MirceaStefanescu/Portfolio, main, the Project directory section of README.md.
Destination: only the PORTFOLIO_PROJECTS block in this repository's README.md.
The biography, contact details, services and screenshots outside the block are
preserved byte for byte.

## Automatic checked PR route

The existing hourly check at minute 37 UTC remains in place. It also runs when
the sync implementation changes on main, through Actions → Sync Portfolio
project directory → Run workflow, or when Profile CI finishes successfully on
the managed automation/portfolio-sync branch.

Each run checks that both repositories are public, selects the exact Portfolio
main commit with successful Portfolio CI, reads immutable file content, and
verifies that neither main branch moved during preparation. If the directory
already matches, it reports UNCHANGED and performs no write.

A change is proposed on the managed branch and opened as a PR. The workflow
dispatches Profile CI explicitly: writes made with GITHUB_TOKEN do not trigger
push workflows, and bot-created pull-request workflows can require approval.
The explicit dispatch validates the managed branch without executing its code
with a write token. The sync job always checks out trusted main, never PR code.

The sync job merges through the normal PR API only after all these conditions:
the PR is owned by github-actions[bot], its source/base identities are current,
its only changed file is the existing README.md, its complete proposed text
matches the expected managed-block update, the latest Profile CI dispatch has
succeeded, and GitHub reports all merge requirements satisfied. The merge request
includes the exact reviewed head SHA. A failed, cancelled, pending or newer
failed CI attempt cannot borrow an older successful result.

Native protection requires Profile status, resolved review discussions and
CodeQL at the configured severity thresholds. A merge is never forced. After a
confirmed merge, the exact committed README is read back and Profile CI is
explicitly dispatched on main. No direct writes to main occur.

## Ownership, permissions and limits

The built-in short-lived token has contents, pull-requests and actions write
permissions only in the sync job; it is supplied only to the bounded API script.
Checkout does not persist credentials. No personal token or external AI is used.
Actions must be allowed to create PRs in this repository; the workflow does not
submit approving reviews.

Only one managed PR may be open. An existing branch is reused with a normal
fast-forward only when it exactly matches an owned, previously merged sync PR.
An unknown branch, changed PR, stale base/source, concurrent update, malformed
source or uncertain API result stops the job for inspection, preserving the
state. It does not overwrite unknown changes, force-push, retry an uncertain
write, delete branches or silently close PRs. A reviewer delay can defer the
merge until a later scheduled check.

GitHub may delay scheduled runs and may disable schedules in inactive public
repositories. The successful checks for this change do not guarantee every
future schedule. Local files are not synchronized by this workflow.

## Verification and recovery

[CONTRIBUTING.md](CONTRIBUTING.md) lists the local checks. A dry-run is
python3 scripts/sync_portfolio.py. Applying requires --apply and the built-in
GH_TOKEN; use the existing workflow instead of putting credentials in files.

Stop using Disable workflow in Actions. If an update must be undone, disable
the sync first and open a revert PR through the same required checks. Preserve
the managed markers and inspect any existing automation branch before retrying.
Do not use direct pushes or force pushes for recovery.

The workflow uses a standard Ubuntu runner in a public repository and no paid
service. References:
[GitHub Actions billing](https://docs.github.com/en/actions/concepts/billing-and-usage),
[GITHUB_TOKEN and event behavior](https://docs.github.com/en/actions/concepts/security/github_token),
[Disable or enable workflows](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows).

