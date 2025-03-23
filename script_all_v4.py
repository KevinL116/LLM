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

RTLLM_DIR = "/mnt/data/RTLLM"  # Root RTLLM directory
OUTPUT_DIR = "/mnt/data/LLM_outputs"  # Where generated Verilog files will be stored
RAW_OUTPUT_DIR = "/mnt/data/RAW_LLM_outputs"  # Folder to store original LLM responses
MAX_RETRIES = 4  # Number of retries on compilation failure
USE_API = False  # Set to True if using API, False for CLI-based LLM

# Ensure output directories exist
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(RAW_OUTPUT_DIR, exist_ok=True)

VERILOG_FORMAT_INSTRUCTION = """
Try to understand the requirements below and give reasoning steps in natural language to achieve it.

Additionally, give advice to avoid syntax errors.

Provide the Verilog code according to the reasoning steps and advice.

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

def get_all_designs(root_dir):
    """
    Recursively find all design directories that contain:
      - design_description.txt
      - testbench.v
    """
    design_paths = []
    for dirpath, _, filenames in os.walk(root_dir):
        if "design_description.txt" in filenames and "testbench.v" in filenames:
            design_paths.append(dirpath)
    return design_paths

design_paths = get_all_designs(RTLLM_DIR)

progress_bar = tqdm(total=len(design_paths))

def extract_verilog_code(output):
    """
    Extract all 'module ... endmodule' blocks from the LLM's raw output.
    Returns all extracted modules joined together OR returns the entire
    output if no valid modules found.
    """
    lines = output.split("\n")
    extracted_modules = []
    current_module = []
    module_depth = 0  # Track if we are inside a module

    for line in lines:
        stripped_line = line.strip()

        if stripped_line.startswith("module "):  # Start of a new module
            if module_depth == 0:
                current_module = [stripped_line]
                module_depth = 1
            else:
                # Another "module" found before 'endmodule'; treat as a new block
                current_module = [stripped_line]

        elif stripped_line.startswith("endmodule"):
            if module_depth == 1:
                current_module.append(stripped_line)
                extracted_modules.append("\n".join(current_module))
                module_depth = 0
                current_module = []
        else:
            if module_depth == 1:
                current_module.append(stripped_line)

    if extracted_modules:
        return "\n\n".join(extracted_modules)
    else:
        return output  # Fallback to entire output if no valid modules found

def generate_verilog(
    design_name, 
    prompt_content, 
    output_file, 
    raw_output_file
):
    """
    Calls an LLM (either local or API) to generate Verilog code.
    Saves both the raw LLM output and the extracted Verilog code.
    """
    full_prompt = VERILOG_FORMAT_INSTRUCTION + "\n\n" + prompt_content

    if USE_API:
        # API-based call
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
            'Authorization': "Bearer sk-darmzk5tbgttdn63"  # Example placeholder
        }

        conn.request("POST", "/maas/v1/chat/completions", payload, headers)
        res = conn.getresponse()
        data = res.read()
        response_json = json.loads(data.decode("utf-8"))

        if "choices" in response_json:
            raw_output = response_json["choices"][0]["message"].get("content", "").strip()
        else:
            raw_output = "No valid response from API."
    else:
        # CLI-based call
        # command = f'ollama run deepseek-coder-v2:16b "{full_prompt}"'
        command = f'ollama run phi4 "{full_prompt}"'
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        raw_output = result.stdout.strip()

    # Save raw LLM output
    with open(raw_output_file, "w", encoding="utf-8") as file:
        file.write(raw_output)

    # Extract 'module...endmodule' code
    verilog_code = extract_verilog_code(raw_output)

    # Save extracted Verilog
    with open(output_file, "w", encoding="utf-8") as file:
        file.write(verilog_code)

summary = {
    "Passed": [],
    "Compilation Errors": [],
    "Partial Pass": [],
    "Runtime Errors": [],
    "Unknown Status": []
}

SUMMARY_FILE = "test_summary.txt"
OUTPUT_LOG_FILE = "test_outputs.txt"
output_log = open(OUTPUT_LOG_FILE, "w")

def log_output(message):
    """
    Print and log output messages to both console and test_outputs.txt
    """
    print(message)
    output_log.write(message + "\n")

def classify_test_result(design_name, output):
    """
    Classify test result by scanning the simulation logs,
    then place the design_name into the correct summary list.
    """
    if ("=========== Your Design Passed ===========" in output or 
        "===========Your Design Passed===========" in output):
        summary["Passed"].append(design_name)
        return "✅ Passed"
    elif ("❌ Testbench failed" in output or 
          "compilation error" in output or
          "compilation failed" in output):
        summary["Compilation Errors"].append(design_name)
        return "❌ Compilation Error"
    elif ("=========== Test completed with" in output or
          "===========Test completed with" in output or
          "Failed at" in output):
        summary["Partial Pass"].append(design_name)
        return "⚠️ Partial Pass"
    elif ("===========Error===========" in output or 
          "ERROR:" in output or 
          "===========Failed===========" in output or 
          "=========== Failed ===========" in output or 
          "timed out" in output):
        summary["Runtime Errors"].append(design_name)
        return "⚠️ Runtime Error"
    else:
        summary["Unknown Status"].append(design_name)
        return "❓ Unknown Status"

def run_testbench(
    design_name, 
    design_path, 
    verilog_path_final, 
    timeout=60, 
    max_retries=MAX_RETRIES
):
    """
    Compile and run the testbench for the generated Verilog design.
    Retries up to max_retries times if there are compilation errors.
    For each attempt, the code is re-generated (using fix prompts)
    and saved to a unique output file, so no data is overwritten.

    """
    testbench_path = os.path.join(design_path, "testbench.v")

    final_output_file = verilog_path_final
    final_raw_output_file = os.path.join(RAW_OUTPUT_DIR, f"{design_name}.txt")

    for attempt in range(1, max_retries + 1):
        # For each attempt, we'll create unique output paths so we don't overwrite
        attempt_output_file = os.path.join(OUTPUT_DIR, f"{design_name}_attempt{attempt}.v")
        attempt_raw_output_file = os.path.join(RAW_OUTPUT_DIR, f"{design_name}_attempt{attempt}.txt")

        if attempt == 1:
            # Attempt #1 uses the already generated base files
            attempt_output_file = verilog_path_final
            attempt_raw_output_file = final_raw_output_file
        else:
            # On subsequent attempts, we call the LLM to fix the code
            log_output(f"🔄 Attempting to fix compilation errors for {design_name} (attempt {attempt})...")
            with open(final_output_file, "r", encoding="utf-8") as file:
                faulty_code = file.read()

            error_message = f"Compilation error on attempt {attempt-1}."
            fix_prompt = FIXING_INSTRUCTIONS + error_message + "\n\nCode:\n" + faulty_code
            generate_verilog(design_name, fix_prompt, attempt_output_file, attempt_raw_output_file)

            # Update final output so the next pass tries to compile the new code
            final_output_file = attempt_output_file
            final_raw_output_file = attempt_raw_output_file

        # Build a unique .out filename for this attempt
        out_file_path = os.path.join(OUTPUT_DIR, f"{design_name}_attempt{attempt}.out")

        # 1) Remove any old .out file with the same name (optional but good practice)
        if os.path.exists(out_file_path):
            os.remove(out_file_path)

        # 2) Compile with iverilog
        compile_command = (
            f"iverilog -o {out_file_path} "
            f"-g 2012 {attempt_output_file} {testbench_path}"
            # f"{attempt_output_file} {testbench_path}"
        )
        compile_result = subprocess.run(compile_command, shell=True, capture_output=True, text=True)

        # Check the return code from iverilog instead of file existence
        if compile_result.returncode != 0:
            # => compilation failed
            error_details = compile_result.stderr.strip()
            error_message = f"compilation error: {compile_result.stderr.strip()}"
            log_output(f"❌ Attempt {attempt} compilation failed for {design_name}.\nError:\n{error_details}")

            if attempt == max_retries:
                # No more attempts left
                classify_test_result(design_name, error_message)
                return False
            else:
                # We'll try again with a fix prompt
                continue
        else:
            # => compilation succeeded; proceed to run simulation
            log_output(f"\n▶️ Running testbench for {design_name} (attempt {attempt})...")
            simulation_command = f"vvp {out_file_path}"
            try:
                simulation_result = subprocess.run(
                    simulation_command, 
                    shell=True, 
                    capture_output=True, 
                    text=True, 
                    timeout=timeout
                )
                test_output = simulation_result.stdout.strip()
                log_output(test_output)
                classify_test_result(design_name, test_output)
                log_output(f"✅ Testbench completed for {design_name} on attempt {attempt}\n")
            except subprocess.TimeoutExpired:
                timeout_message = f"⏳ Testbench for {design_name} timed out after {timeout} seconds on attempt {attempt}."
                log_output(timeout_message)
                classify_test_result(design_name, timeout_message)
            return True

    return False  # If we somehow exhaust the loop unexpectedly

def generate_summary():
    """
    Create summary of the test results in test_summary.txt
    and print them to the log file.
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

# Main Execution
for design_path in design_paths:
    design_name = os.path.basename(design_path)
    prompt_file = os.path.join(design_path, "design_description.txt")

    # Output files for the *first* LLM generation attempt
    base_output_file = os.path.join(OUTPUT_DIR, f"{design_name}.v")
    base_raw_output_file = os.path.join(RAW_OUTPUT_DIR, f"{design_name}.txt")

    # Read the design description prompt
    with open(prompt_file, "r", encoding="utf-8") as file:
        prompt_content = file.read().strip()

    log_output(f"\n🔹 Generating Verilog for {design_name}...")
    generate_verilog(design_name, prompt_content, base_output_file, base_raw_output_file)

    # Compile & run the testbench, with up to MAX_RETRIES
    run_testbench(
        design_name=design_name,
        design_path=design_path,
        verilog_path_final=base_output_file,
        timeout=60,
        max_retries=MAX_RETRIES
    )
    progress_bar.update(1)

progress_bar.close()
generate_summary()
log_output("\n✅ All benchmarks completed!")
output_log.close()
