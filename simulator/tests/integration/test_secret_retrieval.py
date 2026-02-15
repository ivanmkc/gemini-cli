import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
import random
from simulator import SimulationRunner
from models import (
    InteractiveSimulationCase, 
    RegexReactor, 
    ActionType, 
    ReactorAction,
    CommonActions
)

def run_secret_retrieval_test():
    secret_number = random.randint(100000, 999999)

    case = InteractiveSimulationCase(
        name="Secret Retrieval",
        initial_prompt="Can you please use your tools to find the secret number hidden in the file secret.txt in the current directory?",
        setup_files={
            "secret.txt": str(secret_number)
        },
        reactors=[
            RegexReactor(
                pattern=str(secret_number),
                action=ReactorAction(
                    type=ActionType.END_TEST,
                    payload=f"Correct! The secret was {secret_number}."
                )
            )
        ],
        default_action=CommonActions.DONT_KNOW
    )

    SimulationRunner.run(case)

if __name__ == "__main__":
    run_secret_retrieval_test()
