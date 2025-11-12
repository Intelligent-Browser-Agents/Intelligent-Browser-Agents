"""
Timing and metrics utilities
"""

import time
from contextlib import contextmanager
from typing import Dict


class Timer:
    """Simple timer for measuring execution times"""
    
    def __init__(self):
        self.timings: Dict[str, int] = {}
        self._start_times: Dict[str, float] = {}
    
    @contextmanager
    def measure(self, name: str):
        """
        Context manager to measure execution time
        
        Args:
            name: Name of the timing to measure
            
        Yields:
            None
        """
        start = time.perf_counter()
        self._start_times[name] = start
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            self.timings[name] = int(elapsed * 1000)  # Convert to ms
    
    def get_timing(self, name: str) -> int:
        """Get timing in milliseconds"""
        return self.timings.get(name, 0)
    
    def reset(self):
        """Reset all timings"""
        self.timings.clear()
        self._start_times.clear()