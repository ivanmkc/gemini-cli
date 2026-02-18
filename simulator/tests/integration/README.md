# Gemini CLI Integration Tests

This directory contains the integration test scenarios for the `gemini-cli`
simulator harness. The tests use a declarative Pydantic configuration
(`InteractiveSimulationCase`) to map out simulated user interactions and assert
the target LLM agent's outputs.

## Test Structure

Each test case is grouped into its own directory representing the core
capability being tested (e.g., `complex_refactor`, `file_write`,
`secret_retrieval`).

Inside a test case directory:

- `test_case.py`: The executable simulation script containing the
  `InteractiveSimulationCase` definition.
- `snippets/` (Optional): A subdirectory containing files that the simulator
  will automatically scaffold into the temporary test workspace to construct the
  starting state scenario (e.g. `calc.py` to be refactored, or `app.js` to be
  analyzed). This maps to the `setup_dir` argument in
  `InteractiveSimulationCase`.

## LLMReactors

Test cases use an `LLMReactor` pipeline. Rather than validating test output
strings with static regular expressions, an instance of Gemini analyzes the CLI
agent's runtime response and checks if it semantically matches the
`goal_prompt`:

```python
LLMReactor(
    goal_prompt="The agent has successfully identified the code smells...",
    action=ReactorAction(type=ActionType.END_TEST, payload="Refactor and explanation complete.")
)
```

## Adding a New Test

1. Create a new directory under `tests/integration/` matching the capability
   name.
2. Structure your initial setup files into
   `tests/integration/<my_test>/snippets/`.
3. Create `test_case.py` implementing `def test_scenario(backend, output_dir):`.
4. Ensure you append the simulation assertion:
   `assert result.success, "Simulation failed"`.
5. The test runner (`podman_test.sh`) utilizes `pytest` to natively discover and
   evaluate all test scenarios.
