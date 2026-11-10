"""Typed tool outcomes.

Tools historically report problems by returning a message string. That string
still has to reach the LLM/user, but the skill registry must not count it as a
success (mastery gain, rust reset, dopamine reward). ``ToolFailure`` is a
``str`` subclass, so every existing consumer keeps working unchanged.
"""


class ToolFailure(str):
    """A tool result reporting that the tool could not do its job."""
