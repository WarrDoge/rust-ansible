"""Patch ansible strategy for WASI synchronous execution."""

import queue as queue_module

def process_one_result(strategy):
    """Process a single result from the final queue, synchronously."""
    from ansible.plugins.strategy import (
        StrategySentinel, DisplaySend, CallbackSend, _WireTaskResult, PromptSend, display
    )

    try:
        result = strategy._final_q.get_nowait()
    except queue_module.Empty:
        return False

    if isinstance(result, StrategySentinel):
        return False
    elif isinstance(result, DisplaySend):
        dmethod = getattr(display, result.method)
        dmethod(*result.args, **result.kwargs)
    elif isinstance(result, CallbackSend):
        task_result = strategy._convert_wire_task_result_to_raw(result.wire_task_result)
        strategy._tqm.send_callback(result.method_name, task_result)
    elif isinstance(result, _WireTaskResult):
        result = strategy._convert_wire_task_result_to_raw(result)
        with strategy._results_lock:
            strategy._results.append(result)
    elif isinstance(result, PromptSend):
        # For WASI, we can't do interactive prompts - fail with message
        from ansible.errors import AnsibleError
        value = AnsibleError("Interactive prompts not supported in WASI mode")
        strategy._workers[result.worker_id].worker_queue.put(value)
    else:
        display.warning('Received an invalid object (%s) in the result queue: %r' % (type(result), result))

    return True


def drain_results(strategy):
    """Drain all pending results from the queue."""
    while process_one_result(strategy):
        pass


def patch_strategy_base():
    """Patch StrategyBase to use synchronous result processing."""
    import threading
    from ansible.plugins.strategy import StrategyBase

    _original_init = StrategyBase.__init__

    def patched_init(self, tqm):
        _original_init(self, tqm)
        # Stop the results thread that was started - it can't run in WASI
        # We'll process results synchronously instead
        # Note: The thread.start() will have failed already with our stub

    _original_cleanup = StrategyBase.cleanup

    def patched_cleanup(self):
        # Drain any remaining results
        drain_results(self)
        # Don't call original cleanup - it tries to join the thread

    _original_process_pending_results = StrategyBase._process_pending_results

    def patched_process_pending_results(self, iterator, one_pass=False, max_passes=None):
        # First, drain results from final_q into self._results
        drain_results(self)
        # Then call original processing
        return _original_process_pending_results(self, iterator, one_pass, max_passes)

    StrategyBase.__init__ = patched_init
    StrategyBase.cleanup = patched_cleanup
    StrategyBase._process_pending_results = patched_process_pending_results
