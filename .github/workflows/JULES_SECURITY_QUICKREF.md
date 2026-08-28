# Jules Workflow Security Controls - Quick Reference

## What Changed?

Both Jules workflows (`jules-optimization-loop.yml` and `jules-quantum-evolution-loop.yml`) now implement **fail-closed post-change validation gates** to prevent unauthorized code from being auto-merged.

## Key Security Improvements

### ✅ Before Auto-Merge, Workflows Now:

1. **Capture the exact commit SHA** after Jules makes changes
2. **Re-checkout the code** in a clean environment at that specific SHA
3. **Re-run all validation tools** in fail-closed mode:
   - `pytest -v` (no `|| true` suppression)
   - `ruff check . --statistics` (no suppression)
   - `bandit -r . -ll --format txt` (no suppression)
4. **Verify repository provenance** to prevent fork-based attacks
5. **Verify PR head SHA** matches the validated commit
6. **Document validation results** in the PR description

### ❌ If Any Validation Fails:

- The workflow **stops immediately**
- No PR is created or updated
- Auto-merge is **not armed**
- Manual intervention is required

## Pre-Agent vs Post-Agent Validation

| Aspect | Pre-Agent (Steps 6-7) | Post-Agent (Steps 9+) |
|--------|----------------------|----------------------|
| **Purpose** | Provide context to Jules | Enforce security gate |
| **Failure Mode** | Advisory (`\|\| true`) | Fail-closed (no suppression) |
| **When** | Before Jules runs | After Jules commits |
| **Impact** | Logged, workflow continues | Workflow fails, no auto-merge |

## What You Need to Do

### Required: Configure Branch Protection

The workflows now **depend on branch protection rules** to provide defense-in-depth. Configure these on the `main` branch:

1. **Require pull request reviews** (at least 1 approval)
2. **Require status checks to pass**:
   - `CI/CD Build Pipeline / Code Quality & Static Analysis`
   - `CI/CD Build Pipeline / Rust Core Compilation & Unit Tests`
   - `CI/CD Build Pipeline / Python Test Suite Execution`
3. **Require conversation resolution**
4. **Do not allow bypassing**

### Recommended: Create CODEOWNERS

Create `.github/CODEOWNERS`:

```
/.github/workflows/ @your-org/security-team
/eqats_rust_core/ @your-org/architecture-team
/brain.py @your-org/architecture-team
/main.py @your-org/architecture-team
```

## How to Verify It's Working

### Test 1: Introduce a Test Failure

```bash
# In a test file, add a failing test
def test_security_gate():
    assert False, "Testing security gate"
```

Push to an `ai-optimize/*` branch and verify:
- ✅ Workflow runs
- ✅ Pre-agent validation passes (advisory)
- ✅ Jules makes changes
- ❌ Post-change validation fails
- ❌ No auto-merge is armed

### Test 2: Check PR Description

When a workflow succeeds, check the PR description includes:

```
**Post-Change Validation Results:**
- ✅ Test Suite: PASSED
- ✅ Ruff Linter: PASSED
- ✅ Bandit Security: PASSED
- 📌 Validated HEAD SHA: abc123...
```

## Monitoring

Watch for these indicators of security issues:

1. **Workflow failures** at post-change validation steps
2. **PRs with missing validation metadata** in description
3. **SHA mismatch errors** in workflow logs
4. **Repository provenance failures** in workflow logs

## Emergency Response

If you suspect a security incident:

1. **Disable the workflow** (Settings → Actions → Disable workflow)
2. **Review recent PRs** created by the workflow
3. **Check merged PRs** for unauthorized changes
4. **Rotate secrets**: `JULES_API_KEY`, `GITHUB_TOKEN`
5. **Contact security team**

## Questions?

- **Q: Why do pre-agent steps still have `|| true`?**
  - A: They're advisory only - they provide context to Jules but don't enforce security.

- **Q: Can Jules bypass the post-change validation?**
  - A: No. The validation runs in a fresh checkout after Jules commits. Jules cannot modify the validation steps.

- **Q: What if branch protection isn't configured?**
  - A: The workflow will still validate changes, but auto-merge could complete without manual review. **Configure branch protection!**

- **Q: Can I disable the post-change validation?**
  - A: Not recommended. This would reintroduce the security vulnerability. If you must, understand the risks and document the decision.

## Related Documentation

- Full security documentation: `.github/workflows/JULES_WORKFLOW_SECURITY.md`
- GitHub Actions security: https://docs.github.com/en/actions/security-guides
- Branch protection: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches
