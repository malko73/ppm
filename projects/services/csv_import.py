"""CSV インポートサービス。

CSV のバリデーション・パース・DB 反映を一元管理する。
"""
from __future__ import annotations

import csv
import logging
from io import StringIO

from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.utils import timezone

from ..models import Page, Project, ProjectTemplate

logger = logging.getLogger(__name__)

# CSV インジェクション攻撃の起点となる文字
_CSV_INJECTION_CHARS = frozenset('=+-@\t\r')

# アップロード上限 (5 MB)
CSV_MAX_FILE_SIZE = 5 * 1024 * 1024


class CSVImportError(ValueError):
    """CSV インポート固有のバリデーションエラー。"""


class CSVImportService:
    """CSV ファイルの検証・パース・DB 反映を担当するサービスクラス。"""

    def __init__(self, project: Project, template: ProjectTemplate) -> None:
        self.project = project
        self.template = template

    # ------------------------------------------------------------------
    # ファイルバリデーション
    # ------------------------------------------------------------------

    @staticmethod
    def validate_file(uploaded_file: UploadedFile | None) -> UploadedFile:
        """アップロードファイルの形式・サイズを検証して返す。"""
        if not uploaded_file:
            raise CSVImportError('CSVファイルを選択してください。')
        if uploaded_file.size > CSV_MAX_FILE_SIZE:
            raise CSVImportError('CSVファイルは5MB以下にしてください。')
        content_type = (uploaded_file.content_type or '').lower()
        if content_type.startswith('image/'):
            raise CSVImportError('画像ファイルはアップロードできません。CSVファイルを指定してください。')
        filename = (uploaded_file.name or '').lower()
        if not filename.endswith('.csv'):
            raise CSVImportError('CSVファイル（.csv）のみアップロードできます。')
        return uploaded_file

    # ------------------------------------------------------------------
    # パース
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize_cell(value: str) -> str:
        """CSV インジェクション（数式埋め込み）を防ぐためセルの先頭文字を検査する。"""
        stripped = value.strip()
        if stripped and stripped[0] in _CSV_INJECTION_CHARS:
            return "'" + stripped
        return stripped

    def parse(
        self,
        uploaded_file: UploadedFile,
        expected_headers: list[str],
    ) -> list[tuple[int, str, dict[str, str]]]:
        """CSV を読み込み、バリデーション済みの行リストを返す。

        Returns:
            [(page_number, page_name, input_data), ...]
        """
        try:
            raw = uploaded_file.read()
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise CSVImportError('CSVの文字コードはUTF-8でアップロードしてください。')

        try:
            reader = csv.reader(StringIO(text))
            rows = list(reader)
        except csv.Error:
            raise CSVImportError('CSVの形式が不正です。')

        if len(rows) < 2:
            raise CSVImportError('CSVにはヘッダー行と1件以上のデータ行が必要です。')

        actual_headers = [col.strip() for col in rows[0]]
        if len(actual_headers) != len(expected_headers):
            raise CSVImportError(
                f'CSVの項目数が不正です。期待: {len(expected_headers)}項目 / 実際: {len(actual_headers)}項目'
            )
        if actual_headers != expected_headers:
            raise CSVImportError(
                f'CSVヘッダーが一致しません。期待ヘッダー: {", ".join(expected_headers)}'
            )

        text_keys = expected_headers[2:]
        parsed_rows: list[tuple[int, str, dict[str, str]]] = []
        seen_page_numbers: set[int] = set()

        for row_index, row in enumerate(rows[1:], start=2):
            if len(row) != len(expected_headers):
                raise CSVImportError(f'{row_index}行目: 項目数が一致しません。')

            try:
                page_number = int((row[0] or '').strip())
            except ValueError:
                raise CSVImportError(f'{row_index}行目: ページ番号は整数で入力してください。')

            if page_number <= 0:
                raise CSVImportError(f'{row_index}行目: ページ番号は1以上で入力してください。')
            if page_number in seen_page_numbers:
                raise CSVImportError(f'{row_index}行目: ページ番号 {page_number} が重複しています。')
            seen_page_numbers.add(page_number)

            page_name = self._sanitize_cell(row[1] or '')
            input_data = {
                key: self._sanitize_cell(value or '')
                for key, value in zip(text_keys, row[2:])
            }
            parsed_rows.append((page_number, page_name, input_data))

        return parsed_rows

    # ------------------------------------------------------------------
    # DB 反映
    # ------------------------------------------------------------------

    def import_rows(
        self,
        parsed_rows: list[tuple[int, str, dict[str, str]]],
    ) -> int:
        """パース済み行をトランザクション内で一括 DB 反映する。

        Returns:
            インポートした行数。
        """
        now = timezone.now()

        with transaction.atomic():
            existing_pages = list(
                self.project.pages.select_for_update().order_by('page_number')
            )
            page_map = {page.page_number: page for page in existing_pages}
            touched_numbers: set[int] = set()

            pages_to_update: list[Page] = []
            pages_to_create: list[Page] = []

            for page_number, page_name, input_data in parsed_rows:
                page = page_map.get(page_number)
                if page:
                    page.page_name = page_name
                    page.input_data = input_data
                    page.project_template = self.template
                    page.is_finalized = False
                    page.updated_at = now
                    pages_to_update.append(page)
                else:
                    pages_to_create.append(
                        Page(
                            project=self.project,
                            project_template=self.template,
                            order=page_number,
                            page_number=page_number,
                            page_name=page_name,
                            input_data=input_data,
                            is_finalized=False,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                touched_numbers.add(page_number)

            if pages_to_update:
                Page.objects.bulk_update(
                    pages_to_update,
                    ['page_name', 'input_data', 'project_template', 'is_finalized', 'updated_at'],
                )
            if pages_to_create:
                Page.objects.bulk_create(pages_to_create)

            # 今回のCSVに含まれなかったページも校了解除
            untouched = [p for p in existing_pages if p.page_number not in touched_numbers]
            if untouched:
                for p in untouched:
                    p.is_finalized = False
                    p.updated_at = now
                Page.objects.bulk_update(untouched, ['is_finalized', 'updated_at'])

            Page.resequence(self.project)

        return len(parsed_rows)
