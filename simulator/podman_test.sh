#!/bin/bash
set -e

cd "$(dirname "$0")"

# Load local .env file if it exists to allow overriding keys like ANTHROPIC_API_KEY
if [ -f ".env" ]; then
    export $(cat .env | xargs)
fi

# Dynamically extract API keys from local settings if not already exported
if [ -z "$GEMINI_API_KEY" ]; then
    export GEMINI_API_KEY=$(python3 -c "import json, os; settings_path = os.path.expanduser('~/.gemini/settings.json'); print(next((server.get('env', {}).get('GEMINI_API_KEY') for server in json.load(open(settings_path)).get('mcpServers', {}).values() if server.get('env', {}).get('GEMINI_API_KEY')), '') if os.path.exists(settings_path) else '')" 2>/dev/null || echo "")
fi
if [ -z "$ANTHROPIC_API_KEY" ]; then
    export ANTHROPIC_API_KEY=$(python3 -c "import json, os; print(json.load(open(os.path.expanduser('~/.gemini/settings.json'))).get('apiKeys', {}).get('anthropic', '') if os.path.exists(os.path.expanduser('~/.gemini/settings.json')) else '')" 2>/dev/null || echo "")
fi

echo "=== Building Gemini Test Image ==="
podman build -t simulator-test-gemini -f Dockerfile.gemini .

echo "=== Building Claude Test Image ==="
podman build -t simulator-test-claude -f Dockerfile.claude .

echo "=== Running Simulation Tests in Podman: Gemini CLI ==="
podman run --rm \
    -v $(pwd)/..:/workspace \
    -w /workspace/simulator \
    -e GEMINI_API_KEY="${GEMINI_API_KEY}" \
    -e ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
    -e GOOGLE_GENAI_USE_VERTEXAI="${GOOGLE_GENAI_USE_VERTEXAI}" \
    -e GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT}" \
    -e GOOGLE_CLOUD_LOCATION="${GOOGLE_CLOUD_LOCATION}" \
    simulator-test-gemini \
    bash -c "\
        python3 -m venv venv-linux && \
        ./venv-linux/bin/pip install pydantic google-genai pytest pexpect --index-url=https://pypi.org/simple && \
        echo \"=== Running Tests: Gemini CLI ===\" && \
        ./venv-linux/bin/pytest tests/integration/ --backend=gemini-cli"

echo "=== Running Simulation Tests in Podman: Claude Code ==="
podman run --rm \
    -v $(pwd)/..:/workspace \
    -w /workspace/simulator \
    -e GEMINI_API_KEY="${GEMINI_API_KEY}" \
    -e ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
    -e GOOGLE_GENAI_USE_VERTEXAI="${GOOGLE_GENAI_USE_VERTEXAI}" \
    -e GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT}" \
    -e GOOGLE_CLOUD_LOCATION="${GOOGLE_CLOUD_LOCATION}" \
    simulator-test-claude \
    bash -c "\
        python3 -m venv venv-linux && \
        ./venv-linux/bin/pip install pydantic google-genai pytest pexpect --index-url=https://pypi.org/simple && \
        echo \"=== Running Tests: Claude Code ===\" && \
        ./venv-linux/bin/pytest tests/integration/ --backend=claude-code"
