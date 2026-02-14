import pexpect
import os
import json
import glob
import time
import re
import tempfile
from google import genai

class LLMUserSimulant:
    def __init__(self, persona_script):
        self.persona_script = persona_script
        self.client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
        self.history = []

    def generate_reply(self, agent_output):
        prompt = (
            f"You are a human user testing a CLI agent. Follow this script EXACTLY:\n"
            f"{self.persona_script}\n\n"
            f"The agent just said:\n{agent_output}\n\n"
            f"Current History:\n{self.history}\n"
            f"Respond as the user in plain English text WITHOUT markdown code blocks or tool calls.\n"
            f"If the script is finished, say 'TEST_COMPLETE'.\n"
            f"Do not include any other text in your response."
        )
        
        try:
            response = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )
            reply = str(response.text).strip()
            self.history.append({"agent": agent_output, "user": reply})
            return reply
        except Exception as e:
            print(f"DEBUG: Simulant failed to generate text (blocked or empty): {e}")
            return "TEST_COMPLETE"

class GeminiCliHarness:
    def __init__(self, command, args, cwd, log_file_path, fake_home=None):
        self.command = command
        self.args = args
        self.cwd = cwd
        self.log_file_path = log_file_path
        self.fake_home = fake_home
        
        # Clear the debug log at startup to ensure fresh session extraction
        debug_log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug.log")
        if os.path.exists(debug_log):
            open(debug_log, 'w').close()
            
        print(f"Starting gemini-cli driver: {command} {' '.join(args)} in {cwd}")
        
        env = os.environ.copy()
        env["GEMINI_APPROVAL_MODE"] = "yolo"
        env["NO_COLOR"] = "true"
        env["NODE_ENV"] = "development"
        # Try to bypass registry issues that might be inherited
        env["NPM_CONFIG_REGISTRY"] = "https://registry.npmjs.org/"
        # Disable auto-updates during tests
        env["GEMINI_DISABLE_AUTO_UPDATE"] = "1"
        env["NO_UPDATE_NOTIFIER"] = "1"
        env["UPDATE_NOTIFIER_LIB_DISABLE"] = "1"
        env["DEV"] = "true"  # Bypasses internal updateCheck.ts in gemini-cli
        env["GEMINI_DEBUG_LOG_FILE"] = debug_log
        
        if fake_home:
            env["HOME"] = fake_home
        
        self.child = pexpect.spawn(
            command,
            args,
            cwd=cwd,
            encoding="utf-8",
            timeout=180,
            env=env
        )
        self.logfile = open(log_file_path, "w", encoding="utf-8")
        self.child.logfile = self.logfile

    def expect_and_capture(self, pattern, timeout=180):
        try:
            return self.child.expect(pattern, timeout=timeout)
        except pexpect.EOF:
            print(f"Error: End Of File (EOF). {self.child.before}")
            return -1
        except pexpect.TIMEOUT:
            print(f"Error: Timeout after {timeout} seconds. {self.child.before}")
            return -2

    def send_user_reply(self, text: str):
        # The gemini-cli accepts multi-line input and requires shift+tab to submit if it sees newlines.
        # To avoid complex keypress simulation, we ensure our reply is a single line.
        single_line_text = text.replace('\n', ' ').replace('\r', ' ')
        print(f"\n[Turn: SIMULANT]\n{single_line_text}\n")
        self.child.send(single_line_text + "\r")

    def get_agent_turn_text(self):
        try:
            content = self.child.before or ""
            clean_content = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', content)
            return clean_content.strip()
        except Exception as e:
            return ""

    def extract_latest_session(self, fake_home, target_path="structured_metadata.json"):
        if fake_home:
            base_tmp_dir = os.path.join(fake_home, ".gemini", "tmp")
        else:
            base_tmp_dir = os.path.expanduser("~/.gemini/tmp")
            
        if not os.path.exists(base_tmp_dir):
            return None
            
        session_files = glob.glob(os.path.join(base_tmp_dir, "**/chats/session-*.json"), recursive=True)
        if not session_files:
            return None
            
        latest_file = max(session_files, key=os.path.getmtime)
        try:
            with open(latest_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            with open(target_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
                    
            return target_path
        except Exception as e:
            print(f"DEBUG: Failed to extract session: {e}")
            return None

    def close(self):
        self.child.close()
        self.logfile.close()

class SimulationRunner:
    @staticmethod
    def run(name, persona_script, setup_func=None, verify_func=None):
        """
        Standard orchestrator for a simulated user run.
        """
        py_dir = os.path.dirname(os.path.abspath(__file__))
        cli_root = os.path.abspath(os.path.join(py_dir, ".."))
        cli_entry = os.path.join(cli_root, "packages", "cli", "dist", "index.js")
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            print(f"--- Starting Simulation: {name} ---")
            print(f"Sandbox: {tmp_dir}")
            
            # Create a fake HOME to isolate global config and avoid polluting user's ~/.gemini
            fake_home = os.path.join(tmp_dir, ".fake_home")
            os.makedirs(fake_home, exist_ok=True)
            
            # The trusted folders JSON maps paths to TrustLevel enum strings
            trusted_file = os.path.join(fake_home, ".gemini", "trustedFolders.json")
            os.makedirs(os.path.dirname(trusted_file), exist_ok=True)
            with open(trusted_file, "w") as f:
                json.dump({os.path.realpath(tmp_dir): "TRUST_FOLDER"}, f)
                
            # Pre-seed settings to bypass the authentication prompt by setting the selectedType
            settings_file = os.path.join(fake_home, ".gemini", "config", "settings.json")
            os.makedirs(os.path.dirname(settings_file), exist_ok=True)
            with open(settings_file, "w") as f:
                json.dump({
                    "security": {
                        "auth": {
                            "selectedType": "use_gemini"
                        }
                    }
                }, f)
            
            if setup_func:
                setup_func(tmp_dir)
            
            simulant = LLMUserSimulant(persona_script)
            log_path = os.path.join(py_dir, f"session_{name.lower().replace(' ', '_')}.log")
            
            # Start simulation
            success = False
            try:
                print("Starting iterative simulation with headless mode (-p)...")
                
                env = os.environ.copy()
                env["GEMINI_APPROVAL_MODE"] = "yolo"
                env["NO_COLOR"] = "true"
                env["NODE_ENV"] = "development"
                env["NPM_CONFIG_REGISTRY"] = "https://registry.npmjs.org/"
                env["GEMINI_DISABLE_AUTO_UPDATE"] = "1"
                env["NO_UPDATE_NOTIFIER"] = "1"
                env["UPDATE_NOTIFIER_LIB_DISABLE"] = "1"
                env["DEV"] = "true"
                
                debug_log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug.log")
                if os.path.exists(debug_log):
                    open(debug_log, 'w').close()
                env["GEMINI_DEBUG_LOG_FILE"] = debug_log
                env["HOME"] = fake_home

                turn_count = 0
                max_turns = 10
                
                # The first prompt is an empty string so the agent initiates the conversation
                # Or we can just send the first persona reply immediately
                first_prompt = simulant.generate_reply("Hello! How can I help you today?")
                current_prompt = first_prompt
                
                with open(log_path, "w") as logfile:
                    while turn_count < max_turns:
                        turn_count += 1
                        print(f"\n--- [Turn {turn_count}: SIMULANT] ---\n{current_prompt}\n")
                        logfile.write(f"\n[Turn {turn_count}: SIMULANT]\n{current_prompt}\n")
                        
                        cmd_args = [cli_entry, "--yolo"]
                        if turn_count > 1:
                            cmd_args.extend(["-r", "latest"])
                        cmd_args.extend(["-p", current_prompt])
                        
                        # Use subprocess instead of pexpect for a clean run
                        import subprocess
                        print(f"Executing: node {' '.join(cmd_args)}")
                        result = subprocess.run(
                            ["node"] + cmd_args,
                            cwd=tmp_dir,
                            env=env,
                            capture_output=True,
                            text=True
                        )
                        
                        agent_text = result.stdout.strip()
                        print(f"--- [Turn {turn_count}: AGENT] ---\n{agent_text[:500]}...\n")
                        logfile.write(f"\n[Turn {turn_count}: AGENT]\n{agent_text}\n")
                        
                        if result.returncode != 0:
                            print(f"CLI Error Output:\n{result.stderr}")
                            
                        simulated_reply = simulant.generate_reply(agent_text)
                        
                        if "TEST_COMPLETE" in simulated_reply:
                            break
                            
                        current_prompt = simulated_reply
                
                # Mock harness interface for test scripts that expect it
                class MockHarness:
                    def __init__(self, fake_home, log_file_path):
                        self.fake_home = fake_home
                        self.log_file_path = log_file_path
                    def extract_latest_session(self, home, target_path):
                        return GeminiCliHarness.extract_latest_session(None, home, target_path)
                
                mock_harness = MockHarness(fake_home, log_path)
                
                # Run custom verification
                if verify_func:
                    success = verify_func(tmp_dir, mock_harness)
                else:
                    success = True # Default to success if script completed
                    
                # Extract metadata
                metadata_path = os.path.join(py_dir, f"metadata_{name.lower().replace(' ', '_')}.json")
                if mock_harness.extract_latest_session(fake_home, target_path=metadata_path):
                    print(f"Metadata extracted to {metadata_path}")
                    
            except Exception as e:
                print(f"Simulation Error: {e}")
                import traceback
                traceback.print_exc()
                
            print(f"--- Simulation {name} Finished (Success: {success}) ---\n")
            return success
