"""
Integration test module for the 'Mcp' scenario.

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
    mcp_config = '''{
  "mcpServers": {
    "fetch": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-fetch"]
    }
  }
}'''

    case = InteractiveSimulationCase(
        name="MCP Fetch Test",
        initial_prompt="Use the configured 'fetch' tool to retrieve the content from 'https://example.com'. Save the text enclosed in the <h1> tag to 'heading.txt'.",
        setup_files={
            ".fake_home/.gemini/settings.json": mcp_config,
            "mcp.json": mcp_config
        },
        reactors=[
            LLMReactor(
                goal_prompt="The agent has successfully fetched the webpage using the fetch MCP tool, parsed the <h1> tag, and wrote it to a file.",
                action=ReactorAction(type=ActionType.END_TEST, payload="Heading extracted and saved.")
            )
        ],
        expected_files=[
            FileExpectation(path="heading.txt", assert_contains="Example Domain", assert_not_contains="<html>")
        ]
    )
    result = SimulationRunner.run(case, backend=backend, output_dir=output_dir)
    assert result.success, f'Simulation execution failed.'

if __name__ == "__main__":
    test_scenario("gemini-cli", None)
