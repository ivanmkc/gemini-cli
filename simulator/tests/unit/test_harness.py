import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import hashlib
import json
import pytest
from unittest.mock import MagicMock, patch
from simulator import GeminiCliHarness

def test_harness_environment_setup():
    with patch('pexpect.spawn') as mock_spawn:
        harness = GeminiCliHarness(command="node", args=["index.js"], cwd="/tmp", log_file_path="/tmp/log.txt")
        
        # Verify pexpect was called
        mock_spawn.assert_called_once()
        
        # Capture the env passed to spawn
        args, kwargs = mock_spawn.call_args
        env = kwargs.get('env')
        
        assert env["GEMINI_DEBUG_LOG_FILE"].endswith("debug.log")
        assert env["NO_COLOR"] == "true"

def test_extract_latest_session(tmp_path):
    # Setup a mock .gemini/tmp structure
    harness = GeminiCliHarness.__new__(GeminiCliHarness)
    
    chats_dir = tmp_path / ".gemini" / "tmp" / "mock_hash" / "chats"
    chats_dir.mkdir(parents=True)
    
    # Create mock session files
    file1 = chats_dir / "session-2026-02-14T00-00-00.json"
    file2 = chats_dir / "session-2026-02-14T01-00-00.json"
    
    file1.write_text(json.dumps({"id": "old"}))
    file2.write_text(json.dumps({"id": "new"}))
    
    # Set modification times
    os.utime(file1, (0, 0))
    os.utime(file2, (100, 100))
    
    with patch('glob.glob', return_value=[str(file1), str(file2)]):
        with patch('os.path.exists', return_value=True):
            target = str(tmp_path / "extracted.json")
            result = harness.extract_latest_session(fake_home=str(tmp_path), target_path=target)
            
            assert result == target
            with open(target, 'r') as f:
                data = json.load(f)
                assert data["id"] == "new"
