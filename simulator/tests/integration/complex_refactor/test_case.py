"""
Integration test module for the 'Complex Refactor' scenario.

This module defines and executes an interactive simulation case using the 
declarative Pydantic harness. It asserts the agent's behavior through LLM reactors 
and filesystem verification.
"""
import sys, os
# Root is gemini-cli
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
    setup_dir = os.path.join(os.path.dirname(__file__), "snippets")
    
    case = InteractiveSimulationCase(
        name="Complex Code Refactor (Externalized)",
        initial_prompt=(
            "There is a python file called 'calc.py' in the current directory. "
            "It contains a poorly written function. Please analyze it, explain what makes the code bad "
            "(e.g. bad naming, relying on index ranges instead of iterating directly, hardcoded magic numbers), "
            "and then rewrite it in a more idiomatic Pythonic way, saving the new version back to 'calc.py'."
        ),
        setup_dir=setup_dir,
        reactors=[
            LLMReactor(
                goal_prompt=(
                    "The agent has successfully identified the code smells (magic numbers, naming, C-style iteration), "
                    "explained them, and rewritten 'calc.py' in an idiomatic way. End the test successfully."
                ),
                action=ReactorAction(type=ActionType.END_TEST, payload="Refactor and explanation complete.")
            ),
            LLMReactor(
                goal_prompt="The agent is asking for the file content or more information about the task rules.",
                action=ReactorAction(type=ActionType.RESPOND, payload="Please proceed by reading calc.py and performing the requested analysis.")
            )
        ],
        expected_files=[
            FileExpectation(
                path="calc.py",
                exists=True,
                contains_text="def "
            )
        ],
        default_action=CommonActions.DONT_KNOW
    )

    # Custom verification to ensure the code at least parses
    def verify_syntax(tmp_dir, harness):
        calc_path = os.path.join(tmp_dir, "calc.py")
        if not os.path.exists(calc_path):
            return False
        with open(calc_path, 'r') as f:
            content = f.read()
        try:
            compile(content, "calc.py", "exec")
            print("Success: Refactored code parses correctly.")
            return True
        except SyntaxError as e:
            print(f"Failed: Refactored code has syntax errors: {e}")
            return False
            
    case.custom_verify = verify_syntax
    result = SimulationRunner.run(case, backend=backend, output_dir=output_dir)
    assert result.success, f'Simulation execution failed.'

if __name__ == "__main__":
    test_scenario("gemini-cli", None)
