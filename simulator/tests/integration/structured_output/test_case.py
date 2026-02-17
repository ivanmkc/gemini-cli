"""
Integration test module for the 'Structured Output' scenario.

This module defines and executes an interactive simulation case using the 
declarative Pydantic harness, explicitly validating the newly added 
`output_schema` framework support for parsing `output.json` into typed objects.
"""
import sys, os
from pydantic import BaseModel, ConfigDict
# Root is gemini-cli
SIMULATOR_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, SIMULATOR_ROOT)

from simulator import SimulationRunner
from models import (
    InteractiveSimulationCase, 
    LLMReactor, 
    ActionType, 
    ReactorAction
)

class PersonProfile(BaseModel):
    name: str
    age: int
    occupation: str
    is_fictional: bool

def test_scenario(backend, output_dir) -> None:
    """Executes the specific interactive scenario and verifies expected behaviors."""
    case = InteractiveSimulationCase(
        name="Structured Output Pydantic Extraction",
        initial_prompt=(
            "Please analyze the following text and extract the identity details.\n"
            "'Bilbo Baggins is a 111 year old Hobbit from the Shire who works as a Burglar.'\n"
            "Format your extraction into the required `output.json` schema."
        ),
        output_schema=PersonProfile,
        reactors=[
            LLMReactor(
                goal_prompt=(
                    "The agent has successfully written the identity details "
                    "to the output.json file in the required format."
                ),
                action=ReactorAction(type=ActionType.END_TEST, payload="JSON generated.")
            )
        ]
    )
    
    result = result = SimulationRunner.run(case, backend=backend, output_dir=output_dir)
    assert result.success, f'Simulation execution failed.'
    
    # Assert successful execution and parser logic
    assert result.success is True, "Simulation failed to complete or validate JSON."
    
    # Assert hydration
    profile = result.extracted_output
    assert isinstance(profile, PersonProfile), f"Expected PersonProfile, got {type(profile)}"
    assert profile.name == "Bilbo Baggins"
    assert profile.age == 111
    assert profile.is_fictional is True

if __name__ == "__main__":
    test_scenario("gemini-cli", None)
