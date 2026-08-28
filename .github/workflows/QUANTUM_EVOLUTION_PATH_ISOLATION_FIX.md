# Security Fix: PATH Tampering Isolation in Quantum Evolution Loop

## Vulnerability Summary

**Issue:** Post-agent validation code could tamper with `$GITHUB_PATH` to inject a malicious `gh` CLI wrapper, capturing the `GITHUB_TOKEN` in subsequent PR operations.

**Severity:** High - Token disclosure and privilege escalation

## Root Cause

The original workflow executed repository-controlled validation code (pytest, ruff, bandit) in the same job and runner as token-bearing `gh` CLI operations. GitHub Actions processes writes to `GITHUB_PATH` after each step completes, allowing malicious test code to:

1. Create a fake `gh` executable wrapper
2. Append its directory to `$GITHUB_PATH`
3. Capture `GH_TOKEN` when the next step invokes `gh`

The `persist-credentials: false` setting only prevents Git credential persistence; it does not isolate steps from cross-step state channels like `GITHUB_PATH`, `GITHUB_ENV`, or workspace modifications.

## Security Fix Implementation

### Job Isolation Architecture

The workflow has been split into two isolated jobs:

#### Job 1: `quantum-evolution` (Validation Job)
- **Purpose:** Execute Jules agent and run all validation tests
- **Permissions:** 
  - `contents: write` - For Jules to push code
  - `pull-requests: none` - **No PR permissions**
- **Characteristics:**
  - Checks out and executes repository-controlled code
  - Runs validation (pytest, ruff, bandit)
  - Outputs validated SHA and validation status
  - **Never receives PR token or invokes `gh` CLI**

#### Job 2: `create-pull-request` (Isolated PR Job)
- **Purpose:** Create and manage pull requests using validated SHA
- **Permissions:**
  - `contents: read` - Minimal read access
  - `pull-requests: write` - For PR operations only
- **Characteristics:**
  - **Never checks out repository code**
  - Runs in a fresh, isolated runner
  - Only executes trusted system commands
  - Verifies `gh` CLI path before use
  - Receives validated SHA from Job 1 via outputs

### Key Security Controls

1. **Job Dependency Chain:**
   ```yaml
   needs: quantum-evolution
   if: needs.quantum-evolution.outputs.continue_loop == 'true' && 
       needs.quantum-evolution.outputs.validation_passed == 'true'
   ```
   PR job only runs if validation passes.

2. **No Code Checkout:**
   ```yaml
   steps:
     # SECURITY: This job intentionally does NOT check out repository code
     - name: Open and Automerge Pull Request
   ```
   Prevents any repository-controlled code execution.

3. **CLI Path Verification:**
   ```bash
   GH_PATH=$(which gh)
   if [[ ! "$GH_PATH" =~ ^/usr/ ]] && [[ ! "$GH_PATH" =~ ^/opt/hostedtoolcache/ ]]; then
     echo "❌ SECURITY GATE FAILED: gh CLI resolved to unexpected path"
     exit 1
   fi
   ```
   Ensures `gh` resolves to system-installed binary, not workspace-injected wrapper.

4. **Explicit Repository Context:**
   ```bash
   gh pr list --repo "$REPO_NAME" ...
   gh pr create --repo "$REPO_NAME" ...
   ```
   Uses explicit `--repo` flag instead of relying on git context.

## Attack Surface Reduction

### Before Fix
```
[Checkout Code] → [Run Validation] → [Validation writes to $GITHUB_PATH] 
                                   ↓
                        [gh CLI with GH_TOKEN] ← Resolves malicious wrapper
```

### After Fix
```
Job 1 (Validation):
[Checkout Code] → [Run Validation] → [Output validated SHA]
                                   ↓
Job 2 (PR Operations - Fresh Runner):
[No checkout] → [Verify gh path] → [gh CLI with GH_TOKEN] ← Only system binary
```

## Verification

The fix can be verified by:

1. **Job Isolation:** Confirm two separate jobs in workflow runs
2. **No Checkout in PR Job:** Verify `create-pull-request` job has no checkout step
3. **Path Verification:** Check logs for "Using gh CLI from: /usr/..." message
4. **Permission Separation:** Validate job has minimal permissions

## Additional Recommendations

1. **Branch Protection:** Configure required status checks on `main` branch
2. **Environment Protection:** Require manual approval for `quantum-evolution` environment
3. **Audit Logging:** Monitor workflow runs for unexpected `gh` path resolutions
4. **Regular Reviews:** Periodically audit workflow for new cross-step state channels

## References

- GitHub Actions Security Hardening: https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions
- Workflow Command Injection: https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions#understanding-the-risk-of-script-injections
- Job Isolation: https://docs.github.com/en/actions/using-jobs/using-jobs-in-a-workflow
