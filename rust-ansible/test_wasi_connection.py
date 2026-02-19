#!/usr/bin/env python3
"""
Test script to verify the wasi_local connection plugin works.

Run with wasmer:
    eval "$(mise activate bash)" && wasmer run python/python \
        --volume ./assets/stubs:/stubs \
        --volume ../feasibility/pysite/.venv/lib/python3.14/site-packages:/site-packages \
        --volume .:/workspace \
        --env HOME=/workspace \
        --env USER=wasi \
        --env PYTHONPATH=/stubs:/site-packages \
        --cwd /workspace \
        -- /workspace/test_wasi_connection.py
"""

import sys
import os

print("=== WASI Connection Plugin Test ===")
print(f"Python: {sys.version}")
print(f"Platform: {sys.platform}")
print()

# Test 1: Bootstrap initialization
print("1. Testing bootstrap initialization...")
try:
    import wasi_bootstrap
    wasi_bootstrap.initialize()
    print("   OK: Bootstrap initialized")
except Exception as e:
    print(f"   FAIL: {e}")
    sys.exit(1)

# Test 2: OS patches
print("2. Testing OS patches...")
try:
    uid = os.getuid()
    print(f"   OK: getuid() = {uid}")
except Exception as e:
    print(f"   FAIL: {e}")

# Test 3: Ansible import
print("3. Testing ansible import...")
try:
    import ansible
    print(f"   OK: ansible {ansible.__version__}")
except Exception as e:
    print(f"   FAIL: {e}")
    sys.exit(1)

# Test 4: Connection plugin import
print("4. Testing wasi_local connection plugin import...")
try:
    # Add plugin path
    stubs_dir = '/stubs'
    sys.path.insert(0, os.path.join(stubs_dir, 'ansible_plugins', 'connection'))

    from wasi_local import Connection
    print(f"   OK: Connection class imported")
    print(f"   Transport: {Connection.transport}")
except Exception as e:
    print(f"   FAIL: {e}")
    import traceback
    traceback.print_exc()

# Test 5: Module execution simulation
print("5. Testing in-process module execution...")
try:
    import json
    import io

    # Create a simple test script that mimics an ansible module
    test_script = '''
import json
import sys

# Simulate ansible module output
result = {"ping": "pong", "changed": False}
print(json.dumps(result))
sys.exit(0)
'''

    # Write test script to temp file
    test_script_path = '/tmp/test_module.py'
    with open(test_script_path, 'w') as f:
        f.write(test_script)

    # Test the exec-based execution
    original_stdout = sys.stdout
    captured_stdout = io.StringIO()
    sys.stdout = captured_stdout

    exit_code = 0
    try:
        exec_globals = {
            '__name__': '__main__',
            '__file__': test_script_path,
            '__builtins__': __builtins__,
        }
        with open(test_script_path, 'rb') as f:
            exec(compile(f.read(), test_script_path, 'exec'), exec_globals)
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else 0

    sys.stdout = original_stdout
    output = captured_stdout.getvalue()

    print(f"   Exit code: {exit_code}")
    print(f"   Output: {output.strip()}")

    result = json.loads(output.strip())
    if result.get('ping') == 'pong':
        print("   OK: Module execution works!")
    else:
        print("   FAIL: Unexpected result")

except Exception as e:
    print(f"   FAIL: {e}")
    import traceback
    traceback.print_exc()

# Test 6: Full connection plugin test
print("6. Testing full connection plugin (if possible)...")
try:
    from ansible.plugins.connection import ConnectionBase

    # Create a minimal mock for testing
    class MockPlayContext:
        remote_addr = 'localhost'
        remote_user = 'wasi'

    class MockShell:
        pass

    # This would require more mocking to fully test
    print("   SKIP: Full integration test requires more setup")

except Exception as e:
    print(f"   FAIL: {e}")

print()
print("=== Test Complete ===")
