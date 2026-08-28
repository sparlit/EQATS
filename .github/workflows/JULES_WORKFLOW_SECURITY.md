# Jules Workflow Security Controls

## Overview

This document describes the security controls implemented in the Jules AI agent workflows to prevent unauthorized code promotion to the main branch.

## Security Issue Addressed

**Finding:** Write-capable Jules workflows auto-arm attacker-controlled PRs without a fail-closed post-change gate

**Risk:** Workflows with `contents: write` and `pull-requests: write` permissions could enable auto-merge for PRs containing unvalidated or malicious code changes made by the AI agent.

## Implemented Security Controls

### 1. Post-Change Validation Gates (Fail-Closed)

Both `jules-optimization-loop.yml` and `jules-quantum-evolution-loop.yml` now implement comprehensive post-change validation:

#### a. Commit SHA Binding
- Captures the exact commit SHA after Jules makes changes
- All subsequent validation is performed against this specific SHA
- PR auto-merge is only armed if the PR head matches the validated SHA

#### b. Fail-Closed Test Execution
- **Test Suite:** `pytest -v` runs without `|| true` suppression
- **Ruff Linter:** `ruff check . --statistics` runs without suppression
- **Bandit Security Scanner:** `bandit -r . -ll --format txt` runs without suppression
- Any failure in these steps will halt the workflow and prevent auto-merge

#### c. Fresh Environment Validation
- Checks out the post-agent code in a clean state
- Reinstalls all dependencies to ensure reproducible validation
- Runs all validation tools on the exact code that would be merged

### 2. Repository Provenance Verification

Before enabling auto-merge, the workflow verifies:
- The repository URL matches the expected repository
- The branch is not a fork or external repository
- The PR head SHA matches the validated commit SHA

### 3. PR Metadata Validation

The workflow includes validation metadata in the PR description:
- Test suite validation status
- Ruff linter validation status
- Bandit security scanner validation status
- Exact validated commit SHA

### 4. Branch Protection Dependency

The workflows now explicitly document that auto-merge depends on branch protection rules:

```yaml
# SECURITY NOTE: Auto-merge will only complete if branch protection rules are satisfied
# Recommended: Configure branch protection on 'main' to require:
# - Status checks from CI workflow
# - Manual approval from CODEOWNERS
# - Up-to-date branches
```

## Recommended Additional Controls

### Branch Protection Rules

Configure the following branch protection rules on the `main` branch:

1. **Require pull request reviews before merging**
   - Require at least 1 approval
   - Dismiss stale pull request approvals when new commits are pushed
   - Require review from Code Owners

2. **Require status checks to pass before merging**
   - Require branches to be up to date before merging
   - Required status checks:
     - `CI/CD Build Pipeline / Code Quality & Static Analysis`
     - `CI/CD Build Pipeline / Rust Core Compilation & Unit Tests`
     - `CI/CD Build Pipeline / Python Test Suite Execution`

3. **Require conversation resolution before merging**

4. **Do not allow bypassing the above settings**

### CODEOWNERS File

Create a `.github/CODEOWNERS` file to require review from specific team members:

```
# Require security team review for workflow changes
/.github/workflows/ @your-org/security-team

# Require architecture review for core system changes
/eqats_rust_core/ @your-org/architecture-team
/brain.py @your-org/architecture-team
/main.py @your-org/architecture-team
```

### Workflow Permissions Audit

Regularly audit workflow permissions:
- Review which workflows have `contents: write` permission
- Review which workflows have `pull-requests: write` permission
- Ensure workflows with write permissions have appropriate validation gates

## Validation Flow

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Pre-Agent Validation (Advisory)                          │
│    - Run tests to understand current state                  │
│    - Run linters to provide context to agent                │
│    - Failures are logged but do not halt workflow           │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. Jules Agent Execution                                     │
│    - Agent makes code changes based on prompt                │
│    - Agent commits changes to branch                         │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. Post-Change Validation (FAIL-CLOSED) ← NEW               │
│    - Capture exact post-agent commit SHA                     │
│    - Checkout post-agent code in clean environment          │
│    - Run pytest (fails workflow on error)                   │
│    - Run ruff (fails workflow on error)                     │
│    - Run bandit (fails workflow on error)                   │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. PR Creation and Provenance Verification ← NEW            │
│    - Verify repository provenance                           │
│    - Create or update PR with validation metadata           │
│    - Verify PR head SHA matches validated SHA               │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 5. Auto-Merge Arming (Conditional)                          │
│    - Enable auto-merge only if all validations passed       │
│    - Auto-merge will wait for branch protection rules       │
│    - Requires manual approval if configured                 │
└─────────────────────────────────────────────────────────────┘
```

## Testing the Security Controls

### Test 1: Validation Failure Prevents Auto-Merge

1. Modify the workflow to introduce a test failure
2. Trigger the workflow
3. Verify the workflow fails at the post-change validation step
4. Verify no PR is created or auto-merge is not armed

### Test 2: SHA Mismatch Detection

1. Create a PR manually
2. Push a new commit to the branch after the workflow validates
3. Verify the workflow detects the SHA mismatch and fails

### Test 3: Repository Provenance Check

1. Fork the repository
2. Attempt to trigger the workflow from the fork
3. Verify the workflow detects the repository mismatch and fails

## Incident Response

If a security incident occurs related to these workflows:

1. **Immediate Actions:**
   - Disable the affected workflow(s)
   - Review recent PRs created by the workflow
   - Check for any merged PRs that bypassed validation

2. **Investigation:**
   - Review workflow run logs
   - Check for evidence of compromised credentials
   - Analyze any suspicious code changes

3. **Remediation:**
   - Revert any unauthorized changes
   - Rotate affected secrets (JULES_API_KEY, GITHUB_TOKEN)
   - Update workflow security controls as needed
   - Re-enable workflows after validation

## Maintenance

- Review this security documentation quarterly
- Update validation steps when new security tools are added
- Audit workflow permissions during security reviews
- Test security controls after any workflow modifications

## References

- [GitHub Actions Security Best Practices](https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions)
- [Branch Protection Rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
- [CODEOWNERS Documentation](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)
