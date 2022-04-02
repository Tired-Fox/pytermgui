"""This module houses the `Terminal` class, and its provided instance."""

# pylint: disable=cyclic-import

from __future__ import annotations

import os
import sys
import time
import signal
from enum import Enum
from shutil import get_terminal_size
from contextlib import contextmanager
from functools import cached_property
from typing import Any, Callable, TextIO, Generator

from .input import getch
from .regex import strip_ansi, real_length

__all__ = ["terminal", "Recorder", "ColorSystem"]


class Recorder:
    """A class that records & exports terminal content."""

    def __init__(self) -> None:
        """Initializes the Recorder."""

        self.recording: list[tuple[str, float]] = []
        self._start_stamp = time.time()

    @property
    def _content(self) -> str:
        """Returns the str part of self._recording"""

        return "".join(data for data, _ in self.recording)

    def write(self, data: str) -> None:
        """Writes to the recorder."""

        self.recording.append((data, time.time() - self._start_stamp))

    def export_text(self) -> str:
        """Exports current content as plain text."""

        return strip_ansi(self._content)

    def export_html(
        self, prefix: str | None = None, inline_styles: bool = False
    ) -> str:
        """Exports current content as HTML.

        For help on the arguments, see `pytermgui.html.to_html`.
        """

        from .exporters import to_html  # pylint: disable=import-outside-toplevel

        return to_html(self._content, prefix=prefix, inline_styles=inline_styles)

    def export_svg(
        self,
        prefix: str | None = None,
        inline_styles: bool = False,
        title: str = "PyTermGUI",
    ) -> str:
        """Exports current content as SVG.

        For help on the arguments, see `pytermgui.html.to_svg`.
        """

        from .exporters import to_svg  # pylint: disable=import-outside-toplevel

        return to_svg(
            self._content, prefix=prefix, inline_styles=inline_styles, title=title
        )

    def save_plain(self, filename: str) -> None:
        """Exports plain text content to the given file.

        Args:
            filename: The file to save to.
        """

        with open(filename, "w") as file:
            file.write(self.export_text())

    def save_html(
        self, filename: str, prefix: str | None = None, inline_styles: bool = False
    ) -> None:
        """Exports HTML content to the given file.

        For help on the arguments, see `pytermgui.exporters.to_html`.

        Args:
            filename: The file to save to. If the filename does not contain the '.html'
                extension it will be appended to the end.
        """

        if not filename.endswith(".html"):
            filename += ".html"

        with open(filename, "w") as file:
            file.write(self.export_html(prefix=prefix, inline_styles=inline_styles))

    def save_svg(
        self,
        filename: str,
        prefix: str | None = None,
        inline_styles: bool = False,
        title: str = "PyTermGUI",
    ) -> None:
        """Exports SVG content to the given file.

        For help on the arguments, see `pytermgui.exporters.to_svg`.

        Args:
            filename: The file to save to. If the filename does not contain the '.svg'
                extension it will be appended to the end.
        """

        if not filename.endswith(".svg"):
            filename += ".svg"

        with open(filename, "w") as file:
            file.write(
                self.export_svg(prefix=prefix, inline_styles=inline_styles, title=title)
            )


class ColorSystem(Enum):
    """An enumeration of various terminal-supported colorsystems."""

    NO_COLOR = -1
    """No-color terminal. See https://no-color.org/."""

    STANDARD = 0
    """Standard 3-bit colorsystem of the basic 16 colors."""

    EIGHT_BIT = 1
    """xterm 8-bit colors, 0-256."""

    TRUE = 2
    """'True' color, a.k.a. 24-bit RGB colors."""

    def __ge__(self, other):
        """Comparison: self >= other."""

        if self.__class__ is other.__class__:
            return self.value >= other.value

        return NotImplemented

    def __gt__(self, other):
        """Comparison: self > other."""

        if self.__class__ is other.__class__:
            return self.value > other.value

        return NotImplemented

    def __le__(self, other):
        """Comparison: self <= other."""

        if self.__class__ is other.__class__:
            return self.value <= other.value

        return NotImplemented

    def __lt__(self, other):
        """Comparison: self < other."""

        if self.__class__ is other.__class__:
            return self.value < other.value

        return NotImplemented


def _get_env_colorsys() -> ColorSystem | None:
    """Gets a colorsystem if the `PTG_COLORSYS` env var can be linked to one."""

    colorsys = os.getenv("PTG_COLORSYS")
    if colorsys is None:
        return None

    try:
        return ColorSystem[colorsys]

    except NameError:
        return None


class Terminal:  # pylint: disable=too-many-instance-attributes
    """A class to store & access data about a terminal."""

    RESIZE = 0
    """Event sent out when the terminal has been resized.

    Arguments passed:
    - New size: tuple[int, int]
    """

    margins = [0, 0, 0, 0]
    """Not quite sure what this does at the moment."""

    displayhook_installed: bool = False
    """This is set to True when `pretty.install` is called."""

    origin: tuple[int, int] = (1, 1)
    """Origin of the internal coordinate system."""

    def __init__(self, stream: TextIO | None = None) -> None:
        """Initialize `_Terminal` class."""

        if stream is None:
            stream = sys.stdout

        self._stream = stream
        self._recorder: Recorder | None = None
        self._cursor: tuple[int, int] = self.origin

        self.size: tuple[int, int] = self._get_size()
        self.forced_colorsystem: ColorSystem | None = _get_env_colorsys()
        self.pixel_size: tuple[int, int] = self._get_pixel_size()

        self._listeners: dict[int, list[Callable[..., Any]]] = {}

        if hasattr(signal, "SIGWINCH"):
            signal.signal(signal.SIGWINCH, self._update_size)

        # TODO: Support SIGWINCH on Windows.

    @staticmethod
    def _get_pixel_size() -> tuple[int, int]:
        """Gets the terminal's size, in pixels."""

        if sys.stdout.isatty():
            sys.stdout.write("\x1b[14t")
            sys.stdout.flush()

            # TODO: This probably should be error-proofed.
            output = getch()[4:-1]
            if ";" in output:
                size = tuple(int(val) for val in output.split(";"))
                return size[1], size[0]

        return (0, 0)

    def _call_listener(self, event: int, data: Any) -> None:
        """Calls callbacks for event.

        Args:
            event: A terminal event.
            data: Arbitrary data passed to the callback.
        """

        if event in self._listeners:
            for callback in self._listeners[event]:
                callback(data)

    def _get_size(self) -> tuple[int, int]:
        """Gets the screen size with origin substracted."""

        size = get_terminal_size()
        return (size[0] - self.origin[0], size[1] - self.origin[1])

    def _update_size(self, *_: Any) -> None:
        """Resize terminal when SIGWINCH occurs, and call listeners."""

        self.size = self._get_size()
        self.pixel_size = self._get_pixel_size()
        self._call_listener(self.RESIZE, self.size)

        # Wipe the screen in case anything got messed up
        self.write("\x1b[2J")

    @property
    def width(self) -> int:
        """Gets the current width of the terminal."""

        return self.size[0]

    @property
    def height(self) -> int:
        """Gets the current height of the terminal."""

        return self.size[1]

    @staticmethod
    def is_interactive() -> bool:
        """Determines whether shell is interactive.

        A shell is interactive if it is run from `python3` or `python3 -i`.
        """

        return hasattr(sys, "ps1")

    @property
    def forced_colorsystem(self) -> ColorSystem | None:
        """Forces a color system type on this terminal."""

        return self._forced_colorsystem

    @forced_colorsystem.setter
    def forced_colorsystem(self, new: ColorSystem | None) -> None:
        """Sets a colorsystem, clears colorsystem cache."""

        self._forced_colorsystem = new

        if hasattr(self, "colorsystem"):
            del self.colorsystem

    @cached_property
    def colorsystem(self) -> ColorSystem:
        """Gets the current terminal's supported color system."""

        if self.forced_colorsystem is not None:
            return self.forced_colorsystem

        if os.getenv("NO_COLOR") is not None:
            return ColorSystem.NO_COLOR

        color_term = os.getenv("COLORTERM", "").strip().lower()

        if color_term in ["24bit", "truecolor"]:
            return ColorSystem.TRUE

        if color_term == "256color":
            return ColorSystem.EIGHT_BIT

        return ColorSystem.STANDARD

    @contextmanager
    def record(self) -> Generator[Recorder, None, None]:
        """Records the terminal's stream."""

        if self._recorder is not None:
            raise RuntimeError(f"{self!r} is already recording.")

        try:
            self._recorder = Recorder()
            yield self._recorder

        finally:
            self._recorder = None

    def replay(self, recorder: Recorder) -> None:
        """Replays a recording."""

        last_time = 0.0
        for data, delay in recorder.recording:
            if last_time > 0.0:
                time.sleep(delay - last_time)

            self.write(data, flush=True)
            last_time = delay

    def isatty(self) -> bool:
        """Returns whether self._stream is a tty."""

        return self._stream.isatty()

    def subscribe(self, event: int, callback: Callable[..., Any]) -> None:
        """Subcribes a callback to be called when event occurs.

        Args:
            event: The terminal event that calls callback.
            callback: The callable to be called. The signature of this
                callable is dependent on the event. See the documentation
                of the specific event for more information.
        """

        if not event in self._listeners:
            self._listeners[event] = []

        self._listeners[event].append(callback)

    def write(
        self, data: str, pos: tuple[int, int] | None = None, flush: bool = False
    ) -> None:
        """Writes the given data to the terminal's stream.

        Args:
            data: The data to write.
            pos: Terminal-character space position to write the data to, (x, y).
            flush: If set, `flush` will be called on the stream after reading.
        """

        if "\x1b[2J" in data:
            self.clear_stream()

        if pos is not None:
            data = "\x1b[{};{}H".format(*reversed(pos)) + data

        if self._recorder is not None:
            self._recorder.write(data)

        self._stream.write(data)

        if flush:
            self._stream.flush()

        self._cursor = (
            self._cursor[0] + real_length("".join(data.splitlines())),
            self._cursor[1] + data.count("\n"),
        )

    def clear_stream(self) -> None:
        """Clears (truncates) the terminal's stream."""

        self._stream.truncate(0)

    def print(
        self,
        *items,
        pos: tuple[int, int] | None = None,
        sep: str = " ",
        end="\n",
        flush: bool = True,
    ) -> None:
        """Prints items to the stream.

        All arguments not mentioned here are analogous to `print`.

        Args:
            pos: Terminal-character space position to write the data to, (x, y).

        """

        self.write(sep.join(items) + end, pos=pos, flush=flush)

    def flush(self) -> None:
        """Flushes self._stream."""

        self._stream.flush()


terminal = Terminal()
"""Terminal instance that should be used pretty much always."""