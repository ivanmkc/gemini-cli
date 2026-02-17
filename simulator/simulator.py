import pexpect
import os
import json
import glob
import time
import re
import tempfile
from google import genai

class LLMUserSimulant:
    def __init__(self, persona_script: str, model: str = "gemini-2.0-flash") -> None:
        self.persona_script: str = persona_script
        self.model: str = model
        api_key: str | None = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            api_key = SimulationRunner.discover_api_key()
        self.client: genai.Client = genai.Client(api_key=api_key, vertexai=False)
        self.history: list[dict[str, str]] = []

    def generate_reply(self, agent_output: str) -> str:
        prompt: str = (
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
                model=self.model,
                contents=prompt
            )
            reply: str = str(response.text).strip()
            self.history.append({"agent": agent_output, "user": reply})
            return reply
        except Exception as e:
            print(f"DEBUG: Simulant failed to generate text (blocked or empty): {e}")
            return "TEST_COMPLETE"

from abc import ABC, abstractmethod

class BaseSimulatorHarness(ABC):
    def __init__(self, fake_home: str, log_file_path: str):
        self.fake_home = fake_home
        self.log_file_path = log_file_path
        
    @abstractmethod
    def get_base_cmd(self, py_dir: str) -> list[str]:
        pass

    @abstractmethod
    def get_turn_args(self, turn_count: int, prompt: str) -> list[str]:
        pass

    @abstractmethod
    def extract_latest_session(self, target_path: str) -> str | None:
        pass

class GeminiCliHarness(BaseSimulatorHarness):
    def get_base_cmd(self, py_dir: str) -> list[str]:
        cli_command = os.environ.get("GEMINI_CLI_COMMAND")
        if cli_command:
            print(f"Using global CLI command from environment: {cli_command}")
            return [cli_command]
        cli_root = os.path.abspath(os.path.join(py_dir, ".."))
        cli_entry = os.path.join(cli_root, "packages", "cli", "dist", "index.js")
        return ["node", cli_entry]

    def get_turn_args(self, turn_count: int, prompt: str) -> list[str]:
        cmd_args = ["--yolo"]
        if turn_count > 1:
            cmd_args.extend(["-r", "latest"])
        cmd_args.extend(["-p", prompt])
        return cmd_args

    def extract_latest_session(self, target_path: str) -> str | None:
        if self.fake_home:
            base_tmp_dir = os.path.join(self.fake_home, ".gemini", "tmp")
        else:
            base_tmp_dir = os.path.expanduser("~/.gemini/tmp")
            
        if not os.path.exists(base_tmp_dir):
            return None
            
        import glob
        session_files = glob.glob(os.path.join(base_tmp_dir, "**/chats/session-*.json"), recursive=True)
        if not session_files:
            return None
            
        latest_file = max(session_files, key=os.path.getmtime)
        try:
            import json
            with open(latest_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            with open(target_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            return target_path
        except Exception as e:
            print(f"DEBUG: Failed to extract session: {e}")
            return None

class ClaudeCodeHarness(BaseSimulatorHarness):
    def get_base_cmd(self, py_dir: str) -> list[str]:
        base_cmd = ["npx", "-y", "@anthropic-ai/claude-code"]
        print(f"Using Claude Code backend: {base_cmd}")
        return base_cmd

    def get_turn_args(self, turn_count: int, prompt: str) -> list[str]:
        return ["-p", prompt]

    def extract_latest_session(self, target_path: str) -> str | None:
        # Claude code might not export sessions exactly the same way, stubbing it.
        return None

class AntigravityHarness(BaseSimulatorHarness):
    def get_base_cmd(self, py_dir: str) -> list[str]:
        base_cmd = ["antigravity"]
        print(f"Using Antigravity backend: {base_cmd}")
        return base_cmd

    def get_turn_args(self, turn_count: int, prompt: str) -> list[str]:
        # Assuming '-p' for passing a prompt, matching other standard CLIs
        return ["-p", prompt]

    def extract_latest_session(self, target_path: str) -> str | None:
        return None

class CodexHarness(BaseSimulatorHarness):
    def get_base_cmd(self, py_dir: str) -> list[str]:
        base_cmd = ["codex"]
        print(f"Using Codex backend: {base_cmd}")
        return base_cmd

    def get_turn_args(self, turn_count: int, prompt: str) -> list[str]:
        # Assuming '-p' for passing a prompt, matching other standard CLIs
        return ["-p", prompt]

    def extract_latest_session(self, target_path: str) -> str | None:
        return None

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
    def run(case, backend="gemini-cli", output_dir=None):
        """
        Standard orchestrator for a simulated user run using an InteractiveSimulationCase.
        """
        # Ensure we can import the models internally
        try:
            from models import InteractiveSimulationCase, ActionType, CommonActions
        except ImportError:
            from simulator.models import InteractiveSimulationCase, ActionType, CommonActions
            
        py_dir = os.path.dirname(os.path.abspath(__file__))
        
        base_out = output_dir or os.path.join(py_dir, "outputs")
        run_out_dir = os.path.join(base_out, backend)
        os.makedirs(run_out_dir, exist_ok=True)
            
        api_key = SimulationRunner.discover_api_key()
            
        with tempfile.TemporaryDirectory() as tmp_dir:
            print(f"--- Starting Simulation: {case.name} ---")
            print(f"Sandbox: {tmp_dir}")
            
            extracted_output = None
            
            # Auto-dump setup files from directory
            if getattr(case, 'setup_dir', None) and os.path.exists(case.setup_dir):
                import shutil
                for root, dirs, files in os.walk(case.setup_dir):
                    for file in files:
                        src_path = os.path.join(root, file)
                        rel_path = os.path.relpath(src_path, case.setup_dir)
                        # Skip special directories or self-references if needed
                        if rel_path.startswith(".") or "__pycache__" in rel_path:
                            continue
                        dest_path = os.path.join(tmp_dir, rel_path)
                        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                        shutil.copy2(src_path, dest_path)
                print(f"Setup: Seeded workspace from {case.setup_dir}")

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
            
            settings_data = {}
            if os.path.exists(settings_file):
                try:
                    with open(settings_file, "r") as f:
                        settings_data = json.load(f)
                except Exception:
                    pass
            
            if "security" not in settings_data:
                settings_data["security"] = {}
            if "auth" not in settings_data["security"]:
                settings_data["security"]["auth"] = {}
                
            settings_data["security"]["auth"]["selectedType"] = "gemini-api-key"
            
            with open(settings_file, "w") as f:
                json.dump(settings_data, f)
            
            case_slug = case.name.lower().replace(' ', '_')
            case_out_dir = os.path.join(run_out_dir, case_slug)
            os.makedirs(case_out_dir, exist_ok=True)
            
            log_path = os.path.join(case_out_dir, "session.log")
            
            if backend == "claude-code":
                harness = ClaudeCodeHarness(fake_home, log_path)
            elif backend == "antigravity":
                harness = AntigravityHarness(fake_home, log_path)
            elif backend == "codex":
                harness = CodexHarness(fake_home, log_path)
            else:
                harness = GeminiCliHarness(fake_home, log_path)
                
            base_cmd = harness.get_base_cmd(py_dir)
            
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
                
                # Automatically append output schema instructions if requested
                if case.output_schema is not None:
                    schema_json = json.dumps(case.output_schema.model_json_schema(), indent=2)
                    schema_instruction = (
                        f"\n\nCRITICAL OUTPUT REQUIREMENT:\n"
                        f"When you have finished your task, you MUST write your final response "
                        f"to a file named 'output.json' in the current directory.\n"
                        f"The content of 'output.json' MUST strictly conform to this JSON schema:\n"
                        f"{schema_json}\n"
                    )
                    current_prompt += schema_instruction
                
                # Setup LLM Simulant specifically for LLMReactors
                api_key = os.environ.get("GEMINI_API_KEY")
                if not api_key:
                    api_key = SimulationRunner.discover_api_key()
                
                use_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI") == "1"
                
                if use_vertex:
                    llm_engine = genai.Client(vertexai=True, project=os.environ.get("GOOGLE_CLOUD_PROJECT"), location=os.environ.get("GOOGLE_CLOUD_LOCATION"))
                elif api_key:
                    llm_engine = genai.Client(api_key=api_key, vertexai=False)
                else:
                    llm_engine = None
                
                with open(log_path, "w") as logfile:
                    while turn_count < case.max_turns:
                        turn_count += 1
                        print(f"\n--- [Turn {turn_count}: SIMULANT] ---\n{current_prompt}\n")
                        logfile.write(f"\n[Turn {turn_count}: SIMULANT]\n{current_prompt}\n")
                        
                        cmd_args = harness.get_turn_args(turn_count, current_prompt)
                        
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
                        
                        logfile.write(f"\n[EVALUATING REACTORS]\n")
                        logfile.write(f"Default Action: {selected_action.type.value} | Payload: {selected_action.payload}\n")
                        
                        for reactor in case.reactors:
                            logfile.write(f"- Checking Reactor: type={reactor.reactor_type}\n")
                            if reactor.reactor_type == "regex":
                                logfile.write(f"  Regex Pattern: '{reactor.pattern}'\n")
                                if re.search(reactor.pattern, agent_text, re.IGNORECASE):
                                    selected_action = reactor.action
                                    logfile.write(f"  -> MATCHED! Selected Action: {selected_action.type.value} | Payload: {selected_action.payload}\n")
                                    break
                                else:
                                    logfile.write(f"  -> No match.\n")
                            elif reactor.reactor_type == "llm":
                                logfile.write(f"  Goal Prompt: '{reactor.goal_prompt}'\n")
                                if not llm_engine:
                                    msg = "Warning: LLMReactor triggered but no GEMINI_API_KEY found. Skipping."
                                    print(msg)
                                    logfile.write(f"  -> {msg}\n")
                                    continue
                                
                                # Ask Gemini if this reactor's goal is met
                                prompt = (
                                    f"History:\n{logfile_content[-2000:] if 'logfile_content' in locals() else 'No history.'}\n\n"
                                    f"Agent's latest response:\n'{agent_text}'\n\n"
                                    f"Current User Goal: '{reactor.goal_prompt}'\n\n"
                                    "Is the User Goal met or specifically addressed by the Agent's latest response?\n"
                                    "If YES, should the user take the action associated with this goal? (e.g. they answered the question or achieved the milestone)\n"
                                    "If YES, output 'MATCH: [optional brief reasoning]'.\n"
                                    "If the agent is asking a clarifying question that prevents this goal from being met, but you want to respond specifically, output 'RESPOND: [your response]'.\n"
                                    "Otherwise, output 'IGNORE'."
                                )
                                # Read back the log to give context if needed (simplified here)
                                response = llm_engine.models.generate_content(
                                    model="gemini-2.0-flash",
                                    contents=prompt
                                )
                                reply = str(response.text).strip()
                                logfile.write(f"  -> LLM Evaluator Response: '{reply}'\n")
                                
                                if reply.startswith("MATCH:"):
                                    selected_action = reactor.action
                                    logfile.write(f"  -> MATCHED! Selected Action: {selected_action.type.value} | Payload: {selected_action.payload}\n")
                                    break
                                elif reply.startswith("RESPOND:"):
                                    # Override action with dynamic response if LLM specifically suggests one
                                    extracted_payload = reply.replace("RESPOND:", "").strip()
                                    selected_action = ReactorAction(
                                        type=ActionType.RESPOND, 
                                        payload=extracted_payload
                                    )
                                    logfile.write(f"  -> DYNAMIC RESPONSE! Selected Action: RESPOND | Payload: {extracted_payload}\n")
                                    break
                                else:
                                    logfile.write(f"  -> No match (IGNORED).\n")
                                
                        msg = f"[Reactor Engaged] Action: {selected_action.type.value} | Payload: {selected_action.payload}"
                        print(msg)
                        logfile.write(f"\n{msg}\n")
                        
                        if selected_action.type == ActionType.FAIL_TEST:
                            success = False
                            msg_fail = f"Simulation FAILED triggered: {selected_action.payload}"
                            print(msg_fail)
                            logfile.write(f"{msg_fail}\n")
                            break
                            
                        if selected_action.type == ActionType.END_TEST:
                            success = True
                            msg_end = f"Simulation END triggered: {selected_action.payload}"
                            print(msg_end)
                            logfile.write(f"{msg_end}\n")
                            break
                            
                        current_prompt = selected_action.payload or "Okay."
                

                
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
                    success = case.custom_verify(tmp_dir, harness)
                    
                # Extract metadata
                metadata_path = os.path.join(case_out_dir, "metadata.json")
                if harness.extract_latest_session(target_path=metadata_path):
                    print(f"Metadata extracted to {metadata_path}")
                    
                # Extract structured output if requested
                output_json_path = os.path.join(tmp_dir, "output.json")
                if success and case.output_schema is not None:
                    if os.path.exists(output_json_path):
                        try:
                            saved_json_path = os.path.join(case_out_dir, "output.json")
                            import shutil
                            shutil.copy2(output_json_path, saved_json_path)
                            with open(saved_json_path, 'r', encoding='utf-8') as f:
                                json_data = json.load(f)
                            extracted_output = case.output_schema(**json_data)
                            print(f"Successfully extracted and typed output.json into {case.output_schema.__name__}")
                        except Exception as e:
                            success = False
                            print(f"Failed to parse output.json against {case.output_schema.__name__} schema: {e}")
                    else:
                        success = False
                        print(f"Failed: Agent did not produce the required output.json file.")
                    
            except Exception as e:
                print(f"Simulation Error: {e}")
                import traceback
                traceback.print_exc()
                
            print(f"--- Simulation {case.name} Finished (Success: {success}) ---\n")
            
            # Formulate the final result object
            from models import SimulationResult, SimulationTranscript
            transcript = SimulationTranscript(
                case_name=case.name,
                backend=backend,
                turns=[] # Stubbed for brevity, would populate from history
            )
            
            return SimulationResult(
                case_name=case.name,
                backend=backend,
                success=success,
                transcript=transcript,
                extracted_output=extracted_output
            )
