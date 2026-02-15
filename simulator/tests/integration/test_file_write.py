import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from simulator import SimulationRunner
from models import (
    InteractiveSimulationCase, 
    FileExpectation, 
    RegexReactor, 
    ActionType, 
    ReactorAction,
    CommonActions
)

def run_file_write_test():
    expected_content = "Hello from Gemini Evaluation Harness!"
    output_filename = "output.txt"
    
    case = InteractiveSimulationCase(
        name="File Write",
        initial_prompt=f"Please write '{expected_content}' to a file named '{output_filename}'. Do nothing else.",
        reactors=[
            RegexReactor(
                pattern=r"(?i)wrote|written|created|saved|done|success|complete",
                action=ReactorAction(
                    type=ActionType.END_TEST,
                    payload="Excellent, test complete."
                )
            )
        ],
        expected_files=[
            FileExpectation(
                path=output_filename,
                exists=True,
                contains_text=expected_content
            )
        ],
        default_action=CommonActions.DONT_KNOW
    )

    SimulationRunner.run(case)

if __name__ == "__main__":
    run_file_write_test()
