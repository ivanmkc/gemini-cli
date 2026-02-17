"""
Integration test module for the 'Skills' scenario.

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
        name="Skills Support Test",
        initial_prompt="Do we have a skill called 'pr-creator'? If so, tell me its purpose from its documentation.",
        reactors=[
            LLMReactor(
                goal_prompt="The agent has explained the purpose of the 'pr-creator' skill correctly.",
                action=ReactorAction(type=ActionType.END_TEST, payload="Skills test complete.")
            )
        ],
        expected_files=[]
    )
    result = SimulationRunner.run(case, backend=backend, output_dir=output_dir)
    assert result.success, f'Simulation execution failed.'

if __name__ == "__main__":
    test_scenario("gemini-cli", None)
