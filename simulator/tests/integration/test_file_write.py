import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
import os
from simulator import SimulationRunner

def run_file_write_test():
    expected_content = "Hello from Gemini Evaluation Harness!"
    output_filename = "output.txt"
    
    def verify(tmp_dir, harness):
        output_file_path = os.path.join(tmp_dir, output_filename)
        if os.path.exists(output_file_path):
            with open(output_file_path, "r", encoding="utf-8") as f:
                actual_content = f.read()
            return expected_content in actual_content
        return False

    persona_script = (
        f"1. Start by saying 'Ready to test file writing'.\n"
        f"2. Use tools to write the text '{expected_content}' to a file named '{output_filename}'.\n"
        f"3. Once successful, say 'File written'.\n"
        f"4. Finally, say 'TEST_COMPLETE'.\n"
    )

    SimulationRunner.run(
        name="File Write",
        persona_script=persona_script,
        verify_func=verify
    )

if __name__ == "__main__":
    run_file_write_test()
