# OpenWiki CI Security Configuration

This directory contains security-hardened configuration for the OpenWiki CI workflow.

## Security Improvements

The OpenWiki workflow has been hardened against supply chain attacks with the following measures:

### 1. Locked Dependency Installation
- **File**: `openwiki-package.json` - Defines the exact versions of OpenWiki and its dependencies
- **File**: `openwiki-package-lock.json` - Locks all transitive dependencies with integrity hashes
- **Benefit**: Prevents malicious code injection through compromised or updated transitive dependencies

### 2. Disabled Credential Persistence
- The workflow sets `persist-credentials: false` in the checkout step
- **Benefit**: Prevents installed npm packages from accessing the GitHub token via `.git/config`

### 3. Secrets Isolation
- API secrets are only exposed to the execution step, not the installation step
- The GitHub token is provided explicitly only to the PR creation step
- **Benefit**: Reduces the attack surface by limiting when secrets are available

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

Without a lockfile, `npm install --global openwiki@0.3.3` pins only the direct dependency. Transitive dependencies are resolved from current registry metadata on each run, allowing:
- A compromised transitive dependency to inject malicious code
- Newly published versions of transitive dependencies to introduce vulnerabilities
- Malicious code to exfiltrate CI secrets (API keys, GitHub tokens)
- Unauthorized repository modifications using the `contents: write` permission

With this configuration:
- All dependencies are locked with cryptographic integrity hashes
- The GitHub token is never persisted in the working tree
- Secrets are only available during the execution step, not installation
- Supply chain attacks are mitigated through reproducible, integrity-checked builds
