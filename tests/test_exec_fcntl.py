#!/usr/bin/env python3
"""
Test if fcntl patches persist across exec() contexts.
"""
import sys

print("=== Exec FCNTL Test ===")

# Step 1: Patch fcntl
print("\n1. Patching fcntl.lockf...")
import fcntl

def stub_lockf(fd, operation, length=0, start=0, whence=0):
    print(f"   STUB lockf called: fd={fd}, op={operation}")
    return None

fcntl.lockf = stub_lockf
print(f"   Patched: {fcntl.lockf}")

# Step 2: Test direct call
print("\n2. Testing direct call...")
fcntl.lockf(1, fcntl.LOCK_UN)

# Step 3: Test in exec with shared globals
print("\n3. Testing in exec with shared __builtins__...")
code = """
import fcntl
print(f"   Inside exec - fcntl.lockf: {fcntl.lockf}")
fcntl.lockf(1, fcntl.LOCK_UN)
"""
exec(compile(code, '<test>', 'exec'), {'__builtins__': __builtins__})

# Step 4: Test in exec with minimal globals
print("\n4. Testing in exec with minimal globals (like AnsiballZ)...")
code2 = """
import sys
import fcntl
print(f"   Inside exec - fcntl module: {fcntl}")
print(f"   Inside exec - fcntl.lockf: {fcntl.lockf}")
try:
    fcntl.lockf(1, fcntl.LOCK_UN)
    print("   lockf succeeded")
except Exception as e:
    print(f"   lockf failed: {e}")
"""
exec(compile(code2, '<test2>', 'exec'), {'__name__': '__main__', '__builtins__': __builtins__})

# Step 5: Check sys.modules
print("\n5. Checking sys.modules...")
print(f"   fcntl in sys.modules: {'fcntl' in sys.modules}")
if 'fcntl' in sys.modules:
    print(f"   sys.modules['fcntl'].lockf: {sys.modules['fcntl'].lockf}")

print("\n=== Test Complete ===")
