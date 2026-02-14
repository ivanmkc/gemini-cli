import os
from simulator import SimulationRunner

def run_skills_test():
    secret_key = "GOLDEN_SKILL_CAPTURED"
    
    def setup(tmp_dir):
        skills_dir = os.path.join(tmp_dir, ".agents", "skills", "mock-skill")
        os.makedirs(skills_dir, exist_ok=True)
        skill_content = f"""# Mock Skill
This is a test skill. The secret key is '{secret_key}'.
"""
        with open(os.path.join(skills_dir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(skill_content)
        print(f"Setup: Created mock-skill in {skills_dir}")

    def verify(tmp_dir, harness):
        with open(harness.log_file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return secret_key in content

    persona_script = (
        f"1. Start by saying 'Checking for local skills'.\n"
        f"2. Find and read the mock-skill in the workspace.\n"
        f"3. Tell me the secret key found in the skill.\n"
        f"4. Finally, say 'TEST_COMPLETE'.\n"
    )

    SimulationRunner.run(
        name="Skills Support",
        persona_script=persona_script,
        setup_func=setup,
        verify_func=verify
    )

if __name__ == "__main__":
    run_skills_test()
