import os
import re
import sys
import subprocess
from openai import OpenAI

def load_file(filepath):
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    return ""

def save_file(filepath, content):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

def git_commit_and_push(repo_name):
    """Commits and pushes changes directly to main branch inside the runtime loop."""
    try:
        # Setup git credentials inside the runner environment
        subprocess.run(["git", "config", "--local", "user.email", "aquice-bot@github.com"], check=True)
        subprocess.run(["git", "config", "--local", "user.name", "AQuICE Auto-Architect Bot"], check=True)
        
        # Pull latest changes to avoid out-of-sync branch rejections
        subprocess.run(["git", "pull", "origin", "main", "--rebase"], check=True)
        
        # Stage all modified and newly generated code architectures
        subprocess.run(["git", "add", "."], check=True)
        
        # Check if changes exist before trying to commit
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if not status.stdout.strip():
            print(f"No code updates or ledger mutations detected for {repo_name}.")
            return
            
        subprocess.run(["git", "commit", "-m", f"AQuICE: Adapted and optimized {repo_name}"], check=True)
        subprocess.run(["git", "push", "origin", "main"], check=True)
        print(f"Successfully pushed all compiled artifacts for {repo_name} to main branch.")
    except Exception as e:
        print(f"Git execution encountered a sync error on repo {repo_name}: {e}")

def run_conversion_cycle(current_repo, api_key, nim_base_url, nim_model_name):
    """Dispatches a single repository context to NVIDIA NIM and extracts the output."""
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
    print(f"Dispatching context payload for [{current_repo}] to NVIDIA NIM...")
    
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

    # Match files formatted between the custom marker blocks
    file_blocks = re.findall(r'===\s*FILE:\s*([^\s]+)\s*===(.*?)===\s*END FILE\s*===', llm_output, re.DOTALL)
    
    if not file_blocks:
        print(f"CRITICAL ERROR: NIM returned zero parseable code matrices for {current_repo}.")
        # Fallback to update checklist state and prevent freeze
        todo_list = todo_list.replace(f"[ ] {current_repo}", f"[FAILED] {current_repo}")
        save_file("todo_tasks.md", todo_list)
        return False

    for filepath, content in file_blocks:
        filepath = filepath.strip()
        content = content.strip('\n')
        print(f"Extracting artifact to file matrix: {filepath}")
        save_file(filepath, content)

    # Clean up the task lists
    updated_todo = todo_list.replace(f"[ ] {current_repo}", f"[x] {current_repo}")
    save_file("todo_tasks.md", updated_todo)

    updated_blueprint = blueprint.replace(f"⏳ Pending | {current_repo.split('/')[-1]}", f"✅ Completed | {current_repo.split('/')[-1]}")
    save_file("ingestion_blueprint.md", updated_blueprint)
    return True

def main():
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        print("CRITICAL ERROR: LLM_API_KEY environmental secret missing.")
        sys.exit(1)

    nim_base_url = os.getenv("NIM_BASE_URL")
    nim_model_name = os.getenv("NIM_MODEL_NAME")

    # 🔄 THE CONTINUOUS WHILE-LOOP MECHANISM
    while True:
        # Freshly read file states at the start of each iteration step
        todo_list = load_file("todo_tasks.md")
        
        match = re.search(r'-\s*\[\s*\]\s*([a-zA-Z0-9_\-/]+)', todo_list)
        if not match:
            print("🎉 ALL TARGET REPOSITORIES COMPLETED! Exiting processing loop cleanly.")
            break
            
        current_repo = match.group(1)
        print(f"\n--- STARTING CONVERSION MATRIX FOR: {current_repo} ---")
        
        success = run_conversion_cycle(current_repo, api_key, nim_base_url, nim_model_name)
        
        # Instantly push code to GitHub before moving to the next item in the list
        git_commit_and_push(current_repo)
        
        if not success:
            print(f"Skipping downstream pipelines for failed target: {current_repo}")

if __name__ == "__main__":
    main()
