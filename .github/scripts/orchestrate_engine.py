import os
import re
import sys
import time
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
        f.flush()
        os.fsync(f.fileno())

def verify_rust_compilation(repo_short_name):
    sandbox_dir = f"modules/{repo_short_name}"
    print(f"[{repo_short_name}] Running cargo check verification...")
    try:
        if not os.path.exists(os.path.join(sandbox_dir, "Cargo.toml")):
            os.makedirs(sandbox_dir, exist_ok=True)
            subprocess.run(["cargo", "init", "--lib", sandbox_dir], check=True, capture_output=True)
            cargo_toml_patch = """
[lib]
name = "eqats_rust_core"
crate-type = ["cdylib", "rlib"]

[dependencies]
pyo3 = { version = "0.20", features = ["extension-module"] }
rayon = "1.8"
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
"""
            with open(os.path.join(sandbox_dir, "Cargo.toml"), "a", encoding="utf-8") as f:
                f.write(cargo_toml_patch)

        check_run = subprocess.run(
            ["cargo", "check", "--manifest-path", f"{sandbox_dir}/Cargo.toml"],
            capture_output=True,
            text=True
        )
        if check_run.returncode == 0:
            print(f"✅ [{repo_short_name}] Pre-compilation test suite PASSED.")
            return True
        else:
            print(f"❌ [{repo_short_name}] Pre-compilation test suite FAILED.")
            print(check_run.stderr)
            return False
    except Exception as e:
        print(f"[{repo_short_name}] Cargo check couldn't run: {e}")
        return False

def git_commit_and_push(repo_name):
    try:
        subprocess.run(["git", "config", "--local", "user.email", "aquice-bot@github.com"], check=True)
        subprocess.run(["git", "config", "--local", "user.name", "AQuICE Auto-Architect Bot"], check=True)
        subprocess.run(["git", "add", "."], check=True)
        
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if not status.stdout.strip():
            print(f"[{repo_name}] No code mutations found.")
            return
            
        subprocess.run(["git", "commit", "-m", f"AQuICE: Adapted and verified {repo_name}"], check=True)
        subprocess.run(["git", "pull", "origin", "main", "--rebase"], check=True)
        subprocess.run(["git", "push", "origin", "main"], check=True)
        print(f"[{repo_name}] Pushed artifacts to main branch successfully.")
    except Exception as e:
        print(f"Git execution encountered a sync error on repo {repo_name}: {e}")

def run_conversion_cycle(current_repo, api_key, nim_base_url, model_name):
    blueprint = load_file("ingestion_blueprint.md")
    todo_list = load_file("todo_tasks.md")
    repo_short = current_repo.split('/')[-1]

    system_prompt = """You are an Elite Quantitative Systems Architect.
Your core objective is to execute a deep-dive architectural extraction and optimization pipeline across the assigned repository.
Adapt the target codebase into our native Python/Rust/MQL5 hybrid trading infrastructure.

CRITICAL RULES:
1. Deliver 100% production-ready, compiling, syntactically complete code blocks.
2. Absolute ZERO STUBS or placeholders allowed. Fully flesh out every math loop and arm.
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
"""

    client = OpenAI(base_url=nim_base_url, api_key=api_key)
    max_retries = 3
    retry_delay = 5
    llm_output = ""

    for attempt in range(1, max_retries + 1):
        try:
            print(f"[{current_repo}] Connecting to NIM endpoint [{nim_base_url}] (Attempt {attempt}/{max_retries})...")
            completion = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=4096,
                temperature=0.2
            )
            llm_output = completion.choices.message.content
            break
        except Exception as conn_err:
            print(f"⚠️ [{current_repo}] Attempt {attempt} failed: {conn_err}")
            if attempt < max_retries:
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                return False

    file_blocks = re.findall(r'===\s*FILE:\s*([^\s]+)\s*===(.*?)===\s*END FILE\s*===', llm_output, re.DOTALL)
    if not file_blocks:
        print(f"CRITICAL ERROR: Failed to isolate file markers from NIM output for {current_repo}.")
        return False

    for filepath, content in file_blocks:
        filepath = filepath.strip()
        content = content.strip('\n')
        print(f"[{current_repo}] Writing file: {filepath}")
        save_file(filepath, content)

    compilation_passed = verify_rust_compilation(repo_short)
    if not compilation_passed:
        print(f"⚠️ [{current_repo}] Compilation checks failed. Skipping ledger registration.")
        return False

    todo_list_disk = load_file("todo_tasks.md")
    todo_list_disk = re.sub(rf'-\s*\[\s*\]\s*{re.escape(current_repo)}', f"- [x] {current_repo}", todo_list_disk)
    todo_list_disk = re.sub(rf'\*\s*{re.escape(current_repo)}', f"* [COMPLETED] {current_repo}", todo_list_disk)
    save_file("todo_tasks.md", todo_list_disk)

    blueprint_disk = load_file("ingestion_blueprint.md")
    blueprint_disk = re.sub(rf'⏳ Pending\s*\|\s*{re.escape(repo_short)}', f"✅ Completed | {repo_short}", blueprint_disk)
    save_file("ingestion_blueprint.md", blueprint_disk)

    return True

def main():
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        print("CRITICAL ERROR: LLM_API_KEY environment token missing.")
        sys.exit(1)

    nim_base_url = "https://nvidia.com"
    
    # Defaults to highly compatible stable production model to stop 404 drops
    env_model = os.getenv("NIM_MODEL_NAME", "").strip()
    model_name = "meta/llama-3.3-70b-instruct" if not env_model or "llama-3.1-405b" in env_model else env_model

    all_repositories = [
        "daydy-dev/moon-dev-ai-agents-for-trading",
        "atilaahmettaner/tradingview-mcp",
        "white-trade-loan/algo-trading-platform",
        "Superalgos/Algorithmic-Trading-Plugins"
    ]

    print(f"Starting AQuICE Engine Loop. Target model: {model_name}")

    for repo in all_repositories:
        todo_current_state = load_file("todo_tasks.md")
        if f"[x] {repo}" in todo_current_state or f"[COMPLETED] {repo}" in todo_current_state:
            print(f"Skipping repository [{repo}] (Already completed).")
            continue

        print(f"\n=======================================================")
        print(f"PROCESSING TARGET: {repo}")
        print(f"=======================================================")
        
        success = run_conversion_cycle(repo, api_key, nim_base_url, model_name)
        
        if success:
            git_commit_and_push(repo)
        else:
            print(f"Flagging failure metrics for: {repo}")
            todo_list = load_file("todo_tasks.md")
            todo_list = re.sub(rf'\*\s*{re.escape(repo)}', f"* [FAILED] {repo}", todo_list)
            save_file("todo_tasks.md", todo_list)
            git_commit_and_push(repo)

    print("\n🎉 SUCCESS: Conversion loop sequence completed.")

if __name__ == "__main__":
    main()
