# Configuring Required Status Checks & Auto-Merge

## Problem Overview

When GitHub Actions or repository operators attempt to enable **Auto-Merge** on pull requests using `gh pr merge --auto --squash` or via the GitHub UI, GitHub requires that at least one **Required Status Check** is configured in branch protection rules or repository rulesets for the target branch (`main` / `master`).

Without required status checks enabled, GitHub blocks auto-merge with the error:
> `Auto-merge cannot be enabled because there are no required status checks configured for this branch. This prevents accidental merges when no checks are in place.`

---

## Solution Implemented

1. **Unified CI Status Check Job (`.github/workflows/ci.yml`)**:
   - A dedicated job named `Required Status Check` (`required-status-check`) was added to `ci.yml`.
   - It aggregates the results of all CI sub-jobs (`lint-and-typecheck`, `rust-core`, `python-tests`, `build-artifacts`).
   - This provides a single status check name in GitHub settings: **`Required Status Check`**.

2. **Resilient Auto-Merge Workflow Fallbacks (`jules-*.yml`)**:
   - Workflows that execute `gh pr merge --auto --squash` capture CLI errors when auto-merge settings or required status checks are missing on the target branch.
   - If auto-merge cannot be armed, the workflow attempts a direct squash merge for pre-validated PRs or logs clear instructions for administrators instead of failing the workflow run.

---

## Administrator Setup Instructions

To enable GitHub native auto-merge for pull requests, repository administrators must configure branch protection rules on the primary branch (`main` / `master`):

### Step 1: Navigate to Repository Settings
1. Go to your repository on GitHub.
2. Click **Settings** > **Branches** (under *Code and automation*).

### Step 2: Add or Edit Branch Protection Rule
1. Under **Branch protection rules**, click **Add branch ruleset** or **Edit** on your `main` / `master` rule.
2. Under **Protect matching branches**:
   - Check **Require a pull request before merging**.
   - Check **Allow auto-merge**.
   - Check **Require status checks to pass before merging**.

### Step 3: Select Required Status Check
1. Under **Status checks that's required**, search for:
   ```
   Required Status Check
   ```
2. Select **`Required Status Check`** (or `CI/CD Build Pipeline / Required Status Check`).
3. Check **Require branches to be up to date before merging** (optional, recommended).
4. Save changes.

---

## Verification

Once configured:
- Pull requests targeting `main` or `master` will display the required status check requirement in GitHub UI.
- `gh pr merge --auto --squash` executed in workflows will arm auto-merge successfully.
- Once the `Required Status Check` job passes, GitHub will automatically merge the pull request.
