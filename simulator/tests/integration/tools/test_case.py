"""
Integration test module for the 'Tools' scenario.

This module defines and executes an interactive simulation case using the 
declarative Pydantic harness. It asserts the agent's behavior through LLM reactors 
and filesystem verification.
"""
import sys, os
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
    case = InteractiveSimulationCase(
        name="Multi Turn Tools Test",
        initial_prompt="What version of node is installed? Please check and tell me.",
        reactors=[
            LLMReactor(
                goal_prompt="The agent has checked the node version using a shell tool and reported it.",
                action=ReactorAction(type=ActionType.RESPOND, payload="Great. Now write that version number '1.2.3-mock' into a new file called CORE_VERSION.txt in the current directory.")
            ),
            LLMReactor(
                goal_prompt="The agent has successfully written the version '1.2.3-mock' to 'CORE_VERSION.txt'.",
                action=ReactorAction(type=ActionType.END_TEST, payload="Tools multi-turn test complete.")
            )
        ],
        expected_files=[
            FileExpectation(path="CORE_VERSION.txt", exists=True, contains_text="1.2.3-mock")
        ]
    )
    result = SimulationRunner.run(case, backend=backend, output_dir=output_dir)
    assert result.success, f'Simulation execution failed.'

if __name__ == "__main__":
    test_scenario("gemini-cli", None)
