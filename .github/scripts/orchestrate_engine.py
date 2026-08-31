import os
import re
import sys
from openai import OpenAI  # Or change to anthropic if using Claude

def load_file(filepath):
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    return ""

def save_file(filepath, content):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

def main():
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        print("CRITICAL ERROR: LLM_API_KEY secret environment variable missing.")
        sys.exit(1)

    # 1. Parse operational files to identify current work item
    blueprint = load_file("ingestion_blueprint.md")
    todo_list = load_file("todo_tasks.md")

    # Simple regex to extract the first repository marked as pending/todo
    # Assumes format: "- [ ] ricequant/rqalpha" or similar indicator
    match = re.search(r'-\s*\[\s*\]\s*([a-zA-Z0-9_\-/]+)', todo_list)
    if not match:
        print("No pending repositories found in todo_tasks.md. Exiting.")
        sys.exit(0)
        
    current_repo = match.group(1)
    print(f"Executing conversion matrix for target repo: {current_repo}")

    # 2. Build the strict structural system prompt
    system_prompt = """You are an Elite Quantitative Systems Architect operating inside an automated CI/CD conversion workflow.
Your core objective is to execute an un-halted, deep-dive architectural extraction and optimization pipeline across the assigned repository.
You must adapt the target codebase into our native Python/Rust/MQL5 hybrid trading infrastructure.

CRITICAL RULES:
1. Deliver 100% production-ready, compiling, syntactically complete code blocks.
2. Absolute ZERO STUBS, placeholders, or abbreviated snippets are allowed. Fully flesh out every math loop and error-handling branch.
3. Output files using distinct clear file markers so the extraction script can parse them, example:
=== FILE: modules/repo_name/src/lib.rs ===
[Code goes here]
=== END FILE ===
"""

    user_prompt = f"""
CURRENT ACTIVE TARGET REPOSITORY: {current_repo}

=== CURRENT INGESTION BLUEPRINT LEDGER ===
{blueprint}

=== CURRENT TODO TASKS MATRIX ===
{todo_list}

EXECUTE PHASES 1 THROUGH 4 FOR THIS REPOSITORY NOW.
Provide the comprehensive structural steelman deconstruction, optimized multi-threaded Rust codebase wrapped cleanly via PyO3, execution tracking Magic Number assignments, and corresponding pytest scripts. Update the files 'ingestion_blueprint.md' and 'todo_tasks.md' (marking this repository as complete) and output their full updated text inside file markers.
"""

    # 3. Call the API
    client = OpenAI(api_key=api_key)
    print("Dispatching computational context payload to LLM...")
    response = client.chat.completions.create(
        model="gpt-4o", # Or "claude-3-5-sonnet-20241022" if using Anthropic
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.1
    )

    llm_output = response.choices[0].message.content

    # 4. Extract generated production files and update local workspace
    # Matches patterns like === FILE: path/to/file === [content] === END FILE ===
    file_blocks = re.findall(r'===\s*FILE:\s*([^\s]+)\s*===(.*?)===\s*END FILE\s*===', llm_output, re.DOTALL)
    
    if not file_blocks:
        print("WARNING: No explicit file blocks extracted by the regex. Dumping output logs to inspect.")
        save_file(f"logs/failed_run_{current_repo.replace('/', '_')}.log", llm_output)
        # Fallback tracking update to prevent infinite loops on failure
        todo_list = todo_list.replace(f"[ ] {current_repo}", f"[FAIL] {current_repo}")
        save_file("todo_tasks.md", todo_list)
        sys.exit(0)

    for filepath, content in file_blocks:
        filepath = filepath.strip()
        content = content.strip('\n')
        print(f"Writing production-ready artifact to workspace: {filepath}")
        save_file(filepath, content)

    print(f"Successfully processed all adaptive pipelines for: {current_repo}")

if __name__ == "__main__":
    main()
