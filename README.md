# LLM Verilog Generation

This repository contains Python scripts designed to test and evaluate the capability of Large Language Models (LLMs) to generate Verilog code. The evaluation framework used here is RTLLM.

## Overview

The scripts provided mainly utilize Ollama to run various LLMs. There's also functionality to run LLMs via API calls included but not yet thoroughly tested. Each run produces a summary of results, and the output for each test is saved (note: only the latest run is retained if retries exceed one).

## Available Scripts

- **`script_all.py`**:
  - The initial script version that evaluates LLM-generated Verilog code using RTLLM.
  - Change the target LLM by modifying the `generate_verilog` function.

- **`script_all_v2.py`**:
  - Adds automatic rerun capabilities in case of compilation errors.
  - Adjust the number of retries by modifying `MAX_RETRIES`.

- **`script_all_v3.py`**:
  - Enhanced prompts to improve error avoidance.
  - Includes additional reasoning prompts for the LLM.

- **`run5.py`**:
  - Facilitates running benchmarks multiple times.
  - Adjust `NUM_RUNS` to control how many benchmarks are executed.

## Getting Started

### Prerequisites

Install the following software:

- [Ollama](https://github.com/ollama/ollama)
- [Icarus Verilog (iVerilog)](https://github.com/steveicarus/iverilog)
- Desired LLM model from Ollama

### Setup and Configuration

Before running benchmarks, consider the following adjustments based on your environment:

- Update paths to absolute paths if the testbench uses external files.
- Remove instances of `$break` from the asynchronous `FIFO` testbench.
- Use explicit module instantiation for the `LFSR` testbench.
- Rename folders if their names contain spaces.
- Adjust the `modelfile` of the LLM if generation issues arise due to length limitations. Refer to the [Ollama modelfile documentation](https://github.com/ollama/ollama/blob/main/docs/modelfile.md).
- Modify the description of the `barrel_shifter` if generation consistently fails.

## Running the Benchmark

Execute your desired script with Python:

```bash
python script_all_v3.py
```

Ensure all prerequisites and setup configurations are met prior to execution.
