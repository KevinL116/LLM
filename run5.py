import subprocess
import os
import shutil

# Define paths
TEST_SCRIPT = "/mnt/data/LLM/prompts/script_all_v3.py"  # Path to the test script
RESULTS_DIR = "/mnt/data/LLM/prompts/test_results"  # Directory to store results
os.makedirs(RESULTS_DIR, exist_ok=True)  # Ensure results directory exists

# Original output files from the test script
SUMMARY_FILE = "test_summary.txt"
OUTPUT_LOG_FILE = "test_outputs.txt"

# Number of times to run the test
NUM_RUNS = 15

for i in range(1, NUM_RUNS + 1):
    print(f"\n▶️ Running test iteration {i}/{NUM_RUNS}...\n")
    
    # Define log files for this iteration
    output_log = os.path.join(RESULTS_DIR, f"test_output_run_{i}.txt")
    error_log = os.path.join(RESULTS_DIR, f"test_error_run_{i}.txt")
    summary_log = os.path.join(RESULTS_DIR, f"test_summary_run_{i}.txt")
    full_output_log = os.path.join(RESULTS_DIR, f"test_outputs_run_{i}.txt")
    
    # Run the test script and capture output
    with open(output_log, "w") as out_file, open(error_log, "w") as err_file:
        subprocess.run(["python3", TEST_SCRIPT], stdout=out_file, stderr=err_file)
    
    # Copy the generated summary and output log to the results directory
    if os.path.exists(SUMMARY_FILE):
        shutil.copy(SUMMARY_FILE, summary_log)
    if os.path.exists(OUTPUT_LOG_FILE):
        shutil.copy(OUTPUT_LOG_FILE, full_output_log)
    
    print(f"✅ Run {i} completed. Results saved in {RESULTS_DIR}/")

print("\n🎯 All test runs completed. Check the results in /mnt/data/test_results/")
