# Delivery workflow

The user requests automatic delivery after each completed change in this repository:

- Run the relevant checks, commit on a `codex/` branch, and push it.
- Create or update a pull request, wait for CI to pass, then merge into `master` without requesting another confirmation.
- Fix failed checks before merging; if delivery is blocked, report the concrete blocker.
- After merging, synchronize the local checkout with `master` and report the PR link and validation result.
