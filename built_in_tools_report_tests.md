# Built-in Tools Report

This report contains the full source code for the built-in tools in the Gemini
CLI project, along with their associated unit and integration tests.

## 1. run_shell_command (`ShellTool`)

**File:** `packages/core/src/tools/shell.ts`

**Tests:**

- **Unit:** `packages/core/src/tools/shell.test.ts`

```typescript
/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import {
  vi,
  describe,
  it,
  expect,
  beforeAll,
  beforeEach,
  afterEach,
  type Mock,
} from 'vitest';

const mockPlatform = vi.hoisted(() => vi.fn());

const mockShellExecutionService = vi.hoisted(() => vi.fn());
vi.mock('../services/shellExecutionService.js', () => ({
  ShellExecutionService: { execute: mockShellExecutionService },
}));

vi.mock('node:os', async (importOriginal) => {
  const actualOs = await importOriginal<typeof os>();
  return {
    ...actualOs,
    default: {
      ...actualOs,
      platform: mockPlatform,
    },
    platform: mockPlatform,
  };
});
vi.mock('crypto');
vi.mock('../utils/summarizer.js');

import { initializeShellParsers } from '../utils/shell-utils.js';
import { isCommandAllowed } from '../utils/shell-permissions.js';
import { ShellTool } from './shell.js';
import { type Config } from '../config/config.js';
import {
  type ShellExecutionResult,
  type ShellOutputEvent,
} from '../services/shellExecutionService.js';
import * as fs from 'node:fs';
import * as os from 'node:os';
import { EOL } from 'node:os';
import * as path from 'node:path';
import * as crypto from 'node:crypto';
import * as summarizer from '../utils/summarizer.js';
import { ToolErrorType } from './tool-error.js';
import { ToolConfirmationOutcome } from './tools.js';
import { OUTPUT_UPDATE_INTERVAL_MS } from './shell.js';
import { SHELL_TOOL_NAME } from './tool-names.js';
import { WorkspaceContext } from '../utils/workspaceContext.js';

const originalComSpec = process.env['ComSpec'];
const itWindowsOnly = process.platform === 'win32' ? it : it.skip;

describe('ShellTool', () => {
  beforeAll(async () => {
    await initializeShellParsers();
  });

  let shellTool: ShellTool;
  let mockConfig: Config;
  let mockShellOutputCallback: (event: ShellOutputEvent) => void;
  let resolveExecutionPromise: (result: ShellExecutionResult) => void;
  let tempRootDir: string;

  beforeEach(() => {
    vi.clearAllMocks();

    tempRootDir = fs.mkdtempSync(path.join(os.tmpdir(), 'shell-test-'));
    fs.mkdirSync(path.join(tempRootDir, 'subdir'));

    mockConfig = {
      getAllowedTools: vi.fn().mockReturnValue([]),
      getApprovalMode: vi.fn().mockReturnValue('strict'),
      getCoreTools: vi.fn().mockReturnValue([]),
      getExcludeTools: vi.fn().mockReturnValue(new Set([])),
      getDebugMode: vi.fn().mockReturnValue(false),
      getTargetDir: vi.fn().mockReturnValue(tempRootDir),
      getSummarizeToolOutputConfig: vi.fn().mockReturnValue(undefined),
      getWorkspaceContext: vi
        .fn()
        .mockReturnValue(new WorkspaceContext(tempRootDir)),
      getGeminiClient: vi.fn(),
      getEnableInteractiveShell: vi.fn().mockReturnValue(false),
      isInteractive: vi.fn().mockReturnValue(true),
      getShellToolInactivityTimeout: vi.fn().mockReturnValue(300000),
    } as unknown as Config;

    shellTool = new ShellTool(mockConfig);

    mockPlatform.mockReturnValue('linux');
    (vi.mocked(crypto.randomBytes) as Mock).mockReturnValue(
      Buffer.from('abcdef', 'hex'),
    );
    process.env['ComSpec'] =
      'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe';

    // Capture the output callback to simulate streaming events from the service
    mockShellExecutionService.mockImplementation((_cmd, _cwd, callback) => {
      mockShellOutputCallback = callback;
      return {
        pid: 12345,
        result: new Promise((resolve) => {
          resolveExecutionPromise = resolve;
        }),
      };
    });
  });

  afterEach(() => {
    if (fs.existsSync(tempRootDir)) {
      fs.rmSync(tempRootDir, { recursive: true, force: true });
    }
    if (originalComSpec === undefined) {
      delete process.env['ComSpec'];
    } else {
      process.env['ComSpec'] = originalComSpec;
    }
  });

  describe('isCommandAllowed', () => {
    it('should allow a command if no restrictions are provided', () => {
      (mockConfig.getCoreTools as Mock).mockReturnValue(undefined);
      (mockConfig.getExcludeTools as Mock).mockReturnValue(undefined);
      expect(isCommandAllowed('goodCommand --safe', mockConfig).allowed).toBe(
        true,
      );
    });

    it('should allow a command with command substitution using $()', () => {
      const evaluation = isCommandAllowed(
        'echo $(goodCommand --safe)',
        mockConfig,
      );
      expect(evaluation.allowed).toBe(true);
      expect(evaluation.reason).toBeUndefined();
    });
  });

  describe('build', () => {
    it('should return an invocation for a valid command', () => {
      const invocation = shellTool.build({ command: 'goodCommand --safe' });
      expect(invocation).toBeDefined();
    });

    it('should throw an error for an empty command', () => {
      expect(() => shellTool.build({ command: ' ' })).toThrow(
        'Command cannot be empty.',
      );
    });

    it('should return an invocation for a valid relative directory path', () => {
      const invocation = shellTool.build({
        command: 'ls',
        dir_path: 'subdir',
      });
      expect(invocation).toBeDefined();
    });

    it('should throw an error for a directory outside the workspace', () => {
      const outsidePath = path.resolve(tempRootDir, '../outside');
      expect(() =>
        shellTool.build({ command: 'ls', dir_path: outsidePath }),
      ).toThrow(
        `Directory '${outsidePath}' is not within any of the registered workspace directories.`,
      );
    });

    it('should return an invocation for a valid absolute directory path', () => {
      const invocation = shellTool.build({
        command: 'ls',
        dir_path: path.join(tempRootDir, 'subdir'),
      });
      expect(invocation).toBeDefined();
    });
  });

  describe('execute', () => {
    const mockAbortSignal = new AbortController().signal;

    const resolveShellExecution = (
      result: Partial<ShellExecutionResult> = {},
    ) => {
      const fullResult: ShellExecutionResult = {
        rawOutput: Buffer.from(result.output || ''),
        output: 'Success',
        exitCode: 0,
        signal: null,
        error: null,
        aborted: false,
        pid: 12345,
        executionMethod: 'child_process',
        ...result,
      };
      resolveExecutionPromise(fullResult);
    };

    it('should wrap command on linux and parse pgrep output', async () => {
      const invocation = shellTool.build({ command: 'my-command &' });
      const promise = invocation.execute(mockAbortSignal);
      resolveShellExecution({ pid: 54321 });

      // Simulate pgrep output file creation by the shell command
      const tmpFile = path.join(os.tmpdir(), 'shell_pgrep_abcdef.tmp');
      fs.writeFileSync(tmpFile, `54321${EOL}54322${EOL}`);

      const result = await promise;

      const wrappedCommand = `{ my-command & }; __code=$?; pgrep -g 0 >${tmpFile} 2>&1; exit $__code;`;
      expect(mockShellExecutionService).toHaveBeenCalledWith(
        wrappedCommand,
        tempRootDir,
        expect.any(Function),
        expect.any(AbortSignal),
        false,
        { pager: 'cat' },
      );
      expect(result.llmContent).toContain('Background PIDs: 54322');
      // The file should be deleted by the tool
      expect(fs.existsSync(tmpFile)).toBe(false);
    });

    it('should use the provided absolute directory as cwd', async () => {
      const subdir = path.join(tempRootDir, 'subdir');
      const invocation = shellTool.build({
        command: 'ls',
        dir_path: subdir,
      });
      const promise = invocation.execute(mockAbortSignal);
      resolveShellExecution();
      await promise;

      const tmpFile = path.join(os.tmpdir(), 'shell_pgrep_abcdef.tmp');
      const wrappedCommand = `{ ls; }; __code=$?; pgrep -g 0 >${tmpFile} 2>&1; exit $__code;`;
      expect(mockShellExecutionService).toHaveBeenCalledWith(
        wrappedCommand,
        subdir,
        expect.any(Function),
        expect.any(AbortSignal),
        false,
        { pager: 'cat' },
      );
    });

    it('should use the provided relative directory as cwd', async () => {
      const invocation = shellTool.build({
        command: 'ls',
        dir_path: 'subdir',
      });
      const promise = invocation.execute(mockAbortSignal);
      resolveShellExecution();
      await promise;

      const tmpFile = path.join(os.tmpdir(), 'shell_pgrep_abcdef.tmp');
      const wrappedCommand = `{ ls; }; __code=$?; pgrep -g 0 >${tmpFile} 2>&1; exit $__code;`;
      expect(mockShellExecutionService).toHaveBeenCalledWith(
        wrappedCommand,
        path.join(tempRootDir, 'subdir'),
        expect.any(Function),
        expect.any(AbortSignal),
        false,
        { pager: 'cat' },
      );
    });

    itWindowsOnly(
      'should not wrap command on windows',
      async () => {
        mockPlatform.mockReturnValue('win32');
        const invocation = shellTool.build({ command: 'dir' });
        const promise = invocation.execute(mockAbortSignal);
        resolveShellExecution({
          rawOutput: Buffer.from(''),
          output: '',
          exitCode: 0,
          signal: null,
          error: null,
          aborted: false,
          pid: 12345,
          executionMethod: 'child_process',
        });
        await promise;
        expect(mockShellExecutionService).toHaveBeenCalledWith(
          'dir',
          tempRootDir,
          expect.any(Function),
          expect.any(AbortSignal),
          false,
          { pager: 'cat' },
        );
      },
      20000,
    );

    it('should format error messages correctly', async () => {
      const error = new Error('wrapped command failed');
      const invocation = shellTool.build({ command: 'user-command' });
      const promise = invocation.execute(mockAbortSignal);
      resolveShellExecution({
        error,
        exitCode: 1,
        output: 'err',
        rawOutput: Buffer.from('err'),
        signal: null,
        aborted: false,
        pid: 12345,
        executionMethod: 'child_process',
      });

      const result = await promise;
      expect(result.llmContent).toContain('Error: wrapped command failed');
      expect(result.llmContent).not.toContain('pgrep');
    });

    it('should return a SHELL_EXECUTE_ERROR for a command failure', async () => {
      const error = new Error('command failed');
      const invocation = shellTool.build({ command: 'user-command' });
      const promise = invocation.execute(mockAbortSignal);
      resolveShellExecution({
        error,
        exitCode: 1,
      });

      const result = await promise;

      expect(result.error).toBeDefined();
      expect(result.error?.type).toBe(ToolErrorType.SHELL_EXECUTE_ERROR);
      expect(result.error?.message).toBe('command failed');
    });

    it('should throw an error for invalid parameters', () => {
      expect(() => shellTool.build({ command: '' })).toThrow(
        'Command cannot be empty.',
      );
    });

    it('should summarize output when configured', async () => {
      (mockConfig.getSummarizeToolOutputConfig as Mock).mockReturnValue({
        [SHELL_TOOL_NAME]: { tokenBudget: 1000 },
      });
      vi.mocked(summarizer.summarizeToolOutput).mockResolvedValue(
        'summarized output',
      );

      const invocation = shellTool.build({ command: 'ls' });
      const promise = invocation.execute(mockAbortSignal);
      resolveExecutionPromise({
        output: 'long output',
        rawOutput: Buffer.from('long output'),
        exitCode: 0,
        signal: null,
        error: null,
        aborted: false,
        pid: 12345,
        executionMethod: 'child_process',
      });

      const result = await promise;

      expect(summarizer.summarizeToolOutput).toHaveBeenCalledWith(
        mockConfig,
        { model: 'summarizer-shell' },
        expect.any(String),
        mockConfig.getGeminiClient(),
        mockAbortSignal,
      );
      expect(result.llmContent).toBe('summarized output');
      expect(result.returnDisplay).toBe('long output');
    });

    it('should NOT start a timeout if timeoutMs is <= 0', async () => {
      // Mock the timeout config to be 0
      (mockConfig.getShellToolInactivityTimeout as Mock).mockReturnValue(0);

      vi.useFakeTimers();

      const invocation = shellTool.build({ command: 'sleep 10' });
      const promise = invocation.execute(mockAbortSignal);

      // Verify no timeout logic is triggered even after a long time
      resolveShellExecution({
        output: 'finished',
        exitCode: 0,
      });

      await promise;
      // If we got here without aborting/timing out logic interfering, we're good.
      // We can also verify that setTimeout was NOT called for the inactivity timeout.
      // However, since we don't have direct access to the internal `resetTimeout`,
      // we can infer success by the fact it didn't abort.

      vi.useRealTimers();
    });

    it('should clean up the temp file on synchronous execution error', async () => {
      const error = new Error('sync spawn error');
      mockShellExecutionService.mockImplementation(() => {
        // Create the temp file before throwing to simulate it being left behind
        const tmpFile = path.join(os.tmpdir(), 'shell_pgrep_abcdef.tmp');
        fs.writeFileSync(tmpFile, '');
        throw error;
      });

      const invocation = shellTool.build({ command: 'a-command' });
      await expect(invocation.execute(mockAbortSignal)).rejects.toThrow(error);

      const tmpFile = path.join(os.tmpdir(), 'shell_pgrep_abcdef.tmp');
      expect(fs.existsSync(tmpFile)).toBe(false);
    });

    describe('Streaming to `updateOutput`', () => {
      let updateOutputMock: Mock;
      beforeEach(() => {
        vi.useFakeTimers({ toFake: ['Date'] });
        updateOutputMock = vi.fn();
      });
      afterEach(() => {
        vi.useRealTimers();
      });

      it('should immediately show binary detection message and throttle progress', async () => {
        const invocation = shellTool.build({ command: 'cat img' });
        const promise = invocation.execute(mockAbortSignal, updateOutputMock);

        mockShellOutputCallback({ type: 'binary_detected' });
        expect(updateOutputMock).toHaveBeenCalledOnce();
        expect(updateOutputMock).toHaveBeenCalledWith(
          '[Binary output detected. Halting stream...]',
        );

        mockShellOutputCallback({
          type: 'binary_progress',
          bytesReceived: 1024,
        });
        expect(updateOutputMock).toHaveBeenCalledOnce();

        // Advance time past the throttle interval.
        await vi.advanceTimersByTimeAsync(OUTPUT_UPDATE_INTERVAL_MS + 1);

        // Send a SECOND progress event. This one will trigger the flush.
        mockShellOutputCallback({
          type: 'binary_progress',
          bytesReceived: 2048,
        });

        // Now it should be called a second time with the latest progress.
        expect(updateOutputMock).toHaveBeenCalledTimes(2);
        expect(updateOutputMock).toHaveBeenLastCalledWith(
          '[Receiving binary output... 2.0 KB received]',
        );

        resolveExecutionPromise({
          rawOutput: Buffer.from(''),
          output: '',
          exitCode: 0,
          signal: null,
          error: null,
          aborted: false,
          pid: 12345,
          executionMethod: 'child_process',
        });
        await promise;
      });
    });
  });

  describe('shouldConfirmExecute', () => {
    it('should request confirmation for a new command and allowlist it on "Always"', async () => {
      const params = { command: 'npm install' };
      const invocation = shellTool.build(params);
      const confirmation = await invocation.shouldConfirmExecute(
        new AbortController().signal,
      );

      expect(confirmation).not.toBe(false);
      expect(confirmation && confirmation.type).toBe('exec');

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      await (confirmation as any).onConfirm(
        ToolConfirmationOutcome.ProceedAlways,
      );

      // Should now be allowlisted
      const secondInvocation = shellTool.build({ command: 'npm test' });
      const secondConfirmation = await secondInvocation.shouldConfirmExecute(
        new AbortController().signal,
      );
      expect(secondConfirmation).toBe(false);
    });

    it('should throw an error if validation fails', () => {
      expect(() => shellTool.build({ command: '' })).toThrow();
    });

    describe('in non-interactive mode', () => {
      beforeEach(() => {
        (mockConfig.isInteractive as Mock).mockReturnValue(false);
      });

      it('should not throw an error or block for an allowed command', async () => {
        (mockConfig.getAllowedTools as Mock).mockReturnValue(['ShellTool(wc)']);
        const invocation = shellTool.build({ command: 'wc -l foo.txt' });
        const confirmation = await invocation.shouldConfirmExecute(
          new AbortController().signal,
        );
        expect(confirmation).toBe(false);
      });

      it('should not throw an error or block for an allowed command with arguments', async () => {
        (mockConfig.getAllowedTools as Mock).mockReturnValue([
          'ShellTool(wc -l)',
        ]);
        const invocation = shellTool.build({ command: 'wc -l foo.txt' });
        const confirmation = await invocation.shouldConfirmExecute(
          new AbortController().signal,
        );
        expect(confirmation).toBe(false);
      });

      it('should throw an error for command that is not allowed', async () => {
        (mockConfig.getAllowedTools as Mock).mockReturnValue([
          'ShellTool(wc -l)',
        ]);
        const invocation = shellTool.build({ command: 'madeupcommand' });
        await expect(
          invocation.shouldConfirmExecute(new AbortController().signal),
        ).rejects.toThrow('madeupcommand');
      });

      it('should throw an error for a command that is a prefix of an allowed command', async () => {
        (mockConfig.getAllowedTools as Mock).mockReturnValue([
          'ShellTool(wc -l)',
        ]);
        const invocation = shellTool.build({ command: 'wc' });
        await expect(
          invocation.shouldConfirmExecute(new AbortController().signal),
        ).rejects.toThrow('wc');
      });

      it('should require all segments of a chained command to be allowlisted', async () => {
        (mockConfig.getAllowedTools as Mock).mockReturnValue([
          'ShellTool(echo)',
        ]);
        const invocation = shellTool.build({ command: 'echo "foo" && ls -l' });
        await expect(
          invocation.shouldConfirmExecute(new AbortController().signal),
        ).rejects.toThrow(
          'Command "echo "foo" && ls -l" is not in the list of allowed tools for non-interactive mode.',
        );
      });
    });
  });

  describe('getDescription', () => {
    it('should return the windows description when on windows', () => {
      mockPlatform.mockReturnValue('win32');
      const shellTool = new ShellTool(mockConfig);
      expect(shellTool.description).toMatchSnapshot();
    });

    it('should return the non-windows description when not on windows', () => {
      mockPlatform.mockReturnValue('linux');
      const shellTool = new ShellTool(mockConfig);
      expect(shellTool.description).toMatchSnapshot();
    });
  });
});
```

- **Integration:** `integration-tests/run_shell_command.test.ts`

```typescript
/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { TestRig, printDebugInfo, validateModelOutput } from './test-helper.js';
import { getShellConfiguration } from '../packages/core/src/utils/shell-utils.js';

const { shell } = getShellConfiguration();

function getLineCountCommand(): { command: string; tool: string } {
  switch (shell) {
    case 'powershell':
    case 'cmd':
      return { command: `find /c /v`, tool: 'find' };
    case 'bash':
    default:
      return { command: `wc -l`, tool: 'wc' };
  }
}

function getInvalidCommand(): string {
  switch (shell) {
    case 'powershell':
      return `Get-ChildItem | | Select-Object`;
    case 'cmd':
      return `dir | | findstr foo`;
    case 'bash':
    default:
      return `echo "hello" > > file`;
  }
}

function getAllowedListCommand(): string {
  switch (shell) {
    case 'powershell':
      return 'Get-ChildItem';
    case 'cmd':
      return 'dir';
    case 'bash':
    default:
      return 'ls';
  }
}

function getDisallowedFileReadCommand(testFile: string): {
  command: string;
  tool: string;
} {
  const quotedPath = `"${testFile}"`;
  switch (shell) {
    case 'powershell':
      return { command: `Get-Content ${quotedPath}`, tool: 'Get-Content' };
    case 'cmd':
      return { command: `type ${quotedPath}`, tool: 'type' };
    case 'bash':
    default:
      return { command: `cat ${quotedPath}`, tool: 'cat' };
  }
}

function getChainedEchoCommand(): { allowPattern: string; command: string } {
  const secondCommand = getAllowedListCommand();
  switch (shell) {
    case 'powershell':
      return {
        allowPattern: 'Write-Output',
        command: `Write-Output "foo" && ${secondCommand}`,
      };
    case 'cmd':
      return {
        allowPattern: 'echo',
        command: `echo "foo" && ${secondCommand}`,
      };
    case 'bash':
    default:
      return {
        allowPattern: 'echo',
        command: `echo "foo" && ${secondCommand}`,
      };
  }
}

describe('run_shell_command', () => {
  let rig: TestRig;

  beforeEach(() => {
    rig = new TestRig();
  });

  afterEach(async () => await rig.cleanup());
  it('should be able to run a shell command', async () => {
    await rig.setup('should be able to run a shell command', {
      settings: { tools: { core: ['run_shell_command'] } },
    });

    const prompt = `Please run the command "echo hello-world" and show me the output`;

    const result = await rig.run({ args: prompt });

    const foundToolCall = await rig.waitForToolCall('run_shell_command');

    // Add debugging information
    if (!foundToolCall || !result.includes('hello-world')) {
      printDebugInfo(rig, result, {
        'Found tool call': foundToolCall,
        'Contains hello-world': result.includes('hello-world'),
      });
    }

    expect(
      foundToolCall,
      'Expected to find a run_shell_command tool call',
    ).toBeTruthy();

    // Validate model output - will throw if no output, warn if missing expected content
    // Model often reports exit code instead of showing output
    validateModelOutput(
      result,
      ['hello-world', 'exit code 0'],
      'Shell command test',
    );
  });

  it('should be able to run a shell command via stdin', async () => {
    await rig.setup('should be able to run a shell command via stdin', {
      settings: { tools: { core: ['run_shell_command'] } },
    });

    const prompt = `Please run the command "echo test-stdin" and show me what it outputs`;

    const result = await rig.run({ stdin: prompt });

    const foundToolCall = await rig.waitForToolCall('run_shell_command');

    // Add debugging information
    if (!foundToolCall || !result.includes('test-stdin')) {
      printDebugInfo(rig, result, {
        'Test type': 'Stdin test',
        'Found tool call': foundToolCall,
        'Contains test-stdin': result.includes('test-stdin'),
      });
    }

    expect(
      foundToolCall,
      'Expected to find a run_shell_command tool call',
    ).toBeTruthy();

    // Validate model output - will throw if no output, warn if missing expected content
    validateModelOutput(result, 'test-stdin', 'Shell command stdin test');
  });

  it.skip('should run allowed sub-command in non-interactive mode', async () => {
    await rig.setup('should run allowed sub-command in non-interactive mode');

    const testFile = rig.createFile('test.txt', 'Lorem\nIpsum\nDolor\n');
    const { tool, command } = getLineCountCommand();
    const prompt = `use ${command} to tell me how many lines there are in ${testFile}`;

    // Provide the prompt via stdin to simulate non-interactive mode
    const result = await rig.run({
      args: [`--allowed-tools=run_shell_command(${tool})`],
      stdin: prompt,
      yolo: false,
    });

    const foundToolCall = await rig.waitForToolCall('run_shell_command', 15000);

    if (!foundToolCall) {
      const toolLogs = rig.readToolLogs().map(({ toolRequest }) => ({
        name: toolRequest.name,
        success: toolRequest.success,
        args: toolRequest.args,
      }));
      printDebugInfo(rig, result, {
        'Found tool call': foundToolCall,
        'Allowed tools flag': `run_shell_command(${tool})`,
        Prompt: prompt,
        'Tool logs': toolLogs,
        Result: result,
      });
    }

    expect(
      foundToolCall,
      'Expected to find a run_shell_command tool call',
    ).toBeTruthy();

    const toolCall = rig
      .readToolLogs()
      .filter(
        (toolCall) => toolCall.toolRequest.name === 'run_shell_command',
      )[0];
    expect(toolCall.toolRequest.success).toBe(true);
  });

  it.skip('should succeed with no parens in non-interactive mode', async () => {
    await rig.setup('should succeed with no parens in non-interactive mode');

    const testFile = rig.createFile('test.txt', 'Lorem\nIpsum\nDolor\n');
    const { command } = getLineCountCommand();
    const prompt = `use ${command} to tell me how many lines there are in ${testFile}`;

    const result = await rig.run({
      args: '--allowed-tools=run_shell_command',
      stdin: prompt,
      yolo: false,
    });

    const foundToolCall = await rig.waitForToolCall('run_shell_command', 15000);

    if (!foundToolCall) {
      printDebugInfo(rig, result, {
        'Found tool call': foundToolCall,
      });
    }

    expect(
      foundToolCall,
      'Expected to find a run_shell_command tool call',
    ).toBeTruthy();

    const toolCall = rig
      .readToolLogs()
      .filter(
        (toolCall) => toolCall.toolRequest.name === 'run_shell_command',
      )[0];
    expect(toolCall.toolRequest.success).toBe(true);
  });

  it('should succeed with --yolo mode', async () => {
    await rig.setup('should succeed with --yolo mode', {
      settings: { tools: { core: ['run_shell_command'] } },
    });

    const testFile = rig.createFile('test.txt', 'Lorem\nIpsum\nDolor\n');
    const { command } = getLineCountCommand();
    const prompt = `use ${command} to tell me how many lines there are in ${testFile}`;

    const result = await rig.run({
      args: prompt,
      yolo: true,
    });

    const foundToolCall = await rig.waitForToolCall('run_shell_command', 15000);

    if (!foundToolCall) {
      printDebugInfo(rig, result, {
        'Found tool call': foundToolCall,
      });
    }

    expect(
      foundToolCall,
      'Expected to find a run_shell_command tool call',
    ).toBeTruthy();

    const toolCall = rig
      .readToolLogs()
      .filter(
        (toolCall) => toolCall.toolRequest.name === 'run_shell_command',
      )[0];
    expect(toolCall.toolRequest.success).toBe(true);
  });

  it.skip('should work with ShellTool alias', async () => {
    await rig.setup('should work with ShellTool alias');

    const testFile = rig.createFile('test.txt', 'Lorem\nIpsum\nDolor\n');
    const { tool, command } = getLineCountCommand();
    const prompt = `use ${command} to tell me how many lines there are in ${testFile}`;

    const result = await rig.run({
      args: `--allowed-tools=ShellTool(${tool})`,
      stdin: prompt,
      yolo: false,
    });

    const foundToolCall = await rig.waitForToolCall('run_shell_command', 15000);

    if (!foundToolCall) {
      const toolLogs = rig.readToolLogs().map(({ toolRequest }) => ({
        name: toolRequest.name,
        success: toolRequest.success,
        args: toolRequest.args,
      }));
      printDebugInfo(rig, result, {
        'Found tool call': foundToolCall,
        'Allowed tools flag': `ShellTool(${tool})`,
        Prompt: prompt,
        'Tool logs': toolLogs,
        Result: result,
      });
    }

    expect(
      foundToolCall,
      'Expected to find a run_shell_command tool call',
    ).toBeTruthy();

    const toolCall = rig
      .readToolLogs()
      .filter(
        (toolCall) => toolCall.toolRequest.name === 'run_shell_command',
      )[0];
    expect(toolCall.toolRequest.success).toBe(true);
  });

  // TODO(#11062): Un-skip this once we can make it reliable by using hard coded
  // model responses.
  it.skip('should combine multiple --allowed-tools flags', async () => {
    await rig.setup('should combine multiple --allowed-tools flags');

    const { tool, command } = getLineCountCommand();
    const prompt =
      `use both ${command} and ls to count the number of lines in files in this ` +
      `directory. Do not pipe these commands into each other, run them separately.`;

    const result = await rig.run({
      args: [
        `--allowed-tools=run_shell_command(${tool})`,
        '--allowed-tools=run_shell_command(ls)',
      ],
      stdin: prompt,
      yolo: false,
    });

    for (const expected in ['ls', tool]) {
      const foundToolCall = await rig.waitForToolCall(
        'run_shell_command',
        15000,
        (args) => args.toLowerCase().includes(`"command": "${expected}`),
      );

      if (!foundToolCall) {
        printDebugInfo(rig, result, {
          'Found tool call': foundToolCall,
        });
      }

      expect(
        foundToolCall,
        `Expected to find a run_shell_command tool call to "${expected}",` +
          ` got ${rig.readToolLogs().join('\n')}`,
      ).toBeTruthy();
    }

    const toolLogs = rig
      .readToolLogs()
      .filter((toolCall) => toolCall.toolRequest.name === 'run_shell_command');
    expect(toolLogs.length, toolLogs.join('\n')).toBeGreaterThanOrEqual(2);
    for (const toolLog of toolLogs) {
      expect(
        toolLog.toolRequest.success,
        `Expected tool call ${toolLog} to succeed`,
      ).toBe(true);
    }
  });

  it('should reject commands not on the allowlist', async () => {
    await rig.setup('should reject commands not on the allowlist', {
      settings: { tools: { core: ['run_shell_command'] } },
    });

    const testFile = rig.createFile('test.txt', 'Disallowed command check\n');
    const allowedCommand = getAllowedListCommand();
    const disallowed = getDisallowedFileReadCommand(testFile);
    const prompt =
      `I am testing the allowed tools configuration. ` +
      `Attempt to run "${disallowed.command}" to read the contents of ${testFile}. ` +
      `If the command fails because it is not permitted, respond with the single word FAIL. ` +
      `If it succeeds, respond with SUCCESS.`;

    const result = await rig.run({
      args: `--allowed-tools=run_shell_command(${allowedCommand})`,
      stdin: prompt,
      yolo: false,
    });

    if (!result.toLowerCase().includes('fail')) {
      printDebugInfo(rig, result, {
        Result: result,
        AllowedCommand: allowedCommand,
        DisallowedCommand: disallowed.command,
      });
    }
    expect(result).toContain('FAIL');

    const foundToolCall = await rig.waitForToolCall(
      'run_shell_command',
      15000,
      (args) => args.toLowerCase().includes(disallowed.tool.toLowerCase()),
    );

    if (!foundToolCall) {
      printDebugInfo(rig, result, {
        'Found tool call': foundToolCall,
        ToolLogs: rig.readToolLogs(),
      });
    }
    expect(foundToolCall).toBe(true);

    const toolLogs = rig
      .readToolLogs()
      .filter((toolLog) => toolLog.toolRequest.name === 'run_shell_command');
    const failureLog = toolLogs.find((toolLog) =>
      toolLog.toolRequest.args
        .toLowerCase()
        .includes(disallowed.tool.toLowerCase()),
    );

    if (!failureLog || failureLog.toolRequest.success) {
      printDebugInfo(rig, result, {
        ToolLogs: toolLogs,
        DisallowedTool: disallowed.tool,
      });
    }

    expect(
      failureLog,
      'Expected failing run_shell_command invocation',
    ).toBeTruthy();
    expect(failureLog!.toolRequest.success).toBe(false);
  });

  // TODO(#11966): Deflake this test and re-enable once the underlying race is resolved.
  it.skip('should reject chained commands when only the first segment is allowlisted in non-interactive mode', async () => {
    await rig.setup(
      'should reject chained commands when only the first segment is allowlisted',
    );

    const chained = getChainedEchoCommand();
    const shellInjection = `!{${chained.command}}`;

    await rig.run({
      args: `--allowed-tools=ShellTool(${chained.allowPattern})`,
      stdin: `${shellInjection}\n`,
      yolo: false,
    });

    // CLI should refuse to execute the chained command without scheduling run_shell_command.
    const toolLogs = rig
      .readToolLogs()
      .filter((log) => log.toolRequest.name === 'run_shell_command');

    // Success is false because tool is in the scheduled state.
    for (const log of toolLogs) {
      expect(log.toolRequest.success).toBe(false);
      expect(log.toolRequest.args).toContain('&&');
    }
  });

  it('should allow all with "ShellTool" and other specific tools', async () => {
    await rig.setup(
      'should allow all with "ShellTool" and other specific tools',
      {
        settings: { tools: { core: ['run_shell_command'] } },
      },
    );

    const { tool } = getLineCountCommand();
    const prompt = `Please run the command "echo test-allow-all" and show me the output`;

    const result = await rig.run({
      args: [
        `--allowed-tools=run_shell_command(${tool})`,
        '--allowed-tools=run_shell_command',
      ],
      stdin: prompt,
      yolo: false,
    });

    const foundToolCall = await rig.waitForToolCall('run_shell_command', 15000);

    if (!foundToolCall || !result.includes('test-allow-all')) {
      printDebugInfo(rig, result, {
        'Found tool call': foundToolCall,
        Result: result,
      });
    }

    expect(
      foundToolCall,
      'Expected to find a run_shell_command tool call',
    ).toBeTruthy();

    const toolCall = rig
      .readToolLogs()
      .filter(
        (toolCall) => toolCall.toolRequest.name === 'run_shell_command',
      )[0];
    expect(toolCall.toolRequest.success).toBe(true);

    // Validate model output - will throw if no output, warn if missing expected content
    validateModelOutput(
      result,
      'test-allow-all',
      'Shell command stdin allow all',
    );
  });

  it('should propagate environment variables to the child process', async () => {
    await rig.setup('should propagate environment variables', {
      settings: { tools: { core: ['run_shell_command'] } },
    });

    const varName = 'GEMINI_CLI_TEST_VAR';
    const varValue = `test-value-${Math.random().toString(36).substring(7)}`;
    process.env[varName] = varValue;

    try {
      const prompt = `Use echo to learn the value of the environment variable named ${varName} and tell me what it is.`;
      const result = await rig.run({ args: prompt });

      const foundToolCall = await rig.waitForToolCall('run_shell_command');

      if (!foundToolCall || !result.includes(varValue)) {
        printDebugInfo(rig, result, {
          'Found tool call': foundToolCall,
          'Contains varValue': result.includes(varValue),
        });
      }

      expect(
        foundToolCall,
        'Expected to find a run_shell_command tool call',
      ).toBeTruthy();
      validateModelOutput(result, varValue, 'Env var propagation test');
      expect(result).toContain(varValue);
    } finally {
      delete process.env[varName];
    }
  });

  it.skip('should run a platform-specific file listing command', async () => {
    await rig.setup('should run platform-specific file listing');
    const fileName = `test-file-${Math.random().toString(36).substring(7)}.txt`;
    rig.createFile(fileName, 'test content');

    const prompt = `Run a shell command to list the files in the current directory and tell me what they are.`;
    const result = await rig.run({ args: prompt });

    const foundToolCall = await rig.waitForToolCall('run_shell_command');

    // Debugging info
    if (!foundToolCall || !result.includes(fileName)) {
      printDebugInfo(rig, result, {
        'Found tool call': foundToolCall,
        'Contains fileName': result.includes(fileName),
      });
    }

    expect(
      foundToolCall,
      'Expected to find a run_shell_command tool call',
    ).toBeTruthy();

    validateModelOutput(result, fileName, 'Platform-specific listing test');
    expect(result).toContain(fileName);
  });

  it('rejects invalid shell expressions', async () => {
    await rig.setup('rejects invalid shell expressions', {
      settings: { tools: { core: ['run_shell_command'] } },
    });
    const invalidCommand = getInvalidCommand();
    const result = await rig.run({
      args: `I am testing the error handling of the run_shell_command tool. Please attempt to run the following command, which I know has invalid syntax: \`${invalidCommand}\`. If the command fails as expected, please return the word FAIL, otherwise return the word SUCCESS.`,
    });
    expect(result).toContain('FAIL');

    const escapedInvalidCommand = JSON.stringify(invalidCommand).slice(1, -1);
    const foundToolCall = await rig.waitForToolCall(
      'run_shell_command',
      15000,
      (args) =>
        args.toLowerCase().includes(escapedInvalidCommand.toLowerCase()),
    );

    if (!foundToolCall) {
      printDebugInfo(rig, result, {
        'Found tool call': foundToolCall,
        EscapedCommand: escapedInvalidCommand,
        ToolLogs: rig.readToolLogs(),
      });
    }
    expect(foundToolCall).toBe(true);

    const toolLogs = rig
      .readToolLogs()
      .filter((toolLog) => toolLog.toolRequest.name === 'run_shell_command');
    const failureLog = toolLogs.find((toolLog) =>
      toolLog.toolRequest.args
        .toLowerCase()
        .includes(escapedInvalidCommand.toLowerCase()),
    );

    if (!failureLog || failureLog.toolRequest.success) {
      printDebugInfo(rig, result, {
        ToolLogs: toolLogs,
        EscapedCommand: escapedInvalidCommand,
      });
    }

    expect(
      failureLog,
      'Expected failing run_shell_command invocation for invalid syntax',
    ).toBeTruthy();
    expect(failureLog!.toolRequest.success).toBe(false);
  });
});
```

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

```typescript
/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { LSTool } from './ls.js';
import type { Config } from '../config/config.js';
import { FileDiscoveryService } from '../services/fileDiscoveryService.js';
import { ToolErrorType } from './tool-error.js';
import { WorkspaceContext } from '../utils/workspaceContext.js';

describe('LSTool', () => {
  let lsTool: LSTool;
  let tempRootDir: string;
  let tempSecondaryDir: string;
  let mockConfig: Config;
  const abortSignal = new AbortController().signal;

  beforeEach(async () => {
    const realTmp = await fs.realpath(os.tmpdir());
    tempRootDir = await fs.mkdtemp(path.join(realTmp, 'ls-tool-root-'));
    tempSecondaryDir = await fs.mkdtemp(
      path.join(realTmp, 'ls-tool-secondary-'),
    );

    mockConfig = {
      getTargetDir: () => tempRootDir,
      getWorkspaceContext: () =>
        new WorkspaceContext(tempRootDir, [tempSecondaryDir]),
      getFileService: () => new FileDiscoveryService(tempRootDir),
      getFileFilteringOptions: () => ({
        respectGitIgnore: true,
        respectGeminiIgnore: true,
      }),
    } as unknown as Config;

    lsTool = new LSTool(mockConfig);
  });

  afterEach(async () => {
    await fs.rm(tempRootDir, { recursive: true, force: true });
    await fs.rm(tempSecondaryDir, { recursive: true, force: true });
  });

  describe('parameter validation', () => {
    it('should accept valid absolute paths within workspace', async () => {
      const testPath = path.join(tempRootDir, 'src');
      await fs.mkdir(testPath);

      const invocation = lsTool.build({ dir_path: testPath });

      expect(invocation).toBeDefined();
    });

    it('should accept relative paths', async () => {
      const testPath = path.join(tempRootDir, 'src');
      await fs.mkdir(testPath);

      const relativePath = path.relative(tempRootDir, testPath);
      const invocation = lsTool.build({ dir_path: relativePath });

      expect(invocation).toBeDefined();
    });

    it('should reject paths outside workspace with clear error message', () => {
      expect(() => lsTool.build({ dir_path: '/etc/passwd' })).toThrow(
        `Path must be within one of the workspace directories: ${tempRootDir}, ${tempSecondaryDir}`,
      );
    });

    it('should accept paths in secondary workspace directory', async () => {
      const testPath = path.join(tempSecondaryDir, 'lib');
      await fs.mkdir(testPath);

      const invocation = lsTool.build({ dir_path: testPath });

      expect(invocation).toBeDefined();
    });
  });

  describe('execute', () => {
    it('should list files in a directory', async () => {
      await fs.writeFile(path.join(tempRootDir, 'file1.txt'), 'content1');
      await fs.mkdir(path.join(tempRootDir, 'subdir'));
      await fs.writeFile(
        path.join(tempSecondaryDir, 'secondary-file.txt'),
        'secondary',
      );

      const invocation = lsTool.build({ dir_path: tempRootDir });
      const result = await invocation.execute(abortSignal);

      expect(result.llmContent).toContain('[DIR] subdir');
      expect(result.llmContent).toContain('file1.txt');
      expect(result.returnDisplay).toBe('Listed 2 item(s).');
    });

    it('should list files from secondary workspace directory', async () => {
      await fs.writeFile(path.join(tempRootDir, 'file1.txt'), 'content1');
      await fs.mkdir(path.join(tempRootDir, 'subdir'));
      await fs.writeFile(
        path.join(tempSecondaryDir, 'secondary-file.txt'),
        'secondary',
      );

      const invocation = lsTool.build({ dir_path: tempSecondaryDir });
      const result = await invocation.execute(abortSignal);

      expect(result.llmContent).toContain('secondary-file.txt');
      expect(result.returnDisplay).toBe('Listed 1 item(s).');
    });

    it('should handle empty directories', async () => {
      const emptyDir = path.join(tempRootDir, 'empty');
      await fs.mkdir(emptyDir);
      const invocation = lsTool.build({ dir_path: emptyDir });
      const result = await invocation.execute(abortSignal);

      expect(result.llmContent).toBe(`Directory ${emptyDir} is empty.`);
      expect(result.returnDisplay).toBe('Directory is empty.');
    });

    it('should respect ignore patterns', async () => {
      await fs.writeFile(path.join(tempRootDir, 'file1.txt'), 'content1');
      await fs.writeFile(path.join(tempRootDir, 'file2.log'), 'content1');

      const invocation = lsTool.build({
        dir_path: tempRootDir,
        ignore: ['*.log'],
      });
      const result = await invocation.execute(abortSignal);

      expect(result.llmContent).toContain('file1.txt');
      expect(result.llmContent).not.toContain('file2.log');
      expect(result.returnDisplay).toBe('Listed 1 item(s).');
    });

    it('should respect gitignore patterns', async () => {
      await fs.writeFile(path.join(tempRootDir, 'file1.txt'), 'content1');
      await fs.writeFile(path.join(tempRootDir, 'file2.log'), 'content1');
      await fs.writeFile(path.join(tempRootDir, '.git'), '');
      await fs.writeFile(path.join(tempRootDir, '.gitignore'), '*.log');
      const invocation = lsTool.build({ dir_path: tempRootDir });
      const result = await invocation.execute(abortSignal);

      expect(result.llmContent).toContain('file1.txt');
      expect(result.llmContent).not.toContain('file2.log');
      // .git is always ignored by default.
      expect(result.returnDisplay).toBe('Listed 2 item(s). (2 ignored)');
    });

    it('should respect geminiignore patterns', async () => {
      await fs.writeFile(path.join(tempRootDir, 'file1.txt'), 'content1');
      await fs.writeFile(path.join(tempRootDir, 'file2.log'), 'content1');
      await fs.writeFile(path.join(tempRootDir, '.geminiignore'), '*.log');
      const invocation = lsTool.build({ dir_path: tempRootDir });
      const result = await invocation.execute(abortSignal);

      expect(result.llmContent).toContain('file1.txt');
      expect(result.llmContent).not.toContain('file2.log');
      expect(result.returnDisplay).toBe('Listed 2 item(s). (1 ignored)');
    });

    it('should handle non-directory paths', async () => {
      const testPath = path.join(tempRootDir, 'file1.txt');
      await fs.writeFile(testPath, 'content1');

      const invocation = lsTool.build({ dir_path: testPath });
      const result = await invocation.execute(abortSignal);

      expect(result.llmContent).toContain('Path is not a directory');
      expect(result.returnDisplay).toBe('Error: Path is not a directory.');
      expect(result.error?.type).toBe(ToolErrorType.PATH_IS_NOT_A_DIRECTORY);
    });

    it('should handle non-existent paths', async () => {
      const testPath = path.join(tempRootDir, 'does-not-exist');
      const invocation = lsTool.build({ dir_path: testPath });
      const result = await invocation.execute(abortSignal);

      expect(result.llmContent).toContain('Error listing directory');
      expect(result.returnDisplay).toBe('Error: Failed to list directory.');
      expect(result.error?.type).toBe(ToolErrorType.LS_EXECUTION_ERROR);
    });

    it('should sort directories first, then files alphabetically', async () => {
      await fs.writeFile(path.join(tempRootDir, 'a-file.txt'), 'content1');
      await fs.writeFile(path.join(tempRootDir, 'b-file.txt'), 'content1');
      await fs.mkdir(path.join(tempRootDir, 'x-dir'));
      await fs.mkdir(path.join(tempRootDir, 'y-dir'));

      const invocation = lsTool.build({ dir_path: tempRootDir });
      const result = await invocation.execute(abortSignal);

      const lines = (
        typeof result.llmContent === 'string' ? result.llmContent : ''
      )
        .split('\n')
        .filter(Boolean);
      const entries = lines.slice(1); // Skip header

      expect(entries[0]).toBe('[DIR] x-dir');
      expect(entries[1]).toBe('[DIR] y-dir');
      expect(entries[2]).toBe('a-file.txt');
      expect(entries[3]).toBe('b-file.txt');
    });

    it('should handle permission errors gracefully', async () => {
      const restrictedDir = path.join(tempRootDir, 'restricted');
      await fs.mkdir(restrictedDir);

      // To simulate a permission error in a cross-platform way,
      // we mock fs.readdir to throw an error.
      const error = new Error('EACCES: permission denied');
      vi.spyOn(fs, 'readdir').mockRejectedValueOnce(error);

      const invocation = lsTool.build({ dir_path: restrictedDir });
      const result = await invocation.execute(abortSignal);

      expect(result.llmContent).toContain('Error listing directory');
      expect(result.llmContent).toContain('permission denied');
      expect(result.returnDisplay).toBe('Error: Failed to list directory.');
      expect(result.error?.type).toBe(ToolErrorType.LS_EXECUTION_ERROR);
    });

    it('should handle errors accessing individual files during listing', async () => {
      await fs.writeFile(path.join(tempRootDir, 'file1.txt'), 'content1');
      const problematicFile = path.join(tempRootDir, 'problematic.txt');
      await fs.writeFile(problematicFile, 'content2');

      // To simulate an error on a single file in a cross-platform way,
      // we mock fs.stat to throw for a specific file. This avoids
      // platform-specific behavior with things like dangling symlinks.
      const originalStat = fs.stat;
      const statSpy = vi.spyOn(fs, 'stat').mockImplementation(async (p) => {
        if (p.toString() === problematicFile) {
          throw new Error('Simulated stat error');
        }
        return originalStat(p);
      });

      const invocation = lsTool.build({ dir_path: tempRootDir });
      const result = await invocation.execute(abortSignal);

      // Should still list the other files
      expect(result.llmContent).toContain('file1.txt');
      expect(result.llmContent).not.toContain('problematic.txt');
      expect(result.returnDisplay).toBe('Listed 1 item(s).');

      statSpy.mockRestore();
    });
  });

  describe('getDescription', () => {
    it('should return shortened relative path', () => {
      const deeplyNestedDir = path.join(tempRootDir, 'deeply', 'nested');
      const params = {
        dir_path: path.join(deeplyNestedDir, 'directory'),
      };
      const invocation = lsTool.build(params);
      const description = invocation.getDescription();
      expect(description).toBe(path.join('deeply', 'nested', 'directory'));
    });

    it('should handle paths in secondary workspace', () => {
      const params = {
        dir_path: path.join(tempSecondaryDir, 'lib'),
      };
      const invocation = lsTool.build(params);
      const description = invocation.getDescription();
      const expected = path.relative(tempRootDir, params.dir_path);
      expect(description).toBe(expected);
    });
  });

  describe('workspace boundary validation', () => {
    it('should accept paths in primary workspace directory', async () => {
      const testPath = path.join(tempRootDir, 'src');
      await fs.mkdir(testPath);
      const params = { dir_path: testPath };
      expect(lsTool.build(params)).toBeDefined();
    });

    it('should accept paths in secondary workspace directory', async () => {
      const testPath = path.join(tempSecondaryDir, 'lib');
      await fs.mkdir(testPath);
      const params = { dir_path: testPath };
      expect(lsTool.build(params)).toBeDefined();
    });

    it('should reject paths outside all workspace directories', () => {
      const params = { dir_path: '/etc/passwd' };
      expect(() => lsTool.build(params)).toThrow(
        'Path must be within one of the workspace directories',
      );
    });

    it('should list files from secondary workspace directory', async () => {
      await fs.writeFile(
        path.join(tempSecondaryDir, 'secondary-file.txt'),
        'secondary',
      );

      const invocation = lsTool.build({ dir_path: tempSecondaryDir });
      const result = await invocation.execute(abortSignal);

      expect(result.llmContent).toContain('secondary-file.txt');
      expect(result.returnDisplay).toBe('Listed 1 item(s).');
    });
  });
});

````

- **Integration:** `integration-tests/list_directory.test.ts`

```typescript
/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import { describe, it, beforeEach, afterEach } from 'vitest';
import {
  TestRig,
  poll,
  printDebugInfo,
  validateModelOutput,
} from './test-helper.js';
import { existsSync } from 'node:fs';
import { join } from 'node:path';

describe('list_directory', () => {
  let rig: TestRig;

  beforeEach(() => {
    rig = new TestRig();
  });

  afterEach(async () => await rig.cleanup());

  it('should be able to list a directory', async () => {
    await rig.setup('should be able to list a directory', {
      settings: { tools: { core: ['list_directory'] } },
    });
    rig.createFile('file1.txt', 'file 1 content');
    rig.mkdir('subdir');
    rig.sync();

    // Poll for filesystem changes to propagate in containers
    await poll(
      () => {
        // Check if the files exist in the test directory
        const file1Path = join(rig.testDir!, 'file1.txt');
        const subdirPath = join(rig.testDir!, 'subdir');
        return existsSync(file1Path) && existsSync(subdirPath);
      },
      1000, // 1 second max wait
      50, // check every 50ms
    );

    const prompt = `Can you list the files in the current directory.`;

    const result = await rig.run({ args: prompt });

    try {
      await rig.expectToolCallSuccess(['list_directory']);
    } catch (e) {
      // Add debugging information
      if (!result.includes('file1.txt') || !result.includes('subdir')) {
        const allTools = printDebugInfo(rig, result, {
          'Found tool call': false,
          'Contains file1.txt': result.includes('file1.txt'),
          'Contains subdir': result.includes('subdir'),
        });

        console.error(
          'List directory calls:',
          allTools
            .filter((t) => t.toolRequest.name === 'list_directory')
            .map((t) => t.toolRequest.args),
        );
      }
      throw e;
    }

    // Validate model output - will throw if no output, warn if missing expected content
    validateModelOutput(result, ['file1.txt', 'subdir'], 'List directory test');
  });
});
```

````typescript
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

```typescript
/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { ReadFileToolParams } from './read-file.js';
import { ReadFileTool } from './read-file.js';
import { ToolErrorType } from './tool-error.js';
import path from 'node:path';
import os from 'node:os';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import type { Config } from '../config/config.js';
import { FileDiscoveryService } from '../services/fileDiscoveryService.js';
import { StandardFileSystemService } from '../services/fileSystemService.js';
import { createMockWorkspaceContext } from '../test-utils/mockWorkspaceContext.js';
import { WorkspaceContext } from '../utils/workspaceContext.js';

vi.mock('../telemetry/loggers.js', () => ({
  logFileOperation: vi.fn(),
}));

describe('ReadFileTool', () => {
  let tempRootDir: string;
  let tool: ReadFileTool;
  const abortSignal = new AbortController().signal;

  beforeEach(async () => {
    // Create a unique temporary root directory for each test run
    const realTmp = await fsp.realpath(os.tmpdir());
    tempRootDir = await fsp.mkdtemp(path.join(realTmp, 'read-file-tool-root-'));

    const mockConfigInstance = {
      getFileService: () => new FileDiscoveryService(tempRootDir),
      getFileSystemService: () => new StandardFileSystemService(),
      getTargetDir: () => tempRootDir,
      getWorkspaceContext: () => createMockWorkspaceContext(tempRootDir),
      getFileFilteringOptions: () => ({
        respectGitIgnore: true,
        respectGeminiIgnore: true,
      }),
      storage: {
        getProjectTempDir: () => path.join(tempRootDir, '.temp'),
      },
      isInteractive: () => false,
    } as unknown as Config;
    tool = new ReadFileTool(mockConfigInstance);
  });

  afterEach(async () => {
    // Clean up the temporary root directory
    if (fs.existsSync(tempRootDir)) {
      await fsp.rm(tempRootDir, { recursive: true, force: true });
    }
  });

  describe('build', () => {
    it('should return an invocation for valid params (absolute path within root)', () => {
      const params: ReadFileToolParams = {
        file_path: path.join(tempRootDir, 'test.txt'),
      };
      const result = tool.build(params);
      expect(typeof result).not.toBe('string');
    });

    it('should return an invocation for valid params (relative path within root)', () => {
      const params: ReadFileToolParams = {
        file_path: 'test.txt',
      };
      const result = tool.build(params);
      expect(typeof result).not.toBe('string');
      const invocation = result;
      expect(invocation.toolLocations()[0].path).toBe(
        path.join(tempRootDir, 'test.txt'),
      );
    });

    it('should throw error if path is outside root', () => {
      const params: ReadFileToolParams = {
        file_path: '/outside/root.txt',
      };
      expect(() => tool.build(params)).toThrow(
        /File path must be within one of the workspace directories/,
      );
    });

    it('should allow access to files in project temp directory', () => {
      const tempDir = path.join(tempRootDir, '.temp');
      const params: ReadFileToolParams = {
        file_path: path.join(tempDir, 'temp-file.txt'),
      };
      const result = tool.build(params);
      expect(typeof result).not.toBe('string');
    });

    it('should show temp directory in error message when path is outside workspace and temp dir', () => {
      const params: ReadFileToolParams = {
        file_path: '/completely/outside/path.txt',
      };
      expect(() => tool.build(params)).toThrow(
        /File path must be within one of the workspace directories.*or within the project temp directory/,
      );
    });

    it('should throw error if path is empty', () => {
      const params: ReadFileToolParams = {
        file_path: '',
      };
      expect(() => tool.build(params)).toThrow(
        /The 'file_path' parameter must be non-empty./,
      );
    });

    it('should throw error if offset is negative', () => {
      const params: ReadFileToolParams = {
        file_path: path.join(tempRootDir, 'test.txt'),
        offset: -1,
      };
      expect(() => tool.build(params)).toThrow(
        'Offset must be a non-negative number',
      );
    });

    it('should throw error if limit is zero or negative', () => {
      const params: ReadFileToolParams = {
        file_path: path.join(tempRootDir, 'test.txt'),
        limit: 0,
      };
      expect(() => tool.build(params)).toThrow(
        'Limit must be a positive number',
      );
    });
  });

  describe('getDescription', () => {
    it('should return relative path without limit/offset', () => {
      const subDir = path.join(tempRootDir, 'sub', 'dir');
      const params: ReadFileToolParams = {
        file_path: path.join(subDir, 'file.txt'),
      };
      const invocation = tool.build(params);
      expect(typeof invocation).not.toBe('string');
      expect(invocation.getDescription()).toBe(
        path.join('sub', 'dir', 'file.txt'),
      );
    });

    it('should return shortened path when file path is deep', () => {
      const deepPath = path.join(
        tempRootDir,
        'very',
        'deep',
        'directory',
        'structure',
        'that',
        'exceeds',
        'the',
        'normal',
        'limit',
        'file.txt',
      );
      const params: ReadFileToolParams = { file_path: deepPath };
      const invocation = tool.build(params);
      expect(typeof invocation).not.toBe('string');
      const desc = invocation.getDescription();
      expect(desc).toContain('...');
      expect(desc).toContain('file.txt');
    });

    it('should handle non-normalized file paths correctly', () => {
      const subDir = path.join(tempRootDir, 'sub', 'dir');
      const params: ReadFileToolParams = {
        file_path: path.join(subDir, '..', 'dir', 'file.txt'),
      };
      const invocation = tool.build(params);
      expect(typeof invocation).not.toBe('string');
      expect(invocation.getDescription()).toBe(
        path.join('sub', 'dir', 'file.txt'),
      );
    });

    it('should return . if path is the root directory', () => {
      const params: ReadFileToolParams = { file_path: tempRootDir };
      const invocation = tool.build(params);
      expect(typeof invocation).not.toBe('string');
      expect(invocation.getDescription()).toBe('.');
    });
  });

  describe('execute', () => {
    it('should successfully read a file with a relative path', async () => {
      const filePath = path.join(tempRootDir, 'textfile.txt');
      const fileContent = 'This is a test file.';
      await fsp.writeFile(filePath, fileContent, 'utf-8');
      const params: ReadFileToolParams = { file_path: 'textfile.txt' };
      const invocation = tool.build(params);

      expect(await invocation.execute(abortSignal)).toEqual({
        llmContent: fileContent,
        returnDisplay: '',
      });
    });

    it('should return error if file does not exist', async () => {
      const filePath = path.join(tempRootDir, 'nonexistent.txt');
      const params: ReadFileToolParams = { file_path: filePath };
      const invocation = tool.build(params);

      const result = await invocation.execute(abortSignal);
      expect(result).toEqual({
        llmContent:
          'Could not read file because no file was found at the specified path.',
        returnDisplay: 'File not found.',
        error: {
          message: `File not found: ${filePath}`,
          type: ToolErrorType.FILE_NOT_FOUND,
        },
      });
    });

    it('should return success result for a text file', async () => {
      const filePath = path.join(tempRootDir, 'textfile.txt');
      const fileContent = 'This is a test file.';
      await fsp.writeFile(filePath, fileContent, 'utf-8');
      const params: ReadFileToolParams = { file_path: filePath };
      const invocation = tool.build(params);

      expect(await invocation.execute(abortSignal)).toEqual({
        llmContent: fileContent,
        returnDisplay: '',
      });
    });

    it('should return error if path is a directory', async () => {
      const dirPath = path.join(tempRootDir, 'directory');
      await fsp.mkdir(dirPath);
      const params: ReadFileToolParams = { file_path: dirPath };
      const invocation = tool.build(params);

      const result = await invocation.execute(abortSignal);
      expect(result).toEqual({
        llmContent:
          'Could not read file because the provided path is a directory, not a file.',
        returnDisplay: 'Path is a directory.',
        error: {
          message: `Path is a directory, not a file: ${dirPath}`,
          type: ToolErrorType.TARGET_IS_DIRECTORY,
        },
      });
    });

    it('should return error for a file that is too large', async () => {
      const filePath = path.join(tempRootDir, 'largefile.txt');
      // 21MB of content exceeds 20MB limit
      const largeContent = 'x'.repeat(21 * 1024 * 1024);
      await fsp.writeFile(filePath, largeContent, 'utf-8');
      const params: ReadFileToolParams = { file_path: filePath };
      const invocation = tool.build(params);

      const result = await invocation.execute(abortSignal);
      expect(result).toHaveProperty('error');
      expect(result.error?.type).toBe(ToolErrorType.FILE_TOO_LARGE);
      expect(result.error?.message).toContain(
        'File size exceeds the 20MB limit',
      );
    });

    it('should handle text file with lines exceeding maximum length', async () => {
      const filePath = path.join(tempRootDir, 'longlines.txt');
      const longLine = 'a'.repeat(2500); // Exceeds MAX_LINE_LENGTH_TEXT_FILE (2000)
      const fileContent = `Short line\n${longLine}\nAnother short line`;
      await fsp.writeFile(filePath, fileContent, 'utf-8');
      const params: ReadFileToolParams = { file_path: filePath };
      const invocation = tool.build(params);

      const result = await invocation.execute(abortSignal);
      expect(result.llmContent).toContain(
        'IMPORTANT: The file content has been truncated',
      );
      expect(result.llmContent).toContain('--- FILE CONTENT (truncated) ---');
      expect(result.returnDisplay).toContain('some lines were shortened');
    });

    it('should handle image file and return appropriate content', async () => {
      const imagePath = path.join(tempRootDir, 'image.png');
      // Minimal PNG header
      const pngHeader = Buffer.from([
        0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
      ]);
      await fsp.writeFile(imagePath, pngHeader);
      const params: ReadFileToolParams = { file_path: imagePath };
      const invocation = tool.build(params);

      const result = await invocation.execute(abortSignal);
      expect(result.llmContent).toEqual({
        inlineData: {
          data: pngHeader.toString('base64'),
          mimeType: 'image/png',
        },
      });
      expect(result.returnDisplay).toBe('Read image file: image.png');
    });

    it('should handle PDF file and return appropriate content', async () => {
      const pdfPath = path.join(tempRootDir, 'document.pdf');
      // Minimal PDF header
      const pdfHeader = Buffer.from('%PDF-1.4');
      await fsp.writeFile(pdfPath, pdfHeader);
      const params: ReadFileToolParams = { file_path: pdfPath };
      const invocation = tool.build(params);

      const result = await invocation.execute(abortSignal);
      expect(result.llmContent).toEqual({
        inlineData: {
          data: pdfHeader.toString('base64'),
          mimeType: 'application/pdf',
        },
      });
      expect(result.returnDisplay).toBe('Read pdf file: document.pdf');
    });

    it('should handle binary file and skip content', async () => {
      const binPath = path.join(tempRootDir, 'binary.bin');
      // Binary data with null bytes
      const binaryData = Buffer.from([0x00, 0xff, 0x00, 0xff]);
      await fsp.writeFile(binPath, binaryData);
      const params: ReadFileToolParams = { file_path: binPath };
      const invocation = tool.build(params);

      const result = await invocation.execute(abortSignal);
      expect(result.llmContent).toBe(
        'Cannot display content of binary file: binary.bin',
      );
      expect(result.returnDisplay).toBe('Skipped binary file: binary.bin');
    });

    it('should handle SVG file as text', async () => {
      const svgPath = path.join(tempRootDir, 'image.svg');
      const svgContent = '<svg><circle cx="50" cy="50" r="40"/></svg>';
      await fsp.writeFile(svgPath, svgContent, 'utf-8');
      const params: ReadFileToolParams = { file_path: svgPath };
      const invocation = tool.build(params);

      const result = await invocation.execute(abortSignal);
      expect(result.llmContent).toBe(svgContent);
      expect(result.returnDisplay).toBe('Read SVG as text: image.svg');
    });

    it('should handle large SVG file', async () => {
      const svgPath = path.join(tempRootDir, 'large.svg');
      // Create SVG content larger than 1MB
      const largeContent = '<svg>' + 'x'.repeat(1024 * 1024 + 1) + '</svg>';
      await fsp.writeFile(svgPath, largeContent, 'utf-8');
      const params: ReadFileToolParams = { file_path: svgPath };
      const invocation = tool.build(params);

      const result = await invocation.execute(abortSignal);
      expect(result.llmContent).toBe(
        'Cannot display content of SVG file larger than 1MB: large.svg',
      );
      expect(result.returnDisplay).toBe(
        'Skipped large SVG file (>1MB): large.svg',
      );
    });

    it('should handle empty file', async () => {
      const emptyPath = path.join(tempRootDir, 'empty.txt');
      await fsp.writeFile(emptyPath, '', 'utf-8');
      const params: ReadFileToolParams = { file_path: emptyPath };
      const invocation = tool.build(params);

      const result = await invocation.execute(abortSignal);
      expect(result.llmContent).toBe('');
      expect(result.returnDisplay).toBe('');
    });

    it('should support offset and limit for text files', async () => {
      const filePath = path.join(tempRootDir, 'paginated.txt');
      const lines = Array.from({ length: 20 }, (_, i) => `Line ${i + 1}`);
      const fileContent = lines.join('\n');
      await fsp.writeFile(filePath, fileContent, 'utf-8');

      const params: ReadFileToolParams = {
        file_path: filePath,
        offset: 5, // Start from line 6
        limit: 3,
      };
      const invocation = tool.build(params);

      const result = await invocation.execute(abortSignal);
      expect(result.llmContent).toContain(
        'IMPORTANT: The file content has been truncated',
      );
      expect(result.llmContent).toContain(
        'Status: Showing lines 6-8 of 20 total lines',
      );
      expect(result.llmContent).toContain('Line 6');
      expect(result.llmContent).toContain('Line 7');
      expect(result.llmContent).toContain('Line 8');
      expect(result.returnDisplay).toBe(
        'Read lines 6-8 of 20 from paginated.txt',
      );
    });

    it('should successfully read files from project temp directory', async () => {
      const tempDir = path.join(tempRootDir, '.temp');
      await fsp.mkdir(tempDir, { recursive: true });
      const tempFilePath = path.join(tempDir, 'temp-output.txt');
      const tempFileContent = 'This is temporary output content';
      await fsp.writeFile(tempFilePath, tempFileContent, 'utf-8');

      const params: ReadFileToolParams = { file_path: tempFilePath };
      const invocation = tool.build(params);

      const result = await invocation.execute(abortSignal);
      expect(result.llmContent).toBe(tempFileContent);
      expect(result.returnDisplay).toBe('');
    });

    describe('with .geminiignore', () => {
      beforeEach(async () => {
        await fsp.writeFile(
          path.join(tempRootDir, '.geminiignore'),
          ['foo.*', 'ignored/'].join('\n'),
        );
        const mockConfigInstance = {
          getFileService: () => new FileDiscoveryService(tempRootDir),
          getFileSystemService: () => new StandardFileSystemService(),
          getTargetDir: () => tempRootDir,
          getWorkspaceContext: () => new WorkspaceContext(tempRootDir),
          getFileFilteringOptions: () => ({
            respectGitIgnore: true,
            respectGeminiIgnore: true,
          }),
          storage: {
            getProjectTempDir: () => path.join(tempRootDir, '.temp'),
          },
        } as unknown as Config;
        tool = new ReadFileTool(mockConfigInstance);
      });

      it('should throw error if path is ignored by a .geminiignore pattern', async () => {
        const ignoredFilePath = path.join(tempRootDir, 'foo.bar');
        await fsp.writeFile(ignoredFilePath, 'content', 'utf-8');
        const params: ReadFileToolParams = {
          file_path: ignoredFilePath,
        };
        const expectedError = `File path '${ignoredFilePath}' is ignored by configured ignore patterns.`;
        expect(() => tool.build(params)).toThrow(expectedError);
      });

      it('should throw error if file is in an ignored directory', async () => {
        const ignoredDirPath = path.join(tempRootDir, 'ignored');
        await fsp.mkdir(ignoredDirPath, { recursive: true });
        const ignoredFilePath = path.join(ignoredDirPath, 'file.txt');
        await fsp.writeFile(ignoredFilePath, 'content', 'utf-8');
        const params: ReadFileToolParams = {
          file_path: ignoredFilePath,
        };
        const expectedError = `File path '${ignoredFilePath}' is ignored by configured ignore patterns.`;
        expect(() => tool.build(params)).toThrow(expectedError);
      });

      it('should allow reading non-ignored files', async () => {
        const allowedFilePath = path.join(tempRootDir, 'allowed.txt');
        await fsp.writeFile(allowedFilePath, 'content', 'utf-8');
        const params: ReadFileToolParams = {
          file_path: allowedFilePath,
        };
        const invocation = tool.build(params);
        expect(typeof invocation).not.toBe('string');
      });
    });
  });
});

````

- **Integration:** `integration-tests/file-system.test.ts`

```typescript
/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { existsSync } from 'node:fs';
import * as path from 'node:path';
import { TestRig, printDebugInfo, validateModelOutput } from './test-helper.js';

describe('file-system', () => {
  let rig: TestRig;

  beforeEach(() => {
    rig = new TestRig();
  });

  afterEach(async () => await rig.cleanup());

  it('should be able to read a file', async () => {
    await rig.setup('should be able to read a file', {
      settings: { tools: { core: ['read_file'] } },
    });
    rig.createFile('test.txt', 'hello world');

    const result = await rig.run({
      args: `read the file test.txt and show me its contents`,
    });

    const foundToolCall = await rig.waitForToolCall('read_file');

    // Add debugging information
    if (!foundToolCall || !result.includes('hello world')) {
      printDebugInfo(rig, result, {
        'Found tool call': foundToolCall,
        'Contains hello world': result.includes('hello world'),
      });
    }

    expect(
      foundToolCall,
      'Expected to find a read_file tool call',
    ).toBeTruthy();

    // Validate model output - will throw if no output, warn if missing expected content
    validateModelOutput(result, 'hello world', 'File read test');
  });

  it('should be able to write a file', async () => {
    await rig.setup('should be able to write a file', {
      settings: { tools: { core: ['write_file', 'replace', 'read_file'] } },
    });
    rig.createFile('test.txt', '');

    const result = await rig.run({
      args: `edit test.txt to have a hello world message`,
    });

    // Accept multiple valid tools for editing files
    const foundToolCall = await rig.waitForAnyToolCall([
      'write_file',
      'edit',
      'replace',
    ]);

    // Add debugging information
    if (!foundToolCall) {
      printDebugInfo(rig, result);
    }

    expect(
      foundToolCall,
      'Expected to find a write_file, edit, or replace tool call',
    ).toBeTruthy();

    // Validate model output - will throw if no output
    validateModelOutput(result, null, 'File write test');

    const fileContent = rig.readFile('test.txt');

    // Add debugging for file content
    if (!fileContent.toLowerCase().includes('hello')) {
      const writeCalls = rig
        .readToolLogs()
        .filter((t) => t.toolRequest.name === 'write_file')
        .map((t) => t.toolRequest.args);

      printDebugInfo(rig, result, {
        'File content mismatch': true,
        'Expected to contain': 'hello',
        'Actual content': fileContent,
        'Write tool calls': JSON.stringify(writeCalls),
      });
    }

    expect(
      fileContent.toLowerCase().includes('hello'),
      'Expected file to contain hello',
    ).toBeTruthy();

    // Log success info if verbose
    if (process.env['VERBOSE'] === 'true') {
      console.log('File written successfully with hello message.');
    }
  });

  it('should correctly handle file paths with spaces', async () => {
    await rig.setup('should correctly handle file paths with spaces', {
      settings: { tools: { core: ['write_file', 'read_file'] } },
    });
    const fileName = 'my test file.txt';

    const result = await rig.run({
      args: `write "hello" to "${fileName}" and then stop. Do not perform any other actions.`,
    });

    const foundToolCall = await rig.waitForToolCall('write_file');
    if (!foundToolCall) {
      printDebugInfo(rig, result);
    }
    expect(
      foundToolCall,
      'Expected to find a write_file tool call',
    ).toBeTruthy();

    const newFileContent = rig.readFile(fileName);
    expect(newFileContent).toBe('hello');
  });

  it('should perform a read-then-write sequence', async () => {
    await rig.setup('should perform a read-then-write sequence', {
      settings: { tools: { core: ['read_file', 'replace', 'write_file'] } },
    });
    const fileName = 'version.txt';
    rig.createFile(fileName, '1.0.0');

    const prompt = `Read the version from ${fileName} and write the next version 1.0.1 back to the file.`;
    const result = await rig.run({ args: prompt });

    await rig.waitForTelemetryReady();
    const toolLogs = rig.readToolLogs();

    const readCall = toolLogs.find(
      (log) => log.toolRequest.name === 'read_file',
    );
    const writeCall = toolLogs.find(
      (log) =>
        log.toolRequest.name === 'write_file' ||
        log.toolRequest.name === 'replace',
    );

    if (!readCall || !writeCall) {
      printDebugInfo(rig, result, { readCall, writeCall });
    }

    expect(readCall, 'Expected to find a read_file tool call').toBeDefined();
    expect(
      writeCall,
      'Expected to find a write_file or replace tool call',
    ).toBeDefined();

    const newFileContent = rig.readFile(fileName);
    expect(newFileContent).toBe('1.0.1');
  });

  it.skip('should replace multiple instances of a string', async () => {
    rig.setup('should replace multiple instances of a string');
    const fileName = 'ambiguous.txt';
    const fileContent = 'Hey there, \ntest line\ntest line';
    const expectedContent = 'Hey there, \nnew line\nnew line';
    rig.createFile(fileName, fileContent);

    const result = await rig.run({
      args: `rewrite the file ${fileName} to replace all instances of "test line" with "new line"`,
    });

    const validTools = ['write_file', 'edit'];
    const foundToolCall = await rig.waitForAnyToolCall(validTools);
    if (!foundToolCall) {
      printDebugInfo(rig, result, {
        'Tool call found': foundToolCall,
        'Tool logs': rig.readToolLogs(),
      });
    }
    expect(
      foundToolCall,
      `Expected to find one of ${validTools.join(', ')} tool calls`,
    ).toBeTruthy();

    const toolLogs = rig.readToolLogs();
    const successfulEdit = toolLogs.some(
      (log) =>
        validTools.includes(log.toolRequest.name) && log.toolRequest.success,
    );
    if (!successfulEdit) {
      console.error(
        `Expected a successful edit tool call (${validTools.join(', ')}), but none was found.`,
      );
      printDebugInfo(rig, result);
    }
    expect(
      successfulEdit,
      `Expected a successful edit tool call (${validTools.join(', ')})`,
    ).toBeTruthy();

    const newFileContent = rig.readFile(fileName);
    if (newFileContent !== expectedContent) {
      printDebugInfo(rig, result, {
        'Final file content': newFileContent,
        'Expected file content': expectedContent,
        'Tool logs': rig.readToolLogs(),
      });
    }
    expect(newFileContent).toBe(expectedContent);
  });

  it('should fail safely when trying to edit a non-existent file', async () => {
    await rig.setup(
      'should fail safely when trying to edit a non-existent file',
      { settings: { tools: { core: ['read_file', 'replace'] } } },
    );
    const fileName = 'non_existent.txt';

    const result = await rig.run({
      args: `In ${fileName}, replace "a" with "b"`,
    });

    await rig.waitForTelemetryReady();
    const toolLogs = rig.readToolLogs();

    const readAttempt = toolLogs.find(
      (log) => log.toolRequest.name === 'read_file',
    );
    const writeAttempt = toolLogs.find(
      (log) => log.toolRequest.name === 'write_file',
    );
    const successfulReplace = toolLogs.find(
      (log) => log.toolRequest.name === 'replace' && log.toolRequest.success,
    );

    // The model can either investigate (and fail) or do nothing.
    // If it chose to investigate by reading, that read must have failed.
    if (readAttempt && readAttempt.toolRequest.success) {
      console.error(
        'A read_file attempt succeeded for a non-existent file when it should have failed.',
      );
      printDebugInfo(rig, result);
    }
    if (readAttempt) {
      expect(
        readAttempt.toolRequest.success,
        'If model tries to read the file, that attempt must fail',
      ).toBe(false);
    }

    // CRITICAL: Verify that no matter what the model did, it never successfully
    // wrote or replaced anything.
    if (writeAttempt) {
      console.error(
        'A write_file attempt was made when no file should be written.',
      );
      printDebugInfo(rig, result);
    }
    expect(
      writeAttempt,
      'write_file should not have been called',
    ).toBeUndefined();

    if (successfulReplace) {
      console.error('A successful replace occurred when it should not have.');
      printDebugInfo(rig, result);
    }
    expect(
      successfulReplace,
      'A successful replace should not have occurred',
    ).toBeUndefined();

    // Final verification: ensure the file was not created.
    const filePath = path.join(rig.testDir!, fileName);
    const fileExists = existsSync(filePath);
    expect(fileExists, 'The non-existent file should not be created').toBe(
      false,
    );
  });
});
```

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

```
