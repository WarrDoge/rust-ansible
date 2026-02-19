#!/usr/bin/env python3
"""
Check the state of fcntl.lockf throughout execution.
"""
import sys

print("=== FCNTL State Test ===\n")

# Check before any imports
print("1. Initial state (before wasi_bootstrap):")
import fcntl
print(f"   fcntl.lockf = {fcntl.lockf}")
print(f"   id = {id(fcntl.lockf)}\n")

# Import and initialize wasi_bootstrap
print("2. After wasi_bootstrap.initialize():")
import wasi_bootstrap
wasi_bootstrap.initialize()
import fcntl as fcntl2
print(f"   fcntl.lockf = {fcntl.lockf}")
print(f"   id = {id(fcntl.lockf)}")
print(f"   same object? {fcntl is fcntl2}\n")

# Apply ansible patches
print("3. After wasi_bootstrap.apply_ansible_patches():")
wasi_bootstrap.apply_ansible_patches()
print(f"   fcntl.lockf = {fcntl.lockf}")
print(f"   id = {id(fcntl.lockf)}\n")

# Import ansible modules
print("4. After importing ansible:")
from ansible.plugins.connection import ConnectionBase
print(f"   fcntl.lockf = {fcntl.lockf}")
print(f"   id = {id(fcntl.lockf)}\n")

# Check what ConnectionBase has
print("5. Check ConnectionBase.connection_lock:")
import inspect
source = inspect.getsource(ConnectionBase.connection_lock)
print(f"   Source:\n{source}\n")

# Try to call it
print("6. Try calling fcntl.lockf:")
try:
    import io
    test_fd = io.StringIO()
    fcntl.lockf(test_fd.fileno(), fcntl.LOCK_UN)
    print("   SUCCESS\n")
except Exception as e:
    print(f"   FAILED: {e}\n")

print("=== Test Complete ===")
