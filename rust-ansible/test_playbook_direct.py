#!/usr/bin/env python3
"""
Direct playbook execution test to trace the hang.
"""
import sys
import os

print("=== Direct Playbook Execution Test ===")
print(f"Python: {sys.version}")

# Initialize bootstrap
print("\n1. Initializing bootstrap...")
import wasi_bootstrap
wasi_bootstrap.initialize()
print("   Bootstrap initialized")

# Check environment
print("\n2. Environment check:")
print(f"   ANSIBLE_CONFIG: {os.environ.get('ANSIBLE_CONFIG')}")
print(f"   ANSIBLE_CONNECTION_PLUGINS: {os.environ.get('ANSIBLE_CONNECTION_PLUGINS')}")
print(f"   ANSIBLE_CONNECTION: {os.environ.get('ANSIBLE_CONNECTION')}")

# Test ansible import
print("\n3. Importing ansible...")
import ansible
print(f"   Ansible version: {ansible.__version__}")

# Load connection plugin
print("\n4. Loading wasi_local connection plugin...")
from ansible.plugins.loader import connection_loader
print(f"   Connection loader: {connection_loader}")

# List available connections
print("   Available connections (first 10):")
for i, name in enumerate(list(connection_loader.all())[:10]):
    print(f"     - {name}")

# Check if wasi_local is loadable
print("\n5. Loading wasi_local specifically...")
conn_class = connection_loader.get('wasi_local', class_only=True)
print(f"   wasi_local class: {conn_class}")

# Test direct module execution through connection
print("\n6. Testing direct ping module execution...")
try:
    from ansible.module_utils.common.text.converters import to_bytes
    from ansible.modules.ping import main as ping_main
    import json
    import io

    # Find the ping module source
    ping_module_path = ansible.modules.ping.__file__
    print(f"   Ping module: {ping_module_path}")

    # Read the ping module
    with open(ping_module_path, 'rb') as f:
        ping_source = f.read()

    # Execute in isolated namespace
    original_stdout = sys.stdout
    captured_stdout = io.StringIO()
    sys.stdout = captured_stdout

    exit_code = 0
    try:
        exec_globals = {
            '__name__': '__main__',
            '__file__': ping_module_path,
            '__builtins__': __builtins__,
        }
        # Set up the module args
        os.environ['_ANSIBLE_PARAMS'] = json.dumps({'ANSIBLE_MODULE_ARGS': {'data': 'pong'}})
        exec(compile(ping_source, ping_module_path, 'exec'), exec_globals)
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else 0
    finally:
        sys.stdout = original_stdout
        if '_ANSIBLE_PARAMS' in os.environ:
            del os.environ['_ANSIBLE_PARAMS']

    output = captured_stdout.getvalue()
    print(f"   Exit code: {exit_code}")
    print(f"   Output: {output[:200]}...")

    if output:
        result = json.loads(output.strip())
        print(f"   Parsed result: {result}")

except Exception as e:
    print(f"   Error: {e}")
    import traceback
    traceback.print_exc()

# Test the full playbook execution path step by step
print("\n7. Testing PlaybookCLI initialization...")
try:
    from ansible.cli.playbook import PlaybookCLI

    # Create minimal CLI
    args = ['ansible-playbook', '/workspace/test_playbook.yml', '-i', '/workspace/inventory.ini', '-v']
    cli = PlaybookCLI(args)
    print("   CLI created")

    # Parse args
    cli.parse()
    print("   Args parsed")

    # This is where it might hang - run with tracing
    print("\n8. Running playbook (this might hang)...")
    print("   If this hangs, the issue is in task execution...")

    # Try to run
    result = cli.run()
    print(f"   Result: {result}")

except Exception as e:
    print(f"   Error: {e}")
    import traceback
    traceback.print_exc()

print("\n=== Test Complete ===")
