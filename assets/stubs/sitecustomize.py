"""
Site customization for WASI/WASIX ansible.

This file is automatically executed by Python when the interpreter starts
if it's found in sys.path. It initializes the WASI compatibility layer.
"""

# Import our stub multiprocessing FIRST to patch the real module
# before ansible imports it
import multiprocessing  # This is our stub, which patches the real module

import wasi_bootstrap

wasi_bootstrap.initialize()
