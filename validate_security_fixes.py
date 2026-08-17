#!/usr/bin/env python3
"""
Security Fix Validation Script
Validates that hardcoded credentials have been removed and environment variables are properly configured.
"""

import os
import sys
from dotenv import load_dotenv

def check_env_file_exists():
    """Check if .env file exists"""
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        print("[PASS] .env file exists")
        return True
    else:
        print("[FAIL] .env file does not exist")
        print("  Please copy .env.example to .env and fill in your values")
        return False

def check_env_variables():
    """Check if required environment variables are set"""
    load_dotenv()
    
    required_vars = {
        'ENCRYPTION_KEY': 'Security key for encryption',
        'SALT': 'Salt for password hashing',
        'ADMIN_USERNAME': 'Admin username',
        'ADMIN_PASSWORD': 'Admin password',
        'ADMIN_PIN': 'Admin PIN',
        'MT5_SERVER': 'MT5 server',
        'MT5_ACCOUNT_ID': 'MT5 account ID',
        'MT5_PASSWORD': 'MT5 password',
    }
    
    all_set = True
    for var, description in required_vars.items():
        value = os.getenv(var)
        if value:
            # Don't print actual values for security
            print(f"[PASS] {var} is set ({description})")
        else:
            print(f"[FAIL] {var} is NOT set ({description})")
            all_set = False
    
    return all_set

def check_gitignore():
    """Check if .env is in .gitignore"""
    gitignore_path = os.path.join(os.path.dirname(__file__), '.gitignore')
    if not os.path.exists(gitignore_path):
        print("[FAIL] .gitignore does not exist")
        return False
    
    with open(gitignore_path, 'r') as f:
        gitignore_content = f.read()
    
    if '.env' in gitignore_content:
        print("[PASS] .env is in .gitignore")
        return True
    else:
        print("[FAIL] .env is NOT in .gitignore")
        return False

def check_no_hardcoded_credentials():
    """Check that hardcoded credentials are removed from database.py"""
    database_path = os.path.join(os.path.dirname(__file__), 'database.py')
    
    with open(database_path, 'r') as f:
        content = f.read()
    
    # Check for hardcoded credentials
    hardcoded_checks = {
        'QUANT_OPERATOR': 'Hardcoded admin username',
        '"admin"': 'Hardcoded admin password',
        '"741295"': 'Hardcoded admin PIN',
        'EAQTS-Demo-Server': 'Hardcoded server',
        '"10928471"': 'Hardcoded account ID',
        '"demoPass123!"': 'Hardcoded password',
        'EAQTS_CIPHER_KEY_2026': 'Hardcoded encryption key',
        'EAQTS_SOVEREIGN_SALT_2026': 'Hardcoded salt',
    }
    
    found_issues = []
    for check, description in hardcoded_checks.items():
        if check in content:
            found_issues.append(f"[FAIL] Found {description}: {check}")
    
    if found_issues:
        for issue in found_issues:
            print(issue)
        return False
    else:
        print("[PASS] No hardcoded credentials found in database.py")
        return True

def check_aes_encryption():
    """Check that AES-256-GCM encryption is implemented"""
    database_path = os.path.join(os.path.dirname(__file__), 'database.py')
    secure_encryption_path = os.path.join(os.path.dirname(__file__), 'secure_encryption.py')
    
    # Check secure_encryption.py exists
    if not os.path.exists(secure_encryption_path):
        print("[FAIL] secure_encryption.py does not exist")
        return False
    
    print("[PASS] secure_encryption.py exists")
    
    # Check database.py imports secure_encryption
    with open(database_path, 'r') as f:
        content = f.read()
    
    if 'from secure_encryption import' in content:
        print("[PASS] database.py imports secure_encryption module")
    else:
        print("[FAIL] database.py does not import secure_encryption module")
        return False
    
    # Check that AESGCM is used
    if 'AESGCM' in content or 'encrypt_text' in content:
        print("[PASS] AES-256-GCM encryption is used")
    else:
        print("[FAIL] AES-256-GCM encryption not found")
        return False
    
    return True

def check_bcrypt_passwords():
    """Check that bcrypt password hashing is implemented"""
    database_path = os.path.join(os.path.dirname(__file__), 'database.py')
    password_manager_path = os.path.join(os.path.dirname(__file__), 'password_manager.py')
    
    # Check password_manager.py exists
    if not os.path.exists(password_manager_path):
        print("[FAIL] password_manager.py does not exist")
        return False
    
    print("[PASS] password_manager.py exists")
    
    # Check database.py imports password_manager
    try:
        with open(database_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        with open(database_path, 'r', encoding='latin-1') as f:
            content = f.read()
    
    if 'from password_manager import' in content:
        print("[PASS] database.py imports password_manager module")
    else:
        print("[FAIL] database.py does not import password_manager module")
        return False
    
    # Check that bcrypt is used
    if 'bcrypt' in content or 'PasswordManager' in content:
        print("[PASS] Bcrypt password hashing is used")
    else:
        print("[FAIL] Bcrypt password hashing not found")
        return False
    
    # Check that verify_credential function exists
    if 'verify_credential' in content:
        print("[PASS] verify_credential function implemented")
    else:
        print("[FAIL] verify_credential function not found")
        return False
    
    return True

def check_mfa_implementation():
    """Check that multi-factor authentication is implemented"""
    database_path = os.path.join(os.path.dirname(__file__), 'database.py')
    mfa_manager_path = os.path.join(os.path.dirname(__file__), 'mfa_manager.py')
    
    # Check mfa_manager.py exists
    if not os.path.exists(mfa_manager_path):
        print("[FAIL] mfa_manager.py does not exist")
        return False
    
    print("[PASS] mfa_manager.py exists")
    
    # Check database.py imports mfa_manager
    with open(database_path, 'r') as f:
        content = f.read()
    
    if 'from mfa_manager import' in content:
        print("[PASS] database.py imports mfa_manager module")
    else:
        print("[FAIL] database.py does not import mfa_manager module")
        return False
    
    # Check for MFA functions
    mfa_functions = [
        'setup_user_mfa',
        'verify_user_mfa',
        'disable_user_mfa',
        'is_user_mfa_enabled',
        'regenerate_user_backup_codes'
    ]
    
    all_present = True
    for func in mfa_functions:
        if func in content:
            print(f"[PASS] {func} function implemented")
        else:
            print(f"[FAIL] {func} function not found")
            all_present = False
    
    # Check requirements.txt for pyotp and qrcode
    requirements_path = os.path.join(os.path.dirname(__file__), 'requirements.txt')
    with open(requirements_path, 'r') as f:
        req_content = f.read()
    
    if 'pyotp' in req_content:
        print("[PASS] pyotp is in requirements.txt")
    else:
        print("[FAIL] pyotp is NOT in requirements.txt")
        all_present = False
    
    if 'qrcode' in req_content:
        print("[PASS] qrcode is in requirements.txt")
    else:
        print("[FAIL] qrcode is NOT in requirements.txt")
        all_present = False
    
    return all_present

def check_input_validation():
    """Check that input validation is implemented"""
    input_validation_path = os.path.join(os.path.dirname(__file__), 'input_validation.py')
    database_path = os.path.join(os.path.dirname(__file__), 'database.py')
    connector_path = os.path.join(os.path.dirname(__file__), 'connector.py')
    
    # Check input_validation.py exists
    if not os.path.exists(input_validation_path):
        print("[FAIL] input_validation.py does not exist")
        return False
    
    print("[PASS] input_validation.py exists")
    
    # Check database.py imports input_validation
    with open(database_path, 'r') as f:
        db_content = f.read()
    
    if 'from input_validation import' in db_content:
        print("[PASS] database.py imports input_validation module")
    else:
        print("[FAIL] database.py does not import input_validation module")
        return False
    
    # Check connector.py imports input_validation
    with open(connector_path, 'r') as f:
        conn_content = f.read()
    
    if 'from input_validation import' in conn_content:
        print("[PASS] connector.py imports input_validation module")
    else:
        print("[FAIL] connector.py does not import input_validation module")
        return False
    
    # Check for validation functions in input_validation.py
    with open(input_validation_path, 'r') as f:
        iv_content = f.read()
    
    validation_functions = [
        'validate_symbol',
        'validate_price',
        'validate_lots',
        'validate_order',
        'validate_username',
        'validate_password',
        'validate_pin',
        'validate_mfa_token'
    ]
    
    all_present = True
    for func in validation_functions:
        if func in iv_content:
            print(f"[PASS] {func} function implemented")
        else:
            print(f"[FAIL] {func} function not found")
            all_present = False
    
    # Check for Pydantic models
    pydantic_models = [
        'TradingSymbol',
        'OrderValidation',
        'UsernameValidation',
        'PasswordValidation'
    ]
    
    for model in pydantic_models:
        if model in iv_content:
            print(f"[PASS] {model} Pydantic model implemented")
        else:
            print(f"[FAIL] {model} Pydantic model not found")
            all_present = False
    
    return all_present

def check_vacuum_removed():
    """Check that SQLite VACUUM is removed from main loop"""
    brain_self_healer_path = os.path.join(os.path.dirname(__file__), 'institutional_integrations', 'brain_self_healer.py')
    database_maintenance_path = os.path.join(os.path.dirname(__file__), 'database_maintenance.py')
    
    # Check brain_self_healer.py exists
    if not os.path.exists(brain_self_healer_path):
        print("[FAIL] brain_self_healer.py does not exist")
        return False
    
    print("[PASS] brain_self_healer.py exists")
    
    # Check that VACUUM is not in the main loop
    try:
        with open(brain_self_healer_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        # Fallback to latin-1 if utf-8 fails
        with open(brain_self_healer_path, 'r', encoding='latin-1') as f:
            content = f.read()
    
    # Check for VACUUM in execute statements
    if 'cursor.execute("VACUUM")' in content:
        print("[FAIL] VACUUM still in main loop (should be removed)")
        return False
    
    print("[PASS] VACUUM removed from main loop")
    
    # Check for maintenance script
    if not os.path.exists(database_maintenance_path):
        print("[FAIL] database_maintenance.py does not exist")
        return False
    
    print("[PASS] database_maintenance.py exists")
    
    # Check maintenance script has VACUUM function
    with open(database_maintenance_path, 'r', encoding='utf-8') as f:
        maint_content = f.read()
    
    if 'def vacuum_database' in maint_content:
        print("[PASS] vacuum_database function implemented in maintenance script")
    else:
        print("[FAIL] vacuum_database function not found in maintenance script")
        return False
    
    if 'run_full_maintenance' in maint_content:
        print("[PASS] run_full_maintenance function implemented")
    else:
        print("[FAIL] run_full_maintenance function not found")
        return False
    
    return True

def check_kill_switch_implementation():
    """Check that kill switch is implemented"""
    kill_switch_path = os.path.join(os.path.dirname(__file__), 'kill_switch.py')
    connector_path = os.path.join(os.path.dirname(__file__), 'connector.py')
    
    # Check kill_switch.py exists
    if not os.path.exists(kill_switch_path):
        print("[FAIL] kill_switch.py does not exist")
        return False
    
    print("[PASS] kill_switch.py exists")
    
    # Check connector.py imports kill_switch
    try:
        with open(connector_path, 'r', encoding='utf-8') as f:
            conn_content = f.read()
    except UnicodeDecodeError:
        with open(connector_path, 'r', encoding='latin-1') as f:
            conn_content = f.read()
    
    if 'from kill_switch import' in conn_content:
        print("[PASS] connector.py imports kill_switch module")
    else:
        print("[FAIL] connector.py does not import kill_switch module")
        return False
    
    # Check for kill switch functions in kill_switch.py
    with open(kill_switch_path, 'r', encoding='utf-8') as f:
        ks_content = f.read()
    
    kill_switch_functions = [
        'activate',
        'deactivate',
        'is_activated',
        'is_order_allowed',
        'get_state',
        'get_activation_info'
    ]
    
    all_present = True
    for func in kill_switch_functions:
        if func in ks_content:
            print(f"[PASS] {func} function implemented")
        else:
            print(f"[FAIL] {func} function not found")
            all_present = False
    
    # Check for kill switch states
    if 'KillSwitchState' in ks_content:
        print("[PASS] KillSwitchState enum implemented")
    else:
        print("[FAIL] KillSwitchState enum not found")
        all_present = False
    
    # Check for kill switch reasons
    if 'KillSwitchReason' in ks_content:
        print("[PASS] KillSwitchReason enum implemented")
    else:
        print("[FAIL] KillSwitchReason enum not found")
        all_present = False
    
    # Check for database persistence
    if 'kill_switch_events' in ks_content and 'kill_switch_state' in ks_content:
        print("[PASS] Database persistence implemented")
    else:
        print("[FAIL] Database persistence not found")
        all_present = False
    
    return all_present

def check_fake_integrations_removed():
    """Check that fake institutional integrations are disabled"""
    comprehensive_suite_path = os.path.join(os.path.dirname(__file__), 'institutional_integrations', 'comprehensive_suite.py')
    rust_bridge_path = os.path.join(os.path.dirname(__file__), 'institutional_integrations', 'rust_bridge.py')
    go_gateway_path = os.path.join(os.path.dirname(__file__), 'institutional_integrations', 'go_gateway.py')
    quantum_engine_path = os.path.join(os.path.dirname(__file__), 'institutional_integrations', 'quantum_quantum_engine.py')
    
    # Check comprehensive_suite.py for DISABLED instead of MOCKED
    try:
        with open(comprehensive_suite_path, 'r', encoding='utf-8') as f:
            cs_content = f.read()
    except UnicodeDecodeError:
        with open(comprehensive_suite_path, 'r', encoding='latin-1') as f:
            cs_content = f.read()
    
    if 'MOCKED' in cs_content:
        print("[FAIL] MOCKED still found in comprehensive_suite.py")
        return False
    
    print("[PASS] MOCKED removed from comprehensive_suite.py")
    
    if 'DISABLED' in cs_content:
        print("[PASS] DISABLED status implemented in comprehensive_suite.py")
    else:
        print("[FAIL] DISABLED status not found in comprehensive_suite.py")
        return False
    
    # Check rust_bridge.py is disabled
    try:
        with open(rust_bridge_path, 'r', encoding='utf-8') as f:
            rust_content = f.read()
    except UnicodeDecodeError:
        with open(rust_bridge_path, 'r', encoding='latin-1') as f:
            rust_content = f.read()
    
    if 'DISABLED' in rust_content and 'fake' in rust_content.lower():
        print("[PASS] Rust bridge disabled with security warning")
    else:
        print("[FAIL] Rust bridge not properly disabled")
        return False
    
    # Check go_gateway.py is disabled
    try:
        with open(go_gateway_path, 'r', encoding='utf-8') as f:
            go_content = f.read()
    except UnicodeDecodeError:
        with open(go_gateway_path, 'r', encoding='latin-1') as f:
            go_content = f.read()
    
    if 'DISABLED' in go_content and 'fake' in go_content.lower():
        print("[PASS] Go gateway disabled with security warning")
    else:
        print("[FAIL] Go gateway not properly disabled")
        return False
    
    # Check quantum_quantum_engine.py is disabled
    try:
        with open(quantum_engine_path, 'r', encoding='utf-8') as f:
            quantum_content = f.read()
    except UnicodeDecodeError:
        with open(quantum_engine_path, 'r', encoding='latin-1') as f:
            quantum_content = f.read()
    
    if 'DISABLED' in quantum_content and 'fake' in quantum_content.lower():
        print("[PASS] Quantum engine disabled with security warning")
    else:
        print("[FAIL] Quantum engine not properly disabled")
        return False
    
    # Check for integration manager
    integration_manager_path = os.path.join(os.path.dirname(__file__), 'integration_manager.py')
    if not os.path.exists(integration_manager_path):
        print("[FAIL] integration_manager.py does not exist")
        return False
    
    print("[PASS] integration_manager.py exists")
    
    return True

def check_ml_models_fixed():
    """Check that fake ML models are disabled or have warnings"""
    machine_learning_path = os.path.join(os.path.dirname(__file__), 'institutional_integrations', 'machine_learning.py')
    predictive_brain_path = os.path.join(os.path.dirname(__file__), 'predictive_brain.py')
    
    # Check machine_learning.py for disabled fake predictions
    try:
        with open(machine_learning_path, 'r', encoding='utf-8') as f:
            ml_content = f.read()
    except UnicodeDecodeError:
        with open(machine_learning_path, 'r', encoding='latin-1') as f:
            ml_content = f.read()
    
    if 'DISABLED' in ml_content and 'generate_multi_model_ensemble_prediction' in ml_content:
        print("[PASS] Fake ML ensemble prediction disabled")
    else:
        print("[FAIL] Fake ML ensemble prediction not properly disabled")
        return False
    
    if 'SECURITY FIX' in ml_content:
        print("[PASS] Security warning added to machine_learning.py")
    else:
        print("[FAIL] Security warning not found in machine_learning.py")
        return False
    
    # Check predictive_brain.py for persistence warnings
    try:
        with open(predictive_brain_path, 'r', encoding='utf-8') as f:
            pb_content = f.read()
    except UnicodeDecodeError:
        with open(predictive_brain_path, 'r', encoding='latin-1') as f:
            pb_content = f.read()
    
    if 'SECURITY WARNING' in pb_content and 'not persisted' in pb_content:
        print("[PASS] Persistence warning added to predictive_brain.py")
    else:
        print("[FAIL] Persistence warning not found in predictive_brain.py")
        return False
    
    if 'is_predictor_trained' in pb_content:
        print("[PASS] is_predictor_trained function implemented")
    else:
        print("[FAIL] is_predictor_trained function not found")
        return False
    
    if 'disable_predictor' in pb_content:
        print("[PASS] disable_predictor function implemented")
    else:
        print("[FAIL] disable_predictor function not found")
        return False
    
    return True

def check_external_data_feeds():
    """Check that external data feeds are properly implemented"""
    web_api_path = os.path.join(os.path.dirname(__file__), 'institutional_integrations', 'web_api.py')
    requirements_path = os.path.join(os.path.dirname(__file__), 'requirements.txt')
    
    # Check web_api.py for mock removal
    try:
        with open(web_api_path, 'r', encoding='utf-8') as f:
            web_content = f.read()
    except UnicodeDecodeError:
        with open(web_api_path, 'r', encoding='latin-1') as f:
            web_content = f.read()
    
    # Check that mock fallback is removed
    if 'Graceful fallback mock' in web_content or '[1.0952, 1.0948' in web_content:
        print("[FAIL] Mock fallback still present in web_api.py")
        return False
    
    print("[PASS] Mock fallback removed from web_api.py")
    
    # Check for error handling instead of mock
    if 'yfinance library not installed' in web_content:
        print("[PASS] Error handling implemented instead of mock")
    else:
        print("[FAIL] Error handling not found in web_api.py")
        return False
    
    # Check for security warning
    if 'SECURITY FIX' in web_content:
        print("[PASS] Security warning added to web_api.py")
    else:
        print("[FAIL] Security warning not found in web_api.py")
        return False
    
    # Check for yfinance in requirements
    with open(requirements_path, 'r') as f:
        req_content = f.read()
    
    if 'yfinance' in req_content:
        print("[PASS] yfinance is in requirements.txt")
    else:
        print("[FAIL] yfinance is NOT in requirements.txt")
        return False
    
    return True

def check_requirements_updated():
    """Check if requirements.txt includes security packages"""
    requirements_path = os.path.join(os.path.dirname(__file__), 'requirements.txt')
    
    with open(requirements_path, 'r') as f:
        content = f.read()
    
    required_packages = ['python-dotenv', 'cryptography', 'bcrypt', 'pydantic', 'yfinance']
    
    all_present = True
    for package in required_packages:
        if package in content:
            print(f"[PASS] {package} is in requirements.txt")
        else:
            print(f"[FAIL] {package} is NOT in requirements.txt")
            all_present = False
    
    return all_present

def main():
    print("=" * 60)
    print("SECURITY FIX VALIDATION")
    print("=" * 60)
    print()
    
    results = []
    
    print("Step 1: Check .env file")
    results.append(check_env_file_exists())
    print()
    
    print("Step 2: Check environment variables")
    results.append(check_env_variables())
    print()
    
    print("Step 3: Check .gitignore")
    results.append(check_gitignore())
    print()
    
    print("Step 4: Check for hardcoded credentials")
    results.append(check_no_hardcoded_credentials())
    print()
    
    print("Step 5: Check AES-256-GCM encryption")
    results.append(check_aes_encryption())
    print()
    
    print("Step 6: Check bcrypt password hashing")
    results.append(check_bcrypt_passwords())
    print()
    
    print("Step 7: Check MFA implementation")
    results.append(check_mfa_implementation())
    print()
    
    print("Step 8: Check input validation")
    results.append(check_input_validation())
    print()
    
    print("Step 9: Check VACUUM removed from main loop")
    results.append(check_vacuum_removed())
    print()
    
    print("Step 10: Check kill switch implementation")
    results.append(check_kill_switch_implementation())
    print()
    
    print("Step 11: Check fake integrations removed")
    results.append(check_fake_integrations_removed())
    print()
    
    print("Step 12: Check ML models fixed")
    results.append(check_ml_models_fixed())
    print()
    
    print("Step 13: Check external data feeds")
    results.append(check_external_data_feeds())
    print()
    
    print("Step 14: Check requirements.txt")
    results.append(check_requirements_updated())
    print()
    
    print("=" * 60)
    if all(results):
        print("[PASS] ALL CHECKS PASSED")
        print("Security fix implementation is complete!")
        return 0
    else:
        print("[FAIL] SOME CHECKS FAILED")
        print("Please address the issues above")
        return 1

if __name__ == '__main__':
    sys.exit(main())
