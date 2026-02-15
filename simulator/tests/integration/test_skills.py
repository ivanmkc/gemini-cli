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

def run_skills_test():
    secret_key = "GOLDEN_SKILL_CAPTURED"
    
    case = InteractiveSimulationCase(
        name="Skills Support",
        initial_prompt="Checking for local skills. Please find and read any mock-skills in the workspace and tell me the secret key found within.",
        setup_files={
            ".agents/skills/mock-skill/SKILL.md": f"# Mock Skill\nThis is a test skill. The secret key is '{secret_key}'.\n"
        },
        reactors=[
            RegexReactor(
                pattern=secret_key,
                action=ReactorAction(
                    type=ActionType.END_TEST,
                    payload=f"Correct, the key is {secret_key}. Test complete."
                )
            )
        ],
        default_action=CommonActions.DONT_KNOW
    )

    SimulationRunner.run(case)

if __name__ == "__main__":
    run_skills_test()

