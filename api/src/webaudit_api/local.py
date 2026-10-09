"""What the desktop launcher lets the program do with its own data folder.

The brief asks for two things the API cannot do on its own: a button that opens the data
folder, and a way to point the program at a different one. Both are the launcher's job - it
owns the disk, knows where the exe lives and can call Explorer - so it hands the API this
small bundle of callables when it starts the app in local mode. On a server there is none,
and the endpoints answer 404.

Moving the folder never moves the data. The program is running out of that database; copying
it from underneath itself is how people lose work. The new location takes effect on the next
start, and the owner copies the old folder across if they want their audits with them - which
is exactly the "one folder you can move to another computer" the brief describes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class LocalFolder:
    """Callables provided by the launcher; each may raise ValueError with a readable reason."""

    path: Callable[[], str]  # the folder the program is using right now
    pending: Callable[[], str | None]  # a different folder chosen for the next start, if any
    reveal: Callable[[], None]  # open it in the file manager
    choose: Callable[[str], str]  # point the next start at this folder; returns the stored path
