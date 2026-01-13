#!/usr/bin/env python3
"""
Progress tracking and reporting module for the CLI script
"""

import time
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class ProgressTracker:
    """Track progress of operations and provide reporting."""
    
    def __init__(self, operation_name: str, total_items: int):
        """Initialize the progress tracker.
        
        Args:
            operation_name: Name of the operation being tracked
            total_items: Total number of items to process
        """
        self.operation_name = operation_name
        self.total_items = total_items
        self.processed_items = 0
        self.start_time = time.time()
        self.last_update_time = self.start_time
        self.errors = []
        self.successes = []
    
    def update(self, increment: int = 1, message: str = None):
        """Update progress and display progress bar.
        
        Args:
            increment: Number of items processed in this update
            message: Optional message to display
        """
        self.processed_items += increment
        
        # Calculate progress percentage
        progress = (self.processed_items / self.total_items) * 100 if self.total_items > 0 else 100
        
        # Calculate elapsed time
        elapsed_time = time.time() - self.start_time
        
        # Calculate estimated time remaining
        if self.processed_items > 0:
            time_per_item = elapsed_time / self.processed_items
            remaining_items = self.total_items - self.processed_items
            estimated_remaining = time_per_item * remaining_items
        else:
            estimated_remaining = 0
        
        # Format time strings
        elapsed_str = self._format_time(elapsed_time)
        remaining_str = self._format_time(estimated_remaining)
        
        # Create progress bar
        bar_length = 40
        filled_length = int(bar_length * progress / 100)
        bar = '█' * filled_length + '░' * (bar_length - filled_length)
        
        # Display progress
        print(f"\r{self.operation_name}: [{bar}] {progress:.1f}% ({self.processed_items}/{self.total_items}) "
              f"| Elapsed: {elapsed_str} | Remaining: {remaining_str}", end="")
        
        # Add message if provided
        if message:
            print(f" | {message}")
        
        # Flush output
        import sys
        sys.stdout.flush()
    
    def log_error(self, error_message: str):
        """Log an error.
        
        Args:
            error_message: Error message to log
        """
        self.errors.append(error_message)
        logger.error(error_message)
    
    def log_success(self, success_message: str):
        """Log a success.
        
        Args:
            success_message: Success message to log
        """
        self.successes.append(success_message)
        logger.info(success_message)
    
    def complete(self):
        """Mark operation as complete and display final report."""
        elapsed_time = time.time() - self.start_time
        
        # Print newline to move to next line after progress bar
        print()
        
        # Display summary
        print("\n" + "=" * 60)
        print(f"{self.operation_name} Complete")
        print("=" * 60)
        print(f"Total items: {self.total_items}")
        print(f"Processed: {self.processed_items}")
        print(f"Errors: {len(self.errors)}")
        print(f"Successes: {len(self.successes)}")
        print(f"Duration: {self._format_time(elapsed_time)}")
        print("=" * 60)
        
        # Display errors if any
        if self.errors:
            print("\nErrors:")
            for error in self.errors:
                print(f"  - {error}")
            print("=" * 60)
    
    def _format_time(self, seconds: float) -> str:
        """Format time in seconds to a human-readable string.
        
        Args:
            seconds: Time in seconds
            
        Returns:
            Formatted time string
        """
        if seconds < 60:
            return f"{seconds:.1f}s"
        elif seconds < 3600:
            minutes = seconds / 60
            return f"{minutes:.1f}m"
        else:
            hours = seconds / 3600
            return f"{hours:.1f}h"

def create_progress_bar(operation_name: str, total_items: int) -> ProgressTracker:
    """Create a new progress tracker.
    
    Args:
        operation_name: Name of the operation
        total_items: Total number of items to process
        
    Returns:
        ProgressTracker instance
    """
    return ProgressTracker(operation_name, total_items)