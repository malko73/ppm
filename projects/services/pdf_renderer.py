from __future__ import annotations

import io
import os
import hashlib
from pathlib import Path
from typing import Iterable, Literal
from urllib.parse import urlparse
from urllib.request import urlopen
from zipfile import ZIP_DEFLATED, ZipFile

from django.core.files.storage import default_storage
from PIL import Image, ImageOps
from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.ttfonts import TTFError
from reportlab.pdfgen import canvas

from projects.constants import DEFAULT_POSITIONS
from projects.models import Page, PageImage, Project


class PDFRenderService:
    OutputProfile = Literal['preview', 'print']
    _project_root = Path(__file__).resolve().parents[2]
    GOTHIC_FONT_NAME = 'NotoSansJP'
    MINCHO_FONT_NAME = 'NotoSerifJP'
    FALLBACK_GOTHIC_FONT_NAME = 'HeiseiKakuGo-W5'
    FALLBACK_MINCHO_FONT_NAME = 'HeiseiMin-W3'
    _active_font_names: dict[str, str] = {}
    _registered_font_families: set[str] = set()
    _noto_sans_font_candidates = (
        'NotoSansJP-Regular.ttf',
        'NotoSansJP-Regular.otf',
        'NotoSansJP-VariableFont_wght.ttf',
    )
    _noto_serif_font_candidates = (
        'NotoSerifJP-Regular.otf',
        'NotoSerifJP-Regular.ttf',
        'NotoSerifJP-VariableFont_wght.ttf',
    )
    _noto_font_dirs = (
        _project_root / 'fonts',
        _project_root / 'assets' / 'fonts',
        Path('/Library/Fonts'),
        Path('~/Library/Fonts').expanduser(),
        Path('/usr/share/fonts'),
        Path('/usr/local/share/fonts'),
    )
    _font_cache_dir = Path(os.getenv('PDF_FONT_CACHE_DIR', '/tmp/ppm_pdf_fonts'))
    VERTICAL_CHAR_MAP = {
        '|': '｜',
        'ー': '｜',
        'ｰ': '｜',
        '―': '｜',
        '—': '｜',
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
    VERTICAL_DRAW_FALLBACK_MAP: dict[str, str] = {
        '〝': '﹁',
        '〟': '﹂',
        '︴': '〜',
        '︱': '｜',
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
        '｜': (0.10, 0.0),
        '︱': (0.10, 0.0),
        '︴': (0.10, 0.08),
        '〝': (0.18, 0.08),
        '〟': (0.18, 0.08),
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
        'print': {'dpi': 350, 'jpeg_quality': 90},
    }

    @classmethod
    def _find_noto_font_path(cls, family: str) -> Path | None:
        if family == 'mincho':
            env_var = 'NOTO_SERIF_JP_FONT_PATH'
            env_url_var = 'NOTO_SERIF_JP_FONT_URL'
            candidates = cls._noto_serif_font_candidates
        else:
            env_var = 'NOTO_SANS_JP_FONT_PATH'
            env_url_var = 'NOTO_SANS_JP_FONT_URL'
            candidates = cls._noto_sans_font_candidates

        env_path = os.getenv(env_var)
        if env_path:
            path = Path(env_path).expanduser()
            if path.exists():
                return path

        font_url = os.getenv(env_url_var)
        if font_url:
            downloaded_path = cls._download_font_from_url(font_url, family)
            if downloaded_path:
                return downloaded_path

        for base_dir in cls._noto_font_dirs:
            if not base_dir.exists():
                continue
            for candidate in candidates:
                direct_path = base_dir / candidate
                if direct_path.exists():
                    return direct_path
                for nested_path in base_dir.rglob(candidate):
                    if nested_path.exists():
                        return nested_path
        return None

    @classmethod
    def _download_font_from_url(cls, font_url: str, family: str) -> Path | None:
        parsed = urlparse(str(font_url).strip())
        if parsed.scheme not in {'http', 'https'}:
            return None

        suffix = Path(parsed.path).suffix.lower()
        if suffix not in {'.ttf', '.otf'}:
            return None

        digest = hashlib.sha256(font_url.encode('utf-8')).hexdigest()[:16]
        cache_file = cls._font_cache_dir / f'{family}_{digest}{suffix}'
        if cache_file.exists():
            return cache_file

        try:
            cls._font_cache_dir.mkdir(parents=True, exist_ok=True)
            with urlopen(font_url, timeout=10) as response:
                data = response.read(20 * 1024 * 1024)
            if not data:
                return None
            temp_file = cache_file.with_suffix(f'{suffix}.tmp')
            temp_file.write_bytes(data)
            temp_file.replace(cache_file)
            return cache_file
        except Exception:
            return None

    @classmethod
    def _ensure_japanese_font(cls, family: str) -> str:
        normalized_family = 'mincho' if family == 'mincho' else 'gothic'
        if normalized_family not in cls._registered_font_families:
            if normalized_family == 'mincho':
                font_name = cls.MINCHO_FONT_NAME
                fallback_name = cls.FALLBACK_MINCHO_FONT_NAME
            else:
                font_name = cls.GOTHIC_FONT_NAME
                fallback_name = cls.FALLBACK_GOTHIC_FONT_NAME

            noto_font_path = cls._find_noto_font_path(normalized_family)
            try:
                if noto_font_path:
                    pdfmetrics.registerFont(TTFont(font_name, str(noto_font_path)))
                    cls._active_font_names[normalized_family] = font_name
                else:
                    pdfmetrics.registerFont(UnicodeCIDFont(fallback_name))
                    cls._active_font_names[normalized_family] = fallback_name
            except (TTFError, OSError, KeyError, ValueError):
                if normalized_family == 'mincho':
                    # Keep PDF generation alive even when Mincho font cannot be loaded.
                    return cls._ensure_japanese_font('gothic')
                pdfmetrics.registerFont(UnicodeCIDFont(cls.FALLBACK_GOTHIC_FONT_NAME))
                cls._active_font_names[normalized_family] = cls.FALLBACK_GOTHIC_FONT_NAME
            cls._registered_font_families.add(normalized_family)
        return cls._active_font_names[normalized_family]

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
    def _draw_vertical_char_safe(
        cls,
        draw_canvas: canvas.Canvas,
        x: float,
        y: float,
        ch: str,
    ) -> None:
        candidates = [
            ch,
            cls.VERTICAL_DRAW_FALLBACK_MAP.get(ch, ''),
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
                cls._draw_vertical_char_safe(
                    draw_canvas,
                    column_x + (font_size * offset_x_ratio),
                    baseline_y + (font_size * offset_y_ratio),
                    ch,
                )

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
        if output_profile == 'print':
            # Use K-only black for print profile text.
            draw_canvas.setFillColorCMYK(0, 0, 0, 1)
        else:
            draw_canvas.setFillColorRGB(0, 0, 0)
        text_positions = {
            key: pos for key, pos in positions.items() if isinstance(pos, dict) and 'font_size' in pos
        }
        for key, pos in text_positions.items():
            value = data.get(key)
            if not value:
                continue
            font_family = str(pos.get('font_family', 'gothic')).lower()
            font_name = cls._ensure_japanese_font(font_family)
            font_size = float(pos.get('font_size', 12))
            x, top_y, text_width, text_height, line_height = cls._normalize_text_box(pos, page_width, page_height, font_size)
            try:
                draw_canvas.setFont(font_name, font_size)
            except Exception:
                fallback_font_name = cls._ensure_japanese_font('gothic')
                draw_canvas.setFont(fallback_font_name, font_size)
                font_name = fallback_font_name
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
        output = io.BytesIO()
        with ZipFile(output, mode='w', compression=ZIP_DEFLATED) as zip_buffer:
            for page in pages:
                page_pdf = cls.render_single_page_bytes(project, page, output_profile='print')
                filename = f"{project.title}_page_{page.page_number}.pdf"
                zip_buffer.writestr(filename, page_pdf)
        return output.getvalue()
