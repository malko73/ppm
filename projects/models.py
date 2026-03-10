import copy

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Max
from pypdf import PdfReader

from .constants import DEFAULT_POSITIONS

PT_PER_MM = 72 / 25.4


def validate_pdf(file_obj):
    if file_obj.size > 100 * 1024 * 1024:
        raise ValidationError('テンプレートPDFは100MB以下にしてください。')

    current_pos = file_obj.tell()
    try:
        file_obj.seek(0)
        reader = PdfReader(file_obj)
    except Exception as exc:
        raise ValidationError('有効なPDFファイルをアップロードしてください。') from exc
    finally:
        file_obj.seek(current_pos)

    if not reader.pages:
        raise ValidationError('ページを含むPDFファイルをアップロードしてください。')


def validate_image_size(image):
    if image and image.size > 20 * 1024 * 1024:
        raise ValidationError('画像は1ファイル20MB以下にしてください。')


class Project(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='projects')
    participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='participating_projects',
        blank=True,
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    template_file = models.FileField(upload_to='templates/', validators=[validate_pdf], blank=True, null=True)
    default_positions = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self) -> str:
        return self.title

    def save(self, *args, **kwargs):
        if not self.default_positions:
            self.default_positions = copy.deepcopy(DEFAULT_POSITIONS)
        super().save(*args, **kwargs)

    def get_default_template(self) -> 'ProjectTemplate | None':
        template = self.templates.order_by('-is_default', 'id').first()
        if template:
            return template
        return None

    def template_size_mm(self, template: 'ProjectTemplate | None' = None) -> tuple[float, float] | None:
        target_template = template or self.get_default_template()
        template_file = target_template.template_file if target_template else self.template_file
        if not template_file:
            return None
        try:
            template_file.open('rb')
            reader = PdfReader(template_file)
            if not reader.pages:
                return None
            page = reader.pages[0]
            width_mm = round(float(page.mediabox.width) / PT_PER_MM, 1)
            height_mm = round(float(page.mediabox.height) / PT_PER_MM, 1)
            return width_mm, height_mm
        except Exception:
            return None
        finally:
            try:
                template_file.close()
            except Exception:
                pass


class ProjectTemplate(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='templates')
    name = models.CharField(max_length=255)
    template_file = models.FileField(upload_to='templates/', validators=[validate_pdf])
    default_positions = models.JSONField(default=dict, blank=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_default', 'id']

    def __str__(self) -> str:
        return f'{self.project.title} - {self.name}'


class Page(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='pages')
    project_template = models.ForeignKey(
        ProjectTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name='pages'
    )
    order = models.PositiveIntegerField(default=1)
    page_number = models.PositiveIntegerField(default=1)
    page_name = models.CharField(max_length=255, blank=True)
    is_finalized = models.BooleanField(default=False)
    input_data = models.JSONField(default=dict, blank=True)
    main_image = models.ImageField(upload_to='pages/', blank=True, null=True, validators=[validate_image_size])
    sub_image1 = models.ImageField(upload_to='pages/', blank=True, null=True, validators=[validate_image_size])
    sub_image2 = models.ImageField(upload_to='pages/', blank=True, null=True, validators=[validate_image_size])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self) -> str:
        return f'{self.project.title} - {self.page_name or self.page_number}'

    def clean(self):
        total_size = sum(
            image.size for image in [self.main_image, self.sub_image1, self.sub_image2] if image
        )
        if total_size > 50 * 1024 * 1024:
            raise ValidationError('Total image size per page must be 50MB or smaller.')

    @staticmethod
    def next_order(project: Project) -> int:
        max_order = project.pages.aggregate(max_order=Max('order')).get('max_order') or 0
        return max_order + 1

    def save(self, *args, **kwargs):
        if not self.order:
            self.order = self.next_order(self.project)
        self.input_data = self.input_data or {}
        super().save(*args, **kwargs)

    @classmethod
    def resequence(cls, project: Project):
        pages = list(project.pages.order_by('order', 'id'))
        updates: list[Page] = []
        for index, page in enumerate(pages, start=1):
            if page.order != index or page.page_number != index:
                page.order = index
                page.page_number = index
                updates.append(page)
        if updates:
            cls.objects.bulk_update(updates, ['order', 'page_number'])


class PageImage(models.Model):
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name='images')
    key = models.CharField(max_length=64)
    label = models.CharField(max_length=100, blank=True)
    image = models.ImageField(upload_to='pages/', validators=[validate_image_size])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('page', 'key')
        ordering = ['id']

    def __str__(self) -> str:
        return f'{self.page} - {self.key}'
