RTLLM_DIR = "/mnt/data/RTLLM"  # Root RTLLM directory
OUTPUT_DIR = "/mnt/data/LLM_outputs"  # Where generated Verilog files will be stored
RAW_OUTPUT_DIR = "/mnt/data/RAW_LLM_outputs"  # Folder to store original LLM responses

import os
import json
import re
import subprocess
import http.client
import time
from tqdm import tqdm

# Configuration Paths
RTLLM_DIR = "/mnt/data/RTLLM"  # Root RTLLM directory
OUTPUT_DIR = "/mnt/data/LLM_outputs"  # Where generated Verilog files will be stored
RAW_OUTPUT_DIR = "/mnt/data/RAW_LLM_outputs"  # Folder to store original LLM responses
USE_API = False  # Set to True if using API, False for CLI-based LLM

# Ensure output directories exist
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(RAW_OUTPUT_DIR, exist_ok=True)

# Instruction to enforce module-based Verilog extraction
VERILOG_FORMAT_INSTRUCTION = """
Ensure that the Verilog code is properly structured and contains well-defined modules. The output should strictly follow this format:
<Verilog module code>
The code should contain only properly formatted `module ... endmodule` blocks.
"""

# Scan all available design directories dynamically
def get_all_designs(root_dir):
    design_paths = []
    for dirpath, _, filenames in os.walk(root_dir):
        if "design_description.txt" in filenames and "testbench.v" in filenames:
            design_paths.append(dirpath)
    return design_paths

design_paths = get_all_designs(RTLLM_DIR)

# Progress bar setup
progress_bar = tqdm(total=len(design_paths))

# Function to extract all Verilog modules using "module ... endmodule"
def extract_verilog_code(output):
    # Extract all valid module declarations
    verilog_pattern = r"(module\s+[\w\d_]+\s*[\s\S]+?endmodule)"
    matches = re.findall(verilog_pattern, output, re.DOTALL)

    if matches:
        return "\n\n".join(matches)  # Join all detected modules with spacing
    else:
        return "Error: No valid Verilog code found."

# Function to run LLM and generate Verilog code
def generate_verilog(design_name, prompt_content, output_file, raw_output_file):
    # Append instruction to enforce Verilog module format
    full_prompt = prompt_content + "\n\n" + VERILOG_FORMAT_INSTRUCTION

    if USE_API:
        # API-based LLM Request
        conn = http.client.HTTPSConnection("cloud.infini-ai.com")

        payload = json.dumps({
            "model": "deepseek-r1",
            "messages": [{"role": "user", "content": full_prompt}],
            "stream": False,
            "temperature": 0.7,
            "top_p": 1,
            "top_k": -1,
            "n": 1,
            "max_tokens": None,
            "stop": None,
            "presence_penalty": 0,
            "frequency_penalty": 0
        })

        headers = {
            'Content-Type': "application/json",
            'Authorization': "Bearer sk-darmzk5tbgttdn63"  # Replace with actual API key
        }

        conn.request("POST", "/maas/v1/chat/completions", payload, headers)
        res = conn.getresponse()
        data = res.read()
        response_json = json.loads(data.decode("utf-8"))

        raw_output = response_json["choices"][0]["message"].get("content", "No response found").strip() if "choices" in response_json else "No valid response from API."
    else:
        # CLI-based LLM (Ollama)
        command = f'ollama run deepseek-coder-v2:16b "{full_prompt}"'
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        raw_output = result.stdout.strip()

    # Save raw LLM output before extraction
    with open(raw_output_file, "w", encoding="utf-8") as file:
        file.write(raw_output)

    # Extract Verilog code enclosed within module ... endmodule
    verilog_code = extract_verilog_code(raw_output)

    # Save extracted Verilog to file
    with open(output_file, "w", encoding="utf-8") as file:
        file.write(verilog_code)

# Function to run testbench verification
def run_testbench(design_name, design_path, verilog_path):
    testbench_path = os.path.join(design_path, "testbench.v")
    output_file = os.path.join(OUTPUT_DIR, f"{design_name}.out")

    if os.path.exists(testbench_path):
        print(f"\n▶️ Running testbench for {design_name}...")

        # Compile and run simulation
        compile_command = f"iverilog -o {output_file} {verilog_path} {testbench_path}"
        compile_result = subprocess.run(compile_command, shell=True, capture_output=True, text=True)

        if not os.path.exists(output_file):  # If compilation fails, treat as testbench failure
            print(f"❌ Testbench failed for {design_name} (compilation error).")
            return

        # Run simulation
        simulation_command = f"vvp {output_file}"
        simulation_result = subprocess.run(simulation_command, shell=True, capture_output=True, text=True)
        print(simulation_result.stdout)
        print(f"✅ Testbench completed for {design_name}")
    else:
        print(f"⚠️ No testbench found for {design_name}, skipping verification.")

# Dictionary to track test results
result_dict = {design_path: {"syntax_success": 0, "func_success": 0} for design_path in design_paths}

# Main Execution Loop
for design_path in design_paths:
    design_name = os.path.basename(design_path)
    prompt_file = os.path.join(design_path, "design_description.txt")
    output_file = os.path.join(OUTPUT_DIR, f"{design_name}.v")
    raw_output_file = os.path.join(RAW_OUTPUT_DIR, f"{design_name}.txt")

    # Read the design description
    with open(prompt_file, "r", encoding="utf-8") as file:
        prompt_content = file.read().strip()

    print(f"\n🔹 Generating Verilog for {design_name}...")
    generate_verilog(design_name, prompt_content, output_file, raw_output_file)

    # Run verification testbench
    run_testbench(design_name, design_path, output_file)

    progress_bar.update(1)

progress_bar.close()
print("\n✅ All benchmarks completed!")
