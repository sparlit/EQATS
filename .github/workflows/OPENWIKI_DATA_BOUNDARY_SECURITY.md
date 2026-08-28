# OpenWiki Data Boundary Security

## Overview

This document describes the security controls implemented to prevent sensitive repository content from being sent to external inference and tracing services during OpenWiki documentation generation.

## Security Issue

The OpenWiki workflow processes repository content and sends it to external services:
- **Inference Provider** (NVIDIA/OpenRouter): Receives repository-derived prompts and code excerpts for documentation generation
- **LangSmith Tracing** (optional): Receives invocation inputs, outputs, and intermediate results for observability

Without proper controls, this creates a third-party data boundary risk for:
- Proprietary source code and algorithms
- Internal comments and documentation
- Credentials and API keys accidentally committed
- Database files with sensitive data
- Configuration files with secrets

## Implemented Controls

### 1. Path Exclusion via .openwikiignore

A `.openwikiignore` file is dynamically generated before OpenWiki execution to exclude sensitive paths:

**Excluded Categories:**
- **Credentials**: `**/SECURITY*.md`, `**/CREDENTIALS*.md`, `*credentials*.py`, `migrate_credentials.py`
- **Databases**: `*.db`, `*.db-journal`, `*.db-shm`, `*.db-wal`
- **Environment Files**: `.env`, `.env.*`, `**/*.env`, `config.py`
- **Security Tests**: `test_credential*.py`, `test_*_security.py`
- **Build Artifacts**: `__pycache__/`, `*.pyc`, `node_modules/`, `.venv/`, `target/`, `*.exe`, `*.pyd`
- **Logs**: `*.log`, `council_logs/`
- **Proprietary Code**: `institutional_integrations/`, `brain*.py`, `predictive_brain.py`, `eqats_planes.py`, `indicators.py`
- **Binaries**: `*.ex5`, `*.mq5`, `eqats_rust_core/`
- **API Files**: `ft.txt`

### 2. LangSmith Tracing Disabled by Default

LangSmith tracing is **disabled by default** to prevent repository content from being sent to LangSmith's external tracing service. The following environment variables are commented out:

```yaml
# LANGSMITH_API_KEY: ${{ secrets.LANGSMITH_API_KEY }}
# LANGCHAIN_PROJECT: openwiki
# LANGCHAIN_TRACING_V2: "true"
```

**To enable tracing**, you must:
1. Review LangSmith's data retention and privacy policy
2. Verify that your organization's data classification policy permits external tracing
3. Uncomment the environment variables in the workflow file
4. Document the decision and obtain necessary approvals

### 3. Security Warnings in Workflow Comments

The workflow includes explicit security warnings documenting:
- Which external services receive repository content
- What data boundary controls are in place
- Recommendations for private repositories
- Guidance on self-hosted alternatives

## Recommendations for Private Repositories

For repositories containing proprietary or sensitive information, consider:

### 1. Self-Hosted Inference Provider
- Deploy a self-hosted LLM (e.g., Ollama, vLLM, LocalAI)
- Configure OpenWiki to use the self-hosted endpoint
- Maintain full control over data boundaries
- See OPENWIKI_DATA_CLASSIFICATION_POLICY.md for approved self-hosted solutions

### 2. Additional Secret Redaction
- Implement pre-processing to redact patterns like API keys, tokens, passwords
- Use tools like `git-secrets` or `truffleHog` to scan for leaked credentials
- Add custom redaction rules to `.openwikiignore`

### 3. Data Classification Policy
- Establish formal policies for what data can be sent to external services
- Document approved providers and retention requirements
- Require security review for new external service integrations
- **See OPENWIKI_DATA_CLASSIFICATION_POLICY.md for the formal policy framework**

### 4. Audit OpenWiki File Access
- Monitor which files OpenWiki actually accesses during execution
- Verify that `.openwikiignore` is being respected
- Review generated documentation for unintended sensitive content

### 5. Network-Level Controls
- Use network policies to restrict outbound connections to approved endpoints
- Implement egress filtering in CI/CD environments
- Monitor and log all external API calls

## Verification

To verify the controls are working:

1. **Check .openwikiignore is created**:
   ```bash
   # In the workflow, verify the file exists
   ls -la .openwikiignore
   cat .openwikiignore
   ```

2. **Verify LangSmith is disabled**:
   ```bash
   # Check that LANGCHAIN_TRACING_V2 is not set
   env | grep LANGCHAIN
   ```

3. **Review generated documentation**:
   - Inspect the generated files for sensitive content
   - Verify that excluded files are not referenced
   - Check for leaked credentials or proprietary code

4. **Monitor external API calls**:
   - Use network monitoring to verify only approved endpoints are contacted
   - Review API logs for unexpected data transfers

## Incident Response

If sensitive data is inadvertently sent to external services:

1. **Immediate Actions**:
   - Disable the workflow immediately
   - Rotate any exposed credentials
   - Contact the external service provider to request data deletion

2. **Investigation**:
   - Determine what data was exposed
   - Identify the root cause (missing exclusion, configuration error, etc.)
   - Document the incident timeline

3. **Remediation**:
   - Update `.openwikiignore` to prevent recurrence
   - Implement additional controls as needed
   - Test the fix in a non-production environment

4. **Communication**:
   - Notify affected stakeholders
   - Document lessons learned
   - Update security policies as needed

## Maintenance

This security configuration should be reviewed:
- **Quarterly**: Verify exclusion patterns are still appropriate
- **When adding new sensitive files**: Update `.openwikiignore`
- **When changing providers**: Review new provider's data policies
- **After security incidents**: Implement additional controls as needed

## References

- OpenWiki Documentation: https://github.com/openwiki/openwiki
- LangSmith Privacy Policy: https://www.langchain.com/privacy
- NVIDIA API Terms: https://www.nvidia.com/en-us/data-center/products/ai-enterprise/terms-of-use/
- GitHub Actions Security: https://docs.github.com/en/actions/security-guides
- **OPENWIKI_DATA_CLASSIFICATION_POLICY.md**: Formal data classification and retention policy

## Contact

For questions or concerns about OpenWiki data boundary security:
- Review this document and the workflow comments
- Consult your organization's security team
- File an issue in the repository for security improvements
