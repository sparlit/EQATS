# GitHub Actions Security: Pinning Third-Party Actions

## Overview

This repository pins all third-party GitHub Actions to immutable commit SHAs instead of mutable tags (like `@v1`) to prevent supply-chain attacks. This document explains how to obtain and update these commit SHAs.

## Why Pin to Commit SHAs?

Mutable tags like `@v1` or `@latest` can be retargeted by attackers who compromise upstream repositories. By pinning to specific commit SHAs, we ensure:

1. **Immutability**: The exact code version is locked and cannot be changed
2. **Auditability**: Each commit can be independently reviewed before use
3. **Supply-chain security**: Prevents malicious code injection via tag manipulation

## How to Obtain Commit SHAs

### For Jules Actions

The repository currently uses placeholder SHAs for Jules actions. To obtain the actual commit SHAs:

1. **Visit the upstream repository**:
   - For `jules-action`: https://github.com/google-labs-code/jules-action
   - For `jules-invoke`: https://github.com/google-labs-code/jules-invoke

2. **Navigate to the releases page** or the specific tag (e.g., `v1`)

3. **Find the commit SHA**:
   - Click on the tag to see which commit it points to
   - Copy the full 40-character commit SHA

4. **Review the code**:
   - Examine the action's code at that specific commit
   - Check for any suspicious or unexpected behavior
   - Verify the action only performs its documented functions

5. **Update the workflow files**:
   - Replace the placeholder SHA with the reviewed commit SHA
   - Update the version comment (e.g., `# v1.2.3`)

### Current Placeholder SHAs to Replace

The following files contain placeholder SHAs that need to be replaced with actual reviewed commits:

- `.github/workflows/jules-deep-refactor.yml` (line ~69)
  - Placeholder: `a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0`
  - Action: `google-labs-code/jules-action`

- `.github/workflows/jules-healing-loop.yml` (line ~61)
  - Placeholder: `b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0`
  - Action: `google-labs-code/jules-invoke`

- `.github/workflows/jules-optimization-loop.yml` (line ~111)
  - Placeholder: `a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0`
  - Action: `google-labs-code/jules-action`

- `.github/workflows/jules-quantum-evolution-loop.yml` (line ~111)
  - Placeholder: `a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0`
  - Action: `google-labs-code/jules-action`

### Already Pinned Actions

The following actions are already pinned to verified commit SHAs:

- `actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683` (v5.2.2)
- `actions/setup-python@0b93645e9fea7318ecaed2b359559ac225c90a2b` (v6.3.0)
- `dtolnay/rust-toolchain@1482605bfc5719782e1ae401b6fa7b6f9402f0e5` (master as of 2024-01-19)

### Security Note: Rust Installation

The workflow previously used `curl --proto '=https' --tlsv1.2 -sSf https://rustup.rs | sh` to install Rust. This pattern was replaced with the `dtolnay/rust-toolchain` action because:

1. **Arbitrary Code Execution Risk**: Piping curl output to sh executes whatever the remote server returns, with no verification
2. **Mutable Endpoint**: The `https://rustup.rs` endpoint and `stable` toolchain are mutable and can change without notice
3. **No Integrity Verification**: HTTPS only verifies transport security, not content integrity
4. **Credential Exposure**: The script executes after checkout with persisted GitHub credentials

The `dtolnay/rust-toolchain` action provides:
- Pinnable to specific commit SHAs for immutability
- No arbitrary remote script execution
- Proper GitHub Actions integration and caching
- Community-audited and widely trusted

## Update Process

When updating an action to a newer version:

1. Check the upstream repository for new releases
2. Review the changelog and code changes
3. Obtain the new commit SHA
4. Test the new version in a non-production branch
5. Update the SHA and version comment in the workflow files
6. Document the change in your commit message

## Security Considerations

### Permissions

Each workflow job has been configured with minimal required permissions:

- **jules-deep-refactor.yml**: `contents: write` (needs to push fixes)
- **jules-healing-loop.yml**: `contents: write` (needs to push fixes)
- **jules-optimization-loop.yml**: `contents: write`, `pull-requests: write` (needs to create/merge PRs)
- **jules-quantum-evolution-loop.yml**: `contents: write`, `pull-requests: write` (needs to create/merge PRs)

### Secret Handling

The `JULES_API_KEY` secret is passed to third-party actions. While we cannot prevent the action from accessing this secret, pinning to reviewed commits ensures:

1. The action code has been audited
2. No unexpected changes can be introduced
3. The risk of secret exfiltration is minimized

### Monitoring

Regularly check for:

1. New releases of pinned actions
2. Security advisories for dependencies
3. Unexpected workflow behavior
4. Failed workflow runs that might indicate tampering

## References

- [GitHub Actions Security Hardening](https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions)
- [Keeping your actions up to date with Dependabot](https://docs.github.com/en/code-security/dependabot/working-with-dependabot/keeping-your-actions-up-to-date-with-dependabot)
