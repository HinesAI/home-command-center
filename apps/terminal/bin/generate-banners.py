#!/usr/bin/env python3
"""Generate uniform IBM # stripe HCC banners for linux tty (ASCII only)."""

from __future__ import annotations

import pathlib
import sys

# Uniform 6-col stripe glyphs — every letter same size. Tty-safe '#' only.
GLYPHS: dict[str, list[str]] = {
    "H": ["## ##", "## ##", "## ##", "## ##", "#####", "#####", "## ##", "## ##"],
    "I": ["#####"] * 8,
    "N": ["## ##", "### #", "#### ", "## ##", "## ##", "## ##", "## ##", "## ##"],
    "E": ["#####", "#####", "##   ", "#### ", "#### ", "##   ", "#####", "#####"],
    "S": [" ####", "#####", "##   ", " ####", "   ##", "#####", " ####", " ####"],
    "C": [" ####", "#####", "##   ", "##   ", "##   ", "##   ", "#####", " ####"],
    "O": [" ####", "#####", "## ##", "## ##", "## ##", "## ##", "#####", " ####"],
    "M": ["# ###", "#####", "#####", "# ###", "## ##", "## ##", "## ##", "## ##"],
    "A": ["  #  ", " ### ", "## ##", "## ##", "#####", "## ##", "## ##", "## ##"],
    "D": ["#### ", "#####", "## ##", "## ##", "## ##", "## ##", "#####", "#### "],
    "R": ["#### ", "#####", "## ##", "#### ", "## ##", "## ##", "## ##", "## ##"],
    "T": ["#####", "#####", "#####", "  #  ", "  #  ", "  #  ", "  #  ", "  #  "],
    " ": ["     "] * 8,
}

ROW_COUNT = 8


def render(text: str, letter_gap: int = 1) -> list[str]:
    rows = [""] * ROW_COUNT
    chars = list(text.upper())
    for index, char in enumerate(chars):
        glyph = GLYPHS.get(char, GLYPHS[" "])
        for row in range(ROW_COUNT):
            rows[row] += glyph[row]
            if index < len(chars) - 1:
                rows[row] += " " * letter_gap
    return rows


def center_block(lines: list[str]) -> list[str]:
    width = max(len(line.rstrip()) for line in lines)
    centered: list[str] = []
    for line in lines:
        text = line.rstrip()
        pad = max(0, (width - len(text)) // 2)
        centered.append(" " * pad + text)
    return centered


def write_banner(path: pathlib.Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parent.parent / "var")

    # Wide: HOME flows directly into COMMAND (no extra gap between words).
    wide = render("HOMECOMMAND CENTER", letter_gap=1)

    stacked_top = render("HOME", letter_gap=1)
    stacked_bottom = render("COMMAND CENTER", letter_gap=1)
    narrow: list[str] = []
    narrow.extend(center_block(stacked_top))
    narrow.append("")
    narrow.extend(center_block(stacked_bottom))

    write_banner(root / "hcc-banner.txt", wide)
    write_banner(root / "hcc-banner-narrow.txt", narrow)

    print(
        f"Wrote {root / 'hcc-banner.txt'} "
        f"({len(wide)} rows, {max(len(x) for x in wide)} cols)"
    )
    print(
        f"Wrote {root / 'hcc-banner-narrow.txt'} "
        f"({len(narrow)} rows, {max(len(x) for x in narrow)} cols)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
