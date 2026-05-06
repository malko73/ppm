from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from typing import Iterable, Literal
from zipfile import ZIP_DEFLATED, ZipFile

from django.core.files.storage import default_storage
from PIL import Image, ImageDraw, ImageFont, ImageOps, features
from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.ttfonts import TTFError
from reportlab.pdfgen import canvas

from projects.constants import DEFAULT_POSITIONS
from projects.models import Page, PageImage, Project

logger = logging.getLogger(__name__)


class PDFRenderService:
    OutputProfile = Literal['preview', 'print']
    _project_root = Path(__file__).resolve().parents[2]
    GOTHIC_FONT_NAME = 'NotoSansJP'
    MINCHO_FONT_NAME = 'NotoSerifJP'
    FALLBACK_GOTHIC_FONT_NAME = 'HeiseiKakuGo-W5'
    FALLBACK_MINCHO_FONT_NAME = 'HeiseiMin-W3'
    _active_font_names: dict[tuple[str, str], str] = {}
    _registered_font_keys: set[tuple[str, str]] = set()
    _font_family_tokens = {
        'gothic': ('NotoSansJP', 'NotoSansCJKjp'),
        'mincho': ('NotoSerifJP', 'NotoSerifCJKjp', 'SourceHanSerif'),
    }
    _weight_tokens = {
        'light': ('Thin', 'ExtraLight', 'Light', 'W2'),
        'normal': ('Regular', 'Normal', 'W3'),
        'medium': ('Medium', 'W5', 'DemiBold'),
        'bold': ('Bold', 'Heavy', 'W7'),
    }
    _noto_font_candidates = {
        'gothic': {
            'light': (
                'NotoSansJP-Light.ttf',
                'NotoSansJP-Thin.ttf',
                'NotoSansJP-ExtraLight.ttf',
                'NotoSansJP-VariableFont_wght.ttf',
            ),
            'normal': (
                'NotoSansJP-Regular.ttf',
                'NotoSansJP-Regular.otf',
                'NotoSansJP-VariableFont_wght.ttf',
            ),
            'medium': (
                'NotoSansJP-Medium.ttf',
                'NotoSansJP-Medium.otf',
                'NotoSansJP-VariableFont_wght.ttf',
            ),
            'bold': (
                'NotoSansJP-Bold.ttf',
                'NotoSansJP-Bold.otf',
                'NotoSansJP-VariableFont_wght.ttf',
            ),
        },
        'mincho': {
            'light': (
                'NotoSerifJP-Light.ttf',
                'NotoSerifJP-Light.otf',
                'NotoSerifJP-ExtraLight.ttf',
                'NotoSerifJP-ExtraLight.otf',
                'NotoSerifJP-VariableFont_wght.ttf',
            ),
            'normal': (
                'NotoSerifJP-Regular.ttf',
                'NotoSerifJP-Regular.otf',
                'NotoSerifJP-VariableFont_wght.ttf',
            ),
            'medium': (
                'NotoSerifJP-Medium.ttf',
                'NotoSerifJP-Medium.otf',
                'NotoSerifJP-VariableFont_wght.ttf',
            ),
            'bold': (
                'NotoSerifJP-Bold.ttf',
                'NotoSerifJP-Bold.otf',
                'NotoSerifJP-VariableFont_wght.ttf',
            ),
        },
    }
    _noto_font_dirs = (
        _project_root / 'fonts',
        _project_root / 'assets' / 'fonts',
    )
    VERTICAL_CHAR_MAP = {
        '|': '｜',
        'ー': 'ー',
        'ｰ': 'ー',
        '―': 'ー',
        '—': 'ー',
        '〜': '〜',
        '～': '〜',
        '、': '、',
        '。': '。',
        '，': '、',
        '．': '。',
        '､': '、',
        '｡': '。',
        ',': '、',
        '.': '。',
        '(': '（',
        ')': '）',
        '[': '［',
        ']': '］',
        '{': '｛',
        '}': '｝',
        '｢': '「',
        '｣': '」',
        '“': '「',
        '”': '」',
        '"': '」',
        '!': '！',
    }
    VERTICAL_GLYPH_PREFERRED: dict[str, str] = {
        # Prefer vertical punctuation glyphs when font supports them.
        '、': '︑',
        '。': '︒',
        '，': '︑',
        '．': '︒',
        '､': '︑',
        '｡': '︒',
        ',': '︑',
        '.': '︒',
        '｢': '「',
        '｣': '」',
        # Keep parenthesis shape stable in vertical mode.
        '（': '︵',
        '）': '︶',
        '(': '︵',
        ')': '︶',
    }
    VERTICAL_DRAW_FALLBACK_MAP: dict[str, str] = {
        '〝': '「',
        '〟': '」',
        '︴': '〜',
        '︱': '｜',
        '︑': '、',
        '︒': '。',
        '︵': '（',
        '︶': '）',
    }
    # Fine-tune punctuation placement for vertical layout.
    # Offsets are relative to font size: (x_ratio, y_ratio).
    VERTICAL_PUNCT_OFFSET_MAP: dict[str, tuple[float, float]] = {
        # Punctuation (push to right-bottom in the character box)
        '、': (0.00, 0.00),
        '。': (0.00, 0.00),
        '，': (0.00, 0.00),
        '．': (0.00, 0.00),
        '､': (0.00, 0.00),
        '｡': (0.00, 0.00),
        ',': (0.00, 0.00),
        '.': (0.00, 0.00),
        '︑': (0.04, 0.02),
        '︒': (0.04, 0.02),
        '！': (0.12, 0.12),
        '？': (0.12, 0.12),
        '!': (0.12, 0.12),
        '?': (0.12, 0.12),
        # Prolonged sound mark / vertical bar
        'ー': (0.12, -0.04),
        'ｰ': (0.12, -0.04),
        '―': (0.12, -0.04),
        '—': (0.12, -0.04),
        '｜': (0.12, -0.04),
        '︱': (0.12, -0.04),
        '︴': (0.10, 0.08),
        '〝': (0.18, 0.08),
        '〟': (0.18, 0.08),
        # Opening quote / parenthesis (slightly upper-left)
        '「': (0.06, 0.02),
        '『': (0.06, 0.02),
        '（': (0.06, 0.02),
        '(': (0.06, 0.02),
        '︵': (0.06, 0.02),
        # Closing quote / parenthesis (slightly lower-right)
        '」': (0.18, 0.06),
        '』': (0.18, 0.06),
        '）': (0.18, 0.06),
        ')': (0.18, 0.06),
        '︶': (0.18, 0.06),
        '】': (0.18, 0.06),
        '〉': (0.18, 0.06),
        '》': (0.18, 0.06),
        '〕': (0.18, 0.06),
        '］': (0.18, 0.06),
        '｝': (0.18, 0.06),
    }
    FIXED_IMAGE_KEYS = {
        'main_image': 'main_image',
        'sub_image1': 'sub_image1',
        'sub_image2': 'sub_image2',
    }
    IMAGE_PROFILE_SETTINGS: dict[str, dict[str, int]] = {
        'preview': {'dpi': 120, 'jpeg_quality': 45},
        'print': {'dpi': 350, 'jpeg_quality': 90},
    }
    HORIZONTAL_FONT_WEIGHTS: dict[str, int] = {
        'normal': 1,
        'medium': 2,
        'bold': 3,
    }
    # Keep vertical tweak logic switchable.
    ENABLE_VERTICAL_TWEAKS = True
    VERTICAL_ROTATE_CHARS = set('「」『』（）［］｛｝〈〉《》【】()[]{}<>ーｰ―—…')
    _pillow_font_cache: dict[tuple[str, str, int], ImageFont.FreeTypeFont] = {}
    _raqm_available: bool | None = None

    @classmethod
    def _find_noto_font_path(cls, family: str, weight: str) -> Path | None:
        normalized_family = 'mincho' if family == 'mincho' else 'gothic'
        normalized_weight = weight if weight in {'light', 'normal', 'medium', 'bold'} else 'normal'
        search_weights = [normalized_weight] if normalized_weight == 'normal' else [normalized_weight, 'normal']

        if normalized_family == 'mincho':
            env_vars = ('NOTO_SERIF_JP_FONT_PATH', 'NOTO_SERIF_JP_BOLD_FONT_PATH')
        else:
            env_vars = ('NOTO_SANS_JP_FONT_PATH', 'NOTO_SANS_JP_BOLD_FONT_PATH')

        for env_var in env_vars:
            env_path = os.getenv(env_var)
            if not env_path:
                continue
            path = Path(env_path).expanduser()
            if path.exists():
                return path

        for base_dir in cls._noto_font_dirs:
            if not base_dir.exists():
                continue
            for search_weight in search_weights:
                candidates = cls._noto_font_candidates[normalized_family][search_weight]
                for candidate in candidates:
                    direct_path = base_dir / candidate
                    if direct_path.exists():
                        return direct_path
                    for nested_path in base_dir.rglob(candidate):
                        if nested_path.exists():
                            return nested_path
                for family_token in cls._font_family_tokens[normalized_family]:
                    for weight_token in cls._weight_tokens[search_weight]:
                        pattern_ttf = f'*{family_token}*{weight_token}*.ttf'
                        pattern_otf = f'*{family_token}*{weight_token}*.otf'
                        for matched in base_dir.rglob(pattern_ttf):
                            if matched.exists():
                                return matched
                        for matched in base_dir.rglob(pattern_otf):
                            if matched.exists():
                                return matched
        return None

    @classmethod
    def _ensure_japanese_font(cls, family: str, weight: str = 'normal') -> str:
        normalized_family = 'mincho' if family == 'mincho' else 'gothic'
        normalized_weight = weight if weight in {'light', 'normal', 'medium', 'bold'} else 'normal'
        font_key = (normalized_family, normalized_weight)
        if font_key not in cls._registered_font_keys:
            if normalized_family == 'mincho':
                font_name = cls.MINCHO_FONT_NAME
                fallback_name = cls.FALLBACK_MINCHO_FONT_NAME
            else:
                font_name = cls.GOTHIC_FONT_NAME
                fallback_name = cls.FALLBACK_GOTHIC_FONT_NAME

            weighted_font_name = f'{font_name}-{normalized_weight}'
            noto_font_path = cls._find_noto_font_path(normalized_family, normalized_weight)
            try:
                if noto_font_path:
                    pdfmetrics.registerFont(TTFont(weighted_font_name, str(noto_font_path)))
                    cls._active_font_names[font_key] = weighted_font_name
                else:
                    pdfmetrics.registerFont(UnicodeCIDFont(fallback_name))
                    cls._active_font_names[font_key] = fallback_name
            except (TTFError, OSError, KeyError, ValueError):
                if normalized_family == 'mincho':
                    # Keep mincho appearance when custom mincho font cannot be loaded.
                    pdfmetrics.registerFont(UnicodeCIDFont(cls.FALLBACK_MINCHO_FONT_NAME))
                    cls._active_font_names[font_key] = cls.FALLBACK_MINCHO_FONT_NAME
                    cls._registered_font_keys.add(font_key)
                    return cls._active_font_names[font_key]
                pdfmetrics.registerFont(UnicodeCIDFont(cls.FALLBACK_GOTHIC_FONT_NAME))
                cls._active_font_names[font_key] = cls.FALLBACK_GOTHIC_FONT_NAME
            cls._registered_font_keys.add(font_key)
            if os.getenv('PDF_FONT_DEBUG', '').strip() in {'1', 'true', 'TRUE', 'yes', 'YES'}:
                logger.info(
                    'PDF font resolved family=%s weight=%s font=%s path=%s',
                    normalized_family,
                    normalized_weight,
                    cls._active_font_names[font_key],
                    str(noto_font_path) if noto_font_path else '(cid-fallback)',
                )
        return cls._active_font_names[font_key]

    @staticmethod
    def _read_template(project: Project, page: Page | None = None) -> PdfReader:
        selected_template = page.project_template if page and page.project_template_id else project.get_default_template()
        template_file_field = selected_template.template_file if selected_template else project.template_file
        if not template_file_field:
            raise ValueError('テンプレートPDFが設定されていません。')
        with default_storage.open(template_file_field.name, 'rb') as template_file:
            data = template_file.read()
        return PdfReader(io.BytesIO(data))

    @staticmethod
    def _canvas_page_size(template_reader: PdfReader) -> tuple[float, float]:
        first_page = template_reader.pages[0]
        return float(first_page.mediabox.width), float(first_page.mediabox.height)

    @staticmethod
    def _normalize_text_box(
        pos: dict, page_width: float, page_height: float, font_size: float
    ) -> tuple[float, float, float, float, float]:
        x = float(pos.get('x', 0))
        top_y = float(pos.get('y', 0))
        width = float(pos.get('w', page_width - x))
        height = float(pos.get('h', page_height - top_y))
        line_height = float(pos.get('line_height', font_size * 1.4))
        x = max(0.0, min(x, page_width - 1))
        top_y = max(0.0, min(top_y, page_height - 1))
        width = max(1.0, min(width, page_width - x))
        height = max(1.0, min(height, page_height - top_y))
        line_height = max(font_size, line_height)
        return x, top_y, width, height, line_height

    @staticmethod
    def _normalize_image_position(pos: dict, page_width: float, page_height: float) -> tuple[float, float, float, float]:
        width = max(1.0, float(pos.get('w', 120)))
        height = max(1.0, float(pos.get('h', 120)))
        width = min(width, page_width)
        height = min(height, page_height)
        x = max(0.0, min(float(pos.get('x', 0)), page_width - width))
        # Input Y is top-origin; convert image top edge to PDF bottom-origin.
        y = max(0.0, min(page_height - float(pos.get('y', 0)) - height, page_height - height))
        return x, y, width, height

    @staticmethod
    def _wrap_text_to_width(text: str, font_name: str, font_size: float, max_width: float) -> list[str]:
        lines: list[str] = []
        for paragraph in str(text).replace('\r\n', '\n').split('\n'):
            if paragraph == '':
                lines.append('')
                continue
            current = ''
            for ch in paragraph:
                candidate = f'{current}{ch}'
                if current and pdfmetrics.stringWidth(candidate, font_name, font_size) > max_width:
                    lines.append(current)
                    current = ch
                else:
                    current = candidate
            lines.append(current)
        return lines

    @staticmethod
    def _wrap_text_to_vertical_columns(text: str, max_chars_per_column: int) -> list[list[str]]:
        columns: list[list[str]] = []
        for paragraph in str(text).replace('\r\n', '\n').split('\n'):
            if paragraph == '':
                columns.append([])
                continue
            chars = [
                PDFRenderService.VERTICAL_GLYPH_PREFERRED.get(
                    ch,
                    PDFRenderService.VERTICAL_CHAR_MAP.get(ch, ch),
                )
                for ch in paragraph
            ]
            for index in range(0, len(chars), max_chars_per_column):
                columns.append(chars[index:index + max_chars_per_column])
            # Keep paragraph breaks visible as a column gap.
            columns.append([])
        if columns and columns[-1] == []:
            columns.pop()
        return columns

    @classmethod
    def _draw_vertical_char_safe(
        cls,
        draw_canvas: canvas.Canvas,
        x: float,
        y: float,
        ch: str,
    ) -> None:
        safe_basic = cls.VERTICAL_CHAR_MAP.get(ch, ch)
        candidates = [
            ch,
            cls.VERTICAL_DRAW_FALLBACK_MAP.get(ch, ''),
            safe_basic,
            '□',
        ]
        seen: set[str] = set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            try:
                draw_canvas.drawString(x, y, candidate)
                return
            except Exception:
                continue

    @classmethod
    def _draw_vertical_text(
        cls,
        draw_canvas: canvas.Canvas,
        text: str,
        font_name: str,
        font_size: float,
        x: float,
        top_y: float,
        text_width: float,
        text_height: float,
        column_gap: float,
        char_step: float,
        page_height: float,
    ):
        # Draw Japanese vertical text from top-right, then move columns leftward.
        available_height = max(1.0, text_height)
        max_chars_per_column = max(1, int(available_height // char_step))
        max_columns = max(1, int(text_width // column_gap))
        columns = cls._wrap_text_to_vertical_columns(text, max_chars_per_column)

        for column_index, chars in enumerate(columns):
            if column_index >= max_columns:
                break
            column_x = x + text_width - font_size - (column_index * column_gap)
            if column_x < 0:
                break
            for row_index, ch in enumerate(chars):
                baseline_y = page_height - top_y - font_size - (row_index * char_step)
                if baseline_y < page_height - (top_y + text_height):
                    break
                if cls.ENABLE_VERTICAL_TWEAKS:
                    offset_x_ratio, offset_y_ratio = cls.VERTICAL_PUNCT_OFFSET_MAP.get(ch, (0.0, 0.0))
                else:
                    offset_x_ratio, offset_y_ratio = (0.0, 0.0)
                cls._draw_vertical_char_safe(
                    draw_canvas,
                    column_x + (font_size * offset_x_ratio),
                    baseline_y + (font_size * offset_y_ratio),
                    ch,
                )

    @classmethod
    def _load_pillow_font(
        cls,
        family: str,
        weight: str,
        font_size_pt: float,
        dpi: int,
    ) -> ImageFont.FreeTypeFont | None:
        normalized_family = 'mincho' if family == 'mincho' else 'gothic'
        normalized_weight = weight if weight in {'light', 'normal', 'medium', 'bold'} else 'normal'
        font_path = cls._find_noto_font_path(normalized_family, normalized_weight)
        if not font_path:
            font_path = cls._find_noto_font_path(normalized_family, 'normal')
        if not font_path:
            return None

        font_px = max(1, int(round(font_size_pt * dpi / 72)))
        cache_key = (str(font_path), normalized_weight, font_px)
        cached = cls._pillow_font_cache.get(cache_key)
        if cached:
            return cached
        try:
            if cls._is_raqm_available():
                layout_enum = getattr(ImageFont, 'Layout', None)
                if layout_enum is not None and hasattr(layout_enum, 'RAQM'):
                    pillow_font = ImageFont.truetype(
                        str(font_path),
                        font_px,
                        layout_engine=layout_enum.RAQM,
                    )
                elif hasattr(ImageFont, 'LAYOUT_RAQM'):
                    pillow_font = ImageFont.truetype(
                        str(font_path),
                        font_px,
                        layout_engine=ImageFont.LAYOUT_RAQM,
                    )
                else:
                    pillow_font = ImageFont.truetype(str(font_path), font_px)
            else:
                pillow_font = ImageFont.truetype(str(font_path), font_px)
        except OSError:
            return None
        cls._pillow_font_cache[cache_key] = pillow_font
        return pillow_font

    @classmethod
    def _is_raqm_available(cls) -> bool:
        if cls._raqm_available is not None:
            return cls._raqm_available
        try:
            cls._raqm_available = bool(features.check_feature('raqm'))
        except Exception:
            cls._raqm_available = False
        return cls._raqm_available

    @classmethod
    def _draw_vertical_char_pillow_safe(
        cls,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        x_px: int,
        y_px: int,
        cell_size_px: int,
        ch: str,
        pillow_font: ImageFont.FreeTypeFont,
    ) -> None:
        safe_basic = cls.VERTICAL_CHAR_MAP.get(ch, ch)
        candidates = [
            ch,
            cls.VERTICAL_DRAW_FALLBACK_MAP.get(ch, ''),
            safe_basic,
            '□',
        ]
        seen: set[str] = set()
        rotate_char = ch in cls.VERTICAL_ROTATE_CHARS
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            try:
                if rotate_char:
                    bbox = pillow_font.getbbox(candidate)
                    w = max(1, int(bbox[2] - bbox[0]))
                    h = max(1, int(bbox[3] - bbox[1]))
                    pad = 4
                    glyph = Image.new('RGBA', (w + (pad * 2), h + (pad * 2)), (0, 0, 0, 0))
                    glyph_draw = ImageDraw.Draw(glyph)
                    glyph_draw.text(
                        (pad - int(bbox[0]), pad - int(bbox[1])),
                        candidate,
                        fill=(0, 0, 0, 255),
                        font=pillow_font,
                    )
                    rotated = glyph.rotate(90, expand=True, resample=Image.Resampling.BICUBIC)
                    cell = Image.new('RGBA', (cell_size_px, cell_size_px), (0, 0, 0, 0))
                    paste_x = (cell_size_px - rotated.width) // 2
                    paste_y = (cell_size_px - rotated.height) // 2
                    cell.alpha_composite(rotated, (paste_x, paste_y))
                    image.alpha_composite(cell, (x_px, y_px))
                else:
                    bbox = pillow_font.getbbox(candidate)
                    w = max(1, int(bbox[2] - bbox[0]))
                    h = max(1, int(bbox[3] - bbox[1]))
                    cell = Image.new('RGBA', (cell_size_px, cell_size_px), (0, 0, 0, 0))
                    cell_draw = ImageDraw.Draw(cell)
                    text_x = (cell_size_px - w) // 2 - int(bbox[0])
                    text_y = (cell_size_px - h) // 2 - int(bbox[1])
                    cell_draw.text((text_x, text_y), candidate, fill=(0, 0, 0, 255), font=pillow_font)
                    image.alpha_composite(cell, (x_px, y_px))
                return
            except Exception:
                continue

    @classmethod
    def _render_vertical_text_image_bytes(
        cls,
        text: str,
        font_family: str,
        font_weight: str,
        font_size: float,
        text_width: float,
        text_height: float,
        column_gap: float,
        char_step: float,
        output_profile: OutputProfile,
    ) -> bytes | None:
        # Render vertical glyphs on transparent bitmap, then place that bitmap onto PDF.
        dpi = max(180, cls.IMAGE_PROFILE_SETTINGS[output_profile]['dpi'])
        scale = dpi / 72.0
        img_w = max(1, int(round(text_width * scale)))
        img_h = max(1, int(round(text_height * scale)))
        char_step_px = max(1, int(round(char_step * scale)))
        font_size_px = max(1, int(round(font_size * scale)))

        pillow_font = cls._load_pillow_font(font_family, font_weight, font_size, dpi)
        if not pillow_font:
            return None

        max_chars_per_column = max(1, int(max(1.0, text_height) // char_step))
        max_columns = max(1, int(max(1.0, text_width) // column_gap))
        columns = cls._wrap_text_to_vertical_columns(text, max_chars_per_column)

        image = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        if cls._is_raqm_available() and not cls.ENABLE_VERTICAL_TWEAKS:
            for column_index, chars in enumerate(columns):
                if column_index >= max_columns:
                    break
                if not chars:
                    continue
                column_x_pt = text_width - font_size - (column_index * column_gap)
                if column_x_pt < 0:
                    break
                column_x_px = int(round(column_x_pt * scale))
                text_column = ''.join(chars)
                try:
                    draw.text(
                        (column_x_px, 0),
                        text_column,
                        fill=(0, 0, 0, 255),
                        font=pillow_font,
                        direction='ttb',
                        language='ja',
                    )
                except Exception:
                    # Fall back to manual drawing for this column.
                    for row_index, ch in enumerate(chars):
                        row_y_pt = row_index * char_step
                        if row_y_pt + font_size > text_height:
                            break
                        if cls.ENABLE_VERTICAL_TWEAKS:
                            offset_x_ratio, offset_y_ratio = cls.VERTICAL_PUNCT_OFFSET_MAP.get(ch, (0.0, 0.0))
                        else:
                            offset_x_ratio, offset_y_ratio = (0.0, 0.0)
                        x_px = column_x_px + int(round(font_size_px * offset_x_ratio))
                        y_px = (row_index * char_step_px) + int(round(font_size_px * offset_y_ratio))
                        cls._draw_vertical_char_pillow_safe(
                            image=image,
                            draw=draw,
                            x_px=x_px,
                            y_px=y_px,
                            cell_size_px=font_size_px,
                            ch=ch,
                            pillow_font=pillow_font,
                        )
            png_buffer = io.BytesIO()
            image.save(png_buffer, format='PNG', optimize=True)
            return png_buffer.getvalue()

        for column_index, chars in enumerate(columns):
            if column_index >= max_columns:
                break
            column_x_pt = text_width - font_size - (column_index * column_gap)
            if column_x_pt < 0:
                break
            column_x_px = int(round(column_x_pt * scale))
            for row_index, ch in enumerate(chars):
                row_y_pt = row_index * char_step
                if row_y_pt + font_size > text_height:
                    break
                if cls.ENABLE_VERTICAL_TWEAKS:
                    offset_x_ratio, offset_y_ratio = cls.VERTICAL_PUNCT_OFFSET_MAP.get(ch, (0.0, 0.0))
                else:
                    offset_x_ratio, offset_y_ratio = (0.0, 0.0)
                x_px = column_x_px + int(round(font_size_px * offset_x_ratio))
                y_px = (row_index * char_step_px) + int(round(font_size_px * offset_y_ratio))
                cls._draw_vertical_char_pillow_safe(
                    image=image,
                    draw=draw,
                    x_px=x_px,
                    y_px=y_px,
                    cell_size_px=font_size_px,
                    ch=ch,
                    pillow_font=pillow_font,
                )

        png_buffer = io.BytesIO()
        image.save(png_buffer, format='PNG', optimize=True)
        return png_buffer.getvalue()

    @staticmethod
    def _normalize_hex_color(raw_color: str) -> str:
        color = str(raw_color or '').strip()
        if len(color) == 7 and color.startswith('#'):
            try:
                int(color[1:], 16)
                return color.upper()
            except ValueError:
                pass
        return '#000000'

    @classmethod
    def _horizontal_fill_color(
        cls,
        pos: dict,
    ) -> HexColor:
        raw_color = cls._normalize_hex_color(str(pos.get('horizontal_text_color', '#000000')))
        return HexColor(raw_color)

    @classmethod
    def _horizontal_draw_offsets(
        cls,
        pos: dict,
        font_size: float,
    ) -> list[tuple[float, float]]:
        weight = str(pos.get('horizontal_font_weight', 'normal')).strip().lower()
        level = cls.HORIZONTAL_FONT_WEIGHTS.get(weight, 1)
        if level <= 1:
            return [(0.0, 0.0)]
        base = max(0.35, font_size * 0.04)
        if level == 2:
            return [(0.0, 0.0), (base, 0.0), (0.0, base * 0.35)]
        return [
            (0.0, 0.0),
            (base, 0.0),
            (-base * 0.55, 0.0),
            (0.0, base * 0.55),
            (base * 0.25, base * 0.55),
        ]

    @classmethod
    def _draw_horizontal_line(
        cls,
        draw_canvas: canvas.Canvas,
        x: float,
        y: float,
        text: str,
        offsets: list[tuple[float, float]],
    ) -> None:
        for offset_x, offset_y in offsets:
            draw_canvas.drawString(x + offset_x, y + offset_y, text)

    @staticmethod
    def _horizontal_line_x(
        align: str,
        base_x: float,
        box_width: float,
        line_width: float,
    ) -> float:
        remaining = max(0.0, box_width - line_width)
        if align == 'center':
            return base_x + (remaining / 2.0)
        if align == 'right':
            return base_x + remaining
        return base_x

    @classmethod
    def _draw_text(
        cls,
        draw_canvas: canvas.Canvas,
        data: dict,
        positions: dict,
        page_width: float,
        page_height: float,
        output_profile: OutputProfile,
    ):
        text_positions = {
            key: pos for key, pos in positions.items() if isinstance(pos, dict) and 'font_size' in pos
        }
        for key, pos in text_positions.items():
            value = data.get(key)
            if not value:
                continue
            font_family = str(pos.get('font_family', 'gothic')).lower()
            writing_mode = str(pos.get('writing_mode', 'horizontal')).lower()
            font_weight = 'normal'
            if writing_mode == 'horizontal':
                font_weight = str(pos.get('horizontal_font_weight', 'normal')).strip().lower()
            elif writing_mode == 'vertical':
                font_weight = str(pos.get('vertical_font_weight', 'light')).strip().lower()
            font_name = cls._ensure_japanese_font(font_family, font_weight)
            font_size = float(pos.get('font_size', 12))
            x, top_y, text_width, text_height, line_height = cls._normalize_text_box(pos, page_width, page_height, font_size)
            try:
                draw_canvas.setFont(font_name, font_size)
            except Exception:
                fallback_font_name = cls._ensure_japanese_font('gothic', font_weight)
                draw_canvas.setFont(fallback_font_name, font_size)
                font_name = fallback_font_name
            if os.getenv('PDF_FONT_DEBUG', '').strip() in {'1', 'true', 'TRUE', 'yes', 'YES'}:
                logger.info(
                    'PDF draw font key=%s writing_mode=%s font=%s size=%s',
                    key,
                    writing_mode,
                    font_name,
                    font_size,
                )
            if writing_mode == 'vertical':
                vertical_char_step = max(font_size * 0.8, float(pos.get('vertical_char_step', font_size)))
                vertical_png = cls._render_vertical_text_image_bytes(
                    text=str(value),
                    font_family=font_family,
                    font_weight=font_weight,
                    font_size=font_size,
                    text_width=text_width,
                    text_height=text_height,
                    column_gap=line_height,
                    char_step=vertical_char_step,
                    output_profile=output_profile,
                )
                if vertical_png:
                    image = ImageReader(io.BytesIO(vertical_png))
                    draw_canvas.drawImage(
                        image,
                        x,
                        page_height - top_y - text_height,
                        width=text_width,
                        height=text_height,
                        preserveAspectRatio=False,
                        anchor='sw',
                        mask='auto',
                    )
                else:
                    if output_profile == 'print':
                        draw_canvas.setFillColorCMYK(0, 0, 0, 1)
                    else:
                        draw_canvas.setFillColorRGB(0, 0, 0)
                    cls._draw_vertical_text(
                        draw_canvas,
                        str(value),
                        font_name,
                        font_size,
                        x,
                        top_y,
                        text_width,
                        text_height,
                        line_height,
                        vertical_char_step,
                        page_height,
                    )
                continue
            horizontal_color = cls._normalize_hex_color(str(pos.get('horizontal_text_color', '#000000')))
            if output_profile == 'print' and horizontal_color == '#000000':
                draw_canvas.setFillColorCMYK(0, 0, 0, 1)
            else:
                draw_canvas.setFillColor(cls._horizontal_fill_color(pos))
            draw_offsets = cls._horizontal_draw_offsets(pos, font_size)
            horizontal_align = str(pos.get('horizontal_text_align', 'left')).strip().lower()
            if horizontal_align not in {'left', 'center', 'right'}:
                horizontal_align = 'left'
            wrapped_lines = cls._wrap_text_to_width(str(value), font_name, font_size, text_width)
            max_lines = max(1, int(text_height // line_height))
            for line_index, line in enumerate(wrapped_lines):
                if line_index >= max_lines:
                    break
                baseline_y = page_height - top_y - font_size - (line_index * line_height)
                if baseline_y < page_height - (top_y + text_height):
                    break
                line_width = pdfmetrics.stringWidth(line, font_name, font_size)
                line_x = cls._horizontal_line_x(horizontal_align, x, text_width, line_width)
                cls._draw_horizontal_line(draw_canvas, line_x, baseline_y, line, draw_offsets)

    @classmethod
    def _resolve_image_for_key(cls, page: Page, key: str, image_map: dict[str, PageImage]):
        if key in cls.FIXED_IMAGE_KEYS:
            return getattr(page, cls.FIXED_IMAGE_KEYS[key], None)
        image_obj = image_map.get(key)
        return image_obj.image if image_obj else None

    @classmethod
    def _draw_images(
        cls,
        draw_canvas: canvas.Canvas,
        page: Page,
        positions: dict,
        page_width: float,
        page_height: float,
        output_profile: OutputProfile,
    ):
        image_positions = {
            key: pos for key, pos in positions.items() if isinstance(pos, dict) and 'font_size' not in pos
        }
        image_map = {image.key: image for image in page.images.all()}
        for key, pos in image_positions.items():
            image_field = cls._resolve_image_for_key(page, key, image_map)
            if not image_field:
                continue
            cls._draw_image(draw_canvas, image_field, pos, page_width, page_height, output_profile)

    @classmethod
    def _optimize_image_for_profile(
        cls,
        image_bytes: bytes,
        box_width_pt: float,
        box_height_pt: float,
        output_profile: OutputProfile,
    ) -> bytes:
        settings = cls.IMAGE_PROFILE_SETTINGS[output_profile]
        target_max_width_px = max(1, int(round(box_width_pt * settings['dpi'] / 72)))
        target_max_height_px = max(1, int(round(box_height_pt * settings['dpi'] / 72)))

        with Image.open(io.BytesIO(image_bytes)) as src_image:
            image = ImageOps.exif_transpose(src_image)
            image = cls._crop_height_for_box_width(
                image,
                target_max_width_px,
                target_max_height_px,
            )
            if image.width > target_max_width_px or image.height > target_max_height_px:
                image.thumbnail((target_max_width_px, target_max_height_px), Image.Resampling.LANCZOS)

            has_alpha = image.mode in ('RGBA', 'LA') or (
                image.mode == 'P' and 'transparency' in image.info
            )
            output = io.BytesIO()
            if output_profile == 'print':
                if has_alpha:
                    rgba = image.convert('RGBA')
                    flattened = Image.new('RGB', rgba.size, (255, 255, 255))
                    flattened.paste(rgba, mask=rgba.split()[-1])
                    cmyk_image = flattened.convert('CMYK')
                else:
                    cmyk_image = image.convert('CMYK')
                cmyk_image.save(
                    output,
                    format='JPEG',
                    quality=settings['jpeg_quality'],
                    optimize=True,
                    progressive=False,
                )
            elif has_alpha:
                rgba = image.convert('RGBA')
                flattened = Image.new('RGB', rgba.size, (255, 255, 255))
                flattened.paste(rgba, mask=rgba.split()[-1])
                flattened.save(
                    output,
                    format='JPEG',
                    quality=settings['jpeg_quality'],
                    optimize=True,
                    progressive=True,
                )
            else:
                image.convert('RGB').save(
                    output,
                    format='JPEG',
                    quality=settings['jpeg_quality'],
                    optimize=True,
                    progressive=True,
                )
        return output.getvalue()

    @staticmethod
    def _crop_height_for_box_width(
        image: Image.Image,
        box_width_px: int,
        box_height_px: int,
    ) -> Image.Image:
        if box_width_px <= 0 or box_height_px <= 0 or image.width <= 0 or image.height <= 0:
            return image

        required_height = image.width * box_height_px / box_width_px
        if image.height <= required_height:
            return image

        top = int(round((image.height - required_height) / 2))
        cropped_height = max(1, int(round(required_height)))
        bottom = min(image.height, top + cropped_height)
        top = max(0, bottom - cropped_height)
        return image.crop((0, top, image.width, bottom))

    @classmethod
    def _draw_image(
        cls,
        draw_canvas: canvas.Canvas,
        image_field,
        pos: dict,
        page_width: float,
        page_height: float,
        output_profile: OutputProfile,
    ):
        if not image_field:
            return
        image_field.open('rb')
        image_bytes = image_field.read()
        image_field.close()
        x, y, width, height = cls._normalize_image_position(pos, page_width, page_height)
        optimized_bytes = cls._optimize_image_for_profile(image_bytes, width, height, output_profile)
        image = ImageReader(io.BytesIO(optimized_bytes))
        draw_canvas.drawImage(
            image,
            x,
            y,
            width=width,
            height=height,
            preserveAspectRatio=True,
            anchor='sw',
            mask='auto',
        )

    @classmethod
    def render_single_page_bytes(
        cls,
        project: Project,
        page: Page,
        output_profile: OutputProfile = 'preview',
    ) -> bytes:
        template_reader = cls._read_template(project, page)
        width, height = cls._canvas_page_size(template_reader)
        template_positions = (
            page.project_template.default_positions
            if page.project_template_id and page.project_template and page.project_template.default_positions
            else {}
        )
        positions = template_positions or project.default_positions or DEFAULT_POSITIONS

        overlay_buffer = io.BytesIO()
        draw_canvas = canvas.Canvas(overlay_buffer, pagesize=(width, height), pageCompression=1)
        cls._draw_text(draw_canvas, page.input_data or {}, positions, width, height, output_profile)
        cls._draw_images(draw_canvas, page, positions, width, height, output_profile)
        draw_canvas.save()

        overlay_buffer.seek(0)
        overlay_pdf = PdfReader(overlay_buffer)

        writer = PdfWriter()
        base_page = template_reader.pages[0]
        base_page.merge_page(overlay_pdf.pages[0])
        writer.add_page(base_page)

        output = io.BytesIO()
        writer.write(output)
        return output.getvalue()

    @classmethod
    def merge_pages_bytes(
        cls,
        project: Project,
        pages: Iterable[Page],
        output_profile: OutputProfile = 'preview',
    ) -> bytes:
        writer = PdfWriter()
        for page in pages:
            pdf_bytes = cls.render_single_page_bytes(project, page, output_profile=output_profile)
            reader = PdfReader(io.BytesIO(pdf_bytes))
            writer.add_page(reader.pages[0])

        output = io.BytesIO()
        writer.write(output)
        return output.getvalue()

    @classmethod
    def zip_pages_bytes(cls, project: Project, pages: Iterable[Page]) -> bytes:
        page_list = list(pages)
        index_width = max(3, len(str(len(page_list))))
        output = io.BytesIO()
        with ZipFile(output, mode='w', compression=ZIP_DEFLATED) as zip_buffer:
            for index, page in enumerate(page_list, start=1):
                page_pdf = cls.render_single_page_bytes(project, page, output_profile='print')
                filename = f"{index:0{index_width}d}.pdf"
                zip_buffer.writestr(filename, page_pdf)
        return output.getvalue()
