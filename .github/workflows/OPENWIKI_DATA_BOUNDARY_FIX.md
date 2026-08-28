# Security Fix: OpenWiki Data Boundary Controls

## Summary

This patch mitigates unrestricted private repository content exfiltration to external inference and tracing services by implementing path exclusions, disabling LangSmith tracing by default, and adding explicit security warnings.

## Vulnerability

**Title:** Unrestricted private repository content is sent to external inference and tracing services

**Root Cause:** The OpenWiki workflow checked out the full repository and sent content to:
- NVIDIA/OpenRouter inference API (for LLM processing)
- LangSmith tracing service (for observability)

Without path exclusions, secret redaction, or data boundary controls, sensitive content could be exfiltrated:
- Credentials and API keys
- Proprietary trading algorithms
- Database files with sensitive data
- Configuration files with secrets
- Internal comments and documentation

## Changes Made

### 1. Modified Workflows

#### `.github/workflows/openwiki-update.yml`
- Added "Create OpenWiki exclusion configuration" step that generates `.openwikiignore` before OpenWiki execution
- Disabled LangSmith tracing by default (commented out `LANGSMITH_API_KEY`, `LANGCHAIN_PROJECT`, `LANGCHAIN_TRACING_V2`)
- Added comprehensive security warnings documenting external service usage and data flows
- Added recommendations for private repositories (self-hosted providers, secret redaction, data classification policies)

#### `openwiki-update.yml` (root-level)
- Applied identical changes as above for consistency
- Disabled LangSmith tracing by default
- Added path exclusion configuration step
- Added security warnings and recommendations

### 2. Created Files

#### `.openwikiignore`
A committed baseline exclusion file that prevents sensitive paths from being processed:
- Credential files: `**/SECURITY*.md`, `**/CREDENTIALS*.md`, `*credentials*.py`, `migrate_credentials.py`
- Databases: `*.db`, `*.db-journal`, `*.db-shm`, `*.db-wal`
- Environment files: `.env`, `.env.*`, `config.py`
- Security tests: `test_credential*.py`, `test_*_security.py`
- Build artifacts: `__pycache__/`, `*.pyc`, `node_modules/`, `.venv/`, `target/`, `*.exe`, `*.pyd`
- Logs: `*.log`, `council_logs/`
- Proprietary code: `institutional_integrations/`, `brain*.py`, `predictive_brain.py`, `eqats_planes.py`, `indicators.py`
- Binaries: `*.ex5`, `*.mq5`, `eqats_rust_core/`
- API files: `ft.txt`

#### `.github/workflows/OPENWIKI_DATA_BOUNDARY_SECURITY.md`
Comprehensive security documentation covering:
- Overview of the security issue
- Implemented controls (path exclusions, disabled tracing, security warnings)
- Recommendations for private repositories
- Verification procedures
- Incident response procedures
- Maintenance schedule
- References and contact information

### 3. Updated Documentation

#### `.github/workflows/OPENWIKI_SECURITY.md`
- Added new section "5. Data Boundary Controls (NEW)"
- Documented excluded paths and their rationale
- Documented LangSmith tracing policy (disabled by default)
- Added reference to detailed data boundary security documentation

## Security Controls Implemented

### Path Exclusion
The workflow now dynamically generates a `.openwikiignore` file before OpenWiki execution, excluding:
- 7 categories of sensitive files
- 50+ specific patterns
- Comprehensive coverage of credentials, databases, proprietary code, and configuration files

### LangSmith Tracing Disabled
- `LANGCHAIN_TRACING_V2` is commented out by default
- Explicit security warning added explaining the risk
- Clear instructions for enabling (requires policy review and approval)

### Security Warnings
- Explicit documentation of which external services receive data
- Clear explanation of data boundary controls
- Recommendations for private repositories
- Guidance on self-hosted alternatives

### Defense in Depth
The fix implements multiple layers of protection:
1. **Path exclusion** - Prevents sensitive files from being read
2. **Tracing disabled** - Prevents prompts/outputs from being sent to LangSmith
3. **Documentation** - Ensures operators understand the risks
4. **Committed baseline** - Provides a template for customization

## Verification

To verify the fix is working:

1. **Check .openwikiignore is created**:
   ```bash
   # The workflow creates this file before OpenWiki runs
   cat .openwikiignore
   ```

2. **Verify LangSmith is disabled**:
   ```bash
   # Check workflow files for commented-out tracing variables
   grep -A 3 "LANGCHAIN_TRACING_V2" .github/workflows/openwiki-update.yml
   ```

3. **Review generated documentation**:
   - Inspect generated files for sensitive content
   - Verify excluded files are not referenced
   - Check for leaked credentials

4. **Monitor external API calls**:
   - Use network monitoring to verify only approved endpoints are contacted
   - Review API logs for unexpected data transfers

## Recommendations

For organizations using this workflow with private repositories:

1. **Review and customize .openwikiignore** - Add additional patterns specific to your repository
2. **Consider self-hosted inference** - Deploy Ollama, vLLM, or LocalAI for full data control
3. **Implement secret redaction** - Use tools like git-secrets or truffleHog
4. **Establish data classification policy** - Document what data can be sent to external services
5. **Audit OpenWiki file access** - Monitor which files are actually accessed during execution
6. **Network-level controls** - Implement egress filtering in CI/CD environments

## Testing

The fix has been implemented in both workflow files:
- `.github/workflows/openwiki-update.yml` (canonical workflow)
- `openwiki-update.yml` (root-level workflow)

Both workflows now:
- Generate `.openwikiignore` before OpenWiki execution
- Disable LangSmith tracing by default
- Include comprehensive security warnings
- Provide clear guidance for private repositories

## Impact

**Before:**
- Full repository content accessible to OpenWiki
- All files sent to external inference API
- LangSmith tracing enabled, sending prompts/outputs to external service
- No documentation of data flows or risks

**After:**
- Sensitive files excluded via `.openwikiignore`
- LangSmith tracing disabled by default
- Explicit security warnings and documentation
- Clear guidance for private repositories
- Defense-in-depth approach with multiple layers of protection

## Files Modified

1. `.github/workflows/openwiki-update.yml` - Added path exclusions, disabled tracing, added warnings
2. `openwiki-update.yml` - Applied identical changes for consistency
3. `.github/workflows/OPENWIKI_SECURITY.md` - Updated with data boundary controls documentation

## Files Created

1. `.openwikiignore` - Baseline path exclusion configuration
2. `.github/workflows/OPENWIKI_DATA_BOUNDARY_SECURITY.md` - Comprehensive security documentation

## Compliance

This fix addresses the pentest finding by:
- ✅ Implementing path exclusions to prevent sensitive file access
- ✅ Disabling external tracing service by default
- ✅ Adding explicit security warnings and documentation
- ✅ Providing guidance on self-hosted providers and data classification policies
- ✅ Establishing a data boundary control framework

The fix does not:
- ❌ Implement secret redaction (recommended as additional control)
- ❌ Enforce self-hosted provider (left as operator choice)
- ❌ Implement network-level egress filtering (infrastructure-level control)

## Next Steps

Organizations should:
1. Review and customize `.openwikiignore` for their specific needs
2. Decide whether to enable LangSmith tracing (requires policy review)
3. Consider implementing additional controls (secret redaction, self-hosted inference)
4. Establish formal data classification and retention policies
5. Monitor OpenWiki file access patterns in production

## References

- Pentest Finding: "Unrestricted private repository content is sent to external inference and tracing services"
- OpenWiki Documentation: https://github.com/openwiki/openwiki
- LangSmith Privacy Policy: https://www.langchain.com/privacy
- GitHub Actions Security: https://docs.github.com/en/actions/security-guides
