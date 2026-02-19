from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Iterable, Literal
from zipfile import ZIP_DEFLATED, ZipFile

from django.core.files.storage import default_storage
from PIL import Image, ImageOps
from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from projects.constants import DEFAULT_POSITIONS
from projects.models import Page, PageImage, Project


class PDFRenderService:
    OutputProfile = Literal['preview', 'print']
    _project_root = Path(__file__).resolve().parents[2]
    JAPANESE_FONT_NAME = 'NotoSansJP'
    FALLBACK_JAPANESE_FONT_NAME = 'HeiseiKakuGo-W5'
    _active_japanese_font_name = JAPANESE_FONT_NAME
    _japanese_font_registered = False
    _noto_font_candidates = (
        'NotoSansJP-Regular.ttf',
        'NotoSansJP-Regular.otf',
        'NotoSansJP-VariableFont_wght.ttf',
    )
    _noto_font_dirs = (
        _project_root / 'fonts',
        _project_root / 'assets' / 'fonts',
        Path('/Library/Fonts'),
        Path('~/Library/Fonts').expanduser(),
        Path('/usr/share/fonts'),
        Path('/usr/local/share/fonts'),
    )
    VERTICAL_CHAR_MAP = {
        '|': '｜',
        'ー': '｜',
        'ｰ': '｜',
        '、': '︑',
        '。': '︒',
        '，': '︐',
        '．': '︒',
        '､': '︑',
        '｡': '︒',
        ',': '︐',
        '.': '︒',
        '(': '︵',
        ')': '︶',
        '（': '︵',
        '）': '︶',
        '[': '︹',
        ']': '︺',
        '［': '︹',
        '］': '︺',
        '{': '︷',
        '}': '︸',
        '｛': '︷',
        '｝': '︸',
        '「': '﹁',
        '」': '﹂',
        '｢': '﹁',
        '｣': '﹂',
        '『': '﹃',
        '』': '﹄',
        '〈': '︿',
        '〉': '﹀',
        '《': '︽',
        '》': '︾',
        '【': '︻',
        '】': '︼',
    }
    # Fine-tune punctuation placement for vertical layout.
    # Offsets are relative to font size: (x_ratio, y_ratio).
    VERTICAL_PUNCT_OFFSET_MAP: dict[str, tuple[float, float]] = {
        '、': (0.42, 0.42),
        '。': (0.42, 0.42),
        '，': (0.42, 0.42),
        '．': (0.42, 0.42),
        '､': (0.42, 0.42),
        '｡': (0.42, 0.42),
        ',': (0.42, 0.42),
        '.': (0.42, 0.42),
        '︑': (0.42, 0.42),
        '︒': (0.42, 0.42),
        '︐': (0.42, 0.42),
        '！': (0.12, 0.12),
        '？': (0.12, 0.12),
        '!': (0.12, 0.12),
        '?': (0.12, 0.12),
        '」': (0.18, 0.06),
        '』': (0.18, 0.06),
        '）': (0.18, 0.06),
        '】': (0.18, 0.06),
        '〉': (0.18, 0.06),
        '》': (0.18, 0.06),
        '〕': (0.18, 0.06),
        '］': (0.18, 0.06),
        '｝': (0.18, 0.06),
        '︶': (0.18, 0.06),
        '︺': (0.18, 0.06),
        '︸': (0.18, 0.06),
        '﹂': (0.18, 0.06),
        '﹄': (0.18, 0.06),
        '﹀': (0.18, 0.06),
        '︾': (0.18, 0.06),
        '︼': (0.18, 0.06),
    }
    FIXED_IMAGE_KEYS = {
        'main_image': 'main_image',
        'sub_image1': 'sub_image1',
        'sub_image2': 'sub_image2',
    }
    IMAGE_PROFILE_SETTINGS: dict[str, dict[str, int]] = {
        'preview': {'dpi': 120, 'jpeg_quality': 45},
        'print': {'dpi': 300, 'jpeg_quality': 90},
    }

    @classmethod
    def _find_noto_font_path(cls) -> Path | None:
        env_path = os.getenv('NOTO_SANS_JP_FONT_PATH')
        if env_path:
            path = Path(env_path).expanduser()
            if path.exists():
                return path

        for base_dir in cls._noto_font_dirs:
            if not base_dir.exists():
                continue
            for candidate in cls._noto_font_candidates:
                direct_path = base_dir / candidate
                if direct_path.exists():
                    return direct_path
                for nested_path in base_dir.rglob(candidate):
                    if nested_path.exists():
                        return nested_path
        return None

    @classmethod
    def _ensure_japanese_font(cls) -> str:
        if not cls._japanese_font_registered:
            noto_font_path = cls._find_noto_font_path()
            if noto_font_path:
                pdfmetrics.registerFont(TTFont(cls.JAPANESE_FONT_NAME, str(noto_font_path)))
                cls._active_japanese_font_name = cls.JAPANESE_FONT_NAME
            else:
                pdfmetrics.registerFont(UnicodeCIDFont(cls.FALLBACK_JAPANESE_FONT_NAME))
                cls._active_japanese_font_name = cls.FALLBACK_JAPANESE_FONT_NAME
            cls._japanese_font_registered = True
        return cls._active_japanese_font_name

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
            chars = [PDFRenderService.VERTICAL_CHAR_MAP.get(ch, ch) for ch in paragraph]
            for index in range(0, len(chars), max_chars_per_column):
                columns.append(chars[index:index + max_chars_per_column])
            # Keep paragraph breaks visible as a column gap.
            columns.append([])
        if columns and columns[-1] == []:
            columns.pop()
        return columns

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
        page_height: float,
    ):
        # Draw Japanese vertical text from top-right, then move columns leftward.
        char_step = max(font_size, font_size * 1.1)
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
                offset_x_ratio, offset_y_ratio = cls.VERTICAL_PUNCT_OFFSET_MAP.get(ch, (0.0, 0.0))
                draw_canvas.drawString(
                    column_x + (font_size * offset_x_ratio),
                    baseline_y + (font_size * offset_y_ratio),
                    ch,
                )

    @classmethod
    def _draw_text(cls, draw_canvas: canvas.Canvas, data: dict, positions: dict, page_width: float, page_height: float):
        font_name = cls._ensure_japanese_font()
        text_positions = {
            key: pos for key, pos in positions.items() if isinstance(pos, dict) and 'font_size' in pos
        }
        for key, pos in text_positions.items():
            value = data.get(key)
            if not value:
                continue
            font_size = float(pos.get('font_size', 12))
            x, top_y, text_width, text_height, line_height = cls._normalize_text_box(pos, page_width, page_height, font_size)
            draw_canvas.setFont(font_name, font_size)
            writing_mode = str(pos.get('writing_mode', 'horizontal')).lower()
            if writing_mode == 'vertical':
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
                    page_height,
                )
                continue
            wrapped_lines = cls._wrap_text_to_width(str(value), font_name, font_size, text_width)
            max_lines = max(1, int(text_height // line_height))
            for line_index, line in enumerate(wrapped_lines):
                if line_index >= max_lines:
                    break
                baseline_y = page_height - top_y - font_size - (line_index * line_height)
                if baseline_y < page_height - (top_y + text_height):
                    break
                draw_canvas.drawString(x, baseline_y, line)

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
            if image.width > target_max_width_px or image.height > target_max_height_px:
                image.thumbnail((target_max_width_px, target_max_height_px), Image.Resampling.LANCZOS)

            has_alpha = image.mode in ('RGBA', 'LA') or (
                image.mode == 'P' and 'transparency' in image.info
            )
            output = io.BytesIO()
            if has_alpha:
                image.save(output, format='PNG', optimize=True)
            else:
                image.convert('RGB').save(
                    output,
                    format='JPEG',
                    quality=settings['jpeg_quality'],
                    optimize=True,
                    progressive=True,
                )
        return output.getvalue()

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
        draw_canvas = canvas.Canvas(overlay_buffer, pagesize=(width, height))
        cls._draw_text(draw_canvas, page.input_data or {}, positions, width, height)
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
        output = io.BytesIO()
        with ZipFile(output, mode='w', compression=ZIP_DEFLATED) as zip_buffer:
            for page in pages:
                page_pdf = cls.render_single_page_bytes(project, page, output_profile='print')
                filename = f"{project.title}_page_{page.page_number}.pdf"
                zip_buffer.writestr(filename, page_pdf)
        return output.getvalue()
