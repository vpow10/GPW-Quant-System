"""
Script to run the full GPW Quant System pipeline:
Fetch all Stooq data
Fetch WIG20
Preprocess GPW data
Run all strategies
"""
import argparse
import subprocess
import sys
from typing import List


def run_command(cmd: List[str], description: str) -> None:
    print(f"--- Starting: {description} ---")
    print(f"Command: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
        print(f"--- Completed: {description} ---\n")
    except subprocess.CalledProcessError as e:
        print(f"!!! Error during: {description} !!!")
        print(f"Exit code: {e.returncode}")
        sys.exit(e.returncode)
    except KeyboardInterrupt:
        print("\nPipeline interrupted by user.")
        sys.exit(130)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the full GPW Quant System pipeline.")
    parser.parse_args()

    python_exe = sys.executable

    steps = [
        ([python_exe, "-m", "data.scripts.stooq_fetch", "fetch-all"], "Fetch all Stooq data"),
        (
            [python_exe, "-m", "data.scripts.stooq_fetch", "fetch-one", "wig20"],
            "Fetch WIG20 data",
        ),
        ([python_exe, "-m", "data.scripts.preprocess_gpw", "all"], "Preprocess GPW data"),
        (
            [
                python_exe,
                "-m",
                "strategies.run_strategies",
                "--strategies",
                "all",
                "--input",
                "data/processed/reports/combined.parquet",
                "--output-dir",
                "data/signals",
            ],
            "Run all strategies",
        ),
    ]

    print("Starting GPW Quant System Pipeline...")
    for cmd, desc in steps:
        run_command(cmd, desc)

    print("All pipeline steps completed successfully.")


if __name__ == "__main__":
    main()
