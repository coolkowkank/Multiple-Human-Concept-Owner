"""
Utility functions for estimating token counts from character counts.

The estimation simply divides the number of characters by 4 and rounds up,
which is a rough heuristic often used for models where roughly 4 characters
correspond to one token.
"""
import math
from typing import Dict


def estimate_tokens(text: str) -> int:
    """
    Estimate the number of tokens in *text*.

    The heuristic is ``ceil(len(text) / 4)``.  An empty string yields ``0``.
    """
    if not text:
        return 0
    return math.ceil(len(text) / 4)


def measure_prompt(system: str, task: str) -> Dict[str, int]:
    """
    Return a dictionary with character and token statistics for a prompt.

    Keys:
        - ``system_chars``: number of characters in the system prompt.
        - ``task_chars``: number of characters in the task prompt.
        - ``total_chars``: sum of the above two.
        - ``est_tokens``: estimated token count for the concatenated prompts.
    """
    system_chars = len(system)
    task_chars = len(task)
    total_chars = system_chars + task_chars
    est_tokens = estimate_tokens(system + task)
    return {
        "system_chars": system_chars,
        "task_chars": task_chars,
        "total_chars": total_chars,
        "est_tokens": est_tokens,
    }
