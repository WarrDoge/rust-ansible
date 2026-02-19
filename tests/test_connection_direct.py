#!/usr/bin/env python3
"""
Test the connection plugin with a real module execution.
"""
import sys
import os
import tempfile

print("=== Direct Connection Test ===", flush=True)

# Initialize
import wasi_bootstrap
wasi_bootstrap.initialize()
wasi_bootstrap.apply_ansible_patches()

from ansible.parsing.dataloader import DataLoader
from ansible.inventory.manager import InventoryManager
from ansible.vars.manager import VariableManager
from ansible.playbook.play_context import PlayContext
from ansible.plugins.loader import connection_loader
from ansible import context
from ansible.module_utils.common.collections import ImmutableDict

# Set context
context._init_global_context(ImmutableDict(
    connection='wasi_local',
    module_path=['/site-packages/ansible/modules'],
    forks=1,
    become=None,
    become_method=None,
    become_user=None,
    check=False,
    diff=False,
    verbosity=4,
    syntax=False,
    start_at_task=None,
    remote_user='wasi',
))

# Create connection
print("1. Creating wasi_local connection...", flush=True)
play_context = PlayContext()
play_context.remote_addr = 'localhost'
play_context.connection = 'wasi_local'

conn = connection_loader.get('wasi_local', play_context, '/dev/null')
print(f"   Connection: {conn}", flush=True)
print(f"   Transport: {conn.transport}", flush=True)

# Create a minimal test module script
print("\n2. Creating test module...", flush=True)
test_module_code = '''#!/usr/bin/env python3
import json
import sys

# Simple module that prints JSON result
result = {
    "ping": "pong",
    "changed": False,
    "msg": "Module executed successfully"
}

print(json.dumps(result))
sys.exit(0)
'''

# Write to temp file
with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
    module_path = f.name
    f.write(test_module_code)

print(f"   Module path: {module_path}", flush=True)

# Execute the module
print("\n3. Executing module through connection...", flush=True)
try:
    cmd = f"/bin/python {module_path}"
    print(f"   Command: {cmd}", flush=True)

    rc, stdout, stderr = conn.exec_command(cmd)

    print(f"\n   Return code: {rc}", flush=True)
    print(f"   STDOUT: {stdout.decode('utf-8')}", flush=True)
    print(f"   STDERR: {stderr.decode('utf-8')}", flush=True)

    if rc == 0:
        print("\n   SUCCESS: Module executed!", flush=True)
        import json
        result = json.loads(stdout.decode('utf-8'))
        print(f"   Result: {result}", flush=True)
    else:
        print("\n   FAILED: Module returned non-zero", flush=True)

except Exception as e:
    print(f"\n   ERROR: {e}", flush=True)
    import traceback
    traceback.print_exc()

# Cleanup
os.unlink(module_path)

print("\n=== Test Complete ===")
