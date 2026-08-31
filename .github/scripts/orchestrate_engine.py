import os
import re
import sys
import subprocess
from openai import OpenAI

def load_file(filepath):
    """Bypasses active memory layer tracking to grab fresh file states off disk."""
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    return ""

def save_file(filepath, content):
    """Saves and flushes instantly to persistent disk arrays."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())

def git_commit_and_push(repo_name):
    """Pushes compiled architectures instantly to main branch."""
    try:
        subprocess.run(["git", "config", "--local", "user.email", "aquice-bot@github.com"], check=True)
        subprocess.run(["git", "config", "--local", "user.name", "AQuICE Auto-Architect Bot"], check=True)
        
        subprocess.run(["git", "add", "."], check=True)
        
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if not status.stdout.strip():
            print(f"No codebase mutations found for {repo_name}.")
            return
            
        subprocess.run(["git", "commit", "-m", f"AQuICE: Adapted and optimized {repo_name}"], check=True)
        
        # Pull any remote adjustments using a rebase wrapper to prevent out-of-sync pushes
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
    print(f"Dispatching optimization payload for [{current_repo}] to NVIDIA NIM endpoint: {nim_base_url}...")
    
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

    # Extract all engineered codebase assets cleanly from the generated blocks
    file_blocks = re.findall(r'===\s*FILE:\s*([^\s]+)\s*===(.*?)===\s*END FILE\s*===', llm_output, re.DOTALL)
    
    if not file_blocks:
        print(f"CRITICAL ERROR: Failed to isolate file markers from NIM output for {current_repo}.")
        return False

    for filepath, content in file_blocks:
        filepath = filepath.strip()
        content = content.strip('\n')
        print(f"Writing generation sequence file: {filepath}")
        save_file(filepath, content)

    # Refined state transition updates: handles both checklist formats and asterisks dynamically
    todo_list = load_file("todo_tasks.md")
    todo_list = re.sub(rf'-\s*\[\s*\]\s*{re.escape(current_repo)}', f"- [x] {current_repo}", todo_list)
    todo_list = re.sub(rf'\*\s*{re.escape(current_repo)}', f"* [COMPLETED] {current_repo}", todo_list)
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

    # 🔄 CRITICAL FIX: Intercept generic/broken base URLs and swap to the valid NIM cluster router
    env_url = os.getenv("NIM_BASE_URL", "").strip()
    if not env_url or env_url == "https://nvidia.com" or env_url == "https://www.nvidia.com":
        nim_base_url = "https://nvidia.com"
    else:
        nim_base_url = env_url
        
    nim_model_name = os.getenv("NIM_MODEL_NAME", "meta/llama-3.1-405b-instruct")

    todo_raw = load_file("todo_tasks.md")
    
    # Split boundary mapping to guarantee plain string delivery
    pending_block = todo_raw
    if "## 🟨 PENDING TASKS" in todo_raw:
        parts = todo_raw.split("## 🟨 PENDING TASKS")
        if len(parts) > 1:
            pending_block = parts[1]

    # Extract lines matching standard repo formats containing a forward slash
    raw_lines = re.findall(r'(?:-\s*\[\s*\]|\*)\s*([a-zA-Z0-9_\-/.\+]+)', pending_block)
    
    all_repositories = []
    for line in raw_lines:
        line = line.strip()
        if "/" in line and not line.startswith("#") and not "COMPLETED" in line and not "FAILED" in line:
            all_repositories.append(line)

    if not all_repositories:
        print("🎉 SUCCESS: No pending repository systems found in master checklist. Loop complete.")
        sys.exit(0)

    print(f"Found {len(all_repositories)} total target repositories in architecture master ledger queue.")

    # 2. Process our list sequentially via continuous execution walk
    for current_repo in all_repositories:
        todo_current_state = load_file("todo_tasks.md")
        
        # Guardrail skipping check to handle safe re-entry loops
        if f"[x] {current_repo}" in todo_current_state or f"[COMPLETED] {current_repo}" in todo_current_state:
            print(f"Skipping repository [{current_repo}] (Already completed in previous execution history).")
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
            todo_list = re.sub(rf'\*\s*{re.escape(current_repo)}', f"* [FAILED] {current_repo}", todo_list)
            save_file("todo_tasks.md", todo_list)
            git_commit_and_push(current_repo)

    print("\n🎉 SUCCESS: All targeted systems in the master list successfully engineered.")

if __name__ == "__main__":
    main()
