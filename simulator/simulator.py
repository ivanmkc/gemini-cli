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
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            api_key = SimulationRunner.discover_api_key()
        self.client = genai.Client(api_key=api_key, vertexai=False)
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
                model="gemini-2.0-flash",
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
    def discover_api_key():
        """Attempts to find the API key in the environment or user settings."""
        key = os.environ.get("GEMINI_API_KEY")
        if key:
            return key
            
        settings_path = os.path.expanduser("~/.gemini/settings.json")
        if os.path.exists(settings_path):
            try:
                with open(settings_path, 'r') as f:
                    data = json.load(f)
                    # Check MCP servers for a key (common fallback in this repo)
                    mcp_servers = data.get("mcpServers", {})
                    for server in mcp_servers.values():
                        env = server.get("env", {})
                        if env.get("GEMINI_API_KEY"):
                            return env["GEMINI_API_KEY"]
            except Exception:
                pass
        return None

    @staticmethod
    def run(case):
        """
        Standard orchestrator for a simulated user run using an InteractiveSimulationCase.
        """
        # Ensure we can import the models internally
        try:
            from models import InteractiveSimulationCase, ActionType, CommonActions
        except ImportError:
            from simulator.models import InteractiveSimulationCase, ActionType, CommonActions
            
        py_dir = os.path.dirname(os.path.abspath(__file__))
        cli_command = os.environ.get("GEMINI_CLI_COMMAND")
        
        if cli_command:
            base_cmd = [cli_command]
            print(f"Using global CLI command from environment: {cli_command}")
        else:
            cli_root = os.path.abspath(os.path.join(py_dir, ".."))
            cli_entry = os.path.join(cli_root, "packages", "cli", "dist", "index.js")
            base_cmd = ["node", cli_entry]
            
        api_key = SimulationRunner.discover_api_key()
            
        with tempfile.TemporaryDirectory() as tmp_dir:
            print(f"--- Starting Simulation: {case.name} ---")
            print(f"Sandbox: {tmp_dir}")
            
            # Auto-dump setup files
            for filename, content in case.setup_files.items():
                filepath = os.path.join(tmp_dir, filename)
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(content)
                print(f"Setup: Created {filepath}")
            
            # Write a .env file to the workspace to ensure the CLI picks up the API key
            if api_key:
                with open(os.path.join(tmp_dir, ".env"), "w", encoding="utf-8") as f:
                    f.write(f"GEMINI_API_KEY={api_key}\n")
                print(f"Setup: Created {tmp_dir}/.env")
            
            # Create a fake HOME to isolate global config and avoid polluting user's ~/.gemini
            fake_home = os.path.join(tmp_dir, ".fake_home")
            os.makedirs(fake_home, exist_ok=True)
            
            # The trusted folders JSON maps paths to TrustLevel enum strings
            trusted_file = os.path.join(fake_home, ".gemini", "trustedFolders.json")
            os.makedirs(os.path.dirname(trusted_file), exist_ok=True)
            with open(trusted_file, "w") as f:
                json.dump({os.path.realpath(tmp_dir): "TRUST_FOLDER"}, f)
                
            # Pre-seed settings to bypass the authentication prompt by setting the selectedType
            settings_file = os.path.join(fake_home, ".gemini", "settings.json")
            os.makedirs(os.path.dirname(settings_file), exist_ok=True)
            with open(settings_file, "w") as f:
                json.dump({
                    "security": {
                        "auth": {
                            "selectedType": "gemini-api-key"
                        }
                    }
                }, f)
            
            log_path = os.path.join(py_dir, f"session_{case.name.lower().replace(' ', '_')}.log")
            
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
                if api_key:
                    env["GEMINI_API_KEY"] = api_key
                
                debug_log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug.log")
                if os.path.exists(debug_log):
                    open(debug_log, 'w').close()
                env["GEMINI_DEBUG_LOG_FILE"] = debug_log
                env["HOME"] = fake_home

                turn_count = 0
                current_prompt = case.initial_prompt
                
                # Setup LLM Simulant specifically for LLMReactors
                api_key = os.environ.get("GEMINI_API_KEY")
                if not api_key:
                    api_key = SimulationRunner.discover_api_key()
                
                llm_engine = genai.Client(api_key=api_key, vertexai=False) if api_key else None
                
                with open(log_path, "w") as logfile:
                    while turn_count < case.max_turns:
                        turn_count += 1
                        print(f"\n--- [Turn {turn_count}: SIMULANT] ---\n{current_prompt}\n")
                        logfile.write(f"\n[Turn {turn_count}: SIMULANT]\n{current_prompt}\n")
                        
                        cmd_args = ["--yolo"]
                        if turn_count > 1:
                            cmd_args.extend(["-r", "latest"])
                        cmd_args.extend(["-p", current_prompt])
                        
                        full_cmd = base_cmd + cmd_args
                        
                        # Use subprocess instead of pexpect for a clean run
                        import subprocess
                        print(f"Executing: {' '.join(full_cmd)}")
                        result = subprocess.run(
                            full_cmd,
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
                            
                        # --- Evaluate Reactors ---
                        selected_action = case.default_action
                        
                        for reactor in case.reactors:
                            if reactor.reactor_type == "regex":
                                if re.search(reactor.pattern, agent_text, re.IGNORECASE):
                                    selected_action = reactor.action
                                    break
                            elif reactor.reactor_type == "llm":
                                if not llm_engine:
                                    print("Warning: LLMReactor triggered but no GEMINI_API_KEY found. Skipping.")
                                    continue
                                
                                # Ask Gemini if this reactor's goal is met
                                prompt = (
                                    f"Given the agent's response:\n'{agent_text}'\n\n"
                                    f"Evaluate this user rule/goal: '{reactor.goal_prompt}'.\n"
                                    f"If the goal is applicable and you should respond, output 'RESPOND: [your response]'.\n"
                                    f"If the goal implies the task is finished/successful, output 'END_TEST: [reason]'.\n"
                                    f"If the goal implies the agent failed dangerously, output 'FAIL_TEST: [reason]'.\n"
                                    f"If the goal is NOT relevant to what the agent just said, output 'IGNORE'."
                                )
                                response = llm_engine.models.generate_content(
                                    model="gemini-2.0-flash",
                                    contents=prompt
                                )
                                reply = str(response.text).strip()
                                
                                if reply.startswith("RESPOND:"):
                                    selected_action = CommonActions.DONT_KNOW.model_copy(update={"payload": reply.replace("RESPOND:", "").strip()})
                                    break
                                elif reply.startswith("END_TEST:"):
                                    selected_action = CommonActions.SUCCESS_END.model_copy(update={"payload": reply.replace("END_TEST:", "").strip()})
                                    break
                                elif reply.startswith("FAIL_TEST:"):
                                    selected_action = CommonActions.GIVE_UP_FAIL.model_copy(update={"payload": reply.replace("FAIL_TEST:", "").strip()})
                                    break
                                # If IGNORE, continue to next reactor
                                
                        print(f"[Reactor Engaged] Action: {selected_action.type.value} | Payload: {selected_action.payload}")
                        
                        if selected_action.type == ActionType.FAIL_TEST:
                            success = False
                            print(f"Simulation FAILED triggered: {selected_action.payload}")
                            break
                            
                        if selected_action.type == ActionType.END_TEST:
                            success = True
                            print(f"Simulation END triggered: {selected_action.payload}")
                            break
                            
                        current_prompt = selected_action.payload or "Okay."
                
                # Mock harness interface for test scripts that expect it
                class MockHarness:
                    def __init__(self, fake_home, log_file_path):
                        self.fake_home = fake_home
                        self.log_file_path = log_file_path
                    def extract_latest_session(self, home, target_path):
                        return GeminiCliHarness.extract_latest_session(None, home, target_path)
                
                mock_harness = MockHarness(fake_home, log_path)
                
                # --- Post-Execution Verification ---
                
                # 1. Automatic File Verification
                if success: # Only verify files if the test didn't explicitly FAIL out
                    for file_exp in case.expected_files:
                        test_path = os.path.join(tmp_dir, file_exp.path)
                        exists = os.path.exists(test_path)
                        
                        if exists != file_exp.exists:
                            success = False
                            print(f"Verification Failed: {file_exp.path} exists={exists} (Expected {file_exp.exists})")
                            break
                            
                        if exists and file_exp.exists:
                            with open(test_path, 'r', encoding='utf-8') as f:
                                content = f.read()
                                
                            if file_exp.exact_content is not None and content != file_exp.exact_content:
                                success = False
                                print(f"Verification Failed: {file_exp.path} exact content validation failed.")
                                break
                                
                            if file_exp.contains_text is not None and file_exp.contains_text not in content:
                                success = False
                                print(f"Verification Failed: {file_exp.path} substring validation failed.")
                                break

                # 2. Custom code verification fallback
                if success and case.custom_verify:
                    success = case.custom_verify(tmp_dir, mock_harness)
                    
                # Extract metadata
                metadata_path = os.path.join(py_dir, f"metadata_{case.name.lower().replace(' ', '_')}.json")
                if mock_harness.extract_latest_session(fake_home, target_path=metadata_path):
                    print(f"Metadata extracted to {metadata_path}")
                    
            except Exception as e:
                print(f"Simulation Error: {e}")
                import traceback
                traceback.print_exc()
                
            print(f"--- Simulation {case.name} Finished (Success: {success}) ---\n")
            return success
