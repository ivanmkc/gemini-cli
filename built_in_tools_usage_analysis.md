# Built-in Tools Usage Analysis & Workflows

This report analyzes the source code of the Gemini CLI built-in tools
(`run_shell_command`, `list_directory`, `read_file`) to explain **when** they
are used (conditions, validation, use cases) and **how** they function (internal
loops, logic flows, and workflows).

## 1. run_shell_command (`ShellTool`)

**Source:** `packages/core/src/tools/shell.ts`

### When to Use (Conditions & Use Cases)

- **Primary Use Case:** Executing arbitrary shell commands to interact with the
  OS, filesystem, or external tools (e.g., git, npm, grep).
- **Validation Conditions:**
  - **Empty Command:** Fails if the `command` parameter is empty or whitespace
    only.
  - **Allowed Commands:** Checks against a security policy (`isCommandAllowed`).
    If a command is blocked or restricted, execution is denied.
  - **Root Command Identification:** Must be able to identify the root command
    (e.g., "npm" in "npm install") to check permissions.
  - **Workspace Restrictions:** If a `dir_path` is provided, it _must_ resolve
    to a path within the registered workspace directories.
- **Interaction Mode Restrictions:**
  - In **Non-Interactive Mode** (unless in "YOLO" mode): The tool throws an
    error if the command is not explicitly allowlisted. It prevents the tool
    from hanging while waiting for user confirmation that cannot be given.

### How it Works (Workflows & Logic)

1.  **Confirmation Workflow:**
    - Before execution, it identifies "root commands".
    - If a command is not in the `allowlist` (session-based) and not globally
      allowed, it triggers a confirmation request via the `MessageBus`.
    - **User Outcomes:**
      - _Proceed:_ Runs once.
      - _ProceedAlways:_ Adds command to the session `allowlist` so future calls
        don't prompt.
      - _Cancel:_ Aborts execution.

2.  **Execution Logic (`execute` method):**
    - **OS Abstraction:**
      - **Windows:** Executes directly or via PowerShell wrappers. Note: `pgrep`
        is not available, so background PID tracking is limited.
      - **Unix/Linux:** Wraps the command to capture the exit code and uses
        `pgrep` to identify background processes spawned by the command.
    - **Timeout Management:**
      - Starts a strict timer (`getShellToolInactivityTimeout`).
      - **Logic:** The timer is _reset_ every time new output (`data` event) is
        received. If no output is received for the duration of the timeout, the
        process is killed.
    - **Output Streaming:**
      - Uses `ShellExecutionService` to spawn the process.
      - Streams output chunks to the UI in real-time.
      - **Binary Protection:** Detects if output is binary (non-text). If
        detected, it halts the stream to prevent terminal corruption and
        displays a memory usage summary instead.
    - **Summarization (Optional):**
      - If configured, the raw output is passed to a generic
        `summarizeToolOutput` utility (using an LLM model `summarizer-shell`)
        before being returned to the main agent loop. This is useful for massive
        outputs.

3.  **Return Data:**
    - Returns structured text including: `Command`, `Directory`, `Output`
      (Stdout/Stderr combined), `Error` (if any), `Exit Code`, and
      `Background PIDs`.

---

## 2. list_directory (`LSTool`)

**Source:** `packages/core/src/tools/ls.ts`

### When to Use (Conditions & Use Cases)

- **Primary Use Case:** Discovering the file structure of a project. Essential
  for the agent to "see" what files exist before deciding what to read.
- **Validation Conditions:**
  - **Workspace Confinement:** The `dir_path` _must_ be within the workspace.
    The tool strictly enforces this to prevent exploring the user's entire
    filesystem (e.g., `/` or `C:\`).
  - **Existence Check:** Fails if the directory does not exist or is
    inaccessible.
  - **Type Check:** Fails if the path exists but is not a directory (e.g., it's
    a file).

### How it Works (Workflows & Logic)

1.  **File Discovery Loop:**
    - Reads the directory contents using `fs.readdir`.
    - **Empty Check:** Immediately returns "Directory is empty" if no files are
      found.

2.  **Filtering Workflow:**
    - **Step 1: System/Git Ignore:** Passes the raw list to a file service that
      checks against `.gitignore` and `.geminiignore` files. This is crucial for
      performance and noise reduction (hiding `node_modules`, build artifacts,
      etc.).
      - _Control:_ Can be toggled via `file_filtering_options`.
    - **Step 2: Runtime Ignore:** Iterates through the filtered list and checks
      against the `ignore` parameter provided in the tool call (glob patterns).
    - **Reporting:** Keeps a count of how many files were ignored to inform the
      LLM (e.g., "(42 ignored)").

3.  **Metadata Collection:**
    - For every surviving file, it calls `fs.stat` to get:
      - `isDirectory` (boolean)
      - `size` (bytes)
      - `modifiedTime`
    - _Error Handling:_ If `stat` fails for a specific file (e.g., permission
      issue), it logs the debug error but _continues_ processing other files
      (non-blocking failure).

4.  **Sorting & Formatting:**
    - **Sort Logic:** Directories are listed _first_, followed by files. Within
      those groups, items are sorted alphabetically.
    - **Output Format:** Returns a simple list of names, marking directories
      with `[DIR]`.
    - _Example:_
      ```text
      [DIR] src
      [DIR] tests
      package.json
      README.md
      ```

---

## 3. read_file (`ReadFileTool`)

**Source:** `packages/core/src/tools/read-file.ts`

### When to Use (Conditions & Use Cases)

- **Primary Use Case:** Reading the actual content of a file to understand code,
  configuration, or text data.
- **Validation Conditions:**
  - **Path Resolution:** Resolves paths relative to the project root.
  - **Supported Types:** Handles Text, Images (base64 encoded for LLM), PDFs,
    and Audio.
  - **Safety:** Implicitly relies on `processSingleFileContent` which typically
    enforces workspace boundaries (though explicit checks are lighter here
    compared to `ls`, trusting the path resolution).

### How it Works (Workflows & Logic)

1.  **Content Processing (`processSingleFileContent`):**
    - Determines file type (MIME detection).
    - **Binary/Media:** Reads file and formats it appropriately (e.g.,
      converting images/audio to the specific `PartUnion` format required by the
      Gemini API).
    - **Text:** Reads file as UTF-8.

2.  **Pagination/Truncation Workflow:**
    - **Inputs:** Accepts `offset` (start line) and `limit` (max lines).
    - **Logic:**
      - If the file is small, it returns the whole content.
      - If `limit` is set or defaults apply, it slices the content.
      - **Truncation Detection:** If the file has more lines than
        requested/allowed, it _modifies the output_ to include a specific
        "IMPORTANT" header.
    - **Interactive Header:**
      - Injects a status message: `Status: Showing lines X-Y of Z total lines.`
      - Injects an Action prompt: Instructs the LLM on how to call the tool
        again with the correct `offset` to read the next chunk.
      - _Goal:_ This creates a "loop" where the LLM can paginate through massive
        files without crashing the context window.

3.  **Telemetry:**
    - Logs the file operation, including file extension, MIME type, and detected
      programming language, to the telemetry system for usage tracking.
