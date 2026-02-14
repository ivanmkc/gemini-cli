import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
import os
import random
from simulator import SimulationRunner

def run_secret_retrieval_test():
    secret_number = random.randint(100000, 999999)
    
    def setup(tmp_dir):
        with open(os.path.join(tmp_dir, "secret.txt"), "w", encoding="utf-8") as f:
            f.write(str(secret_number))
        print(f"Setup: Written secret {secret_number} to {tmp_dir}/secret.txt")

    def verify(tmp_dir, harness):
        # We check the exported structured metadata for the secret
        log_path = harness.log_file_path
        if not os.path.exists(log_path):
            print(f"Error: Log file {log_path} not found.")
            return False
            
        with open(log_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        if str(secret_number) in content:
            print(f"Success: Found {secret_number} in session log")
            return True
            
        print(f"Error: Secret {secret_number} not found in session log.")
        return False

    persona_script = (
        "1. Ask me to use tools to find the secret number hidden in the file secret.txt in the current directory.\n"
        "2. Wait for me to use my tools to read the file.\n"
        "3. Once I tell you the specific 6-digit number, verify it and then say 'TEST_COMPLETE'. DO NOT say 'TEST_COMPLETE' until I report a 6-digit number.\n"
        "Do not make up a number yourself."
    )

    SimulationRunner.run(
        name="Secret Retrieval",
        persona_script=persona_script,
        setup_func=setup,
        verify_func=verify
    )

if __name__ == "__main__":
    run_secret_retrieval_test()
