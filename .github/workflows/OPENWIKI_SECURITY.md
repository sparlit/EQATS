# OpenWiki CI Security Configuration

This directory contains security-hardened configuration for the OpenWiki CI workflow.

## Security Improvements

The OpenWiki workflow has been hardened against supply chain attacks with the following measures:

### 1. Job-Level Permission Isolation
- The workflow is split into two jobs: `generate` (read-only) and `create-pr` (write-only)
- The `generate` job runs all third-party code (npm packages, OpenWiki) with only `contents: read` permission
- The `create-pr` job has `contents: write` and `pull-requests: write` but executes no third-party code
- **Benefit**: Prevents compromised packages or dependencies from accessing repository-write credentials, even if they attempt to read `GITHUB_TOKEN` from the environment

### 2. Locked Dependency Installation
- **File**: `openwiki-package.json` - Defines the exact versions of OpenWiki and its dependencies
- **File**: `openwiki-package-lock.json` - Locks all transitive dependencies with integrity hashes
- **Benefit**: Prevents malicious code injection through compromised or updated transitive dependencies

### 3. Disabled Credential Persistence
- The workflow sets `persist-credentials: false` in all checkout steps
- **Benefit**: Prevents installed npm packages from accessing the GitHub token via `.git/config`

### 4. Secrets Isolation
- API secrets are only exposed to the OpenWiki execution step in the read-only job
- The GitHub token with write permissions is only available in the `create-pr` job
- **Benefit**: Reduces the attack surface by limiting when secrets are available and preventing write-capable tokens from being exposed to third-party code

## Generating the Lockfile

On the first workflow run, if `openwiki-package-lock.json` does not exist, it will be automatically generated. The workflow will create a PR that includes this lockfile, which should be merged to ensure reproducible builds.

To manually generate or update the lockfile:

```bash
cd .github/workflows
cp openwiki-package.json package.json
npm install --package-lock-only
mv package-lock.json openwiki-package-lock.json
rm package.json
```

## Updating Dependencies

To update OpenWiki or its dependencies:

1. Edit `openwiki-package.json` with the new version
2. Regenerate the lockfile using the commands above
3. Commit both files
4. The next workflow run will use the updated, locked dependencies

## Security Rationale

Without proper isolation, even with locked dependencies, a compromised package could:
- Read the `GITHUB_TOKEN` environment variable (available to all steps in a job with write permissions)
- Use that token to push unauthorized commits, modify workflow files, or manipulate pull requests
- Bypass branch protection by creating malicious PRs or modifying existing ones

With this configuration:
- Third-party code runs in a job with only read permissions, so `GITHUB_TOKEN` cannot write to the repository
- All dependencies are locked with cryptographic integrity hashes
- The GitHub token is never persisted in the working tree (`.git/config`)
- Write-capable tokens are only available in a separate job that executes no third-party code
- Supply chain attacks are mitigated through job-level permission isolation and reproducible, integrity-checked builds
