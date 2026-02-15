# Gemini CLI Tool Architecture & Workflows

This report details how `gemini-cli` orchestrates its tools, the hierarchy of
its agents, and the workflows that govern their execution. The system is not
merely a flat list of tools; it uses a sophisticated **Agent-Subagent
architecture** with specific execution loops and prompt-driven workflows.

## 1. Core Architecture: The `LocalAgentExecutor`

At the heart of the system is the `LocalAgentExecutor`
(`packages/core/src/agents/local-executor.ts`). This class is responsible for
running an agent's "life cycle."

### The Execution Loop

Tools are not called in a hardcoded sequence. Instead, they are made available
to the LLM within a **ReAct-style loop**:

1.  **Observation:** The agent receives the current conversation history and
    tool results.
2.  **Thought:** The LLM reasons about the state (often emitting "thought
    chunks").
3.  **Action:** The LLM selects one or more tools to call.
4.  **Execution:** The `LocalAgentExecutor` intercepts these calls, executes
    them (checking permissions), and feeds the output back into the loop.

### Deterministic Constraints

While the _choice_ of tools is probabilistic (LLM-driven), the _structure_ of
the execution is deterministic:

- **`complete_task` Mandate:** Every agent MUST call the special `complete_task`
  tool to finish. Stopping without calling this triggers an error
  (`ERROR_NO_COMPLETE_TASK_CALL`) and forces a recovery attempt.
- **Grace Period:** If an agent times out or fails protocol, the executor
  triggers a "Final Warning Turn" (Grace Period), allowing the agent one last
  chance to save its work using `complete_task`.
- **Permission Checks:** Before any tool runs, `executeToolCall` verifies if the
  user needs to approve the action (unless in `YOLO` mode).

---

## 2. Tool Availability & Hierarchy

Tools are managed via a `ToolRegistry`. Usage is not flat; it is hierarchical
based on the active **Agent Definition**.

### Level 1: The General Agent (Main Loop)

- **Role:** The general contractor.
- **Tool Access:** Broad access to `ShellTool`, `WriteFile`, `ReadFile`, etc.
- **Workflow:** Open-ended. It decides its own plan based on the user's initial
  request.

### Level 2: Specialized Sub-Agents (e.g., `CodebaseInvestigator`)

The system defines specialized agents (like `CodebaseInvestigatorAgent` in
`packages/core/src/agents/codebase-investigator.ts`) that act as "tools" for the
main agent.

- **Role:** Specialized subcontractor (e.g., "Analyze the code structure").
- **Restricted Toolset:** Explicitly limited in `toolConfig`. For example, the
  Investigator has **Read-Only** access (`LS`, `READ_FILE`, `GLOB`, `GREP`) and
  _cannot_ execute shell commands or write files.
- **Structured Output:** Must return data strictly adhering to a JSON schema
  (e.g., `CodebaseInvestigationReportSchema`).

---

## 3. Workflows: Prompt-Driven vs. Code-Driven

The "workflow" is a hybrid of hardcoded logic and prompt engineering.

### Prompt-Driven Workflows (Soft Logic)

Defined in the `systemPrompt` of specific agents.

- **Example (`CodebaseInvestigator`):**
  - **Scratchpad Rule:** "On your very first turn, you MUST create the
    `<scratchpad>` section."
  - **Checklist:** "Analyze the task and create an initial Checklist."
  - **Loop:** "Update the scratchpad after every `<OBSERVATION>`."
  - These instructions force the LLM into a specific behavioral loop (Plan ->
    Explore -> Update -> Report) without hardcoding it in TypeScript.

### Code-Driven Workflows (Hard Logic)

Defined in `LocalAgentExecutor` and `nonInteractiveToolExecutor`.

- **Non-Interactive Enforcement:** If the CLI is in non-interactive mode, tool
  calls requiring user input are strictly blocked (throwing errors) to prevent
  hanging.
- **Output Validation:** When `complete_task` is called, the executor validates
  the arguments against the agent's output schema (Zod). If validation fails,
  the task is **not** marked complete, and the error is fed back to the agent to
  fix.

## Summary

The `gemini-cli` uses tools as a dynamic set available to an agent, but wraps
them in a rigid **Executor** that enforces:

1.  **Life-cycle rules** (Start -> Loop -> `complete_task`).
2.  **Safety boundaries** (Permission checks, Read-only modes for sub-agents).
3.  **Hierarchical delegation** (Main Agent -> Sub-Agent -> Tools).
