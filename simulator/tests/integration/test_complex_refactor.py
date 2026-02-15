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

def run_complex_refactor_test():
    # Setup a deliberately convoluted python file
    bad_code = """
def calculateTotal( items ):
  t = 0
  for i in range(len(items)):
    if items[i]['type'] == 'food':
       t = t + items[i]['price']
    if items[i]['type'] == 'electronics':
       t = t + (items[i]['price'] * 1.2) # tax
  return t
"""
    
    # We expect the agent to refactor it to something cleaner, perhaps using a list comprehension or just cleaner iteration.
    case = InteractiveSimulationCase(
        name="Complex Code Refactor",
        initial_prompt="There is a python file called 'calc.py' in the current directory. It contains a poorly written function. Please analyze it, explain what makes the code bad (e.g. bad naming, relying on index ranges instead of iterating directly, hardcoded magic numbers), and then rewrite it in a more idiomatic Pythonic way, saving the new version back to 'calc.py'.",
        setup_files={
            "calc.py": bad_code
        },
        reactors=[
            LLMReactor(
                goal_prompt="The agent has explained the code smells (like magic numbers, bad naming, using range(len())) and has written the refactored code back to the file. We should now verify the refactoring by telling it 'Code looks good, test complete.' and ending the test.",
                action=ReactorAction(type=ActionType.END_TEST, payload="Code looks good, test complete.")
            ),
            RegexReactor(
                pattern=r"(?i)what.*file|where.*code|can you.*show",
                action=ReactorAction(type=ActionType.RESPOND, payload="Please use your tools to read calc.py directly.")
            )
        ],
        expected_files=[
            FileExpectation(
                path="calc.py",
                exists=True
            )
        ],
        default_action=CommonActions.DONT_KNOW
    )

    # Custom verification to ensure the code was fundamentally changed
    def check_refactor(tmp_dir, harness):
        import ast
        with open(os.path.join(tmp_dir, "calc.py"), 'r') as f:
            code = f.read()
            
        if "range(len(" in code:
            print("Failed: The agent did not remove the unidiomatic index iteration.")
            return False
            
        try:
            ast.parse(code)
            print("Success: Refactored code parses correctly.")
            return True
        except SyntaxError:
            print("Failed: The agent wrote invalid syntax.")
            return False
            
    case.custom_verify = check_refactor
    SimulationRunner.run(case)

if __name__ == "__main__":
    run_complex_refactor_test()
