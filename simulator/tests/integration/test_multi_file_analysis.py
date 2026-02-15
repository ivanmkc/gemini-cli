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

def run_multi_file_analysis_test():
    # Setup multiple files that require cross-referencing
    constants_content = "API_VERSION = 'v3.5.0'\nMIN_RETRY_COUNT = 5"
    app_content = """
import constants

def connect_to_api():
    # TODO: Update the version from the hardcoded v1 to the one in constants.py
    print("Connecting using API version v1.0.0")
    
def get_config():
    return {
        "retry": 3 # This should match MIN_RETRY_COUNT in constants.py
    }
"""
    
    case = InteractiveSimulationCase(
        name="Multi-File Analysis",
        initial_prompt="There are two files in this workspace: 'constants.py' and 'app.py'. Please update 'app.py' so that the connect_to_api function uses the API_VERSION and the get_config function uses the MIN_RETRY_COUNT defined in 'constants.py'. Do not hardcode the values in app.py; import them from constants instead if they aren't already.",
        setup_files={
            "constants.py": constants_content,
            "app.py": app_content
        },
        reactors=[
            LLMReactor(
                goal_prompt="The agent has successfully modified app.py to use constants.API_VERSION and constants.MIN_RETRY_COUNT instead of hardcoded values. End the test with a success message.",
                action=ReactorAction(type=ActionType.END_TEST, payload="Analysis and update complete. Cross-file consistency verified.")
            ),
            RegexReactor(
                pattern=r"(?i)which.*file|need.*read",
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
        with open(os.path.join(tmp_dir, "app.py"), 'r') as f:
            content = f.read()
        
        # Check that 'v1.0.0' and '3' are gone or at least replaced by variables
        if "v1.0.0" in content:
            print("Failed: Hardcoded API version still exists in app.py.")
            return False
        if "3" in content and "retry" in content:
             # Basic check to see if it was swapped
             if "constants.MIN_RETRY_COUNT" not in content:
                print("Failed: Retry count still seems hardcoded.")
                return False
                
        print("Success: app.py appears to use references from constants.py.")
        return True
            
    case.custom_verify = verify_import_usage
    SimulationRunner.run(case)

if __name__ == "__main__":
    run_multi_file_analysis_test()
