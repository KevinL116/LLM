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
MAX_RETRIES = 4  # Number of retries on compilation failure
USE_API = False  # Set to True if using API, False for CLI-based LLM

# Ensure output directories exist
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(RAW_OUTPUT_DIR, exist_ok=True)

# Instruction to enforce module-based Verilog extraction
VERILOG_FORMAT_INSTRUCTION = """

Ensure that the Verilog code is properly structured and contains well-defined modules.
The code should contain only properly formatted `module ... endmodule` blocks.
You should never include any code for the testbench.

Generate Verilog code that strictly adheres to the IEEE 1364-2005 Verilog standard and avoids features from SystemVerilog, C, or any other languages that are not supported in Verilog. Ensure that:

No SystemVerilog-Specific Constructs

Do not use logic, bit, byte, struct, union, enum, interface, modport, or always_ff/always_comb/always_latch.
Use reg and wire instead of logic.
Use explicit always blocks for sequential logic instead of always_ff.
No C-Like Syntax

When writing Verilog code, strictly follow the correct usage of reg and wire to avoid misinterpretation:

Combinational Logic:
Use wire for signals driven by continuous assignments (assign statements).
Do not use reg for purely combinational signals unless it is part of an always block.
Sequential Logic:
Use reg for signals assigned inside an always block triggered by a clock or reset (always @(posedge clk) or always @(posedge clk or posedge reset)).
Do not use wire for signals inside procedural always blocks.
Avoid Incorrect Usage:
Do not declare a reg but drive it with an assign statement.
Do not use wire for a variable assigned within an always block.

Do not use typedef, inline functions, or imported packages.
Instead of typedef enum logic [N-1:0], use traditional parameter definitions or localparam to define state encoding.
Define each state using parameter or localparam rather than typedef.
Use reg [N-1:0] state, next_state; instead of typedef enum.

Do not use for (int i = 0; i < N; i++), use integer i instead.
No begin-end blocks within a single statement unless required by multiple statements.
Only Verilog-Compatible Ports and Data Types

Do not use var or automatic variables; only use reg, wire, and integer.
Use input, output, and inout ports with explicit bit widths.
No SystemVerilog Assertions or Constraints

Do not use assert, assume, cover, constraint, or randomization constructs.
No immediate or concurrent assertions.
Synthesis-Compatible Code

Avoid constructs that are only valid for simulation (e.g., $random, initial blocks except for testbenches).
No always @* (use explicit sensitivity lists in always blocks).
Explicit Module Instantiations

Use explicit parameter passing syntax (#(...)), avoiding SystemVerilog-style parameter type.
"""

FIXING_INSTRUCTIONS = """
The Verilog code has some errors.
Ensure that the Verilog code is properly structured and contains well-defined modules.
The code should contain only properly formatted `module ... endmodule` blocks.
You should never include any code for the testbench.

Generate Verilog code that strictly adheres to the IEEE 1364-2005 Verilog standard and avoids features from SystemVerilog, C, or any other languages that are not supported in Verilog. Ensure that:

No SystemVerilog-Specific Constructs

Do not use logic, bit, byte, struct, union, enum, interface, modport, or always_ff/always_comb/always_latch.
Use reg and wire instead of logic.
Use explicit always blocks for sequential logic instead of always_ff.
No C-Like Syntax

When writing Verilog code, strictly follow the correct usage of reg and wire to avoid misinterpretation:

Combinational Logic:
Use wire for signals driven by continuous assignments (assign statements).
Do not use reg for purely combinational signals unless it is part of an always block.
Sequential Logic:
Use reg for signals assigned inside an always block triggered by a clock or reset (always @(posedge clk) or always @(posedge clk or posedge reset)).
Do not use wire for signals inside procedural always blocks.
Avoid Incorrect Usage:
Do not declare a reg but drive it with an assign statement.
Do not use wire for a variable assigned within an always block.

Do not use typedef, inline functions, or imported packages.
Instead of typedef enum logic [N-1:0], use traditional parameter definitions or localparam to define state encoding.
Define each state using parameter or localparam rather than typedef.
Use reg [N-1:0] state, next_state; instead of typedef enum.

Do not use for (int i = 0; i < N; i++), use integer i instead.
No begin-end blocks within a single statement unless required by multiple statements.
Only Verilog-Compatible Ports and Data Types

Do not use var or automatic variables; only use reg, wire, and integer.
Use input, output, and inout ports with explicit bit widths.
No SystemVerilog Assertions or Constraints

Do not use assert, assume, cover, constraint, or randomization constructs.
No immediate or concurrent assertions.
Synthesis-Compatible Code

Avoid constructs that are only valid for simulation (e.g., $random, initial blocks except for testbenches).
No always @* (use explicit sensitivity lists in always blocks).
Explicit Module Instantiations

Use explicit parameter passing syntax (#(...)), avoiding SystemVerilog-style parameter type.

Fix this Verilog code based on the following error:\n

"""

REASONING_PROMPT_TEMPLATE = """Please act as a professional Verilog designer. Try to understand the requirements below and give reasoning steps in natural language to achieve it.

Additionally, give advice to avoid syntax errors.

Provide the Verilog code according to the reasoning steps and advice.

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

def extract_verilog_code(output):
    lines = output.split("\n")
    extracted_modules = []
    current_module = []
    module_depth = 0  # Keeps track of whether we are inside a module

    for line in lines:
        stripped_line = line.strip()

        if stripped_line.startswith("module "):  # Start of a new module
            if module_depth == 0:  # If no open module, start collecting
                current_module = [stripped_line]
                module_depth = 1  # Mark module as open
            else:
                # Another "module" appears before "endmodule", discard the previous module
                current_module = [stripped_line]  # Restart collection

        elif stripped_line.startswith("endmodule"):  # End of a module
            if module_depth == 1:  # Ensure module was open
                current_module.append(stripped_line)
                extracted_modules.append("\n".join(current_module))  # Save valid module
                module_depth = 0  # Reset for next module
                current_module = []  # Clear module buffer

        elif module_depth == 1:  # Inside a module
            current_module.append(stripped_line)

    return "\n\n".join(extracted_modules) if extracted_modules else "Error: No complete Verilog module found."



# Function to run LLM and generate Verilog code
def generate_verilog(design_name, prompt_content, output_file, raw_output_file):
    # Append instruction to enforce Verilog module format
    full_prompt = VERILOG_FORMAT_INSTRUCTION + "\n\n" + prompt_content 

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
        # command = f'ollama run phi4 "{full_prompt}"'
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        raw_output = result.stdout.strip()
        # print(raw_output)

    # Save raw LLM output before extraction
    with open(raw_output_file, "w", encoding="utf-8") as file:
        file.write(raw_output)

    # Extract Verilog code enclosed within module ... endmodule
    verilog_code = extract_verilog_code(raw_output)

    # Save extracted Verilog to file
    with open(output_file, "w", encoding="utf-8") as file:
        file.write(verilog_code)

# Summary storage
summary = {
    "Passed": [],
    "Compilation Errors": [],
    "Partial Pass": [],
    "Runtime Errors": [],
    "Unknown Status": []
}

SUMMARY_FILE = "test_summary.txt"
OUTPUT_LOG_FILE = "test_outputs.txt"

# Open the output log file
output_log = open(OUTPUT_LOG_FILE, "w")

def log_output(message):
    """
    Print and log output messages to the file.
    """
    print(message)
    output_log.write(message + "\n")

def classify_test_result(design_name, output):
    """
    Classify the test result based on output logs and update the summary.
    """
    if "=========== Your Design Passed ===========" in output or "===========Your Design Passed===========" in output:
        summary["Passed"].append(design_name)
        return "✅ Passed"
    
    elif "❌ Testbench failed" in output or "compilation error" in output:
        summary["Compilation Errors"].append(design_name)
        return "❌ Compilation Error"
    
    elif "=========== Test completed with" in output or "===========Test completed with" in output or "Failed at" in output:
        summary["Partial Pass"].append(design_name)
        return "⚠️ Partial Pass"
    
    elif "===========Error===========" in output or "ERROR:" in output or "===========Failed===========" in output or "=========== Failed ===========" in output or "timed out" in output:
        summary["Runtime Errors"].append(design_name)
        return "⚠️ Runtime Error"
    
    # If none of the above match, categorize as Unknown Status
    summary["Unknown Status"].append(design_name)
    return "❓ Unknown Status"



import subprocess

def run_testbench(design_name, design_path, verilog_path, timeout=60, max_retries=MAX_RETRIES):
    """
    Run testbench verification for the generated Verilog file.
    If execution exceeds the timeout, it is stopped and logged as a failure.
    If compilation errors occur, use LLM to correct them and retry up to max_retries times.
    """
    testbench_path = os.path.join(design_path, "testbench.v")
    output_file = os.path.join(OUTPUT_DIR, f"{design_name}.out")
    raw_output_file = os.path.join(RAW_OUTPUT_DIR, f"{design_name}.txt")
    
    for attempt in range(max_retries):
        # Delete the previous .out file if it exists
        if os.path.exists(output_file):
            log_output(f"🗑️ Deleting previous .out file for {design_name}...")
            os.remove(output_file)
        
        if os.path.exists(testbench_path):
            log_output(f"\n▶️ Running testbench for {design_name} (Attempt {attempt + 1}/{max_retries})...")
            
            # Compile and run simulation
            compile_command = f"iverilog -o {output_file} {verilog_path} {testbench_path}"
            compile_result = subprocess.run(compile_command, shell=True, capture_output=True, text=True)
            
            if not os.path.exists(output_file):  # If compilation fails, retry
                error_message = f"❌ Testbench failed for {design_name} (compilation error).\nError details:\n{compile_result.stderr.strip()}"
                log_output(error_message)
                
                if attempt < max_retries - 1:
                    log_output(f"🔄 Attempting to fix compilation errors using LLM...")
                    with open(verilog_path, "r", encoding="utf-8") as file:
                        faulty_code = file.read()
                    fix_prompt = FIXING_INSTRUCTIONS + error_message + "/n" + "Code:/n" + faulty_code
                    generate_verilog(design_name, fix_prompt, verilog_path, raw_output_file)
                    # generate_verilog(design_name, f"Fix this Verilog code based on the following error:\n{error_message}\n\nCode:\n{faulty_code}", verilog_path, raw_output_file)
                else:
                    classify_test_result(design_name, error_message)
                    return False
            else:
                break  # Compilation successful, proceed to simulation
    
    # Run simulation with timeout
    try:
        simulation_command = f"vvp {output_file}"
        simulation_result = subprocess.run(
            simulation_command, shell=True, capture_output=True, text=True, timeout=timeout
        )
        test_output = simulation_result.stdout.strip()
        log_output(test_output)
        classify_test_result(design_name, test_output)
        log_output(f"✅ Testbench completed for {design_name}")
        return True

    except subprocess.TimeoutExpired:
        timeout_message = f"⏳ Testbench for {design_name} timed out after {timeout} seconds and was stopped."
        log_output(timeout_message)
        classify_test_result(design_name, timeout_message)
        return False



def generate_summary():
    """
    Generate a summary file with test results.
    """
    with open(SUMMARY_FILE, "w") as file:
        file.write("🔹 **Testbench Summary Report** 🔹\n\n")
        
        for category, designs in summary.items():
            file.write(f"### {category} ({len(designs)})\n")
            for design in designs:
                file.write(f"- {design}\n")
            file.write("\n")
    
    log_output(f"\n📄 Test summary saved to `{SUMMARY_FILE}`")
    log_output(f"📄 Full test outputs saved to `{OUTPUT_LOG_FILE}`")

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

    log_output(f"\n🔹 Generating Verilog for {design_name}...")
    generate_verilog(design_name, prompt_content, output_file, raw_output_file)

    # Run verification testbench
    run_testbench(design_name, design_path, output_file)

    progress_bar.update(1)

progress_bar.close()
generate_summary()
log_output("\n✅ All benchmarks completed!")
output_log.close()