# Gemini CLI Python Simulator

This directory contains a standalone, headless Python simulation harness
designed to test the `gemini-cli` Node.js package. This ensures the CLI tool
registry, telemetry logging, and core decision logic work natively without being
obstructed by interactive TTY (Ink UI) racing conditions.

## Architecture

The harness utilizes the native `-p/--prompt` (Headless) and `-r/--resume` flags
to simulate multi-turn interactions with the user simulator LLM
(`LLMUserSimulant`). This operates without requiring any special debug hooks in
the `packages/cli` codebase, allowing robust integration testing on the
production bundle.

## Subdirectories

- `simulator.py`: the main test orchestrator (`SimulationRunner`).
- `tests/unit/`: Contains infrastructure unit tests (e.g., `test_harness.py`).
- `tests/integration/`: Contains automated multi-turn workflow scripts like:
  - `test_tools.py`
  - `test_secret_retrieval.py`
  - `test_skills.py`
  - `test_mcp.py`
  - `test_file_write.py`

## Running Tests

Execute tests natively utilizing `uv`:

```bash
# Run Unit Tests
uv run pytest tests/unit

# Run Integration tests
uv run tests/integration/test_tools.py
uv run tests/integration/test_secret_retrieval.py
```

All interactions will be logged as human-readable transcripts to
`session_*.log`, and all precise backend LLM outputs (thoughts, arrays,
parameters) are saved to `metadata_*.json`.

## Standalone Container Environment

You can configure and run the validation suite completely independent of the
GitHub repository context by utilizing the bundled Dockerfile. It provisions the
environment, globally installs `@google/gemini-cli` from NPM, configures Python,
and runs the entire suite autonomously:

```bash
cd simulator
podman build -t gemini-simulator .
podman run --rm -e GEMINI_API_KEY="YOUR_KEY_HERE" gemini-simulator
```
