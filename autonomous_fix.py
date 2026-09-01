import os
import sys
import subprocess
import json
from typing import Any
from openai import OpenAI  # Or anthropic, google-genai, etc.

# Configuration
MAX_RETRIES = 3
TEST_COMMAND = "python -m pytest -n auto -vv -s --count=100 --full-trace --cache-clear -k 'not gui_integration' --json-report --json-report-file=.pytest_report.json"

client = OpenAI(api_key=os.getenv("LLM_API_KEY"))

def run_tests() -> bool:
    """Runs the test suite and returns True if successful, False otherwise."""
    print(f"Executing: {TEST_COMMAND}")
    result = subprocess.run(TEST_COMMAND, shell=True)
    return result.returncode == 0

def get_failed_test_details() -> str:
    """Parses the pytest-json-report file to find exactly what failed."""
    if not os.path.exists(".pytest_report.json"):
        return "No report found. Pytest crashed early."
    
    with open(".pytest_report.json", "r") as f:
        data = json.load(f)
    
    failures = []
    for test in data.get("tests", []):
        if test.get("outcome") == "failed":
            # Extract test name and traceback details
            nodeid = test.get("nodeid")
            longrepr = test.get("call", {}).get("longrepr", "No traceback info")
            failures.append(f"Test: {nodeid}\nTraceback:\n{longrepr}\n")
    
    return "\n---\n".join(failures)

def find_target_file_contents() -> dict[str, str]:
    """
    Helper to locate and read relevant codebase files. 
    For a fully advanced setup, you could pass the traceback to let the LLM map the file path.
    """
    # Simple example: Pass the entire main source directory or the specific file under test
    # Adjust this logic to scan your codebase or read specific file paths from the traceback
    target_files = {}
    for root, _, files in os.walk("src"):  # Change "src" to your app directory
        for file in files:
            if file.endswith(".py"):
                path = os.path.join(root, file)
                with open(path, "r") as f:
                    target_files[path] = f.read()
    return target_files

def ask_ai_to_fix(errors: str, codebase: dict[str, str]) -> dict[str, Any]:
    """Sends code and errors to the LLM to get an updated code layout."""
    prompt = f"""
    You are an autonomous engineering agent. A test suite just failed. 
    Your objective is to fix the code files so that the tests pass. Do not break existing functionality.
    
    FAILED TEST DETAILS:
    {errors}
    
    CURRENT CODEBASE FILES:
    {json.dumps(codebase, indent=2)}
    
    Respond strictly in JSON format matching this schema:
    {{
        "explanation": "Brief reason for the failure and your fix",
        "modifications": {{
            "path/to/file.py": "FULL NEW UPDATED CODE FOR THIS FILE"
        }}
    }}
    Do not wrap your response in markdown code blocks like ```json. Return raw JSON text.
    """
    
    response = client.chat.completions.create(
        model="gpt-4o",  # or claude-3-5-sonnet
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )
    
    content = response.choices[0].message.content
    res: dict[str, Any] = json.loads(content) if content else {}
    return res

def apply_fixes(fixes: dict[str, Any]) -> None:
    """Overwrites code files with the AI's generated corrections."""
    print(f"AI Plan: {fixes.get('explanation')}")
    for filepath, file_content in fixes.get("modifications", {}).items():
        print(f"Applying fix to: {filepath}")
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w") as f:
            f.write(file_content)

def main() -> None:
    # Install dependency required to parse errors dynamically if missing
    subprocess.run("pip install pytest-json-report", shell=True)

    for attempt in range(1, MAX_RETRIES + 1):
        print(f"\n=== Autonomous Cycle Attempt {attempt}/{MAX_RETRIES} ===")
        
        if run_tests():
            print("🎉 Success! All tests are passing cleanly.")
            sys.exit(0)
            
        print("❌ Tests failed. Initiating autonomous healing...")
        errors = get_failed_test_details()
        codebase = find_target_file_contents()
        
        try:
            fixes = ask_ai_to_fix(errors, codebase)
            apply_fixes(fixes)
        except Exception as e:
            print(f"Critical error during AI execution loop: {e}")
            sys.exit(1)
            
    print("❌ Reached maximum retry count. Agent could not fix the codebase autonomously.")
    sys.exit(1)

if __name__ == "__main__":
    main()
