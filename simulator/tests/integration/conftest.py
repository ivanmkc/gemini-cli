import pytest
import os

def pytest_addoption(parser):
    parser.addoption(
        "--backend", action="store", default="gemini-cli", help="Simulator backend to execute: e.g. gemini-cli, claude-code"
    )
    parser.addoption(
        "--output-dir", action="store", default=None, help="Root directory for storing test artifacts."
    )

@pytest.fixture
def backend(request):
    return request.config.getoption("--backend")

@pytest.fixture
def output_dir(request):
    return request.config.getoption("--output-dir")
