import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from simulator import SimulationRunner
from models import (
    InteractiveSimulationCase, 
    RegexReactor, 
    ActionType, 
    ReactorAction,
    CommonActions
)

def run_mcp_test():
    case = InteractiveSimulationCase(
        name="MCP Support",
        initial_prompt="Checking for MCP configuration. Please read 'mcp-config.json' and tell me the name of the server defined there.",
        setup_files={
            "mcp-config.json": '{"mcpServers": {"eval-server": {"command": "node", "args": ["-e", "console.log(\'MCP Active\')"]}}}'
        },
        reactors=[
            RegexReactor(
                pattern="eval-server",
                action=ReactorAction(
                    type=ActionType.END_TEST,
                    payload="Yes, eval-server is the one. Test complete."
                )
            )
        ],
        default_action=CommonActions.DONT_KNOW
    )

    SimulationRunner.run(case)

if __name__ == "__main__":
    run_mcp_test()

