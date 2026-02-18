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

if [ -z "$GEMINI_API_KEY" ]; then
    echo "Error: GEMINI_API_KEY is missing. Please set it in .env or ~/.gemini/settings.json"
    exit 1
fi



# Generate timestamp for output consolidation
RUN_TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
export RUN_TIMESTAMP
echo "Test Run Timestamp: ${RUN_TIMESTAMP}"

RUN_OUT_DIR="outputs/${RUN_TIMESTAMP}"
mkdir -p "${RUN_OUT_DIR}"
chmod 777 "${RUN_OUT_DIR}"

# Bootstrap Anthropic DevContainer Auth
if [ ! -f "$HOME/.claude.json" ]; then
    echo "=== Anthropic Credentials Not Found ==="
    echo "To test the claude-code backend hermetically, you must authenticate once."
    echo "Launching an interactive one-time setup container..."
    
    # Run a tiny ephemeral node container explicitly to capture the login callback
    podman run -it --rm \
        -v "$HOME":/root \
        node:20-slim \
        bash -c "npm install -g @anthropic-ai/claude-code && claude login" || true
        
    echo "Login capture complete."
fi

CLAUDE_MOUNT=""
if [ -f "$HOME/.claude.json" ]; then
    cp "$HOME/.claude.json" "${RUN_OUT_DIR}/.claude.json"
    chmod 666 "${RUN_OUT_DIR}/.claude.json"
    CLAUDE_MOUNT="-v $(pwd)/${RUN_OUT_DIR}/.claude.json:/root/.claude.json"
fi

echo "=== Building Gemini Test Image ==="
podman build -t simulator-test-gemini -f Dockerfile.gemini .

echo "=== Building Claude Test Image ==="
podman build -t simulator-test-claude -f Dockerfile.claude .

# Pre-create debug.log with write permissions so the non-root container can write to it
touch debug.log
chmod 666 debug.log

echo "=== Running Simulation Tests in Podman: Gemini CLI ==="
podman run --rm \
    -v $(pwd)/..:/workspace \
    -w /workspace/simulator \
    -e GEMINI_API_KEY="${GEMINI_API_KEY}" \
    -e ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
    -e GOOGLE_GENAI_USE_VERTEXAI="${GOOGLE_GENAI_USE_VERTEXAI}" \
    -e GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT}" \
    -e GOOGLE_CLOUD_LOCATION="${GOOGLE_CLOUD_LOCATION}" \
    -e PYTHONDONTWRITEBYTECODE=1 \
    simulator-test-gemini \
    bash -c "\
        python3 -m venv venv-linux && \
        ./venv-linux/bin/pip install pydantic google-genai pytest pexpect --index-url=https://pypi.org/simple && \
        echo \"=== Running Tests: Gemini CLI ===\" && \
        ./venv-linux/bin/pytest tests/integration/ -o cache_dir=/tmp/.pytest_cache --backend=gemini-cli --output-dir=/workspace/simulator/outputs/${RUN_TIMESTAMP}" || true

echo "=== Running Simulation Tests in Podman: Claude Code ==="
podman run --rm \
    -v $(pwd)/..:/workspace \
    $CLAUDE_MOUNT \
    -w /workspace/simulator \
    -e GEMINI_API_KEY="${GEMINI_API_KEY}" \
    -e ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
    -e GOOGLE_GENAI_USE_VERTEXAI="${GOOGLE_GENAI_USE_VERTEXAI}" \
    -e GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT}" \
    -e GOOGLE_CLOUD_LOCATION="${GOOGLE_CLOUD_LOCATION}" \
    -e PYTHONDONTWRITEBYTECODE=1 \
    simulator-test-claude \
    bash -c "\
        python3 -m venv /tmp/venv-linux && \
        /tmp/venv-linux/bin/pip install pydantic google-genai pytest pexpect --index-url=https://pypi.org/simple && \
        echo \"=== Running Tests: Claude Code ===\" && \
        /tmp/venv-linux/bin/pytest tests/integration/ -o cache_dir=/tmp/.pytest_cache --backend=claude-code --output-dir=/workspace/simulator/outputs/${RUN_TIMESTAMP}" || true

echo "=== Generating Final Summary Report ==="
python3 -c "
import os, json, glob
res_dir = 'outputs/${RUN_TIMESTAMP}'
report = [f'# Simulation Run Report: {res_dir}']
if os.path.exists(res_dir):
    for backend in os.listdir(res_dir):
        back_dir = os.path.join(res_dir, backend)
        if os.path.isdir(back_dir):
            report.append(f'\n## Backend: {backend}')
            for test_case in os.listdir(back_dir):
                meta_path = os.path.join(back_dir, test_case, 'metadata.json')
                if os.path.exists(meta_path):
                    with open(meta_path, 'r') as f:
                        data = json.load(f)
                    stat = '✅ PASS' if data.get('success', False) else '❌ FAIL'
                    report.append(f'- **{test_case}**: {stat}')
    with open(os.path.join(res_dir, 'final_report.md'), 'w') as f:
        f.write('\n'.join(report))
    print(f'Report written to {res_dir}/final_report.md')
"
