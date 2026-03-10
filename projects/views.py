import copy
import csv
import json
import uuid
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.text import slugify
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from .forms import PageForm, ProjectForm
from .models import Page, Project, ProjectTemplate
from .services.csv_import import CSVImportError, CSVImportService
from .services.pdf_renderer import PDFRenderService
from .tasks import build_pages_zip


def _user_project_qs(user):
    """ログインユーザーがアクセス可能なプロジェクトのクエリセットを返す。"""
    return (
        Project.objects.select_related('user')
        .prefetch_related('templates', 'participants')
        .filter(Q(user=user) | Q(participants=user))
        .distinct()
    )


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


def _ordered_text_fields(project: Project) -> list[tuple[str, str]]:
    positions = project.default_positions or {}
    text_fields: list[tuple[int, str, str]] = []
    for key, pos in positions.items():
        if not isinstance(pos, dict) or 'font_size' not in pos:
            continue
        order = int(pos.get('order') or 0)
        label = str(pos.get('label') or key)
        text_fields.append((order, key, label))
    text_fields.sort(key=lambda value: (value[0], value[1]))
    return [(key, label) for _, key, label in text_fields]


def _project_csv_headers(project: Project) -> list[str]:
    text_fields = _ordered_text_fields(project)
    return ['ページ番号', 'ページ名'] + [key for key, _ in text_fields]


class UserProjectMixin(LoginRequiredMixin):
    model = Project

    def get_queryset(self):
        return _user_project_qs(self.request.user)


class ProjectListView(UserProjectMixin, ListView):
    template_name = 'projects/project_list.html'
    context_object_name = 'projects'


class ProjectCreateView(LoginRequiredMixin, CreateView):
    model = Project
    form_class = ProjectForm
    template_name = 'projects/project_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request_user'] = self.request.user
        kwargs['layout_target'] = self.request.POST.get('layout_target') or self.request.GET.get('layout_target')
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
        return kwargs

    def get_success_url(self):
        return reverse('project_detail', kwargs={'pk': self.object.pk})


class ProjectDeleteView(UserProjectMixin, DeleteView):
    template_name = 'projects/project_confirm_delete.html'
    success_url = reverse_lazy('project_list')


@require_POST
@login_required
def copy_project(request, pk: int):
    source_project = get_object_or_404(_user_project_qs(request.user), pk=pk)

    copied_project = Project.objects.create(
        user=request.user,
        title=f'{source_project.title} (コピー)',
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
            _user_project_qs(request.user),
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
    project = get_object_or_404(_user_project_qs(request.user), pk=project_id)
    page = get_object_or_404(Page, pk=pk, project=project)
    page.is_finalized = not page.is_finalized
    page.save(update_fields=['is_finalized', 'updated_at'])
    state_label = 'ON' if page.is_finalized else 'OFF'
    messages.success(request, f'校了状態を{state_label}に変更しました。')
    return redirect('project_detail', pk=project.pk)


@require_POST
@login_required
def reorder_pages(request, project_id: int):
    project = get_object_or_404(_user_project_qs(request.user), pk=project_id)

    order_ids = request.POST.get('order')
    if order_ids:
        order_ids = [id_.strip() for id_ in order_ids.split(',') if id_.strip()]
    else:
        try:
            body = json.loads(request.body.decode('utf-8'))
            order_ids = body['order']
        except (json.JSONDecodeError, KeyError):
            return HttpResponseBadRequest('Invalid payload')

    with transaction.atomic():
        page_map = {page.id: page for page in project.pages.select_for_update()}

        # 存在しないページIDが含まれていれば先に検出する
        missing = [pid for pid in order_ids if page_map.get(int(pid)) is None]
        if missing:
            raise Http404('Page not found')

        updates: list[Page] = []
        for index, page_id in enumerate(order_ids, start=1):
            page = page_map[int(page_id)]
            page.order = index
            page.page_number = index
            updates.append(page)

        Page.objects.bulk_update(updates, ['order', 'page_number'])

    pages = project.pages.order_by('order', 'id')
    return render(request, 'partials/page_list.html', {'project': project, 'pages': pages})


@login_required
def download_single_page_pdf(request, project_id: int, pk: int):
    project = get_object_or_404(_user_project_qs(request.user), pk=project_id)
    page = get_object_or_404(Page, pk=pk, project=project)
    pdf_bytes = PDFRenderService.render_single_page_bytes(project, page, output_profile='preview')
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{project.title}_page_{page.page_number}.pdf"'
    return response


@login_required
def download_merged_pdf(request, project_id: int):
    project = get_object_or_404(_user_project_qs(request.user), pk=project_id)
    pages = project.pages.prefetch_related('images').order_by('order', 'id')
    if not pages.exists():
        return redirect('project_detail', pk=project.pk)
    pdf_bytes = PDFRenderService.merge_pages_bytes(project, pages, output_profile='preview')
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{project.title}_merged.pdf"'
    return response


# ---------------------------------------------------------------------------
# ZIPダウンロード（Celery非同期）
# ---------------------------------------------------------------------------

def _zip_cache_key(project_id: int, token: str) -> str:
    return f'project_zip_{project_id}_{token}'


@login_required
def start_pages_zip(request, project_id: int):
    """Celeryタスクを起動してZIP生成を開始し、待機ページへリダイレクトする。"""
    project = get_object_or_404(_user_project_qs(request.user), pk=project_id)
    pages = project.pages.only('is_finalized')

    if not pages.exists():
        return redirect('project_detail', pk=project.pk)
    if pages.filter(is_finalized=False).exists():
        messages.error(request, '全ページを校了（ON）にするとZIPをダウンロードできます。')
        return redirect('project_detail', pk=project.pk)

    token = uuid.uuid4().hex
    cache_key = _zip_cache_key(project_id, token)
    request.session[f'zip_token_{project_id}'] = token

    build_pages_zip.delay(project_id, cache_key)

    return redirect(reverse('project_pdf_zip_pending', kwargs={'project_id': project_id}))


@login_required
def download_pending_zip(request, project_id: int):
    """ZIP生成待機ページ。完了したらダウンロードリンクを表示する。"""
    project = get_object_or_404(_user_project_qs(request.user), pk=project_id)
    return render(request, 'projects/download_pending.html', {'project': project})


@login_required
def poll_pages_zip(request, project_id: int):
    """ZIP生成状況をJSONで返すポーリングエンドポイント。"""
    get_object_or_404(_user_project_qs(request.user), pk=project_id)

    token = request.session.get(f'zip_token_{project_id}')
    if not token:
        return JsonResponse({'status': 'error', 'message': 'セッションが見つかりません。再度お試しください。'})

    cache_key = _zip_cache_key(project_id, token)
    if cache.get(cache_key) is not None:
        return JsonResponse({'status': 'ready', 'download_url': reverse('project_pdf_zip_download', kwargs={'project_id': project_id})})

    return JsonResponse({'status': 'pending'})


@login_required
def download_pages_zip(request, project_id: int):
    """生成済みZIPをキャッシュから取り出してレスポンスとして返す。"""
    project = get_object_or_404(_user_project_qs(request.user), pk=project_id)

    token = request.session.get(f'zip_token_{project_id}')
    if not token:
        messages.error(request, 'ZIPの生成情報が見つかりません。再度お試しください。')
        return redirect('project_detail', pk=project.pk)

    cache_key = _zip_cache_key(project_id, token)
    zip_bytes = cache.get(cache_key)
    if zip_bytes is None:
        return redirect(reverse('project_pdf_zip_pending', kwargs={'project_id': project_id}))

    # 取得後はキャッシュとセッションを削除
    cache.delete(cache_key)
    del request.session[f'zip_token_{project_id}']

    response = HttpResponse(zip_bytes, content_type='application/zip')
    filename = quote(f'{project.title}_pages.zip')
    response['Content-Disposition'] = f"attachment; filename*=UTF-8''{filename}"
    return response


@login_required
def download_pages_csv(request, project_id: int):
    project = get_object_or_404(_user_project_qs(request.user), pk=project_id)
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
    project = get_object_or_404(_user_project_qs(request.user), pk=project_id)
    _ensure_project_templates(project)

    default_template = project.get_default_template()
    if not default_template:
        messages.error(request, 'テンプレートが設定されていません。')
        return redirect('project_detail', pk=project.pk)

    try:
        uploaded_file = CSVImportService.validate_file(request.FILES.get('csv_file'))
        service = CSVImportService(project=project, template=default_template)
        expected_headers = _project_csv_headers(project)
        parsed_rows = service.parse(uploaded_file, expected_headers)
        count = service.import_rows(parsed_rows)
    except CSVImportError as exc:
        messages.error(request, str(exc))
        return redirect('project_detail', pk=project.pk)

    messages.success(request, f'CSVを取り込みました（{count}件）。画像はCSVからは登録されません。')
    return redirect('project_detail', pk=project.pk)


@login_required
def download_project_csv_format(request, project_id: int):
    project = get_object_or_404(_user_project_qs(request.user), pk=project_id)
    headers = _project_csv_headers(project)
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response.write('\ufeff')
    filename = quote(f'{project.title}_format.csv')
    response['Content-Disposition'] = f"attachment; filename*=UTF-8''{filename}"
    writer = csv.writer(response)
    writer.writerow(headers)
    return response
