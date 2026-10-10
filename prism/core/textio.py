"""Decoding source files the same way everywhere (parsers, postings and delivered source).

Using one decoder keeps the text a parser saw, the text that was indexed and the text handed to an
agent identical, so a line number or a literal never refers to different characters.
"""

from __future__ import annotations

import codecs
import re
import unicodedata

_COOKIE = re.compile(rb"^[ \t\f]*#.*?coding[:=][ \t]*([-\w.]+)", re.ASCII)
MAX_STRAY_BYTES = 3  # a few undecodable bytes are a damaged file; more means another encoding


def decode_source(raw: bytes) -> str:
    """Text of a source file: BOM stripped, PEP 263 coding honoured, else UTF-8.

    A file that is not valid UTF-8 is decoded lossily when only a few stray bytes are bad (so its
    symbols are still found) and as Windows-1252/Latin-1 when it is clearly another encoding."""
    if raw.startswith(codecs.BOM_UTF8):
        raw = raw[len(codecs.BOM_UTF8) :]
    for line in raw.split(b"\n", 2)[:2]:
        match = _COOKIE.match(line)
        if match:
            try:
                return raw.decode(match.group(1).decode("ascii"))
            except (LookupError, UnicodeDecodeError):
                break
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    replaced = raw.decode("utf-8", errors="replace")
    if replaced.count("�") <= MAX_STRAY_BYTES:
        return replaced
    try:
        return raw.decode("cp1252")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def normalize(text: str) -> str:
    """Canonical (NFC) form, so a composed `é` matches a decomposed `e` + combining accent."""
    return unicodedata.normalize("NFC", text) if not text.isascii() else text
