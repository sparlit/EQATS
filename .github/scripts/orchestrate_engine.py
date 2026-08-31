import os
import re
import sys
import subprocess
from openai import OpenAI

def load_file(filepath):
    """Reads raw contents fresh off disk arrays without active memory layer tracking."""
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    return ""

def save_file(filepath, content):
    """Saves and flushes instantly to persistent disk arrays with hard OS syncs."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())

def git_commit_and_push(repo_name):
    """Pushes compiled architectures instantly to GitHub main branch."""
    try:
        subprocess.run(["git", "config", "--local", "user.email", "aquice-bot@github.com"], check=True)
        subprocess.run(["git", "config", "--local", "user.name", "AQuICE Auto-Architect Bot"], check=True)
        
        subprocess.run(["git", "add", "."], check=True)
        
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if not status.stdout.strip():
            print(f"No codebase mutations found for {repo_name}.")
            return
            
        subprocess.run(["git", "commit", "-m", f"AQuICE: Adapted and optimized {repo_name}"], check=True)
        
        # Merge remote work streams using a safe rebase handler before pushing changes
        subprocess.run(["git", "pull", "origin", "main", "--rebase"], check=True)
        subprocess.run(["git", "push", "origin", "main"], check=True)
        print(f"Successfully pushed all compiled artifacts for {repo_name} to main branch.")
    except Exception as e:
        print(f"Git execution encountered a sync error on repo {repo_name}: {e}")

def run_conversion_cycle(current_repo, api_key, nim_base_url, model_name):
    """Dispatches quantitative architecture requirements directly to NVIDIA NIM API via OpenAI SDK."""
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

    # Target the base URL via the pre-installed OpenAI client wrapper
    client = OpenAI(base_url=nim_base_url, api_key=api_key)

    # Clean multi-modal payload routing structures optimized for Moonshot Kimi-K3 parsing requirements
    messages_payload = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f"{system_prompt}\n\n{user_prompt}"
                }
            ]
        }
    ]

    print(f"Dispatching optimization context via SDK to endpoint [{nim_base_url}] using model: {model_name}...")
    
    # Configure exact inference block properties natively
    extra_params = {}
    if "kimi-k3" in model_name:
        extra_params["seed"] = 0
        extra_params["reasoning_effort"] = "max"

    response = client.chat.completions.create(
        model=model_name,
        messages=messages_payload,
        max_tokens=16384 if "kimi-k3" in model_name else 4096,
        temperature=1.0 if "kimi-k3" in model_name else 0.1,
        **extra_params
    )

    llm_output = response.choices.message.content

    # Safely unpack file boundaries formatted between our custom structural block tags
    file_blocks = re.findall(r'===\s*FILE:\s*([^\s]+)\s*===(.*?)===\s*END FILE\s*===', llm_output, re.DOTALL)
    
    if not file_blocks:
        print(f"CRITICAL ERROR: Failed to isolate file markers from NIM output for {current_repo}.")
        return False

    for filepath, content in file_blocks:
        filepath = filepath.strip()
        content = content.strip('\n')
        print(f"Deploying engineered vector source asset: {filepath}")
        save_file(filepath, content)

    # Clean out checklist markers within document parameters smoothly
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
        print("CRITICAL ERROR: LLM_API_KEY variable bindings are missing from runtime scope.")
        sys.exit(1)

    # Direct v1 path gateway routing via OpenAI SDK client wrapper
    nim_base_url = "https://integrate.api.nvidia.com/v1"
    model_name = "moonshotai/kimi-k3"

    # In-memory tracking array queue layout configuration
    all_repositories = [
        "daydy-dev/moon-dev-ai-agents-for-trading",
        "atilaahmettaner/tradingview-mcp",
        "white-trade-loan/algo-trading-platform",
        "Superalgos/Algorithmic-Trading-Plugins"
    ]

    print(f"Found {len(all_repositories)} target repositories initialized within native memory matrices.")

    for current_repo in all_repositories:
        current_repo = current_repo.strip()
        todo_current_state = load_file("todo_tasks.md")
        
        if f"[x] {current_repo}" in todo_current_state or f"[COMPLETED] {current_repo}" in todo_current_state:
            print(f"Skipping repository [{current_repo}] (Already marked complete in execution logs).")
            continue

        print(f"\n=======================================================")
        print(f"PROCESSING REPOSITORY ARTIFACT: {current_repo}")
        print(f"=======================================================")
        
        success = run_conversion_cycle(current_repo, api_key, nim_base_url, model_name)
        
        # Push file mutations onto your code repository branch on every loop iteration
        git_commit_and_push(current_repo)
        
        if not success:
            print(f"Flagging conversion runtime failure tracking parameters for: {current_repo}")
            todo_list = load_file("todo_tasks.md")
            todo_list = re.sub(rf'\*\s*{re.escape(current_repo)}', f"* [FAILED] {current_repo}", todo_list)
            save_file("todo_tasks.md", todo_list)
            git_commit_and_push(current_repo)

    print("\n🎉 SUCCESS: All quantitative engineering pipelines processed down to completion.")

if __name__ == "__main__":
    main()
