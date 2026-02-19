# WASI/WASIX local connection plugin - executes modules in-process
#
# This plugin replaces subprocess.Popen with exec() to run ansible modules
# in the same Python interpreter. Required because WASI/WASIX cannot spawn
# new processes.
#
# Copyright: (c) 2025
# License: MIT

from __future__ import annotations

DOCUMENTATION = """
    name: wasi_local
    short_description: execute on controller without subprocess
    description:
        - This connection plugin executes tasks in-process without subprocess.
        - Designed for WASI/WASIX environments where process spawning is unavailable.
        - Only supports localhost execution.
    author: rust-ansible
    version_added: "0.1"
    notes:
        - This plugin is for WASI/WASIX environments only.
        - Does not support become/privilege escalation.
        - Only localhost execution is supported.
"""

import io
import os
import shutil
import sys
import traceback
import typing as t

from ansible.errors import AnsibleError, AnsibleFileNotFound
from ansible.module_utils.common.text.converters import to_bytes, to_text, to_native
from ansible.plugins.connection import ConnectionBase
from ansible.utils.display import Display
from ansible.utils.path import unfrackpath

display = Display()


class Connection(ConnectionBase):
    """WASI/WASIX local connection - executes modules in-process"""

    transport = 'wasi_local'
    has_pipelining = True

    def __init__(self, *args: t.Any, **kwargs: t.Any) -> None:
        super(Connection, self).__init__(*args, **kwargs)
        self.cwd = None
        self.default_user = os.environ.get('USER', 'wasi')

    def _connect(self) -> 'Connection':
        """Connect to local host - nothing to do"""
        self._play_context.remote_user = self.default_user
        if not self._connected:
            display.vvv(
                f"ESTABLISH WASI LOCAL CONNECTION FOR USER: {self._play_context.remote_user}",
                host=self._play_context.remote_addr
            )
            self._connected = True
        return self

    def exec_command(
        self,
        cmd: str,
        in_data: bytes | None = None,
        sudoable: bool = True
    ) -> tuple[int, bytes, bytes]:
        """
        Execute command in-process instead of via subprocess.

        For WASI/WASIX, we intercept the Python command and exec() it directly,
        capturing stdout/stderr and the exit code.
        """
        super(Connection, self).exec_command(cmd, in_data=in_data, sudoable=sudoable)

        display.debug("in wasi_local.exec_command()")
        display.vvv(f"EXEC (in-process) {to_text(cmd)}", host=self._play_context.remote_addr)

        # Debug: log the command and in_data
        cmd_str = to_text(cmd) if isinstance(cmd, bytes) else cmd
        display.vvv(f"WASI: Command length: {len(cmd_str)}", host=self._play_context.remote_addr)
        if in_data:
            display.vvv(f"WASI: in_data length: {len(in_data)}", host=self._play_context.remote_addr)

        return self._exec_python_inprocess(cmd_str, in_data)

    def _exec_python_inprocess(
        self,
        cmd: str,
        in_data: bytes | None
    ) -> tuple[int, bytes, bytes]:
        """
        Execute a Python script in-process.

        Ansible modules are wrapped in AnsiballZ scripts that:
        1. Extract module code from embedded zipfile
        2. Set up sys.path
        3. Import and run the module
        4. Module calls exit_json() which prints JSON and calls sys.exit(0)

        We intercept this by:
        1. Parsing the command to find the script path
        2. Reading the script content
        3. Executing with exec() in an isolated namespace
        4. Capturing stdout/stderr and exit code
        """
        import re

        # Handle Python discovery commands
        # Format 1: "echo FOUND; command -v 'python3.14'; command -v 'python3.13'..."
        # We should return the path to Python
        if 'command -v' in cmd and 'python' in cmd:
            # Return the "discovered" Python path
            # We use /usr/bin/python3 as the canonical path in WASI
            output = 'FOUND\n/usr/bin/python3\n'
            display.debug(f"WASI: Python discovery command, returning: {output}")
            return (0, output.encode(), b'')

        # Handle pipelining: if we have in_data and the command is to run Python,
        # we should execute the script from in_data rather than treating it as a check
        if in_data and 'python' in cmd and '.py' not in cmd:
            # This is pipelining - module script is in in_data
            display.debug(f"WASI: Pipelining mode, executing {len(in_data)} bytes from in_data")
            return self._exec_pipelined_script(cmd, in_data)

        # Format 2: "/bin/sh -c '/usr/bin/python3 && sleep 0'" with no in_data
        # We just return success since Python is obviously available in WASI
        if 'python' in cmd and '&&' in cmd and 'sleep' in cmd and not in_data:
            display.debug(f"WASI: Python availability check, returning success")
            return (0, b'', b'')

        # Handle echo commands used by ansible to prepare temp directories
        if cmd.startswith('echo ') or "'echo " in cmd or '"echo ' in cmd:
            # Try to extract and execute the echo
            echo_match = re.search(r"echo\s+([^\s;]+)", cmd)
            if echo_match:
                output = echo_match.group(1).strip("'\"")
                return (0, output.encode() + b'\n', b'')
            return (0, b'\n', b'')

        # Handle mkdir commands
        if 'mkdir' in cmd:
            # Extract path from mkdir -p /path
            mkdir_match = re.search(r'mkdir\s+-p\s+([^\s;]+)', cmd)
            if mkdir_match:
                path = mkdir_match.group(1).strip("'\"")
                try:
                    os.makedirs(path, exist_ok=True)
                    return (0, b'', b'')
                except Exception as e:
                    return (1, b'', f'mkdir failed: {e}'.encode())

        # Handle chmod commands (no-op in WASI)
        if 'chmod' in cmd:
            return (0, b'', b'')

        # Handle rm commands for cleanup
        if cmd.startswith('rm ') or '/rm ' in cmd:
            return (0, b'', b'')

        # Extract Python script path from command
        # Typical format: "/path/python /tmp/ansible_xxx/AnsiballZ_module.py"
        # Or shell command: "/bin/sh -c '/path/python /tmp/script.py'"

        script_path = None

        # Try to find .py file in the command
        py_match = re.search(r'(/[^\s\'\"]+\.py)', cmd)
        if py_match:
            script_path = py_match.group(1)

        if not script_path:
            # Fallback: try to execute as shell command (limited support)
            display.warning(f"WASI: Cannot parse command as Python script: {cmd}")
            return (1, b'', f'WASI connection cannot execute non-Python commands: {cmd}'.encode())

        display.debug(f"WASI: Executing Python script in-process: {script_path}")

        # Read the script
        try:
            script_path_bytes = to_bytes(script_path, errors='surrogate_or_strict')
            with open(script_path_bytes, 'rb') as f:
                script_content = f.read()

            # Debug: show first 500 chars of script
            display.vvv(f"WASI: Script preview: {script_content[:500]}", host=self._play_context.remote_addr)

            # Save script for debugging
            debug_path = '/workspace/.ansible/last_module_script.py'
            try:
                os.makedirs(os.path.dirname(debug_path), exist_ok=True)
                with open(debug_path, 'wb') as df:
                    df.write(script_content)
                display.vvv(f"WASI: Saved script to {debug_path}", host=self._play_context.remote_addr)
            except Exception:
                pass  # Ignore debug save errors

        except FileNotFoundError:
            return (1, b'', f'Script not found: {script_path}'.encode())
        except Exception as e:
            return (1, b'', f'Failed to read script {script_path}: {e}'.encode())

        # Set up stdin if pipelining data provided
        original_stdin = sys.stdin
        if in_data:
            sys.stdin = io.TextIOWrapper(io.BytesIO(in_data), encoding='utf-8')

        # Capture stdout/stderr
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()
        sys.stdout = captured_stdout
        sys.stderr = captured_stderr

        # Store original __name__ to restore later
        exit_code = 0

        try:
            # Create execution namespace
            exec_globals = {
                '__name__': '__main__',
                '__file__': script_path,
                '__builtins__': __builtins__,
            }

            # Execute the script
            exec(compile(script_content, script_path, 'exec'), exec_globals)

        except SystemExit as e:
            # Modules call sys.exit(0) on success, sys.exit(1) on failure
            exit_code = e.code if isinstance(e.code, int) else (1 if e.code else 0)
            display.debug(f"WASI: Module exited with code {exit_code}")

        except Exception as e:
            # Execution error
            exit_code = 1
            traceback.print_exc(file=captured_stderr)
            display.debug(f"WASI: Module execution failed: {e}")

        finally:
            # Restore stdout/stderr/stdin
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            sys.stdin = original_stdin

        stdout_bytes = captured_stdout.getvalue().encode('utf-8')
        stderr_bytes = captured_stderr.getvalue().encode('utf-8')

        display.debug(f"WASI: Command completed with rc={exit_code}")
        if stderr_bytes:
            display.debug(f"WASI: stderr={stderr_bytes[:500]}")

        return (exit_code, stdout_bytes, stderr_bytes)

    def _exec_pipelined_script(
        self,
        cmd: str,
        script_data: bytes
    ) -> tuple[int, bytes, bytes]:
        """
        Execute a pipelined Python script.

        When ansible uses pipelining, it passes the module script via stdin
        (in_data) instead of writing it to a file. The command is typically
        just "/usr/bin/python3".

        We execute the script from in_data using exec().
        """
        display.debug(f"WASI: Pipelining mode, executing {len(script_data)} bytes")

        # Save script for debugging
        debug_path = '/workspace/.ansible/last_pipelined_script.py'
        try:
            os.makedirs(os.path.dirname(debug_path), exist_ok=True)
            with open(debug_path, 'wb') as df:
                df.write(script_data)
            display.vvv(f"WASI: Saved pipelined script to {debug_path}",
                       host=self._play_context.remote_addr)
        except Exception:
            pass

        # Capture stdout/stderr
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()
        sys.stdout = captured_stdout
        sys.stderr = captured_stderr

        exit_code = 0

        try:
            # Create execution namespace
            exec_globals = {
                '__name__': '__main__',
                '__file__': '<pipelined>',
                '__builtins__': __builtins__,
            }

            # Decode and execute the script
            script_text = script_data.decode('utf-8')
            exec(compile(script_text, '<pipelined>', 'exec'), exec_globals)

        except SystemExit as e:
            exit_code = e.code if isinstance(e.code, int) else (1 if e.code else 0)
            display.debug(f"WASI: Pipelined module exited with code {exit_code}")

        except Exception as e:
            exit_code = 1
            traceback.print_exc(file=captured_stderr)
            display.debug(f"WASI: Pipelined module execution failed: {e}")

        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr

        stdout_bytes = captured_stdout.getvalue().encode('utf-8')
        stderr_bytes = captured_stderr.getvalue().encode('utf-8')

        display.debug(f"WASI: Pipelined command completed with rc={exit_code}")
        if stderr_bytes:
            display.debug(f"WASI: stderr={stderr_bytes[:500]}")

        return (exit_code, stdout_bytes, stderr_bytes)

    def put_file(self, in_path: str, out_path: str) -> None:
        """Transfer a file from local to local"""
        super(Connection, self).put_file(in_path, out_path)

        in_path = unfrackpath(in_path, basedir=self.cwd)
        out_path = unfrackpath(out_path, basedir=self.cwd)

        display.vvv(f"PUT {in_path} TO {out_path}", host=self._play_context.remote_addr)

        if not os.path.exists(to_bytes(in_path, errors='surrogate_or_strict')):
            raise AnsibleFileNotFound(f"file or module does not exist: {to_native(in_path)}")

        try:
            shutil.copyfile(
                to_bytes(in_path, errors='surrogate_or_strict'),
                to_bytes(out_path, errors='surrogate_or_strict')
            )
        except shutil.Error:
            raise AnsibleError(f"failed to copy: {to_native(in_path)} and {to_native(out_path)} are the same")
        except OSError as ex:
            raise AnsibleError(f"Failed to transfer file to {out_path!r}.") from ex

    def fetch_file(self, in_path: str, out_path: str) -> None:
        """Fetch a file from local to local"""
        super(Connection, self).fetch_file(in_path, out_path)
        display.vvv(f"FETCH {in_path} TO {out_path}", host=self._play_context.remote_addr)
        self.put_file(in_path, out_path)

    def connection_lock(self) -> None:
        """No-op for WASI - no file locking needed for in-process execution"""
        pass

    def connection_unlock(self) -> None:
        """No-op for WASI - no file locking needed for in-process execution"""
        pass

    def reset(self) -> None:
        pass

    def close(self) -> None:
        """Terminate the connection"""
        self._connected = False
