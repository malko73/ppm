from celery import shared_task

from .models import Project
from .services.pdf_renderer import PDFRenderService


@shared_task
def build_merged_pdf(project_id: int) -> bytes:
    project = Project.objects.get(pk=project_id)
    pages = project.pages.order_by('order', 'id')
    return PDFRenderService.merge_pages_bytes(project, pages)
