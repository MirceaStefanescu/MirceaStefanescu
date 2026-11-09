# Portfolio profile synchronization

Source: MirceaStefanescu/Portfolio, main, the Project directory section of README.md.
Destination: only the PORTFOLIO_PROJECTS block in this repository's README.md.
The biography, contact details, services and screenshots outside the block are
preserved byte for byte.

## Checked PR route with native workflow approval

The existing hourly check at minute 37 UTC remains in place. It also runs when
the sync implementation changes on main, through Actions → Sync Portfolio
project directory → Run workflow, or when Profile CI finishes successfully on
the managed automation/portfolio-sync branch.

Each run checks that both repositories are public, selects the exact Portfolio
main commit with successful Portfolio CI, reads immutable file content, and
verifies that neither main branch moved during preparation. If the directory
already matches, it reports UNCHANGED and performs no write.

A change is proposed on the managed branch and opened as a PR. GitHub puts
pull-request workflows created by GITHUB_TOKEN into an approval-required state.
Open that PR, inspect Files changed to confirm the expected README-only update,
and select Approve workflows to run in its merge panel. This maintainer action
is required for each new bot PR; the sync does not approve its own checks.
After approval, native pull-request CI runs with its restricted job permissions.
The sync job always checks out trusted main, never PR code.

A branch workflow_dispatch is not a substitute: GitHub does not accept its job
checks as required PR status checks. No personal token, new GitHub App credential
or alternate check-reporting route is used to avoid the approval requirement.

The sync job merges through the normal PR API only after all these conditions:
the PR is owned by github-actions[bot], its source/base identities are current,
its only changed file is the existing README.md, its complete proposed text
matches the expected managed-block update, the latest native Profile CI run is
associated with this PR's exact head and base and has succeeded, and GitHub
reports all merge requirements satisfied. The merge request
includes the exact reviewed head SHA. A failed, cancelled, pending or newer
failed CI attempt cannot borrow an older successful result.

Native protection requires Profile status and resolved review discussions.
Profile status includes the Python CodeQL job; the separate CodeQL results rule
enforces severity thresholds after a main-branch analysis baseline is available.
A merge is never forced. After a
confirmed merge, the exact committed README is read back and Profile CI is
explicitly dispatched on main. No direct writes to main occur.
If that dispatch fails, the result preserves MERGED and the verified commit,
adds main_ci_dispatch: unconfirmed and dispatch_error, and exits with failure
so the missing CI request is visible. Inspect Actions for the recorded
profile_commit SHA. If no run exists and main still points to that SHA, use
Profile CI → Run workflow on main. If main has advanced, create a new temporary
branch named recovery/profile-ci-<profile_commit> at the recorded full SHA,
verify its head matches, then select that branch in Profile CI → Run workflow.
Do not overwrite an existing recovery branch or move main backwards. Confirm
the run's exact head SHA and successful result before calling that commit
verified; retain the recovery branch until its verification receipt is checked.
Also verify current main separately at its own exact SHA, since testing the
historical commit does not verify later changes. Do not repeat the merge;
later sync checks can correctly report UNCHANGED.

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

To stop the sync, open Actions → Sync Portfolio project directory → Disable
workflow. Disabling prevents new runs but does not cancel queued or running
runs: cancel those existing sync runs and wait for them to reach a terminal
state before recovery. Check whether any PR already merged. If an update must
be undone, keep the sync disabled and open a revert PR through the same required
checks. Preserve the managed markers and inspect any existing automation branch
before retrying. Correct the source directory in Portfolio main through its own
reviewed PR and passing CI before re-enabling sync; otherwise keep sync disabled
so it cannot propose the reverted content again. Do not use direct pushes or
force pushes for recovery.

If a managed PR is stale because its recorded source or base changed, closing
it alone is insufficient: the script will refuse to reuse an unmerged branch.
After stopping and cancelling sync as above, inspect the PR and the current
automation/portfolio-sync branch. Record their exact head SHA and preserve that
commit in a separately named archive branch; verify the archive points to the
same SHA, and retain any needed work for a separately reviewed PR. Only with
owner confirmation, and after verifying no other open PR depends on this
obsolete branch, close the stale managed PR without merging and delete only
automation/portfolio-sync. Do not remove the archive or any unknown branch.
If ownership or preservation is uncertain, keep sync disabled and stop.
Once the source is correct with passing CI, re-enable sync and run it again:
it creates a fresh branch from current main and a new PR, whose native workflows
still require maintainer approval. No force push or direct-main repair is used.

The workflow uses a standard Ubuntu runner in a public repository and no paid
service. References:
[GitHub Actions billing](https://docs.github.com/en/actions/concepts/billing-and-usage),
[GITHUB_TOKEN and event behavior](https://docs.github.com/en/actions/concepts/security/github_token),
[Required status check event restrictions](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks),
[Disable or enable workflows](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows).

