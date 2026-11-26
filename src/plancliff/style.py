import os
from typing import TextIO

RESET = "\033[0m"
BOLD, DIM = "1", "2"
RED, GREEN, YELLOW, MAGENTA, CYAN = "31", "32", "33", "35", "36"


def wants_color(mode: str, stream: TextIO) -> bool:
    """wants_color honours `always` and `never`; `auto` follows NO_COLOR, then FORCE_COLOR, then whether the stream is a terminal."""
    if mode != "auto":
        return mode == "always"
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return stream.isatty() and os.environ.get("TERM") != "dumb"


class Style:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def __call__(self, text: str, *codes: str) -> str:
        if not self.enabled or not codes:
            return text
        return f"\033[{';'.join(codes)}m{text}{RESET}"
