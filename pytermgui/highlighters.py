"""This module provides the `Highlighter` class, and some pre-configured instances."""

from __future__ import annotations
import re
import keyword
import builtins
from dataclasses import dataclass, field
from typing import Pattern, Match, Protocol

from .regex import RE_MARKUP

__all__ = [
    "Highlighter",
    "RegexHighlighter",
    "highlight_python",
]


class Highlighter(Protocol):  # pylint: disable=too-few-public-methods
    """The protocol for highlighters."""

    def __call__(self, text: str, cache: bool = True) -> str:
        """Highlights the given text.

        Args:
            text: The text to highlight.
            cache: If set (default), results will be stored, keyed by their respective
                inputs, and retrieved the next time the same key is given.
        """


@dataclass
class RegexHighlighter(Highlighter):
    """A class to highlight strings using regular expressions.

    This class must be provided with a list of styles. These styles are really just a
    tuple of the markup alias name, and their associated RE patterns. If *all* aliases
    in the instance use the same prefix, it can be given under the `prefix` key and
    ommitted from the style names.

    On construction, the instance will combine all of its patterns into a monster regex
    including named capturing groups. The general format is something like:

        (?P<{name1}>{pattern1})|(?P<{name2}>{pattern2})|...

    Calling this instance will then replace all matches, going in the order of
    definition, with style-injected versions. These follow the format:

        [{prefix?}{name}]{content}[/{prefix}{name}]

    Oddities to keep in mind:
    - Regex replace goes in the order of the defined groups, and is non-overlapping. Two
        groups cannot match the same text.
    - Because of how capturing groups work, everything within the patterns will be
        matched. To look for context around a match, look-around assertions can be used.
    """

    styles: list[tuple[str, str]]
    prefix: str = ""

    _pattern: Pattern = field(init=False)
    _highlight_cache: dict[str, str] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        """Combines all styles into one pattern."""

        pattern = ""
        names: list[str] = []
        for name, ptrn in self.styles:
            pattern += f"(?P<{name}>{ptrn})|"
            names.append(name)

        pattern = pattern.rstrip("|")

        self._pattern = re.compile(pattern)

    def __call__(self, text: str, cache: bool = True) -> str:
        """Highlights the given text, using the combined regex pattern."""

        if cache and text in self._highlight_cache:
            return self._highlight_cache[text]

        cache_key = text

        def _insert_style(matchobj: Match) -> str:
            """Returns the match inserted into a markup style."""

            groups = matchobj.groupdict()

            name = matchobj.lastgroup
            content = groups.get(str(name), None)

            # Literalize "[" characters to avoid TIM parsing them
            if name == "str":
                if len(RE_MARKUP.findall(content)) > 0:
                    content = content.replace("[", r"\[")

            tag = f"{self.prefix}{name}"
            style = f"[{tag}]{{}}[/{tag}]"

            return style.format(content)

        text = self._pattern.sub(_insert_style, text)
        self._highlight_cache[cache_key] = text

        return text


_BUILTIN_NAMES = "|".join(f"(?:{item})" for item in dir(builtins))
_KEYWORD_NAMES = "|".join(f"(?:{keyw})" for keyw in keyword.kwlist)
_STR_DELIMS = "|".join(('(?:"|("""))', "(?:'|('''))"))

highlight_python = RegexHighlighter(
    prefix="code.",
    styles=[
        ("str", rf"[frbu]*?(?P<str_start>(?:{_STR_DELIMS})).+(?P=str_start)"),
        ("comment", "(#.*)"),
        ("keyword", rf"(\b)({_KEYWORD_NAMES}+)\b"),
        ("builtin", rf"\b(?<!\.)({_BUILTIN_NAMES})\b"),
        ("identifier", r"([^ \.\(]+)(?=\()"),
        ("global", r"(?<=\b)([A-Z]\w+)"),
        ("number", r"((?:0x[\da-zA-Z]+)|(?:\d+))"),
    ],
)