#!/usr/bin/env python3
"""
Regenerates src/styles/semi-palette.css.

Semi Design derives every semantic colour from palette variables
(`--semi-blue-5`, `--semi-green-5`, …) as `rgba(var(--semi-blue-5), 1)`. That
means overriding `--semi-color-primary` alone leaves the `-hover`, `-active` and
`-light-*` variants pointing at the original hue, which is how stray blues and
greens leak into an otherwise monochrome UI.

This script reads the palettes out of the installed semi-ui stylesheet and emits
a replacement ramp that keeps Semi's lightness structure but removes the hue:

  * decorative palettes (blue, cyan, purple, violet, pink, teal, lime, indigo,
    light-blue, light-green, grey) become achromatic;
  * the status palettes (green, red, yellow/orange/amber) keep their saturation
    and lightness but rotate to the hue of this app's up / down / warn tokens,
    so coloured state matches the rest of the UI exactly.

Run:  python3 scripts/gen_semi_palette.py
"""

from __future__ import annotations

import colorsys
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SEMI_CSS = ROOT / "node_modules/@douyinfe/semi-ui/dist/css/semi.min.css"
OUT = ROOT / "src/styles/semi-palette.css"

# Palette -> how to treat it.
NEUTRALISE = {
    "blue",
    "cyan",
    "purple",
    "violet",
    "pink",
    "teal",
    "lime",
    "indigo",
    "light-blue",
    "light-green",
    "grey",
}

# Palette -> the app token whose hue it should adopt.
REHUE = {
    "green": "up",
    "light-green-keep": None,  # placeholder, kept for readability
    "red": "down",
    "yellow": "warn",
    "orange": "warn",
    "amber": "warn",
}

TOKEN_HUE = {
    "light": {"up": 0x15803D, "down": 0xB91C1C, "warn": 0xB45309},
    "dark": {"up": 0x4ADE80, "down": 0xF87171, "warn": 0xFBBF24},
}

HEX6 = 6


def parse_palettes(css: str) -> dict[str, dict[str, dict[int, tuple[int, int, int]]]]:
    """{theme: {palette: {index: (r, g, b)}}} from the minified stylesheet."""
    palettes: dict[str, dict[str, dict[int, tuple[int, int, int]]]] = {
        "light": {},
        "dark": {},
    }
    for rule in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selector, body = rule.group(1), rule.group(2)
        theme = "dark" if "theme-mode=dark" in selector else "light"
        for decl in re.finditer(r"--semi-([a-z-]+)-(\d+):\s*(\d+),(\d+),(\d+)", body):
            name, index = decl.group(1), int(decl.group(2))
            rgb = (int(decl.group(3)), int(decl.group(4)), int(decl.group(5)))
            palettes[theme].setdefault(name, {})[index] = rgb
    return palettes


def hue_of(hex_value: int) -> float:
    r = ((hex_value >> 16) & 0xFF) / 255
    g = ((hex_value >> 8) & 0xFF) / 255
    b = (hex_value & 0xFF) / 255
    return colorsys.rgb_to_hls(r, g, b)[0]


def to_rgb255(h: float, lightness: float, saturation: float) -> tuple[int, int, int]:
    r, g, b = colorsys.hls_to_rgb(h, lightness, saturation)
    return (
        round(max(0.0, min(1.0, r)) * 255),
        round(max(0.0, min(1.0, g)) * 255),
        round(max(0.0, min(1.0, b)) * 255),
    )


def transform(rgb: tuple[int, int, int], target_hue: float | None) -> tuple[int, int, int]:
    h, lightness, saturation = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    if target_hue is None:
        # Achromatic: keep the perceived lightness (HLS L is close enough here).
        return to_rgb255(h, lightness, 0.0)
    # Keep the palette's own saturation and lightness; only rotate the hue.
    return to_rgb255(target_hue, lightness, saturation)


def main() -> None:
    css = SEMI_CSS.read_text(encoding="utf-8")
    palettes = parse_palettes(css)

    lines = [
        "/*",
        " * GENERATED FILE — do not edit by hand.",
        " * Regenerate with: python3 scripts/gen_semi_palette.py",
        " *",
        " * Semi Design builds every semantic colour from palette variables",
        " * (`rgba(var(--semi-blue-5), 1)`), so overriding `--semi-color-primary`",
        " * alone leaves its hover/active/light variants tinted. These ramps keep",
        " * Semi's lightness structure but flatten decorative hues to grey and bind",
        " * the status hues to this app's up/down/warn tokens.",
        " */",
        "",
    ]

    for theme in ("light", "dark"):
        # `html body[...]` (0,1,2) outranks Semi's own `body[theme-mode=dark]`
        # (0,1,1). Specificity is required rather than source order because Semi
        # duplicates its theme-variable block into many per-component CSS chunks
        # that Vite injects late, after the entry stylesheets.
        selector = f"html body[theme-mode='{theme}']"
        lines.append(f"{selector} {{")
        hues = TOKEN_HUE[theme]
        for palette in sorted(palettes[theme]):
            if palette in NEUTRALISE:
                target = None
            elif token := REHUE.get(palette):
                target = hue_of(hues[token])
            else:
                # Anything Semi adds later that we have no policy for: flatten it
                # rather than let an unknown hue through.
                target = None

            for index in sorted(palettes[theme][palette]):
                r, g, b = transform(palettes[theme][palette][index], target)
                lines.append(f"  --semi-{palette}-{index}: {r},{g},{b};")
        lines.append("}")
        lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT} ({len(lines)} lines)")


if __name__ == "__main__":
    main()
