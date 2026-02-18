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

The simulator can interchangeably invoke standard CLI binaries (using the
`InteractiveSimulationCase` abstraction).

- **gemini-cli**: The primary target. Uses experimental
  `GEMINI_APPROVAL_MODE=yolo`.
- **claude-code**: Evaluated side-by-side using Anthropic's node CLI.
- **antigravity**: Internal agentic framework backend.
- **codex**: Experimental backend.

> **Note**: The harness includes automatic retry logic for
> `429 RESOURCE_EXHAUSTED` errors from the Gemini API to verify agent behavior
> robustly even under rate limits.

## Running Tests Local

Execute tests natively utilizing `pytest`:

```bash
cd simulator
python3 -m pytest tests/integration/ --backend=gemini-cli
```

## Running Tests Hermetically (Podman)

You can run the validation suite completely independent of the GitHub repository
context inside Podman. It globally installs the CLI bundles and routes tests
identically to ensure consistent framework metrics.

1. **Authentication:** Create a `.env` file in the `simulator/` directory
   explicitly stipulating test overrides. The host `GEMINI_API_KEY` is bound
   automatically via `~/.gemini/settings.json`, but Claude Code requires you to
   map the Auth key:
   ```env
   ANTHROPIC_API_KEY="sk-ant-..."
   ```
2. **Execution:** Launch the wrapper shell script which will autonomously build
   the `Dockerfile` implementations, run `pytest`, and dump testing artifacts
   organized by a strict `RUN_TIMESTAMP`.
   ```bash
   ./podman_test.sh
   ```

_(Note: The `claude-code` container will additionally mount your
`~/.claude.json` configuration locally if you choose to bypass the `.env` token
and use standard Claude API authentication using a DevContainer mechanism)_

## Test Artifacts & Logs

After a run is completed, outputs are routed into heavily organized timestamp
folders mapping backend performance characteristics side-by-side.

All interaction trails are logged into:

- `outputs/<run_timestamp>/<backend>/<case>/session.log`
- `outputs/<run_timestamp>/<backend>/<case>/metadata.json`

At the climax of the test suite execution, the `podman_test.sh` orchestration
script will evaluate all metrics to compile and export:

- `outputs/<run_timestamp>/final_report.md`
