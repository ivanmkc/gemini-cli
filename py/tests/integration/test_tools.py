import os
from simulator import SimulationRunner

def run_complex_tool_test():
    # A persona script that requires multi-turn tool interaction
    persona_script = (
        "1. Ask me to find the version of gemini-cli-core in its package.json file. Wait for me to read the file and tell you the version.\n"
        "2. Once I give you the version number, ask me to write that version number into a new file called CORE_VERSION.txt in the current directory.\n"
        "3. Wait for me to write the file, then ask me to list the files in the directory to verify it exists.\n"
        "4. Once I list the files and you see CORE_VERSION.txt, verify it is correct and say 'TEST_COMPLETE'. DO NOT say 'TEST_COMPLETE' until you have verified the file is in the directory listing.\n"
    )
    
    def setup(tmp_dir):
        # We need a dummy package.json in the tmp_dir to simulate the finding part
        # Alternatively, we let the agent search the real workspace if we ran from root,
        # but the simulator runs in an isolated tmp_dir. So we create a mock one.
        os.makedirs(os.path.join(tmp_dir, "packages", "core"), exist_ok=True)
        with open(os.path.join(tmp_dir, "packages", "core", "package.json"), "w", encoding="utf-8") as f:
            f.write('{"name": "gemini-cli-core", "version": "1.2.3-mock"}')
        print(f"Setup: Created mock package.json in {tmp_dir}")

    def verify(tmp_dir, harness):
        # We check the exported structured metadata to ensure the file was created
        version_file = os.path.join(tmp_dir, "CORE_VERSION.txt")
        if os.path.exists(version_file):
            print(f"Success: Found {version_file}")
            with open(version_file, 'r', encoding='utf-8') as f:
                content = f.read()
            if "1.2.3-mock" in content:
                print("Success: File contains correct version.")
                return True
            else:
                print(f"Error: File contains incorrect content {content}")
        else:
            print("Error: CORE_VERSION.txt not created.")
            
        return False

    SimulationRunner.run(
        name="Multi Turn Tools",
        persona_script=persona_script,
        setup_func=setup,
        verify_func=verify
    )

if __name__ == "__main__":
    run_complex_tool_test()
