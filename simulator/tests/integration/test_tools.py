import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from simulator import SimulationRunner
from models import (
    InteractiveSimulationCase, 
    FileExpectation, 
    RegexReactor, 
    LLMReactor,
    ActionType, 
    ReactorAction,
    CommonActions
)

def run_complex_tool_test():
    expected_version = "1.2.3-mock"
    
    case = InteractiveSimulationCase(
        name="Multi Turn Tools",
        initial_prompt="Find the version of gemini-cli-core in its package.json file (located in packages/core/package.json).",
        setup_files={
            "packages/core/package.json": f'{{"name": "gemini-cli-core", "version": "{expected_version}"}}'
        },
        reactors=[
            RegexReactor(
                pattern=expected_version,
                action=ReactorAction(
                    type=ActionType.RESPOND, 
                    payload=f"Great. Now write that version number '{expected_version}' into a new file called CORE_VERSION.txt in the current directory."
                )
            ),
            RegexReactor(
                pattern=r"(?i)written|created|saved",
                action=ReactorAction(
                    type=ActionType.RESPOND,
                    payload="Now list the files in the directory to verify it exists."
                )
            ),
            RegexReactor(
                pattern=r"(?i)CORE_VERSION.txt",
                action=ReactorAction(
                    type=ActionType.END_TEST,
                    payload="I see it. Test complete."
                )
            )
        ],
        expected_files=[
            FileExpectation(
                path="CORE_VERSION.txt",
                exists=True,
                contains_text=expected_version
            )
        ],
        default_action=CommonActions.DONT_KNOW
    )

    SimulationRunner.run(case)

if __name__ == "__main__":
    run_complex_tool_test()

