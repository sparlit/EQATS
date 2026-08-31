import os
import re
import sys
import subprocess
from openai import OpenAI

def load_file(filepath):
    """Bypasses default python caches by forcing an uncached system read."""
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8', buffering=0) as f:
            return f.read()
    return ""

def save_file(filepath, content):
    """Saves and flushes instantly to disk storage arrays."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())

def git_commit_and_push(repo_name):
    """Pushes code transformations instantly to prevent repo divergence."""
    try:
        subprocess.run(["git", "config", "--local", "user.email", "aquice-bot@github.com"], check=True)
        subprocess.run(["git", "config", "--local", "user.name", "AQuICE Auto-Architect Bot"], check=True)
        
        # Pull any remote adjustments using a rebase wrapper
        subprocess.run(["git", "pull", "origin", "main", "--rebase"], check=True)
        subprocess.run(["git", "add", "."], check=True)
        
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if not status.stdout.strip():
            print(f"No codebase mutations found for {repo_name}.")
            return
            
        subprocess.run(["git", "commit", "-m", f"AQuICE: Transformed code matrix for {repo_name}"], check=True)
        subprocess.run(["git", "push", "origin", "main"], check=True)
        print(f"Pushed compiled artifacts for {repo_name} to main.")
    except Exception as e:
        print(f"Git loop sync exception caught on {repo_name}: {e}")

def run_conversion_cycle(current_repo, api_key, nim_base_url, nim_model_name):
    """Fires contextual trading framework requirements to NVIDIA NIM endpoints."""
    blueprint = load_file("ingestion_blueprint.md")
    todo_list = load_file("todo_tasks.md")

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

    client = OpenAI(base_url=nim_base_url, api_key=api_key)
    print(f"Dispatching optimization payload for [{current_repo}] to NVIDIA NIM...")
    
    response = client.chat.completions.create(
        model=nim_model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.1,
        max_tokens=4096
    )

    llm_output = response.choices.message.content

    # Extract all multi-language source configurations safely
    file_blocks = re.findall(r'===\s*FILE:\s*([^\s]+)\s*===(.*?)===\s*END FILE\s*===', llm_output, re.DOTALL)
    
    if not file_blocks:
        print(f"CRITICAL ERROR: Failed to isolate file markers from NIM output for {current_repo}.")
        return False

    for filepath, content in file_blocks:
        filepath = filepath.strip()
        content = content.strip('\n')
        print(f"Writing generation sequence file: {filepath}")
        save_file(filepath, content)

    # Multi-regex target replacement logic to avoid format mismatch drops
    todo_list = re.sub(rf'-\s*\[\s*\]\s*{re.escape(current_repo)}', f"- [x] {current_repo}", todo_list)
    save_file("todo_tasks.md", todo_list)

    repo_short = current_repo.split('/')[-1]
    blueprint = re.sub(rf'⏳ Pending\s*\|\s*{re.escape(repo_short)}', f"✅ Completed | {repo_short}", blueprint)
    save_file("ingestion_blueprint.md", blueprint)
    return True

def main():
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        print("CRITICAL ERROR: LLM_API_KEY is not defined in scope.")
        sys.exit(1)

    nim_base_url = os.getenv("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
    nim_model_name = os.getenv("NIM_MODEL_NAME", "meta/llama-3.1-405b-instruct")

    # High-throughput sequential iteration pipeline execution engine
    while True:
        todo_list = load_file("todo_tasks.md")
        
        # Regex scans for any remaining open box targets dynamically
        match = re.search(r'-\s*\[\s*\]\s*([a-zA-Z0-9_\-/]+)', todo_list)
        if not match:
            print("🎉 SUCCESS: All targeted systems successfully engineered. Exiting.")
            break
            
        current_repo = match.group(1).strip()
        print(f"\n=======================================================")
        print(f"PROCESSING REPOSITORY ARTIFACT: {current_repo}")
        print(f"=======================================================")
        
        success = run_conversion_cycle(current_repo, api_key, nim_base_url, nim_model_name)
        
        # Execute immediate system hard write to repository branch
        git_commit_and_push(current_repo)
        
        if not success:
            print(f"Skipping downstream steps. Flagging target failure context: {current_repo}")
            # Mutate structural checklist element to avoid dead execution traps
            todo_list = load_file("todo_tasks.md")
            todo_list = re.sub(rf'-\s*\[\s*\]\s*{re.escape(current_repo)}', f"- [FAILED] {current_repo}", todo_list)
            save_file("todo_tasks.md", todo_list)
            git_commit_and_push(current_repo)

if __name__ == "__main__":
    main()
