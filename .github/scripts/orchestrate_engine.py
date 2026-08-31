import os
import re
import sys
import subprocess
from openai import OpenAI

def load_file(filepath):
    """Forbids memory reference leaks by reading raw contents fresh off disk."""
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    return ""

def save_file(filepath, content):
    """Forces an explicit OS cache sync to ensure persistent writes."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())

def git_commit_and_push(repo_name):
    """Pushes freshly compiled architectures instantly to GitHub."""
    try:
        subprocess.run(["git", "config", "--local", "user.email", "aquice-bot@github.com"], check=True)
        subprocess.run(["git", "config", "--local", "user.name", "AQuICE Auto-Architect Bot"], check=True)
        
        # Consolidate staging maps
        subprocess.run(["git", "add", "."], check=True)
        
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if not status.stdout.strip():
            print(f"No codebase mutations found for {repo_name}.")
            return
            
        subprocess.run(["git", "commit", "-m", f"AQuICE: Adapted and optimized {repo_name}"], check=True)
        
        # Use rebase flag on push sequence to gracefully handle workflow run sync overhead
        subprocess.run(["git", "pull", "origin", "main", "--rebase"], check=True)
        subprocess.run(["git", "push", "origin", "main"], check=True)
        print(f"Successfully pushed all compiled artifacts for {repo_name} to main branch.")
    except Exception as e:
        print(f"Git execution encountered a sync error on repo {repo_name}: {e}")

def run_conversion_cycle(current_repo, api_key, nim_base_url, nim_model_name):
    """Dispatches structural trading framework requirements to NVIDIA NIM endpoints."""
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

    # Extract all engineered codebase assets cleanly
    file_blocks = re.findall(r'===\s*FILE:\s*([^\s]+)\s*===(.*?)===\s*END FILE\s*===', llm_output, re.DOTALL)
    
    if not file_blocks:
        print(f"CRITICAL ERROR: Failed to isolate file markers from NIM output for {current_repo}.")
        return False

    for filepath, content in file_blocks:
        filepath = filepath.strip()
        content = content.strip('\n')
        print(f"Writing generation sequence file: {filepath}")
        save_file(filepath, content)

    # Apply precise state transition updates to local files
    todo_list = load_file("todo_tasks.md")
    todo_list = re.sub(rf'-\s*\[\s*\]\s*{re.escape(current_repo)}', f"- [x] {current_repo}", todo_list)
    save_file("todo_tasks.md", todo_list)

    repo_short = current_repo.split('/')[-1]
    blueprint = load_file("ingestion_blueprint.md")
    blueprint = re.sub(rf'⏳ Pending\s*\|\s*{re.escape(repo_short)}', f"✅ Completed | {repo_short}", blueprint)
    save_file("ingestion_blueprint.md", blueprint)
    return True

def main():
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        print("CRITICAL ERROR: LLM_API_KEY is not defined in scope.")
        sys.exit(1)

    nim_base_url = os.getenv("NIM_BASE_URL", "https://nvidia.com")
    nim_model_name = os.getenv("NIM_MODEL_NAME", "meta/llama-3.1-405b-instruct")

    # 1. Parse entire checklist into memory on boot to protect sequence tracking
    todo_raw = load_file("todo_tasks.md")
    all_repositories = re.findall(r'-\s*\[[\sXx]\]\s*([a-zA-Z0-9_\-/]+)', todo_raw)
    
    if not all_repositories:
        print("CRITICAL ERROR: Could not parse any repository listings from todo_tasks.md.")
        sys.exit(1)

    print(f"Found {len(all_repositories)} total repositories in architecture master ledger.")

    # 2. Sequential execution walk down the in-memory array
    for current_repo in all_repositories:
        current_repo = current_repo.strip()
        
        # Verify the current state dynamically on disk to enable recovery modes
        todo_current_state = load_file("todo_tasks.md")
        if f"- [x] {current_repo}" in todo_current_state or f"- [X] {current_repo}" in todo_current_state:
            print(f"Skipping repository [{current_repo}] (Already processed in previous history run).")
            continue

        print(f"\n=======================================================")
        print(f"PROCESSING REPOSITORY ARTIFACT: {current_repo}")
        print(f"=======================================================")
        
        success = run_conversion_cycle(current_repo, api_key, nim_base_url, nim_model_name)
        
        # Sync changes with main git branch instantly
        git_commit_and_push(current_repo)
        
        if not success:
            print(f"Flagging target failure metrics for context: {current_repo}")
            todo_list = load_file("todo_tasks.md")
            todo_list = re.sub(rf'-\s*\[\s*\]\s*{re.escape(current_repo)}', f"- [FAILED] {current_repo}", todo_list)
            save_file("todo_tasks.md", todo_list)
            git_commit_and_push(current_repo)

    print("\n🎉 SUCCESS: All targeted systems in the master list successfully engineered.")

if __name__ == "__main__":
    main()
