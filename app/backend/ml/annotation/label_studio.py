"""
Label Studio project config for plan annotation (Workstream 1A).

Generates the Label Studio labeling-interface XML your annotators use to draw
room polygons and symbol boxes on plan images. The classes come straight from
the project's space/symbol lists, so the labels annotators produce map 1:1 onto
the trainer's classes — and Label Studio's polygon export is already handled by
``ml/annotation/formats.label_studio_to_rings``.

Pure string generation — no Label Studio SDK, no network — so it's unit-tested
and you can paste the output straight into a Label Studio project's Labeling
Interface, or POST it via their API.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

# A stable, colorblind-friendly-ish palette cycled across labels.
_PALETTE = [
    "#e6194B", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#42d4f4",
    "#f032e6", "#bfef45", "#fabed4", "#469990", "#dcbeff", "#9A6324",
    "#800000", "#aaffc3", "#808000", "#000075", "#a9a9a9",
]


def _labels_xml(values: Sequence[str], offset: int = 0) -> str:
    return "\n".join(
        f'    <Label value="{v}" background="{_PALETTE[(i + offset) % len(_PALETTE)]}"/>'
        for i, v in enumerate(values)
    )


def build_labeling_config(
    space_classes: Sequence[str],
    symbol_classes: Optional[Sequence[str]] = None,
    *,
    image_value: str = "$image",
) -> str:
    """Label Studio labeling-interface XML for rooms (polygons) + symbols (boxes).

    ``space_classes`` become ``PolygonLabels`` (areas); ``symbol_classes`` (if
    any) become ``RectangleLabels`` (counts). Zoom/pan enabled for large sheets.
    """
    if not space_classes:
        raise ValueError("at least one space class is required")

    blocks = [
        f'  <Image name="image" value="{image_value}" zoom="true" zoomControl="true" '
        f'rotateControl="true"/>',
        '  <PolygonLabels name="rooms" toName="image" strokeWidth="2" '
        'pointSize="small" opacity="0.4">',
        _labels_xml(space_classes),
        "  </PolygonLabels>",
    ]
    if symbol_classes:
        blocks += [
            '  <RectangleLabels name="symbols" toName="image">',
            _labels_xml(symbol_classes, offset=len(space_classes)),
            "  </RectangleLabels>",
        ]
    inner = "\n".join(blocks)
    return f"<View>\n{inner}\n</View>\n"
