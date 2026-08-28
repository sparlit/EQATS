# Security Fix: Jules Deep Refactor Workflow - Secret Exfiltration Prevention

## Vulnerability Summary

**Finding:** Secret-bearing workflow executes attacker-controlled branch contents

**Affected File:** `.github/workflows/jules-deep-refactor.yml`

**Severity:** High

## Root Cause

The workflow was configured with a `push` trigger on branch pattern `ai-refactor-/*`:

```yaml
on:
  push:
    branches:
      - 'ai-refactor-/*'
```

When a workflow is triggered by a `push` event, GitHub Actions evaluates the workflow definition **from the pushed commit**, not from the default branch. This creates a critical security vulnerability:

1. A repository contributor with write access can create a branch matching `ai-refactor-/*` (e.g., `ai-refactor-/malicious`)
2. The contributor modifies the workflow file in that branch to exfiltrate secrets or abuse permissions
3. When the branch is pushed, GitHub Actions runs the **modified workflow** with access to:
   - `secrets.JULES_API_KEY` (passed to the Jules action)
   - `contents: write` permission (granted to the job)
   - `GITHUB_TOKEN` with write access

Example attack scenarios:
- Add a step that sends `JULES_API_KEY` to an attacker-controlled endpoint
- Modify the Jules action invocation to use a malicious fork
- Add steps that abuse the `contents: write` permission to modify protected files
- Replace the entire workflow with malicious code

## Security Fix Implemented

### 1. Removed Push Trigger

The `push` trigger has been completely removed from the workflow:

```yaml
on:
  # SECURITY: Removed push trigger to prevent secret-bearing workflow from executing
  # attacker-controlled branch contents. Push-triggered workflows evaluate the workflow
  # definition from the pushed revision, allowing a repository contributor to modify
  # this workflow in a branch matching 'ai-refactor-/*' and exfiltrate JULES_API_KEY
  # or misuse the contents: write permission.
  workflow_dispatch:
```

### 2. Retained Manual Trigger with Branch Input

The workflow now uses `workflow_dispatch` exclusively, with a branch input parameter:

```yaml
workflow_dispatch:
  inputs:
    branch:
      description: 'Branch to refactor (e.g., ai-refactor-auth)'
      required: false
      default: ''
      type: string
```

### 3. Updated Checkout and Jules Action Steps

The workflow now properly handles the branch input:

```yaml
- name: Checkout Repository
  uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v5.2.2
  with:
    ref: ${{ inputs.branch || github.ref }}
    persist-credentials: false

- name: Summon Jules for Deep Scan
  uses: google-labs-code/jules-action@a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0 # v1.x.x
  with:
    jules_api_key: ${{ secrets.JULES_API_KEY }}
    branch: ${{ inputs.branch || github.ref_name }}
```

## Security Benefits

### 1. Trusted Workflow Code Execution

With `workflow_dispatch`, the workflow definition is **always evaluated from the default branch** (typically `main`), not from the branch being refactored. This ensures:
- The workflow code itself is trusted and reviewed
- Attackers cannot modify the workflow logic
- Secret access is controlled by the trusted workflow definition

### 2. Explicit Authorization Required

Manual triggering requires:
- The user to be authenticated to GitHub
- The user to have appropriate repository permissions
- Explicit user action (clicking "Run workflow" in the GitHub UI)
- Conscious selection of the target branch

This prevents:
- Automatic execution of potentially malicious workflows
- Accidental triggering by branch pushes
- Unauthorized workflow execution

### 3. Audit Trail

Manual workflow triggers create a clear audit trail:
- Who triggered the workflow
- When it was triggered
- Which branch was selected
- All workflow runs are logged with the triggering user

## Usage Instructions

To use the refactored workflow:

1. Navigate to the GitHub repository
2. Click on the "Actions" tab
3. Select "Jules Deep Project Refactor" from the workflow list
4. Click "Run workflow"
5. Select the branch you want to refactor (e.g., `ai-refactor-auth`)
6. Click "Run workflow" to start the refactoring process

## Alternative Mitigation Strategies Considered

### Option 1: Use pull_request_target (Not Chosen)

`pull_request_target` runs the workflow from the default branch but requires:
- Creating a PR first (adds friction to the workflow)
- Additional authorization checks (like in `ai-loop-fixer.yml`)
- More complex workflow logic

This was not chosen because the deep refactor workflow is designed for direct branch work, not PR-based workflows.

### Option 2: Use GitHub Environments (Partial Protection)

GitHub Environments with required reviewers provide protection but:
- Still execute workflow code from the pushed branch
- Require manual approval for each run (similar to workflow_dispatch)
- Don't prevent workflow code modification, only delay secret access

This provides defense-in-depth but doesn't address the root cause.

### Option 3: Restrict Branch Pattern Further (Insufficient)

Making the branch pattern more restrictive (e.g., `ai-refactor-approved-/*`) doesn't solve the problem:
- Contributors with write access can still create matching branches
- The fundamental issue of untrusted workflow code execution remains

## Related Workflows

The following workflows may have similar vulnerabilities and should be reviewed:

1. **jules-optimization-loop.yml** - Triggers on `push` to `ai-optimize-/*` with `JULES_API_KEY`
2. **jules-healing-loop.yml** - Triggers on `push` to `ai-fix-/*` with `JULES_API_KEY`
3. **jules-quantum-evolution-loop.yml** - Triggers on `push` to `ai-quantum-/*` with `JULES_API_KEY`
   - Note: Uses `environment: quantum-evolution` for partial protection

These workflows should be evaluated for similar security fixes based on their intended use cases.

## Testing the Fix

### Verify the Vulnerability is Mitigated

1. Create a branch matching `ai-refactor-/*`
2. Modify the workflow file in that branch to add a malicious step
3. Push the branch
4. Verify that the workflow does **not** automatically execute

### Verify Functionality is Preserved

1. Navigate to Actions → Jules Deep Project Refactor
2. Click "Run workflow"
3. Select a branch to refactor
4. Verify the workflow executes successfully
5. Verify Jules makes the expected refactoring changes

## References

- [GitHub Actions Security Hardening](https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions)
- [Security hardening for GitHub Actions: Preventing pwn requests](https://securitylab.github.com/research/github-actions-preventing-pwn-requests/)
- [Keeping your GitHub Actions and workflows secure Part 1: Preventing pwn requests](https://securitylab.github.com/research/github-actions-preventing-pwn-requests/)

## Maintenance

- Review this security fix during quarterly security audits
- When adding new Jules workflows, ensure they use `workflow_dispatch` or `pull_request_target` with proper authorization
- Never use `push` triggers with workflows that access secrets or have write permissions
- Document any exceptions with clear security justification
