"""非同期 PDF / ZIP 生成タスク。

重い処理は Celery ワーカーに委譲し、結果を Redis キャッシュに格納する。
ビューは cache_key を介して生成済みデータを取得する。
"""
from __future__ import annotations

import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    name='projects.build_merged_pdf',
)
def build_merged_pdf(self, project_id: int, cache_key: str) -> None:
    """全ページ結合 PDF を生成して Redis キャッシュに保存する。"""
    from django.core.cache import cache
    from .models import Project
    from .services.pdf_renderer import PDFRenderService

    try:
        project = Project.objects.prefetch_related('templates').get(pk=project_id)
        pages = project.pages.prefetch_related('images').order_by('order', 'id')
        pdf_bytes = PDFRenderService.merge_pages_bytes(project, pages, output_profile='preview')
        cache.set(cache_key, pdf_bytes, timeout=3600)
        logger.info('build_merged_pdf completed: project=%s cache_key=%s', project_id, cache_key)
    except SoftTimeLimitExceeded:
        logger.error('build_merged_pdf soft timeout: project=%s', project_id)
        raise
    except Exception as exc:
        logger.exception('build_merged_pdf failed: project=%s', project_id)
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    name='projects.build_pages_zip',
)
def build_pages_zip(self, project_id: int, cache_key: str) -> None:
    """全ページ ZIP（350dpi 印刷用）を生成して Redis キャッシュに保存する。"""
    from django.core.cache import cache
    from .models import Project
    from .services.pdf_renderer import PDFRenderService

    try:
        project = Project.objects.prefetch_related('templates').get(pk=project_id)
        pages = project.pages.prefetch_related('images').order_by('order', 'id')
        zip_bytes = PDFRenderService.zip_pages_bytes(project, pages)
        cache.set(cache_key, zip_bytes, timeout=3600)
        logger.info('build_pages_zip completed: project=%s cache_key=%s', project_id, cache_key)
    except SoftTimeLimitExceeded:
        logger.error('build_pages_zip soft timeout: project=%s', project_id)
        raise
    except Exception as exc:
        logger.exception('build_pages_zip failed: project=%s', project_id)
        raise self.retry(exc=exc)
