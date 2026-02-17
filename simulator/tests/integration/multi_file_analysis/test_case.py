"""
Integration test module for the 'Multi File Analysis' scenario.

This module defines and executes an interactive simulation case using the 
declarative Pydantic harness. It asserts the agent's behavior through LLM reactors 
and filesystem verification.
"""
import sys, os
# Root is gemini-cli
# This file is in simulator/tests/integration/multi_file_analysis/test_case.py
SIMULATOR_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, SIMULATOR_ROOT)

from simulator import SimulationRunner
from models import (
    InteractiveSimulationCase, 
    FileExpectation, 
    LLMReactor, 
    ActionType, 
    ReactorAction,
    CommonActions
)

def test_scenario(backend, output_dir) -> None:
    """Executes the specific interactive scenario and verifies expected behaviors."""
    # Path to the snippets directory relative to this file
    setup_dir = os.path.join(os.path.dirname(__file__), "snippets")
    
    case = InteractiveSimulationCase(
        name="Multi-File Analysis (Externalized)",
        initial_prompt=(
            "There are two files in this workspace: 'constants.py' and 'app.py'. "
            "Please update 'app.py' so that the connect_to_api function uses the API_VERSION "
            "and the get_config function uses the MIN_RETRY_COUNT defined in 'constants.py'. "
            "Do not hardcode the values in app.py; import them from constants instead if they aren't already."
        ),
        setup_dir=setup_dir, # SEEDED FROM EXTERNAL DIRECTORY
        reactors=[
            LLMReactor(
                goal_prompt=(
                    "The agent has successfully modified app.py to use constants.API_VERSION "
                    "and constants.MIN_RETRY_COUNT instead of hardcoded values. "
                    "End the test with a success message."
                ),
                action=ReactorAction(type=ActionType.END_TEST, payload="Analysis and update complete. Cross-file consistency verified.")
            ),
            LLMReactor(
                goal_prompt="The agent is asking for clarification about which files to read or what the constants are.",
                action=ReactorAction(type=ActionType.RESPOND, payload="Please read both constants.py and app.py to understand the required changes.")
            )
        ],
        expected_files=[
            FileExpectation(
                path="app.py",
                exists=True,
                contains_text="constants.API_VERSION"
            ),
            FileExpectation(
                path="app.py",
                exists=True,
                contains_text="constants.MIN_RETRY_COUNT"
            )
        ],
        default_action=CommonActions.DONT_KNOW
    )

    # Custom verification to ensure it's not just a string replacement but a logical fix
    def verify_import_usage(tmp_dir, harness):
        app_path = os.path.join(tmp_dir, "app.py")
        if not os.path.exists(app_path):
            print(f"Failed: {app_path} does not exist.")
            return False
            
        with open(app_path, 'r') as f:
            content = f.read()
        
        # Check that old hardcoded values are gone
        if "v1.0.0" in content:
            print("Failed: Hardcoded API version still exists in app.py.")
            return False
        if "3" in content and "retry" in content:
             if "constants.MIN_RETRY_COUNT" not in content:
                print("Failed: Retry count still seems hardcoded.")
                return False
                
        print("Success: app.py appears to use references from constants.py.")
        return True
            
    case.custom_verify = verify_import_usage
    result = SimulationRunner.run(case, backend=backend, output_dir=output_dir)
    assert result.success, f'Simulation execution failed.'

if __name__ == "__main__":
    test_scenario("gemini-cli", None)
