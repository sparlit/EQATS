# Aider Installation Security Fix

## Vulnerability Description

The `ai-loop-fixer.yml` workflow had a fail-open security vulnerability in the Aider installation step (line 135). The workflow attempted to install `aider-chat==0.42.1` with `--require-hashes --only-binary=:all:` flags but without providing actual cryptographic hashes. This approach was fundamentally flawed because:

1. **`--require-hashes` requires a complete hash allowlist**: The flag requires SHA256 hashes for every package in the resolved installation set, including all transitive dependencies. A bare version pin like `aider-chat==0.42.1` does not provide any hashes.

2. **The first installation always failed**: Without hashes, pip would refuse to install and return an error.

3. **The `||` fallback was fail-open**: The shell `||` operator immediately retried with `pipx install aider-chat==0.42.1` without any hash verification or binary restrictions, completely bypassing the intended security control.

4. **High-privilege execution context**: The installed package runs in a job with:
   - `contents: write` permission
   - `pull-requests: write` permission  
   - Access to `OPENAI_API_KEY`
   - Access to `GITHUB_TOKEN` with write capabilities
   - Ability to push changes to the repository

### Attack Scenario

A compromised Aider artifact, malicious dependency, or man-in-the-middle attack on the distribution path could:
- Execute arbitrary code during installation
- Read and exfiltrate `OPENAI_API_KEY` and `GITHUB_TOKEN`
- Modify the checked-out repository
- Push unauthorized changes using the write-capable GitHub token
- Persist backdoors in the codebase

While the `ai-fix-approved` label limits who can trigger the workflow, it does not validate package provenance or protect the job after an authorized run begins.

## Fix Implementation

The fix implements a **fail-closed** approach with proper hash verification:

### 1. Created Hash-Pinned Lockfile Infrastructure

**`.github/workflows/aider-requirements.txt`**
- Source file listing the desired package and version
- Used as input for generating the hash-pinned lockfile

**`.github/workflows/aider-requirements-lock.txt`**
- Hash-pinned lockfile with SHA256 hashes for all packages and transitive dependencies
- Generated using `pip-compile --generate-hashes`
- Currently contains placeholder hashes with instructions for generation

### 2. Updated Workflow Installation Logic

The workflow now:

1. **Checks for lockfile existence**: Verifies that `.github/workflows/aider-requirements-lock.txt` exists
2. **Validates hash authenticity**: Detects placeholder hashes and refuses to proceed
3. **Fails closed by default**: Exits with error if lockfile is missing or has placeholder hashes
4. **Provides clear remediation instructions**: Shows exact commands to generate proper hashes
5. **Requires explicit override**: Emergency fallback requires setting `AIDER_ALLOW_UNVERIFIED=true` environment variable
6. **Maintains binary-only restriction**: Even in fallback mode, uses `--only-binary=:all:` to prevent source builds

### 3. Security Properties

The fix provides multiple security layers:

- **Cryptographic verification**: SHA256 hashes for all packages prevent tampering
- **Complete dependency graph**: Transitive dependencies are also hash-verified
- **Fail-closed design**: Missing or invalid hashes cause installation to fail, not fall back
- **Explicit override required**: Bypassing security requires conscious decision
- **Audit trail**: Lockfile changes are visible in git diff
- **Binary-only installation**: Prevents malicious setup.py execution during source builds
- **Immutable installation**: pip refuses to install if hashes don't match

## Generating the Lockfile

The lockfile currently contains placeholder hashes. To generate actual cryptographic hashes:

### Prerequisites

```bash
# Install pip-tools
pip install pip-tools==7.4.1
```

### Generate Lockfile

```bash
# From repository root
pip-compile --generate-hashes --allow-unsafe \
  --output-file=.github/workflows/aider-requirements-lock.txt \
  .github/workflows/aider-requirements.txt
```

This command will:
1. Resolve all dependencies for `aider-chat==0.42.1`
2. Download all packages (including transitive dependencies)
3. Compute SHA256 hashes for each package
4. Generate a complete lockfile with all hashes

### Review and Commit

```bash
# Review the generated lockfile
git diff .github/workflows/aider-requirements-lock.txt

# Verify it contains real hashes (not placeholders)
grep "sha256:" .github/workflows/aider-requirements-lock.txt

# Commit both files
git add .github/workflows/aider-requirements.txt
git add .github/workflows/aider-requirements-lock.txt
git commit -m "security: add hash-pinned lockfile for aider-chat"
```

## Current State

**Status**: Partially mitigated (fail-closed, but lockfile needs generation)

The workflow will now **fail by default** instead of falling back to unverified installation. This is a significant security improvement because:

1. **No silent bypass**: The fail-open vulnerability is eliminated
2. **Clear error messages**: Developers know exactly what needs to be done
3. **Conscious override required**: Bypassing security requires explicit action

However, to achieve **full mitigation**, the lockfile must be generated with actual hashes:

```bash
pip install pip-tools==7.4.1
pip-compile --generate-hashes --allow-unsafe \
  --output-file=.github/workflows/aider-requirements-lock.txt \
  .github/workflows/aider-requirements.txt
git add .github/workflows/aider-requirements-lock.txt
git commit -m "security: add cryptographic hashes for aider-chat"
```

## Emergency Fallback

If the workflow must run before the lockfile is generated (NOT RECOMMENDED), set the environment variable:

```yaml
- name: Install AI Agent CLI
  env:
    AIDER_ALLOW_UNVERIFIED: true  # INSECURE - only for emergency use
  run: |
    # ... installation script
```

This will:
- Log prominent warnings
- Install with version pinning only (no hash verification)
- Still enforce `--only-binary=:all:` to prevent source builds

**WARNING**: This fallback should only be used in emergencies and should be removed as soon as the lockfile is generated.

## Maintenance

### Updating Aider Version

1. Update version in `.github/workflows/aider-requirements.txt`
2. Regenerate lockfile:
   ```bash
   pip-compile --generate-hashes --allow-unsafe \
     --output-file=.github/workflows/aider-requirements-lock.txt \
     .github/workflows/aider-requirements.txt
   ```
3. Review the diff to understand what changed
4. Test locally
5. Commit both files together

### Monitoring

- Set up Dependabot or Renovate to automate dependency updates
- Monitor for security advisories affecting `aider-chat`
- Regularly regenerate lockfiles to pick up security patches
- Review lockfile diffs carefully for unexpected changes

## Testing

### Verify Fail-Closed Behavior

```bash
# Remove lockfile and verify workflow fails
rm .github/workflows/aider-requirements-lock.txt
# Trigger workflow - should fail with clear error message

# Restore lockfile with placeholder hashes
git checkout .github/workflows/aider-requirements-lock.txt
# Trigger workflow - should fail with clear error message
```

### Verify Hash Verification Works

```bash
# Generate lockfile with real hashes
pip-compile --generate-hashes --allow-unsafe \
  --output-file=.github/workflows/aider-requirements-lock.txt \
  .github/workflows/aider-requirements.txt

# Trigger workflow - should succeed with hash verification
```

### Verify Emergency Fallback

```yaml
# Add to workflow (temporarily)
env:
  AIDER_ALLOW_UNVERIFIED: true

# Trigger workflow - should install with warnings but no hash verification
```

## References

- [pip --require-hashes documentation](https://pip.pypa.io/en/stable/topics/secure-installs/)
- [pip-tools documentation](https://pip-tools.readthedocs.io/)
- [Supply chain security best practices](https://slsa.dev/)
- Related fix: `.github/workflows/DEPENDENCY_HASH_PINNING_FIX.md`
