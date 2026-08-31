import os
import re
import sys
from openai import OpenAI

def load_file(filepath):
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()import os
import re
import sys
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

def main():
    # 1. Capture authorization keys
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        print("CRITICAL ERROR: LLM_API_KEY environment variable missing.")
        sys.exit(1)

    # 2. Configure NIM Endpoint Parameters
    # Default to hosted NVIDIA API Catalog if no private endpoint URL is provided
    # Swap to "http://your-gpu-server-ip:8000/v1" if utilizing a local self-hosted NIM instance
    nim_base_url = os.getenv("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
    
    # Define which target NIM model slug will serve the architect queries
    # e.g., "meta/llama3-70b-instruct", "meta/llama-3.1-405b-instruct", etc.
    nim_model_name = os.getenv("NIM_MODEL_NAME", "meta/llama-3.1-405b-instruct")

    blueprint = load_file("ingestion_blueprint.md")
    todo_list = load_file("todo_tasks.md")

    # Extract the active pending codebase to adapt
    match = re.search(r'-\s*\[\s*\]\s*([a-zA-Z0-9_\-/]+)', todo_list)
    if not match:
        print("No pending repositories found in todo_tasks.md. Loop complete.")
        sys.exit(0)
        
    current_repo = match.group(1)
    print(f"Initializing optimization framework for: {current_repo}")
    print(f"Targeting NIM Endpoint Matrix: {nim_base_url} | Model: {nim_model_name}")

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

    # Initialize client targeting custom NVIDIA Microservice architecture
    client = OpenAI(
        base_url=nim_base_url,
        api_key=api_key
    )
    
    print("Dispatching computational context payload to NVIDIA NIM cluster...")
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

    # Extract structural code components from model response
    file_blocks = re.findall(r'===\s*FILE:\s*([^\s]+)\s*===(.*?)===\s*END FILE\s*===', llm_output, re.DOTALL)
    
    if not file_blocks:
        print("WARNING: Zero structural code blocks parsed. Inspecting run log templates.")
        todo_list = todo_list.replace(f"[ ] {current_repo}", f"[FAILED] {current_repo}")
        save_file("todo_tasks.md", todo_list)
        sys.exit(0)

    for filepath, content in file_blocks:
        filepath = filepath.strip()
        content = content.strip('\n')
        print(f"Deploying production-ready vector to storage: {filepath}")
        save_file(filepath, content)

    # Register item completion
    updated_todo = todo_list.replace(f"[ ] {current_repo}", f"[x] {current_repo}")
    save_file("todo_tasks.md", updated_todo)

    # Sync ledger documentation status
    updated_blueprint = blueprint.replace(f"⏳ Pending | {current_repo.split('/')[-1]}", f"✅ Completed | {current_repo.split('/')[-1]}")
    save_file("ingestion_blueprint.md", updated_blueprint)

    print(f"Extraction cycle fully executed for: {current_repo}")

if __name__ == "__main__":
    main()

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

    blueprint = load_file("ingestion_blueprint.md")
    todo_list = load_file("todo_tasks.md")

    # Extract the first unchecked repository string
    match = re.search(r'-\s*\[\s*\]\s*([a-zA-Z0-9_\-/]+)', todo_list)
    if not match:
        print("No pending repositories found in todo_tasks.md. Exiting workflow.")
        sys.exit(0)
        
    current_repo = match.group(1)
    print(f"Executing conversion matrix for target repo: {current_repo}")

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

    client = OpenAI(api_key=api_key)
    print("Dispatching computational context payload to LLM...")
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.1
    )

    llm_output = response.choices.message.content

    # Extract generated production files and write them to workspace
    file_blocks = re.findall(r'===\s*FILE:\s*([^\s]+)\s*===(.*?)===\s*END FILE\s*===', llm_output, re.DOTALL)
    
    if not file_blocks:
        print("WARNING: No explicit file blocks extracted by the regex. Updating lists.")
        # Mark as failed to avoid infinite loops if the LLM errors out
        todo_list = todo_list.replace(f"[ ] {current_repo}", f"[FAILED] {current_repo}")
        save_file("todo_tasks.md", todo_list)
        sys.exit(0)

    for filepath, content in file_blocks:
        filepath = filepath.strip()
        content = content.strip('\n')
        print(f"Writing production-ready artifact to workspace: {filepath}")
        save_file(filepath, content)

    # Mark the repository as completed by updating the markdown checklist bracket
    updated_todo = todo_list.replace(f"[ ] {current_repo}", f"[x] {current_repo}")
    save_file("todo_tasks.md", updated_todo)

    # Update ledger status text
    updated_blueprint = blueprint.replace(f"⏳ Pending | {current_repo.split('/')[-1]}", f"✅ Completed | {current_repo.split('/')[-1]}")
    save_file("ingestion_blueprint.md", updated_blueprint)

    print(f"Successfully processed all adaptive pipelines for: {current_repo}")

if __name__ == "__main__":
    main()
