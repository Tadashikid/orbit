"""Guardian: every tool call is checked here, in code, before it runs. A prompt is not a security boundary.

- Only tools discovered from a plugged-in server can run (no invented tool names).
- Write tools (anything not marked readOnlyHint) never run on the model's say-so: only the user can approve
  a change, through the UI. Neither the model nor anything it read (emails, events) can approve it.
"""


def check(name, catalogue):
    """("allowed" | "blocked" | "needs_approval", reason) for a requested "<server>__<tool>" call."""
    tool = next((t for t in catalogue if t["name"] == name), None)
    if tool is None:
        return "blocked", "not a tool from a plugged-in server"
    if not tool["read_only"]:
        return "needs_approval", "write tool: only you can approve this, not the AI"
    return "allowed", ""
