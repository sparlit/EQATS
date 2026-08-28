# OpenWiki Data Classification and Retention Policy

## Purpose

This document establishes a formal data classification and retention policy for the OpenWiki documentation workflow, addressing the third-party data boundary risks associated with sending repository content to external inference services.

## Scope

This policy applies to all OpenWiki workflow executions that process repository content and send it to external inference providers (NVIDIA, OpenRouter, or other LLM services).

## Data Classification

### Data Categories Processed by OpenWiki

#### 1. **EXCLUDED - High Sensitivity** (Never sent to external services)
Files matching `.openwikiignore` patterns are excluded from processing:
- **Credentials**: API keys, passwords, authentication tokens, security files
- **Databases**: SQLite files, database journals, database content
- **Environment Files**: `.env` files, configuration files with secrets
- **Proprietary Algorithms**: Trading strategies, brain modules, prediction engines
- **Compiled Binaries**: Executable files, compiled Rust code
- **Logs**: Runtime logs that may contain sensitive data
- **Build Artifacts**: Dependencies, compiled code, temporary files

**Control**: Path exclusion via `.openwikiignore` (generated before OpenWiki execution)

#### 2. **TRANSMITTED - Medium Sensitivity** (Sent to approved external providers only)
Non-excluded repository content that OpenWiki processes:
- **Source Code**: Python, JavaScript, YAML, and other source files
- **Documentation**: Markdown files, README files, code comments
- **Configuration**: Non-sensitive configuration files
- **Workflow Files**: GitHub Actions workflows

**Control**: Transmitted to approved external providers with documented retention policies

#### 3. **PROHIBITED - Critical Sensitivity** (Must never be transmitted)
Content that should never exist in the repository or must be excluded:
- **Production Credentials**: Live API keys, production passwords
- **Customer Data**: PII, financial data, customer information
- **Regulated Data**: HIPAA, PCI-DSS, or other regulated information
- **Trade Secrets**: Confidential business information

**Control**: Should not be committed to repository; if accidentally committed, must be added to `.openwikiignore` immediately

## Approved External Providers

### Current Approved Providers

#### NVIDIA Inference API
- **Service**: NVIDIA NIM (NVIDIA Inference Microservices)
- **Model**: nvidia/nemotron-3-ultra-550b-a55b
- **Data Retention**: Subject to NVIDIA API Terms of Use
- **Terms**: https://www.nvidia.com/en-us/data-center/products/ai-enterprise/terms-of-use/
- **Approval Status**: Approved for non-excluded repository content
- **Approval Date**: [To be documented by security team]
- **Review Date**: [Quarterly review required]

#### OpenRouter API
- **Service**: OpenRouter (LLM routing service)
- **Model**: z-ai/glm-5.2
- **Data Retention**: Subject to OpenRouter Terms of Service
- **Terms**: https://openrouter.ai/terms
- **Approval Status**: Approved for non-excluded repository content
- **Approval Date**: [To be documented by security team]
- **Review Date**: [Quarterly review required]

### Provider Approval Requirements

To add a new external provider, the following must be documented:
1. **Service Name and Endpoint**: Full provider details
2. **Data Retention Policy**: How long data is retained, where it's stored
3. **Privacy Policy**: Link to provider's privacy policy
4. **Terms of Service**: Link to provider's terms
5. **Security Review**: Internal security team approval
6. **Data Classification**: Confirmation that only Medium Sensitivity data will be sent
7. **Incident Response**: Provider's process for data deletion requests

### Prohibited Providers

The following are explicitly prohibited:
- **LangSmith Tracing** (disabled by default): Would send prompts/outputs to additional third party
- **Unapproved LLM Services**: Any provider not listed in "Approved External Providers"
- **Public LLM Interfaces**: ChatGPT web interface, Claude web interface, etc.

## Self-Hosted Provider Option (Recommended)

### Benefits
- **No External Data Transfer**: All data remains within controlled infrastructure
- **Full Data Control**: Complete control over data retention and deletion
- **No Third-Party Terms**: Not subject to external provider terms
- **Audit Trail**: Full visibility into data processing

### Approved Self-Hosted Solutions
- **Ollama**: Local LLM inference (https://ollama.ai)
- **vLLM**: High-performance LLM serving (https://github.com/vllm-project/vllm)
- **LocalAI**: OpenAI-compatible local inference (https://localai.io)
- **LM Studio**: Desktop LLM application (https://lmstudio.ai)

### Configuration
To use a self-hosted provider:
1. Deploy the self-hosted inference service
2. Update `OPENWIKI_PROVIDER` to the local endpoint (e.g., `http://localhost:11434`)
3. Remove or comment out external provider API keys
4. Verify `.openwikiignore` patterns are still appropriate
5. Document the self-hosted configuration in this policy

## Data Retention

### External Provider Retention
- **Retention Period**: Subject to provider's terms (see Approved External Providers)
- **Data Deletion**: Must be requested from provider according to their process
- **Audit Trail**: No direct audit trail of provider's data handling

### Self-Hosted Provider Retention
- **Retention Period**: Configurable by organization
- **Data Deletion**: Under organization's control
- **Audit Trail**: Full audit trail available

### Retention Requirements
1. **Minimize Retention**: Configure providers to minimize data retention where possible
2. **Document Retention**: Document actual retention periods for each provider
3. **Deletion Process**: Establish process for requesting data deletion
4. **Incident Response**: Include data deletion in incident response procedures

## Compliance and Monitoring

### Quarterly Review
This policy must be reviewed quarterly to:
1. Verify approved providers are still appropriate
2. Update provider terms and retention policies
3. Review `.openwikiignore` patterns for completeness
4. Assess new self-hosted provider options
5. Document any security incidents or data exposures

### Monitoring Requirements
1. **Workflow Execution**: Monitor OpenWiki workflow runs for failures or anomalies
2. **File Access**: Audit which files OpenWiki actually processes
3. **Network Traffic**: Monitor outbound connections to verify only approved endpoints
4. **Secret Scanning**: Run git-secrets or truffleHog to detect leaked credentials
5. **Generated Documentation**: Review generated files for unintended sensitive content

### Incident Response
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
   - Update this policy as needed

## Enforcement

### Technical Controls
1. **Path Exclusion**: `.openwikiignore` file generated before OpenWiki execution
2. **Tracing Disabled**: LangSmith tracing disabled by default
3. **Read-Only Permissions**: OpenWiki job has only read permissions
4. **No Token Persistence**: GitHub token not persisted in .git/config
5. **Locked Dependencies**: OpenWiki installed from committed lockfile

### Policy Controls
1. **Approved Providers**: Only approved providers may be configured
2. **Security Review**: New providers require security team approval
3. **Quarterly Review**: Policy reviewed quarterly
4. **Incident Response**: Documented process for data exposure incidents
5. **Documentation**: All provider approvals must be documented

### Audit Controls
1. **Workflow Logs**: All OpenWiki executions logged in GitHub Actions
2. **File Access**: Monitor which files are processed
3. **Network Monitoring**: Verify only approved endpoints contacted
4. **Secret Scanning**: Regular scans for leaked credentials
5. **Documentation Review**: Review generated files for sensitive content

## Recommendations for Private Repositories

For repositories containing proprietary or highly sensitive information:

### 1. Use Self-Hosted Provider (Highest Security)
- Eliminates external data transfer entirely
- Full control over data retention and deletion
- No third-party terms or privacy policies to manage
- Recommended for repositories with trade secrets or regulated data

### 2. Enhance Path Exclusions
- Review and customize `.openwikiignore` for your specific repository
- Add patterns for any proprietary or sensitive files
- Test exclusions before enabling workflow
- Document rationale for each exclusion pattern

### 3. Implement Secret Redaction
- Use git-secrets or truffleHog to scan for leaked credentials
- Implement pre-processing to redact patterns (API keys, tokens, passwords)
- Add custom redaction rules to `.openwikiignore`
- Run secret scanning in CI/CD pipeline

### 4. Network-Level Controls
- Implement egress filtering to approved endpoints only
- Use network policies to restrict outbound connections
- Monitor and log all external API calls
- Alert on connections to unapproved endpoints

### 5. Establish Formal Approval Process
- Require security team approval for external provider usage
- Document business justification for external data transfer
- Obtain necessary approvals from legal/compliance teams
- Review and renew approvals quarterly

## Policy Approval

This policy must be approved by:
- [ ] Security Team Lead
- [ ] Engineering Manager
- [ ] Legal/Compliance (if applicable)
- [ ] Data Protection Officer (if applicable)

**Approval Date**: [To be documented]  
**Next Review Date**: [Quarterly from approval date]  
**Policy Owner**: [Security Team]  
**Policy Version**: 1.0

## References

- OpenWiki Documentation: https://github.com/openwiki/openwiki
- NVIDIA API Terms: https://www.nvidia.com/en-us/data-center/products/ai-enterprise/terms-of-use/
- OpenRouter Terms: https://openrouter.ai/terms
- LangSmith Privacy Policy: https://www.langchain.com/privacy
- GitHub Actions Security: https://docs.github.com/en/actions/security-guides
- OPENWIKI_DATA_BOUNDARY_SECURITY.md: Detailed security controls documentation

## Contact

For questions or concerns about this policy:
- Review this document and the workflow security documentation
- Consult your organization's security team
- File an issue in the repository for policy improvements
- Contact the policy owner for clarification

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | [Date] | Security Team | Initial policy creation |
