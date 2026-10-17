"""Canonical layout positions for Project / ProjectTemplate.

Canonical storage (``default_positions``) is a flat mapping keyed by field name,
measured in PDF points (pt)::

    {
        "title":   {"label": "タイトル", "x": 340.16, "y": 62.36, "w": 425.2,
                    "h": 51.02, "font_size": 18, "writing_mode": "horizontal",
                    "font_family": "gothic", "horizontal_font_weight": "normal",
                    "horizontal_text_color": "#000000",
                    "horizontal_text_align": "left", "order": 1},
        "main_image": {"label": "メイン画像", "x": ..., "y": ..., "w": ..., "h": ..., "order": 1},
    }

Text entries are identified by the presence of ``font_size`` — that is the same
discriminator ``PDFRenderService`` and the CSV header builder use. Image entries
must never carry ``font_size``.

The layout editor UI works in millimetres (``x/y/w/h`` in mm) because it is easier
to reason about on an A4 canvas. ``rows_from_positions`` and
``merge_rows_into_positions`` are the only translation boundary:

    canonical pt  <->  editor rows (mm)

Persisting the editor's mm rows directly would write a schema the renderer cannot
read, which is the defect this module exists to prevent.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from .coordinates import A4_HEIGHT_MM, A4_WIDTH_MM, MM_PER_POINT, POINTS_PER_MM

VALID_KEY_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]{0,63}$')

HORIZONTAL_FONT_WEIGHTS = {'normal', 'medium', 'bold'}
# The renderer's vertical default is 'light' (see PDFRenderService._ensure_japanese_font),
# so 'light' must round-trip instead of being coerced to 'normal'.
VERTICAL_FONT_WEIGHTS = {'light', 'normal', 'medium', 'bold'}
HORIZONTAL_TEXT_ALIGNS = {'left', 'center', 'right'}
FONT_FAMILIES = {'gothic', 'mincho'}

# Editor (CSS) <-> canonical writing mode
_TO_CANONICAL_WRITING_MODE = {
    'horizontal': 'horizontal',
    'horizontal-tb': 'horizontal',
    'vertical': 'vertical',
    'vertical-rl': 'vertical',
    'vertical-lr': 'vertical',
}
_TO_EDITOR_WRITING_MODE = {'horizontal': 'horizontal-tb', 'vertical': 'vertical-rl'}

# Legacy container keys written by the pre-canonical editor. They are read for
# backward compatibility and never written again.
LEGACY_CONTAINER_KEYS = ('text_layout', 'image_layout', 'text', 'image', 'width_mm', 'height_mm')


def mm_to_pt(value: Any) -> float:
    return round(float(value) * POINTS_PER_MM, 2)


def pt_to_mm(value: Any) -> float:
    return round(float(value) * MM_PER_POINT, 1)


def template_size_mm(positions: dict | None) -> tuple[float, float]:
    """Page size in mm, falling back to the legacy size keys then A4."""
    positions = positions or {}
    width = positions.get('width_mm')
    height = positions.get('height_mm')
    try:
        width_mm = float(width) if width is not None else A4_WIDTH_MM
        height_mm = float(height) if height is not None else A4_HEIGHT_MM
    except (TypeError, ValueError):
        return A4_WIDTH_MM, A4_HEIGHT_MM
    if width_mm <= 0 or height_mm <= 0:
        return A4_WIDTH_MM, A4_HEIGHT_MM
    return width_mm, height_mm


def is_text_position(position: Any) -> bool:
    return isinstance(position, dict) and 'font_size' in position


def normalize_positions(raw: Any) -> dict[str, dict]:
    """Return only flat, dict-valued entries with a valid key.

    Legacy containers (``text_layout`` / ``image_layout`` / ``width_mm`` …) are
    dropped so the next write stores canonical data only.
    """
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, dict] = {}
    for key, position in raw.items():
        if not isinstance(key, str) or not VALID_KEY_RE.match(key):
            continue
        if key in LEGACY_CONTAINER_KEYS:
            continue
        if not isinstance(position, dict):
            continue
        entry = dict(position)
        if 'font_size' in entry:
            try:
                entry['font_size'] = int(float(entry['font_size']))
            except (TypeError, ValueError):
                entry.pop('font_size', None)
        normalized[key] = entry
    return normalized


def _legacy_rows(positions: dict) -> tuple[list[dict], list[dict]] | None:
    """Rows written by the pre-canonical editor, if present."""
    text_rows = positions.get('text_layout') or positions.get('text')
    image_rows = positions.get('image_layout') or positions.get('image')
    if not isinstance(text_rows, list) and not isinstance(image_rows, list):
        return None

    def _clean(rows: Any) -> list[dict]:
        if not isinstance(rows, list):
            return []
        return [dict(row) for row in rows if isinstance(row, dict) and row.get('key')]

    return _clean(text_rows), _clean(image_rows)


def rows_from_positions(positions: Any) -> tuple[list[dict], list[dict]]:
    """Canonical positions -> editor rows in mm.

    Legacy rows are returned as-is when present so an unsaved editor session keeps
    showing what the user last saw; saving rewrites them canonically.
    """
    positions = positions if isinstance(positions, dict) else {}

    legacy = _legacy_rows(positions)
    if legacy is not None:
        return legacy

    flat = normalize_positions(positions)
    indexed = list(enumerate(flat.items()))
    indexed.sort(key=lambda item: (int(flat[item[1][0]].get('order') or 0), item[0]))

    text_rows: list[dict] = []
    image_rows: list[dict] = []
    for _, (key, position) in indexed:
        row = {
            'key': key,
            'label': str(position.get('label') or key),
            'x': pt_to_mm(position.get('x', 0)),
            'y': pt_to_mm(position.get('y', 0)),
            'w': pt_to_mm(position.get('w', 0)),
            'h': pt_to_mm(position.get('h', 0)),
        }
        if is_text_position(position):
            writing_mode = _TO_CANONICAL_WRITING_MODE.get(
                str(position.get('writing_mode', 'horizontal')).strip().lower(), 'horizontal'
            )
            if writing_mode == 'vertical':
                weight = str(position.get('vertical_font_weight') or 'light').strip().lower()
            else:
                weight = str(position.get('horizontal_font_weight') or 'normal').strip().lower()
            row.update(
                {
                    'font_size': int(position.get('font_size', 12)),
                    'font_family': str(position.get('font_family', 'gothic')),
                    'writing_mode': _TO_EDITOR_WRITING_MODE[writing_mode],
                    'font_weight': weight,
                    'color': str(position.get('horizontal_text_color', '#000000')),
                    'text_align': str(position.get('horizontal_text_align', 'left')),
                }
            )
            text_rows.append(row)
        else:
            image_rows.append(row)
    return text_rows, image_rows


def _as_float(raw: Any, field_name: str, minimum: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{field_name} は数値で入力してください。') from exc
    if value != value or value < minimum:  # NaN guard
        raise ValueError(f'{field_name} は {minimum} 以上で入力してください。')
    return value


def _text_entry(existing: dict, row: dict, order: int | None) -> dict:
    """Apply an editor text row (mm) onto an existing canonical entry."""
    entry = dict(existing)
    writing_mode = _TO_CANONICAL_WRITING_MODE.get(
        str(row.get('writing_mode', entry.get('writing_mode', 'horizontal'))).strip().lower(),
        'horizontal',
    )
    font_family = str(row.get('font_family', entry.get('font_family', 'gothic'))).strip().lower()
    if font_family not in FONT_FAMILIES:
        font_family = 'gothic'

    font_weight = str(
        row.get('font_weight')
        or row.get('vertical_font_weight' if writing_mode == 'vertical' else 'horizontal_font_weight')
        or ''
    ).strip().lower()
    weight_set = VERTICAL_FONT_WEIGHTS if writing_mode == 'vertical' else HORIZONTAL_FONT_WEIGHTS
    if font_weight:
        if font_weight not in weight_set:
            font_weight = 'light' if writing_mode == 'vertical' else 'normal'
    else:
        fallback = (
            entry.get('vertical_font_weight') if writing_mode == 'vertical'
            else entry.get('horizontal_font_weight')
        )
        font_weight = str(fallback or ('light' if writing_mode == 'vertical' else 'normal')).strip().lower()
        if font_weight not in weight_set:
            font_weight = 'light' if writing_mode == 'vertical' else 'normal'

    color = str(
        row.get('color') or row.get('horizontal_text_color') or entry.get('horizontal_text_color')
        or '#000000'
    ).strip()
    if not re.match(r'^#[0-9a-fA-F]{6}$', color):
        color = '#000000'

    text_align = str(
        row.get('text_align') or row.get('horizontal_text_align')
        or entry.get('horizontal_text_align') or 'left'
    ).strip().lower()
    if text_align not in HORIZONTAL_TEXT_ALIGNS:
        text_align = 'left'

    entry.update(
        {
            'label': str(row.get('label') or entry.get('label') or row.get('key') or ''),
            'x': mm_to_pt(_as_float(row.get('x'), 'X', 0)),
            'y': mm_to_pt(_as_float(row.get('y'), 'Y', 0)),
            'w': mm_to_pt(_as_float(row.get('w'), '幅', 0.1)),
            'h': mm_to_pt(_as_float(row.get('h'), '高さ', 0.1)),
            'font_size': int(_as_float(row.get('font_size', entry.get('font_size', 12)), '文字サイズ', 1)),
            'writing_mode': writing_mode,
            'font_family': font_family,
            'horizontal_font_weight': font_weight if writing_mode == 'horizontal' else 'normal',
            'horizontal_text_color': color.upper() if writing_mode == 'horizontal' else '#000000',
            'horizontal_text_align': text_align if writing_mode == 'horizontal' else 'left',
        }
    )
    if writing_mode == 'vertical':
        entry['vertical_font_weight'] = font_weight
    else:
        entry.pop('vertical_font_weight', None)
    if order is not None:
        entry['order'] = order
    return entry


def _image_entry(existing: dict, row: dict, order: int | None) -> dict:
    """Apply an editor image row (mm) onto an existing canonical entry."""
    entry = dict(existing)
    # `font_size` is the renderer's text discriminator: an image must not carry it.
    entry.pop('font_size', None)
    entry.update(
        {
            'label': str(row.get('label') or entry.get('label') or row.get('key') or ''),
            'x': mm_to_pt(_as_float(row.get('x'), 'X', 0)),
            'y': mm_to_pt(_as_float(row.get('y'), 'Y', 0)),
            'w': mm_to_pt(_as_float(row.get('w'), '幅', 0.1)),
            'h': mm_to_pt(_as_float(row.get('h'), '高さ', 0.1)),
        }
    )
    if order is not None:
        entry['order'] = order
    return entry


def merge_rows_into_positions(
    raw_positions: Any,
    text_rows: Iterable[dict] | None = None,
    image_rows: Iterable[dict] | None = None,
) -> dict[str, dict]:
    """Editor rows (mm) -> canonical positions (pt), merged over existing keys.

    Each row is applied on top of the entry already stored for that key, so
    canonical fields the editor does not expose (``order``, ``line_height``,
    ``vertical_char_step`` …) survive a save. Keys the editor never sent are
    preserved untouched, so a partial save can never delete a field from the PDF.
    Raises ``ValueError`` on malformed rows.
    """
    positions = normalize_positions(raw_positions)

    for index, row in enumerate(text_rows or [], start=1):
        if not isinstance(row, dict):
            raise ValueError(f'テキスト {index} 行目の形式が不正です')
        key = str(row.get('key', '')).strip()
        if not VALID_KEY_RE.match(key):
            raise ValueError(f'テキスト {index} 行目: キーが不正です（{key!r}）')
        positions[key] = _text_entry(positions.get(key) or {}, row, index)

    for index, row in enumerate(image_rows or [], start=1):
        if not isinstance(row, dict):
            raise ValueError(f'画像 {index} 行目の形式が不正です')
        key = str(row.get('key', '')).strip()
        if not VALID_KEY_RE.match(key):
            raise ValueError(f'画像 {index} 行目: キーが不正です（{key!r}）')
        positions[key] = _image_entry(positions.get(key) or {}, row, index)

    return positions


def canonicalize(raw_positions: Any) -> dict[str, dict]:
    """Canonical positions only, folding any legacy rows into the flat form.

    Legacy rows are in mm, so they go through ``merge_rows_into_positions``; a
    payload that is already canonical is only normalized. Used before a partial
    save so old rows are migrated instead of being silently ignored.
    """
    positions = normalize_positions(raw_positions)
    legacy = _legacy_rows(raw_positions if isinstance(raw_positions, dict) else {})
    if legacy:
        text_rows, image_rows = legacy
        positions = merge_rows_into_positions(positions, text_rows, image_rows)
    return positions


