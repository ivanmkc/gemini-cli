import sys
import os

# simulator.py facade
# This file imports everything from the new modules to maintain backward compatibility
# for tests that import from `simulator`.

# Ensure the current directory is in the path so we can import models, harness, runner
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import (
    InteractiveSimulationCase,
    FileExpectation,
    ReactorAction,
    ActionType,
    LLMReactor,
    RegexReactor,
    CommonActions,
    SimulationResult,
    SimulationTranscript,
    BaseModel
)

from harness import (
    BaseSimulatorHarness,
    GeminiCliHarness,
    ClaudeCodeHarness,
    AntigravityHarness,
    CodexHarness
)

from runner import (
    SimulationRunner,
    LLMUserSimulant
)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Gemini CLI Simulator")
    parser.add_argument("--case", type=str, help="Name of the simulation case to run")
    parser.add_argument("--backend", type=str, default="gemini-cli", help="Backend to use: gemini-cli, claude-code, etc.")
    parser.add_argument("--prompt", type=str, help="Manual prompt mode (headless)")
    
    # We can add more CLI args here if the simulator is run directly
    # For now, tests use pytest which invokes SimulationRunner directly.
    
    args = parser.parse_args()
    
    if args.case:
        print(f"Running case: {args.case} on backend: {args.backend}")
        # Note: This is just a stub. The actual test runner logic is in pytest files that use SimulationRunner.
        # If we want to run a specific case by name from CLI, we'd need to load it dynamically.
        pass
