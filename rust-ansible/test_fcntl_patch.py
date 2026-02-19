#!/usr/bin/env python3
"""
Test to verify fcntl.lockf patching works.
"""
import sys

print("=== FCNTL Patch Test ===", flush=True)

# Step 1: Check fcntl before patch
print("\n1. Importing fcntl BEFORE patch...", flush=True)
try:
    import fcntl
    print(f"   fcntl module: {fcntl}", flush=True)
    print(f"   Has lockf: {hasattr(fcntl, 'lockf')}", flush=True)
    if hasattr(fcntl, 'lockf'):
        print(f"   lockf function: {fcntl.lockf}", flush=True)
        try:
            # Try calling it
            fcntl.lockf(sys.stdout.fileno(), fcntl.LOCK_UN)
            print("   lockf() call succeeded", flush=True)
        except Exception as e:
            print(f"   lockf() call failed: {e}", flush=True)
except ImportError as e:
    print(f"   fcntl not available: {e}", flush=True)

# Step 2: Apply patch
print("\n2. Applying patch...", flush=True)
import wasi_bootstrap
wasi_bootstrap.patch_fcntl_module()

# Step 3: Check fcntl after patch
print("\n3. Checking fcntl AFTER patch...", flush=True)
import fcntl
print(f"   fcntl module: {fcntl}", flush=True)
print(f"   Has lockf: {hasattr(fcntl, 'lockf')}", flush=True)
if hasattr(fcntl, 'lockf'):
    print(f"   lockf function: {fcntl.lockf}", flush=True)
    try:
        # Try calling it
        fcntl.lockf(sys.stdout.fileno(), fcntl.LOCK_UN)
        print("   lockf() call succeeded", flush=True)
    except Exception as e:
        print(f"   lockf() call failed: {e}", flush=True)

# Step 4: Test in an exec context (like AnsiballZ)
print("\n4. Testing in exec() context (like AnsiballZ)...", flush=True)
test_code = '''
import fcntl
import sys
try:
    fcntl.lockf(sys.stdout.fileno(), fcntl.LOCK_UN)
    print("   exec context: lockf() call succeeded", flush=True)
except Exception as e:
    print(f"   exec context: lockf() call failed: {e}", flush=True)
'''

exec_globals = {'__builtins__': __builtins__}
exec(compile(test_code, '<test>', 'exec'), exec_globals)

print("\n=== Test Complete ===")
