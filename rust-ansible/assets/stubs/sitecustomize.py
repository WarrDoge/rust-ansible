"""
Site customization for WASI/WASIX ansible.

This file is automatically executed by Python when the interpreter starts
if it's found in sys.path. It initializes the WASI compatibility layer.
"""

import sys

# Import our stub multiprocessing FIRST to patch the real module
# before ansible imports it
import multiprocessing  # This is our stub, which patches the real module

import wasi_bootstrap

wasi_bootstrap.initialize()


def _patch_on_sys_modules_access():
    """Apply patches when sys.modules is accessed for ansible.executor.process.worker.

    This is a simpler alternative to import hooks.
    """
    import sys

    _original_getitem = sys.modules.__class__.__getitem__
    _patched = [False]

    def patched_getitem(self, key):
        module = _original_getitem(self, key)
        if key == 'ansible.executor.process.worker' and not _patched[0]:
            _patched[0] = True
            wasi_bootstrap.apply_ansible_patches()
        return module

    # This doesn't work because sys.modules is a dict subclass
    # and we can't easily monkey-patch __getitem__

    # Alternative: just ensure apply_ansible_patches is called before running
    pass


# Don't use import hooks - they're too complex and unreliable
# Instead, the user code should call wasi_bootstrap.apply_ansible_patches()
# after importing ansible modules but before using them.
