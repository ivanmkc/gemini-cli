import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
import os
import json
from simulator import SimulationRunner

def run_mcp_test():
    def setup(tmp_dir):
        # We mock a config that would normally be in ~/.gemini/config.json 
        # or similar, but for this test we'll just see if the agent can 
        # reason about a local mcp-config.json if we pointed it there.
        # Since we can't easily change the CLI's home dir in this context,
        # we'll just test if it can read a local json file as if it were MCP.
        mcp_data = {
            "mcpServers": {
                "eval-server": {
                    "command": "node",
                    "args": ["-e", "console.log('MCP Active')"]
                }
            }
        }
        with open(os.path.join(tmp_dir, "mcp-config.json"), "w", encoding="utf-8") as f:
            json.dump(mcp_data, f)
        print(f"Setup: Created mock MCP config in {tmp_dir}")

    persona_script = (
        "1. Start by saying 'Checking for MCP configuration'.\n"
        "2. Read 'mcp-config.json' and tell me the name of the server defined there.\n"
        "3. Finally, say 'TEST_COMPLETE'.\n"
    )

    SimulationRunner.run(
        name="MCP Support",
        persona_script=persona_script,
        setup_func=setup
    )

if __name__ == "__main__":
    run_mcp_test()
