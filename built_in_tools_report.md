# Built-in Tools Report

This report contains the full source code for the built-in tools in the Gemini
CLI project, along with their associated unit and integration tests.

## 1. run_shell_command (`ShellTool`)

**File:** `packages/core/src/tools/shell.ts`

**Tests:**

- **Unit:** `packages/core/src/tools/shell.test.ts`
- **Integration:** `integration-tests/run_shell_command.test.ts`

````typescript
/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import fs from 'node:fs';
import path from 'node:path';
import os, { EOL } from 'node:os';
import crypto from 'node:crypto';
import type { Config } from '../config/config.js';
import { debugLogger, type AnyToolInvocation } from '../index.js';
import { ToolErrorType } from './tool-error.js';
import type {
  ToolInvocation,
  ToolResult,
  ToolCallConfirmationDetails,
  ToolExecuteConfirmationDetails,
} from './tools.js';
import {
  BaseDeclarativeTool,
  BaseToolInvocation,
  Kind,
  type PolicyUpdateOptions,
} from './tools.js';
import { ApprovalMode } from '../policy/types.js';

import { getErrorMessage } from '../utils/errors.js';
import { summarizeToolOutput } from '../utils/summarizer.js';
import type {
  ShellExecutionConfig,
  ShellOutputEvent,
} from '../services/shellExecutionService.js';
import { ShellExecutionService } from '../services/shellExecutionService.js';
import { formatMemoryUsage } from '../utils/formatters.js';
import type { AnsiOutput } from '../utils/terminalSerializer.js';
import {
  getCommandRoots,
  initializeShellParsers,
  stripShellWrapper,
} from '../utils/shell-utils.js';
import {
  isCommandAllowed,
  isShellInvocationAllowlisted,
} from '../utils/shell-permissions.js';
import { SHELL_TOOL_NAME } from './tool-names.js';
import type { MessageBus } from '../confirmation-bus/message-bus.js';

export const OUTPUT_UPDATE_INTERVAL_MS = 1000;

export interface ShellToolParams {
  command: string;
  description?: string;
  dir_path?: string;
}

export class ShellToolInvocation extends BaseToolInvocation<
  ShellToolParams,
  ToolResult
> {
  constructor(
    private readonly config: Config,
    params: ShellToolParams,
    private readonly allowlist: Set<string>,
    messageBus?: MessageBus,
    _toolName?: string,
    _toolDisplayName?: string,
  ) {
    super(params, messageBus, _toolName, _toolDisplayName);
  }

  getDescription(): string {
    let description = `${this.params.command}`;
    // append optional [in directory]
    // note description is needed even if validation fails due to absolute path
    if (this.params.dir_path) {
      description += ` [in ${this.params.dir_path}]`;
    } else {
      description += ` [current working directory ${process.cwd()}]`;
    }
    // append optional (description), replacing any line breaks with spaces
    if (this.params.description) {
      description += ` (${this.params.description.replace(/\n/g, ' ')})`;
    }
    return description;
  }

  protected override getPolicyUpdateOptions(
    outcome: ToolConfirmationOutcome,
  ): PolicyUpdateOptions | undefined {
    if (outcome === ToolConfirmationOutcome.ProceedAlwaysAndSave) {
      return { commandPrefix: this.params.command };
    }
    return undefined;
  }

  protected override async getConfirmationDetails(
    _abortSignal: AbortSignal,
  ): Promise<ToolCallConfirmationDetails | false> {
    const command = stripShellWrapper(this.params.command);
    const rootCommands = [...new Set(getCommandRoots(command))];

    // In non-interactive mode, we need to prevent the tool from hanging while
    // waiting for user input. If a tool is not fully allowed (e.g. via
    // --allowed-tools="ShellTool(wc)"), we should throw an error instead of
    // prompting for confirmation. This check is skipped in YOLO mode.
    if (
      !this.config.isInteractive() &&
      this.config.getApprovalMode() !== ApprovalMode.YOLO
    ) {
      if (this.isInvocationAllowlisted(command)) {
        // If it's an allowed shell command, we don't need to confirm execution.
        return false;
      }

      throw new Error(
        `Command "${command}" is not in the list of allowed tools for non-interactive mode.`,
      );
    }

    const commandsToConfirm = rootCommands.filter(
      (command) => !this.allowlist.has(command),
    );

    if (commandsToConfirm.length === 0) {
      return false; // already approved and allowlisted
    }

    const confirmationDetails: ToolExecuteConfirmationDetails = {
      type: 'exec',
      title: 'Confirm Shell Command',
      command: this.params.command,
      rootCommand: commandsToConfirm.join(', '),
      onConfirm: async (outcome: ToolConfirmationOutcome) => {
        if (outcome === ToolConfirmationOutcome.ProceedAlways) {
          commandsToConfirm.forEach((command) => this.allowlist.add(command));
        }
        await this.publishPolicyUpdate(outcome);
      },
    };
    return confirmationDetails;
  }

  async execute(
    signal: AbortSignal,
    updateOutput?: (output: string | AnsiOutput) => void,
    shellExecutionConfig?: ShellExecutionConfig,
    setPidCallback?: (pid: number) => void,
  ): Promise<ToolResult> {
    const strippedCommand = stripShellWrapper(this.params.command);

    if (signal.aborted) {
      return {
        llmContent: 'Command was cancelled by user before it could start.',
        returnDisplay: 'Command cancelled by user.',
      };
    }

    const isWindows = os.platform() === 'win32';
    const tempFileName = `shell_pgrep_${crypto
      .randomBytes(6)
      .toString('hex')}.tmp`;
    const tempFilePath = path.join(os.tmpdir(), tempFileName);

    const timeoutMs = this.config.getShellToolInactivityTimeout();
    const timeoutController = new AbortController();
    let timeoutTimer: NodeJS.Timeout | undefined;

    // Handle signal combination manually to avoid TS issues or runtime missing features
    const combinedController = new AbortController();

    const onAbort = () => combinedController.abort();

    try {
      // pgrep is not available on Windows, so we can't get background PIDs
      const commandToExecute = isWindows
        ? strippedCommand
        : (() => {
            // wrap command to append subprocess pids (via pgrep) to temporary file
            let command = strippedCommand.trim();
            if (!command.endsWith('&')) command += ';';
            return `{ ${command} }; __code=$?; pgrep -g 0 >${tempFilePath} 2>&1; exit $__code;`;
          })();

      const cwd = this.params.dir_path
        ? path.resolve(this.config.getTargetDir(), this.params.dir_path)
        : this.config.getTargetDir();

      let cumulativeOutput: string | AnsiOutput = '';
      let lastUpdateTime = Date.now();
      let isBinaryStream = false;

      const resetTimeout = () => {
        if (timeoutMs <= 0) {
          return;
        }
        if (timeoutTimer) clearTimeout(timeoutTimer);
        timeoutTimer = setTimeout(() => {
          timeoutController.abort();
        }, timeoutMs);
      };

      signal.addEventListener('abort', onAbort, { once: true });
      timeoutController.signal.addEventListener('abort', onAbort, {
        once: true,
      });

      // Start timeout
      resetTimeout();

      const { result: resultPromise, pid } =
        await ShellExecutionService.execute(
          commandToExecute,
          cwd,
          (event: ShellOutputEvent) => {
            resetTimeout(); // Reset timeout on any event
            if (!updateOutput) {
              return;
            }

            let shouldUpdate = false;

            switch (event.type) {
              case 'data':
                if (isBinaryStream) break;
                cumulativeOutput = event.chunk;
                shouldUpdate = true;
                break;
              case 'binary_detected':
                isBinaryStream = true;
                cumulativeOutput =
                  '[Binary output detected. Halting stream...]';
                shouldUpdate = true;
                break;
              case 'binary_progress':
                isBinaryStream = true;
                cumulativeOutput = `[Receiving binary output... ${formatMemoryUsage(
                  event.bytesReceived,
                )} received]`;
                if (Date.now() - lastUpdateTime > OUTPUT_UPDATE_INTERVAL_MS) {
                  shouldUpdate = true;
                }
                break;
              default: {
                throw new Error('An unhandled ShellOutputEvent was found.');
              }
            }

            if (shouldUpdate) {
              updateOutput(cumulativeOutput);
              lastUpdateTime = Date.now();
            }
          },
          combinedController.signal,
          this.config.getEnableInteractiveShell(),
          { ...shellExecutionConfig, pager: 'cat' },
        );

      if (pid && setPidCallback) {
        setPidCallback(pid);
      }

      const result = await resultPromise;

      const backgroundPIDs: number[] = [];
      if (os.platform() !== 'win32') {
        if (fs.existsSync(tempFilePath)) {
          const pgrepLines = fs
            .readFileSync(tempFilePath, 'utf8')
            .split(EOL)
            .filter(Boolean);
          for (const line of pgrepLines) {
            if (!/^\d+$/.test(line)) {
              debugLogger.error(`pgrep: ${line}`);
            }
            const pid = Number(line);
            if (pid !== result.pid) {
              backgroundPIDs.push(pid);
            }
          }
        } else {
          if (!signal.aborted) {
            debugLogger.error('missing pgrep output');
          }
        }
      }

      let llmContent = '';
      let timeoutMessage = '';
      if (result.aborted) {
        if (timeoutController.signal.aborted) {
          timeoutMessage = `Command was automatically cancelled because it exceeded the timeout of ${(
            timeoutMs / 60000
          ).toFixed(1)} minutes without output.`;
          llmContent = timeoutMessage;
        } else {
          llmContent =
            'Command was cancelled by user before it could complete.';
        }
        if (result.output.trim()) {
          llmContent += ` Below is the output before it was cancelled:\n${result.output}`;
        } else {
          llmContent += ' There was no output before it was cancelled.';
        }
      } else {
        // Create a formatted error string for display, replacing the wrapper command
        // with the user-facing command.
        const finalError = result.error
          ? result.error.message.replace(commandToExecute, this.params.command)
          : '(none)';

        llmContent = [
          `Command: ${this.params.command}`,
          `Directory: ${this.params.dir_path || '(root)'}`,
          `Output: ${result.output || '(empty)'}`,
          `Error: ${finalError}`, // Use the cleaned error string.
          `Exit Code: ${result.exitCode ?? '(none)'}`,
          `Signal: ${result.signal ?? '(none)'}`,
          `Background PIDs: ${
            backgroundPIDs.length ? backgroundPIDs.join(', ') : '(none)'
          }`,
          `Process Group PGID: ${result.pid ?? '(none)'}`,
        ].join('\n');
      }

      let returnDisplayMessage = '';
      if (this.config.getDebugMode()) {
        returnDisplayMessage = llmContent;
      } else {
        if (result.output.trim()) {
          returnDisplayMessage = result.output;
        } else {
          if (result.aborted) {
            if (timeoutMessage) {
              returnDisplayMessage = timeoutMessage;
            } else {
              returnDisplayMessage = 'Command cancelled by user.';
            }
          } else if (result.signal) {
            returnDisplayMessage = `Command terminated by signal: ${result.signal}`;
          } else if (result.error) {
            returnDisplayMessage = `Command failed: ${getErrorMessage(
              result.error,
            )}`;
          } else if (result.exitCode !== null && result.exitCode !== 0) {
            returnDisplayMessage = `Command exited with code: ${result.exitCode}`;
          }
          // If output is empty and command succeeded (code 0, no error/signal/abort),
          // returnDisplayMessage will remain empty, which is fine.
        }
      }

      const summarizeConfig = this.config.getSummarizeToolOutputConfig();
      const executionError = result.error
        ? {
            error: {
              message: result.error.message,
              type: ToolErrorType.SHELL_EXECUTE_ERROR,
            },
          }
        : {};
      if (summarizeConfig && summarizeConfig[SHELL_TOOL_NAME]) {
        const summary = await summarizeToolOutput(
          this.config,
          { model: 'summarizer-shell' },
          llmContent,
          this.config.getGeminiClient(),
          signal,
        );
        return {
          llmContent: summary,
          returnDisplay: returnDisplayMessage,
          ...executionError,
        };
      }

      return {
        llmContent,
        returnDisplay: returnDisplayMessage,
        ...executionError,
      };
    } finally {
      if (timeoutTimer) clearTimeout(timeoutTimer);
      signal.removeEventListener('abort', onAbort);
      timeoutController.signal.removeEventListener('abort', onAbort);
      if (fs.existsSync(tempFilePath)) {
        fs.unlinkSync(tempFilePath);
      }
    }
  }

  private isInvocationAllowlisted(command: string): boolean {
    const allowedTools = this.config.getAllowedTools() || [];
    if (allowedTools.length === 0) {
      return false;
    }

    const invocation = { params: { command } } as unknown as AnyToolInvocation;
    return isShellInvocationAllowlisted(invocation, allowedTools);
  }
}

function getShellToolDescription(): string {
  const returnedInfo = `

      The following information is returned:

      Command: Executed command.
      Directory: Directory where command was executed, or `(root)`.
      Stdout: Output on stdout stream. Can be `(empty)` or partial on error and for any unwaited background processes.
      Stderr: Output on stderr stream. Can be `(empty)` or partial on error and for any unwaited background processes.
      Error: Error or `(none)` if no error was reported for the subprocess.
      Exit Code: Exit code or `(none)` if terminated by signal.
      Signal: Signal number or `(none)` if no signal was received.
      Background PIDs: List of background processes started or `(none)`.
      Process Group PGID: Process group started or `(none)``;

  if (os.platform() === 'win32') {
    return `This tool executes a given shell command as `powershell.exe -NoProfile -Command <command>`. Command can start background processes using PowerShell constructs such as `Start-Process -NoNewWindow` or `Start-Job`.${returnedInfo}`;
  } else {
    return `This tool executes a given shell command as `bash -c <command>`. Command can start background processes using `&`. Command is executed as a subprocess that leads its own process group. Command process group can be terminated as `kill -- -PGID` or signaled as `kill -s SIGNAL -- -PGID`.${returnedInfo}`;
  }
}

function getCommandDescription(): string {
  if (os.platform() === 'win32') {
    return 'Exact command to execute as `powershell.exe -NoProfile -Command <command>`';
  } else {
    return 'Exact bash command to execute as `bash -c <command>`';
  }
}

export class ShellTool extends BaseDeclarativeTool<
  ShellToolParams,
  ToolResult
> {
  static readonly Name = SHELL_TOOL_NAME;

  private allowlist: Set<string> = new Set();

  constructor(
    private readonly config: Config,
    messageBus?: MessageBus,
  ) {
    void initializeShellParsers().catch(() => {
      // Errors are surfaced when parsing commands.
    });
    super(
      ShellTool.Name,
      'Shell',
      getShellToolDescription(),
      Kind.Execute,
      {
        type: 'object',
        properties: {
          command: {
            type: 'string',
            description: getCommandDescription(),
          },
          description: {
            type: 'string',
            description:
              'Brief description of the command for the user. Be specific and concise. Ideally a single sentence. Can be up to 3 sentences for clarity. No line breaks.',
          },
          dir_path: {
            type: 'string',
            description:
              '(OPTIONAL) The path of the directory to run the command in. If not provided, the project root directory is used. Must be a directory within the workspace and must already exist.',
          },
        },
        required: ['command'],
      },
      false, // output is not markdown
      true, // output can be updated
      messageBus,
    );
  }

  protected override validateToolParamValues(
    params: ShellToolParams,
  ): string | null {
    if (!params.command.trim()) {
      return 'Command cannot be empty.';
    }

    const commandCheck = isCommandAllowed(params.command, this.config);
    if (!commandCheck.allowed) {
      if (!commandCheck.reason) {
        debugLogger.error(
          'Unexpected: isCommandAllowed returned false without a reason',
        );
        return `Command is not allowed: ${params.command}`;
      }
      return commandCheck.reason;
    }
    if (getCommandRoots(params.command).length === 0) {
      return 'Could not identify command root to obtain permission from user.';
    }
    if (params.dir_path) {
      const resolvedPath = path.resolve(
        this.config.getTargetDir(),
        params.dir_path,
      );
      const workspaceContext = this.config.getWorkspaceContext();
      if (!workspaceContext.isPathWithinWorkspace(resolvedPath)) {
        return `Directory '${resolvedPath}' is not within any of the registered workspace directories.`;
      }
    }
    return null;
  }

  protected createInvocation(
    params: ShellToolParams,
    messageBus?: MessageBus,
    _toolName?: string,
    _toolDisplayName?: string,
  ): ToolInvocation<ShellToolParams, ToolResult> {
    return new ShellToolInvocation(
      this.config,
      params,
      this.allowlist,
      messageBus,
      _toolName,
      _toolDisplayName,
    );
  }
}

## 2. list_directory (`LSTool`)

**File:** `packages/core/src/tools/ls.ts`

**Tests:**
*   **Unit:** `packages/core/src/tools/ls.test.ts`
*   **Integration:** `integration-tests/list_directory.test.ts`

```typescript
/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import type { MessageBus } from '../confirmation-bus/message-bus.js';
import fs from 'node:fs/promises';
import path from 'node:path';
import type { ToolInvocation, ToolResult } from './tools.js';
import { BaseDeclarativeTool, BaseToolInvocation, Kind } from './tools.js';
import { makeRelative, shortenPath } from '../utils/paths.js';
import type { Config } from '../config/config.js';
import { DEFAULT_FILE_FILTERING_OPTIONS } from '../config/constants.js';
import { ToolErrorType } from './tool-error.js';
import { LS_TOOL_NAME } from './tool-names.js';
import { debugLogger } from '../utils/debugLogger.js';

/**
 * Parameters for the LS tool
 */
export interface LSToolParams {
  /**
   * The absolute path to the directory to list
   */
  dir_path: string;

  /**
   * Array of glob patterns to ignore (optional)
   */
  ignore?: string[];

  /**
   * Whether to respect .gitignore and .geminiignore patterns (optional, defaults to true)
   */
  file_filtering_options?: {
    respect_git_ignore?: boolean;
    respect_gemini_ignore?: boolean;
  };
}

/**
 * File entry returned by LS tool
 */
export interface FileEntry {
  /**
   * Name of the file or directory
   */
  name: string;

  /**
   * Absolute path to the file or directory
   */
  path: string;

  /**
   * Whether this entry is a directory
   */
  isDirectory: boolean;

  /**
   * Size of the file in bytes (0 for directories)
   */
  size: number;

  /**
   * Last modified timestamp
   */
  modifiedTime: Date;
}

class LSToolInvocation extends BaseToolInvocation<LSToolParams, ToolResult> {
  constructor(
    private readonly config: Config,
    params: LSToolParams,
    messageBus?: MessageBus,
    _toolName?: string,
    _toolDisplayName?: string,
  ) {
    super(params, messageBus, _toolName, _toolDisplayName);
  }

  /**
   * Checks if a filename matches any of the ignore patterns
   * @param filename Filename to check
   * @param patterns Array of glob patterns to check against
   * @returns True if the filename should be ignored
   */
  private shouldIgnore(filename: string, patterns?: string[]): boolean {
    if (!patterns || patterns.length === 0) {
      return false;
    }
    for (const pattern of patterns) {
      // Convert glob pattern to RegExp
      const regexPattern = pattern
        .replace(/[.+^${}()|[\\\]/g, '\$&') // Escape special regex characters
        .replace(/\*/g, '.*') // Convert glob '*' to regex '.*'
        .replace(/\?/g, '.'); // Convert glob '?' to regex '.'
      const regex = new RegExp(`^${regexPattern}$`);
      if (regex.test(filename)) {
        return true;
      }
    }
    return false;
  }

  /**
   * Gets a description of the file reading operation
   * @returns A string describing the file being read
   */
  getDescription(): string {
    const relativePath = makeRelative(
      this.params.dir_path,
      this.config.getTargetDir(),
    );
    return shortenPath(relativePath);
  }

  // Helper for consistent error formatting
  private errorResult(
    llmContent: string,
    returnDisplay: string,
    type: ToolErrorType,
  ): ToolResult {
    return {
      llmContent,
      // Keep returnDisplay simpler in core logic
      returnDisplay: `Error: ${returnDisplay}`,
      error: {
        message: llmContent,
        type,
      },
    };
  }

  /**
   * Executes the LS operation with the given parameters
   * @returns Result of the LS operation
   */
  async execute(_signal: AbortSignal): Promise<ToolResult> {
    const resolvedDirPath = path.resolve(
      this.config.getTargetDir(),
      this.params.dir_path,
    );
    try {
      const stats = await fs.stat(resolvedDirPath);
      if (!stats) {
        // fs.statSync throws on non-existence, so this check might be redundant
        // but keeping for clarity. Error message adjusted.
        return this.errorResult(
          `Error: Directory not found or inaccessible: ${resolvedDirPath}`,
          `Directory not found or inaccessible.`,
          ToolErrorType.FILE_NOT_FOUND,
        );
      }
      if (!stats.isDirectory()) {
        return this.errorResult(
          `Error: Path is not a directory: ${resolvedDirPath}`,
          `Path is not a directory.`,
          ToolErrorType.PATH_IS_NOT_A_DIRECTORY,
        );
      }

      const files = await fs.readdir(resolvedDirPath);
      if (files.length === 0) {
        // Changed error message to be more neutral for LLM
        return {
          llmContent: `Directory ${resolvedDirPath} is empty.`,
          returnDisplay: `Directory is empty.`,
        };
      }

      const relativePaths = files.map((file) =>
        path.relative(
          this.config.getTargetDir(),
          path.join(resolvedDirPath, file),
        ),
      );

      const fileDiscovery = this.config.getFileService();
      const { filteredPaths, ignoredCount } =
        fileDiscovery.filterFilesWithReport(relativePaths, {
          respectGitIgnore:
            this.params.file_filtering_options?.respect_git_ignore ??
            this.config.getFileFilteringOptions().respectGitIgnore ??
            DEFAULT_FILE_FILTERING_OPTIONS.respectGitIgnore,
          respectGeminiIgnore:
            this.params.file_filtering_options?.respect_gemini_ignore ??
            this.config.getFileFilteringOptions().respectGeminiIgnore ??
            DEFAULT_FILE_FILTERING_OPTIONS.respectGeminiIgnore,
        });

      const entries = [];
      for (const relativePath of filteredPaths) {
        const fullPath = path.resolve(this.config.getTargetDir(), relativePath);

        if (this.shouldIgnore(path.basename(fullPath), this.params.ignore)) {
          continue;
        }

        try {
          const stats = await fs.stat(fullPath);
          const isDir = stats.isDirectory();
          entries.push({
            name: path.basename(fullPath),
            path: fullPath,
            isDirectory: isDir,
            size: isDir ? 0 : stats.size,
            modifiedTime: stats.mtime,
          });
        } catch (error) {
          // Log error internally but don't fail the whole listing
          debugLogger.debug(`Error accessing ${fullPath}: ${error}`);
        }
      }

      // Sort entries (directories first, then alphabetically)
      entries.sort((a, b) => {
        if (a.isDirectory && !b.isDirectory) return -1;
        if (!a.isDirectory && b.isDirectory) return 1;
        return a.name.localeCompare(b.name);
      });

      // Create formatted content for LLM
      const directoryContent = entries
        .map((entry) => `${entry.isDirectory ? '[DIR] ' : ''}${entry.name}`)
        .join('\n');

      let resultMessage = `Directory listing for ${resolvedDirPath}:\n${directoryContent}`;
      if (ignoredCount > 0) {
        resultMessage += `\n\n(${ignoredCount} ignored)`;
      }

      let displayMessage = `Listed ${entries.length} item(s).`;
      if (ignoredCount > 0) {
        displayMessage += ` (${ignoredCount} ignored)`;
      }

      return {
        llmContent: resultMessage,
        returnDisplay: displayMessage,
      };
    } catch (error) {
      const errorMsg = `Error listing directory: ${error instanceof Error ? error.message : String(error)}`;
      return this.errorResult(
        errorMsg,
        'Failed to list directory.',
        ToolErrorType.LS_EXECUTION_ERROR,
      );
    }
  }
}

/**
 * Implementation of the LS tool logic
 */
export class LSTool extends BaseDeclarativeTool<LSToolParams, ToolResult> {
  static readonly Name = LS_TOOL_NAME;

  constructor(
    private config: Config,
    messageBus?: MessageBus,
  ) {
    super(
      LSTool.Name,
      'ReadFolder',
      'Lists the names of files and subdirectories directly within a specified directory path. Can optionally ignore entries matching provided glob patterns.',
      Kind.Search,
      {
        properties: {
          dir_path: {
            description: 'The path to the directory to list',
            type: 'string',
          },
          ignore: {
            description: 'List of glob patterns to ignore',
            items: {
              type: 'string',
            },
            type: 'array',
          },
          file_filtering_options: {
            description:
              'Optional: Whether to respect ignore patterns from .gitignore or .geminiignore',
            type: 'object',
            properties: {
              respect_git_ignore: {
                description:
                  'Optional: Whether to respect .gitignore patterns when listing files. Only available in git repositories. Defaults to true.',
                type: 'boolean',
              },
              respect_gemini_ignore: {
                description:
                  'Optional: Whether to respect .geminiignore patterns when listing files. Defaults to true.',
                type: 'boolean',
              },
            },
          },
        },
        required: ['dir_path'],
        type: 'object',
      },
      true,
      false,
      messageBus,
    );
  }

  /**
   * Validates the parameters for the tool
   * @param params Parameters to validate
   * @returns An error message string if invalid, null otherwise
   */
  protected override validateToolParamValues(
    params: LSToolParams,
  ): string | null {
    const resolvedPath = path.resolve(
      this.config.getTargetDir(),
      params.dir_path,
    );
    const workspaceContext = this.config.getWorkspaceContext();
    if (!workspaceContext.isPathWithinWorkspace(resolvedPath)) {
      const directories = workspaceContext.getDirectories();
      return `Path must be within one of the workspace directories: ${directories.join(
        ', ',
      )}`;
    }
    return null;
  }

  protected createInvocation(
    params: LSToolParams,
    messageBus?: MessageBus,
    _toolName?: string,
    _toolDisplayName?: string,
  ): ToolInvocation<LSToolParams, ToolResult> {
    return new LSToolInvocation(
      this.config,
      params,
      messageBus,
      _toolName,
      _toolDisplayName,
    );
  }
}

## 3. read_file (`ReadFileTool`)

**File:** `packages/core/src/tools/read-file.ts`

**Tests:**
*   **Unit:** `packages/core/src/tools/read-file.test.ts`
*   **Integration:** `integration-tests/file-system.test.ts`

```typescript
/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import type { MessageBus } from '../confirmation-bus/message-bus.js';
import path from 'node:path';
import { makeRelative, shortenPath } from '../utils/paths.js';
import type { ToolInvocation, ToolLocation, ToolResult } from './tools.js';
import { BaseDeclarativeTool, BaseToolInvocation, Kind } from './tools.js';

import type { PartUnion } from '@google/genai';
import {
  processSingleFileContent,
  getSpecificMimeType,
} from '../utils/fileUtils.js';
import type { Config } from '../config/config.js';
import { FileOperation } from '../telemetry/metrics.js';
import { getProgrammingLanguage } from '../telemetry/telemetry-utils.js';
import { logFileOperation } from '../telemetry/loggers.js';
import { FileOperationEvent } from '../telemetry/types.js';
import { READ_FILE_TOOL_NAME } from './tool-names.js';

/**
 * Parameters for the ReadFile tool
 */
export interface ReadFileToolParams {
  /**
   * The path to the file to read
   */
  file_path: string;

  /**
   * The line number to start reading from (optional)
   */
  offset?: number;

  /**
   * The number of lines to read (optional)
   */
  limit?: number;
}

class ReadFileToolInvocation extends BaseToolInvocation<
  ReadFileToolParams,
  ToolResult
> {
  private readonly resolvedPath: string;
  constructor(
    private config: Config,
    params: ReadFileToolParams,
    messageBus?: MessageBus,
    _toolName?: string,
    _toolDisplayName?: string,
  ) {
    super(params, messageBus, _toolName, _toolDisplayName);
    this.resolvedPath = path.resolve(
      this.config.getTargetDir(),
      this.params.file_path,
    );
  }

  getDescription(): string {
    const relativePath = makeRelative(
      this.resolvedPath,
      this.config.getTargetDir(),
    );
    return shortenPath(relativePath);
  }

  override toolLocations(): ToolLocation[] {
    return [{ path: this.resolvedPath, line: this.params.offset }];
  }

  async execute(): Promise<ToolResult> {
    const result = await processSingleFileContent(
      this.resolvedPath,
      this.config.getTargetDir(),
      this.config.getFileSystemService(),
      this.params.offset,
      this.params.limit,
    );

    if (result.error) {
      return {
        llmContent: result.llmContent,
        returnDisplay: result.returnDisplay || 'Error reading file',
        error: {
          message: result.error,
          type: result.errorType,
        },
      };
    }

    let llmContent: PartUnion;
    if (result.isTruncated) {
      const [start, end] = result.linesShown!;
      const total = result.originalLineCount!;
      const nextOffset = this.params.offset
        ? this.params.offset + end - start + 1
        : end;
      llmContent = `
IMPORTANT: The file content has been truncated.
Status: Showing lines ${start}-${end} of ${total} total lines.
Action: To read more of the file, you can use the 'offset' and 'limit' parameters in a subsequent 'read_file' call. For example, to read the next section of the file, use offset: ${nextOffset}.

--- FILE CONTENT (truncated) ---
${result.llmContent}`;
    } else {
      llmContent = result.llmContent || '';
    }

    const lines =
      typeof result.llmContent === 'string'
        ? result.llmContent.split('\n').length
        : undefined;
    const mimetype = getSpecificMimeType(this.resolvedPath);
    const programming_language = getProgrammingLanguage({
      file_path: this.resolvedPath,
    });
    logFileOperation(
      this.config,
      new FileOperationEvent(
        READ_FILE_TOOL_NAME,
        FileOperation.READ,
        lines,
        mimetype,
        path.extname(this.resolvedPath),
        programming_language,
      ),
    );

    return {
      llmContent,
      returnDisplay: result.returnDisplay || '',
    };
  }
}

/**
 * Implementation of the ReadFile tool logic
 */
export class ReadFileTool extends BaseDeclarativeTool<
  ReadFileToolParams,
  ToolResult
> {
  static readonly Name = READ_FILE_TOOL_NAME;

  constructor(
    private config: Config,
    messageBus?: MessageBus,
  ) {
    super(
      ReadFileTool.Name,
      'ReadFile',
      `Reads and returns the content of a specified file. If the file is large, the content will be truncated. The tool's response will clearly indicate if truncation has occurred and will provide details on how to read more of the file using the 'offset' and 'limit' parameters. Handles text, images (PNG, JPG, GIF, WEBP, SVG, BMP), audio files (MP3, WAV, AIFF, AAC, OGG, FLAC), and PDF files. For text files, it can read specific line ranges.`,
      Kind.Read,
      {
        properties: {
          file_path: {
            description: 'The path to the file to read.',
            type: 'string',
          },
          offset: {
            description:

````
