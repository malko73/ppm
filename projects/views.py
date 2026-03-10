import copy
import csv
import json
from io import StringIO
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.files.uploadedfile import UploadedFile
from django.db.models import Q
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from .forms import PageForm, ProjectForm
from .models import Page, Project, ProjectTemplate
from .services.pdf_renderer import PDFRenderService


def _ensure_project_templates(project: Project) -> None:
    if project.templates.exists() or not project.template_file:
        return
    ProjectTemplate.objects.create(
        project=project,
        name='既存テンプレート',
        template_file=project.template_file,
        default_positions=copy.deepcopy(project.default_positions or {}),
        is_default=True,
    )


def _ordered_text_fields(project: Project, template: ProjectTemplate | None = None) -> list[tuple[str, str]]:
    positions = (
        template.default_positions
        if template and template.default_positions
        else (project.default_positions or {})
    )
    text_fields: list[tuple[int, str, str]] = []
    for key, pos in positions.items():
        if not isinstance(pos, dict) or 'font_size' not in pos:
            continue
        order = int(pos.get('order') or 0)
        label = str(pos.get('label') or key)
        text_fields.append((order, key, label))
    text_fields.sort(key=lambda value: (value[0], value[1]))
    return [(key, label) for _, key, label in text_fields]


def _project_csv_headers(project: Project, template: ProjectTemplate | None = None) -> list[str]:
    text_fields = _ordered_text_fields(project, template)
    return ['ページ番号', 'ページ名'] + [key for key, _ in text_fields]


def _resolve_project_template(
    project: Project,
    template_id_raw: str | None,
    *,
    required: bool = False,
) -> ProjectTemplate | None:
    template_id = str(template_id_raw or '').strip()
    if template_id.isdigit():
        selected = project.templates.filter(pk=int(template_id)).first()
        if selected:
            return selected
    if required:
        raise ValueError('CSV対象テンプレートを選択してください。')
    return project.get_default_template()


def _validate_project_csv_upload(uploaded_file: UploadedFile | None) -> UploadedFile:
    if not uploaded_file:
        raise ValueError('CSVファイルを選択してください。')
    filename = (uploaded_file.name or '').lower()
    content_type = (uploaded_file.content_type or '').lower()
    if content_type.startswith('image/'):
        raise ValueError('画像ファイルはアップロードできません。CSVファイルを指定してください。')
    if not filename.endswith('.csv'):
        raise ValueError('CSVファイル（.csv）のみアップロードできます。')
    return uploaded_file


class UserProjectMixin(LoginRequiredMixin):
    model = Project

    def get_queryset(self):
        return Project.objects.filter(
            Q(user=self.request.user) | Q(participants=self.request.user)
        ).distinct()


class ProjectListView(UserProjectMixin, ListView):
    template_name = 'projects/project_list.html'
    context_object_name = 'projects'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        projects = list(context.get('projects') or [])

        grouped: dict[str, list[Project]] = {}
        for project in projects:
            category = (project.category or '').strip() or '未分類'
            grouped.setdefault(category, []).append(project)

        group_names = sorted(name for name in grouped.keys() if name != '未分類')
        project_groups: list[tuple[str, list[Project]]] = []
        if '未分類' in grouped:
            project_groups.append(('未分類', grouped['未分類']))
        for name in group_names:
            project_groups.append((name, grouped[name]))

        context['project_groups'] = project_groups
        return context


class ProjectCreateView(LoginRequiredMixin, CreateView):
    model = Project
    form_class = ProjectForm
    template_name = 'projects/project_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request_user'] = self.request.user
        kwargs['layout_target'] = self.request.POST.get('layout_target') or self.request.GET.get('layout_target')
        kwargs['delete_requested'] = bool(self.request.POST.get('delete_template'))
        return kwargs

    def form_valid(self, form):
        form.instance.user = self.request.user
        messages.success(self.request, 'プロジェクトを作成しました。')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('project_detail', kwargs={'pk': self.object.pk})


class ProjectDetailView(UserProjectMixin, DetailView):
    template_name = 'projects/project_detail.html'
    context_object_name = 'project'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        _ensure_project_templates(self.object)
        pages = self.object.pages.order_by('order', 'id')
        templates = self.object.templates.order_by('-is_default', 'id')
        context['pages'] = pages
        context['templates'] = templates
        context['template_size_mm'] = self.object.template_size_mm()
        context['all_pages_finalized'] = pages.exists() and not pages.filter(is_finalized=False).exists()
        return context


class ProjectUpdateView(UserProjectMixin, UpdateView):
    form_class = ProjectForm
    template_name = 'projects/project_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request_user'] = self.request.user
        kwargs['layout_target'] = self.request.POST.get('layout_target') or self.request.GET.get('layout_target')
        kwargs['delete_requested'] = bool(self.request.POST.get('delete_template'))
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        if form.cleaned_data.get('_delete_target_template'):
            messages.success(self.request, 'テンプレートを削除しました。')
        else:
            messages.success(self.request, 'プロジェクト設定を更新しました。')
        return response

    def get_success_url(self):
        return reverse('project_detail', kwargs={'pk': self.object.pk})


class ProjectDeleteView(UserProjectMixin, DeleteView):
    template_name = 'projects/project_confirm_delete.html'
    success_url = reverse_lazy('project_list')


@require_POST
@login_required
def copy_project(request, pk: int):
    source_project = get_object_or_404(
        Project.objects.filter(Q(user=request.user) | Q(participants=request.user)).distinct(),
        pk=pk,
    )

    copied_project = Project.objects.create(
        user=request.user,
        title=f'{source_project.title} (コピー)',
        category=source_project.category,
        description=source_project.description,
        template_file=source_project.template_file,
        default_positions=copy.deepcopy(source_project.default_positions or {}),
    )
    source_templates = list(source_project.templates.order_by('-is_default', 'id'))
    if source_templates:
        copied_templates = []
        for source_template in source_templates:
            copied_templates.append(
                ProjectTemplate.objects.create(
                    project=copied_project,
                    name=source_template.name,
                    template_file=source_template.template_file,
                    default_positions=copy.deepcopy(source_template.default_positions or {}),
                    is_default=source_template.is_default,
                )
            )
        if copied_templates and not copied_project.template_file:
            copied_project.template_file = copied_templates[0].template_file
            copied_project.save(update_fields=['template_file', 'updated_at'])
    elif source_project.template_file:
        template = ProjectTemplate.objects.create(
            project=copied_project,
            name='既存テンプレート',
            template_file=source_project.template_file,
            default_positions=copy.deepcopy(source_project.default_positions or {}),
            is_default=True,
        )
        if not copied_project.template_file:
            copied_project.template_file = template.template_file
            copied_project.save(update_fields=['template_file', 'updated_at'])

    if request.user.is_staff:
        copied_project.participants.set(source_project.participants.all())

    messages.success(request, 'プロジェクトをコピーしました。ページと入力データは引き継いでいません。')
    return redirect('project_detail', pk=copied_project.pk)


class UserPageMixin(LoginRequiredMixin):
    model = Page

    def dispatch(self, request, *args, **kwargs):
        self.project = get_object_or_404(
            Project.objects.filter(Q(user=request.user) | Q(participants=request.user)).distinct(),
            pk=self.kwargs['project_id'],
        )
        _ensure_project_templates(self.project)
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return Page.objects.filter(project=self.project)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['project'] = self.project
        kwargs['selected_template_id'] = (
            self.request.POST.get('project_template') or self.request.GET.get('template_id')
        )
        return kwargs


class PageCreateView(UserPageMixin, CreateView):
    form_class = PageForm
    template_name = 'projects/page_form.html'

    def form_valid(self, form):
        form.instance.project = self.project
        form.instance.order = Page.next_order(self.project)
        response = super().form_valid(form)
        Page.resequence(self.project)
        messages.success(self.request, 'ページを追加しました。')
        return response

    def get_success_url(self):
        return reverse('project_detail', kwargs={'pk': self.project.pk})


class PageUpdateView(UserPageMixin, UpdateView):
    form_class = PageForm
    template_name = 'projects/page_form.html'

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        if request.POST.get('apply_template'):
            template_id = str(request.POST.get('project_template') or '').strip()
            selected_template = self.project.templates.filter(pk=template_id).first() if template_id.isdigit() else None
            if not selected_template:
                messages.error(request, 'テンプレートの変更に失敗しました。')
                return redirect('page_update', project_id=self.project.pk, pk=self.object.pk)
            self.object.project_template = selected_template
            self.object.is_finalized = False
            self.object.save(update_fields=['project_template', 'is_finalized', 'updated_at'])
            messages.success(request, 'テンプレートを変更しました。')
            return redirect(f"{reverse('page_update', kwargs={'project_id': self.project.pk, 'pk': self.object.pk})}?template_id={selected_template.pk}")
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        if form.changed_data:
            messages.success(self.request, 'ページを更新しました。校了状態をOFFに戻しました。')
        else:
            messages.success(self.request, 'ページを更新しました。')
        return response

    def get_success_url(self):
        return reverse('project_detail', kwargs={'pk': self.project.pk})


class PageDeleteView(UserPageMixin, DeleteView):
    template_name = 'projects/page_confirm_delete.html'

    def get_form_kwargs(self):
        # DeleteView uses a plain Form, so do not inject PageForm-specific kwargs.
        return DeleteView.get_form_kwargs(self)

    def get_success_url(self):
        return reverse('project_detail', kwargs={'pk': self.project.pk})

    def delete(self, request, *args, **kwargs):
        response = super().delete(request, *args, **kwargs)
        Page.resequence(self.project)
        messages.success(request, 'ページを削除しました。')
        return response


@require_POST
@login_required
def toggle_page_finalized(request, project_id: int, pk: int):
    project = get_object_or_404(
        Project.objects.filter(Q(user=request.user) | Q(participants=request.user)).distinct(),
        pk=project_id,
    )
    page = get_object_or_404(Page, pk=pk, project=project)
    page.is_finalized = not page.is_finalized
    page.save(update_fields=['is_finalized', 'updated_at'])
    state_label = 'ON' if page.is_finalized else 'OFF'
    messages.success(request, f'校了状態を{state_label}に変更しました。')
    return redirect('project_detail', pk=project.pk)


@require_POST
@login_required
def reorder_pages(request, project_id: int):
    project = get_object_or_404(
        Project.objects.filter(Q(user=request.user) | Q(participants=request.user)).distinct(),
        pk=project_id,
    )
    order_ids = request.POST.get('order')
    if order_ids:
        order_ids = [id_.strip() for id_ in order_ids.split(',') if id_.strip()]
    else:
        try:
            body = json.loads(request.body.decode('utf-8'))
            order_ids = body['order']
        except (json.JSONDecodeError, KeyError):
            return HttpResponseBadRequest('Invalid payload')

    page_map = {page.id: page for page in project.pages.all()}
    for index, page_id in enumerate(order_ids, start=1):
        page = page_map.get(int(page_id))
        if not page:
            raise Http404('Page not found')
        page.order = index
        page.page_number = index
        page.save(update_fields=['order', 'page_number'])

    pages = project.pages.order_by('order', 'id')
    return render(request, 'partials/page_list.html', {'project': project, 'pages': pages})


@login_required
def download_single_page_pdf(request, project_id: int, pk: int):
    project = get_object_or_404(
        Project.objects.filter(Q(user=request.user) | Q(participants=request.user)).distinct(),
        pk=project_id,
    )
    page = get_object_or_404(Page, pk=pk, project=project)
    pdf_bytes = PDFRenderService.render_single_page_bytes(project, page, output_profile='preview')
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    page_name = slugify((page.page_name or '').strip(), allow_unicode=True)
    filename = f"{page.page_number:03d}.pdf"
    if page_name:
        filename = f"{page.page_number:03d}_{page_name}.pdf"
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    return response


@login_required
def download_merged_pdf(request, project_id: int):
    project = get_object_or_404(
        Project.objects.filter(Q(user=request.user) | Q(participants=request.user)).distinct(),
        pk=project_id,
    )
    pages = project.pages.order_by('order', 'id')
    if not pages.exists():
        return redirect('project_detail', pk=project.pk)
    pdf_bytes = PDFRenderService.merge_pages_bytes(project, pages, output_profile='preview')
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{project.title}_merged.pdf"'
    return response


@login_required
def download_pages_zip(request, project_id: int):
    project = get_object_or_404(
        Project.objects.filter(Q(user=request.user) | Q(participants=request.user)).distinct(),
        pk=project_id,
    )
    pages = project.pages.order_by('order', 'id')
    if not pages.exists():
        return redirect('project_detail', pk=project.pk)
    if pages.filter(is_finalized=False).exists():
        messages.error(request, '全ページを校了（ON）にするとZIPをダウンロードできます。')
        return redirect('project_detail', pk=project.pk)
    zip_bytes = PDFRenderService.zip_pages_bytes(project, pages)
    response = HttpResponse(zip_bytes, content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="{project.title}_pages.zip"'
    return response


@login_required
def download_pages_csv(request, project_id: int):
    project = get_object_or_404(
        Project.objects.filter(Q(user=request.user) | Q(participants=request.user)).distinct(),
        pk=project_id,
    )
    pages = project.pages.order_by('order', 'id')
    if not pages.exists():
        return redirect('project_detail', pk=project.pk)
    if pages.filter(is_finalized=False).exists():
        messages.error(request, '全ページを校了（ON）にするとCSVをダウンロードできます。')
        return redirect('project_detail', pk=project.pk)

    text_fields = _ordered_text_fields(project)
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response.write('\ufeff')
    filename = quote(f'{project.title}_pages.csv')
    response['Content-Disposition'] = f"attachment; filename*=UTF-8''{filename}"

    writer = csv.writer(response)
    headers = ['ページ番号', 'ページ名', '校了状態'] + [label for _, label in text_fields]
    writer.writerow(headers)

    for page in pages:
        input_data = page.input_data or {}
        row = [page.page_number, page.page_name, 'ON' if page.is_finalized else 'OFF']
        row.extend(str(input_data.get(key, '')) for key, _ in text_fields)
        writer.writerow(row)

    return response


@require_POST
@login_required
def upload_project_csv(request, project_id: int):
    project = get_object_or_404(
        Project.objects.filter(Q(user=request.user) | Q(participants=request.user)).distinct(),
        pk=project_id,
    )
    _ensure_project_templates(project)
    try:
        selected_template = _resolve_project_template(
            project,
            request.POST.get('template_id'),
            required=True,
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('project_detail', pk=project.pk)

    try:
        uploaded_file = _validate_project_csv_upload(request.FILES.get('csv_file'))
        raw = uploaded_file.read()
        text = raw.decode('utf-8-sig')
        reader = csv.reader(StringIO(text))
        rows = list(reader)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('project_detail', pk=project.pk)
    except UnicodeDecodeError:
        messages.error(request, 'CSVの文字コードはUTF-8でアップロードしてください。')
        return redirect('project_detail', pk=project.pk)
    except csv.Error:
        messages.error(request, 'CSVの形式が不正です。')
        return redirect('project_detail', pk=project.pk)

    if len(rows) < 2:
        messages.error(request, 'CSVにはヘッダー行と1件以上のデータ行が必要です。')
        return redirect('project_detail', pk=project.pk)

    expected_headers = _project_csv_headers(project, selected_template)
    actual_headers = [col.strip() for col in rows[0]]
    if len(actual_headers) != len(expected_headers):
        messages.error(
            request,
            f'CSVの項目数が不正です。期待: {len(expected_headers)}項目 / 実際: {len(actual_headers)}項目',
        )
        return redirect('project_detail', pk=project.pk)
    if actual_headers != expected_headers:
        messages.error(
            request,
            f'CSVヘッダーが一致しません。期待ヘッダー: {", ".join(expected_headers)}',
        )
        return redirect('project_detail', pk=project.pk)

    text_keys = expected_headers[2:]
    parsed_rows: list[tuple[int, str, dict[str, str]]] = []
    seen_page_numbers: set[int] = set()

    for index, row in enumerate(rows[1:], start=2):
        if len(row) != len(expected_headers):
            messages.error(request, f'{index}行目: 項目数が一致しません。')
            return redirect('project_detail', pk=project.pk)
        try:
            page_number = int((row[0] or '').strip())
        except ValueError:
            messages.error(request, f'{index}行目: ページ番号は整数で入力してください。')
            return redirect('project_detail', pk=project.pk)

        if page_number <= 0:
            messages.error(request, f'{index}行目: ページ番号は1以上で入力してください。')
            return redirect('project_detail', pk=project.pk)
        if page_number in seen_page_numbers:
            messages.error(request, f'{index}行目: ページ番号 {page_number} が重複しています。')
            return redirect('project_detail', pk=project.pk)
        seen_page_numbers.add(page_number)

        page_name = (row[1] or '').strip()
        input_data = {key: str(value or '').strip() for key, value in zip(text_keys, row[2:])}
        parsed_rows.append((page_number, page_name, input_data))

    page_map = {page.page_number: page for page in project.pages.all()}
    touched_numbers: set[int] = set()

    for page_number, page_name, input_data in parsed_rows:
        page = page_map.get(page_number)
        if page:
            page.page_name = page_name
            page.input_data = input_data
            page.project_template = selected_template
            page.is_finalized = False
            page.save(update_fields=['page_name', 'input_data', 'project_template', 'is_finalized', 'updated_at'])
        else:
            Page.objects.create(
                project=project,
                project_template=selected_template,
                order=page_number,
                page_number=page_number,
                page_name=page_name,
                input_data=input_data,
                is_finalized=False,
            )
        touched_numbers.add(page_number)

    for page in project.pages.exclude(page_number__in=touched_numbers):
        page.is_finalized = False
        page.save(update_fields=['is_finalized', 'updated_at'])

    Page.resequence(project)
    messages.success(
        request,
        f'CSVを取り込みました（{len(parsed_rows)}件 / テンプレート: {selected_template.name}）。画像はCSVからは登録されません。',
    )
    return redirect('project_detail', pk=project.pk)


@login_required
def download_project_csv_format(request, project_id: int):
    project = get_object_or_404(
        Project.objects.filter(Q(user=request.user) | Q(participants=request.user)).distinct(),
        pk=project_id,
    )
    _ensure_project_templates(project)
    try:
        selected_template = _resolve_project_template(
            project,
            request.GET.get('template_id'),
            required=True,
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('project_detail', pk=project.pk)

    headers = _project_csv_headers(project, selected_template)
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response.write('\ufeff')
    template_slug = slugify(selected_template.name, allow_unicode=True) or f'template-{selected_template.pk}'
    filename = quote(f'{project.title}_{template_slug}_format.csv')
    response['Content-Disposition'] = f"attachment; filename*=UTF-8''{filename}"
    writer = csv.writer(response)
    writer.writerow(headers)
    return response
