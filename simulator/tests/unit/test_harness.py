import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import json
import pytest
from unittest.mock import MagicMock, patch
from simulator import GeminiCliHarness

def test_harness_get_base_cmd():
    harness = GeminiCliHarness(fake_home="/tmp/fake_home", log_file_path="/tmp/log.txt")
    cmd = harness.get_base_cmd("/tmp/py_dir")
    assert cmd[0] == "node"
    assert "index.js" in cmd[1]

def test_extract_latest_session(tmp_path):
    # Setup a mock .gemini/tmp structure using the updated Harness constructor
    harness = GeminiCliHarness(fake_home=str(tmp_path), log_file_path="/tmp/log.txt")
    
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
            result = harness.extract_latest_session(target_path=target)
            
            assert result == target
            with open(target, 'r') as f:
                data = json.load(f)
                assert data["id"] == "new"
