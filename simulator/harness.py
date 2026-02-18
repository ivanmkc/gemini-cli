from abc import ABC, abstractmethod
import os
import json
import glob

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

class ClaudeCodeHarness(BaseSimulatorHarness):
    def get_base_cmd(self, py_dir: str) -> list[str]:
        base_cmd = ["npx", "-y", "@anthropic-ai/claude-code", "--dangerously-skip-permissions"]
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
