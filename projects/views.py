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
from django.utils.text import slugify
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from .forms import PageForm, ProjectForm
from .models import Page, Project, ProjectTemplate
from .services.csv_import import CSVImportError, CSVImportService
from .services.pdf_renderer import PDFRenderService
from .tasks import build_pages_zip
from .utils.coordinates import CoordinateConverter


def _user_project_qs(user):
    """ログインユーザーがアクセス可能なプロジェクトのクエリセットを返す。"""
    return (
        Project.objects.select_related('user')
        .prefetch_related('templates', 'participants')
        .filter(Q(user=user) | Q(participants=user))
        .distinct()
    )


def _project_category(project: Project) -> str:
    return str(getattr(project, 'category', '') or '').strip()


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


class UserProjectMixin(LoginRequiredMixin):
    model = Project

    def get_queryset(self):
        return _user_project_qs(self.request.user)


class ProjectListView(UserProjectMixin, ListView):
    template_name = 'projects/project_list.html'
    context_object_name = 'projects'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        projects = list(context.get('projects') or [])

        grouped: dict[str, list[Project]] = {}
        for project in projects:
            category = _project_category(project) or '未分類'
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
        
        # Progress display data
        total_pages = pages.count()
        finalized_pages = pages.filter(is_finalized=True).count()
        unfinalized_pages = total_pages - finalized_pages
        progress_percentage = int((finalized_pages / total_pages * 100)) if total_pages > 0 else 0
        last_modified = pages.order_by('-updated_at').first()
        last_modified_str = last_modified.updated_at.strftime('%m月%d日 %H:%M') if last_modified else '-'
        
        context['pages'] = pages
        context['templates'] = templates
        context['template_size_mm'] = self.object.template_size_mm()
        context['all_pages_finalized'] = pages.exists() and not pages.filter(is_finalized=False).exists()
        
        # Progress display context
        context['total_pages'] = total_pages
        context['finalized_pages'] = finalized_pages
        context['unfinalized_pages'] = unfinalized_pages
        context['progress_percentage'] = progress_percentage
        context['last_modified_str'] = last_modified_str
        
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
    source_project = get_object_or_404(_user_project_qs(request.user), pk=pk)

    create_kwargs = dict(
        user=request.user,
        title=f'{source_project.title} (コピー)',
        description=source_project.description,
        template_file=source_project.template_file,
        default_positions=copy.deepcopy(source_project.default_positions or {}),
    )
    if any(field.name == 'category' for field in Project._meta.get_fields()):
        create_kwargs['category'] = _project_category(source_project)
    copied_project = Project.objects.create(**create_kwargs)
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
    page_name = slugify((page.page_name or '').strip(), allow_unicode=True)
    filename = f"{page.page_number:03d}.pdf"
    if page_name:
        filename = f"{page.page_number:03d}_{page_name}.pdf"
    response['Content-Disposition'] = f'inline; filename="{filename}"'
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
        return JsonResponse({'status': 'ready', 'download_url': reverse('project_pdf_zip', kwargs={'project_id': project_id})})

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
        uploaded_file = CSVImportService.validate_file(request.FILES.get('csv_file'))
        service = CSVImportService(project=project, template=selected_template)
        expected_headers = _project_csv_headers(project, selected_template)
        parsed_rows = service.parse(uploaded_file, expected_headers)
        count = service.import_rows(parsed_rows)
    except CSVImportError as exc:
        messages.error(request, str(exc))
        return redirect('project_detail', pk=project.pk)

    messages.success(
        request,
        f'CSVを取り込みました（{count}件 / テンプレート: {selected_template.name}）。画像はCSVからは登録されません。',
    )
    return redirect('project_detail', pk=project.pk)


@login_required
def download_project_csv_format(request, project_id: int):
    project = get_object_or_404(_user_project_qs(request.user), pk=project_id)
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
@login_required
def layout_editor(request, project_id: int, template_id: int = None):
    """
    レイアウトエディタ UI
    
    GET: レイアウト編集画面を表示
    POST (JSON): ドラッグ・リサイズ後の座標を mm で保存
    
    Data flow:
    UI px座標 → mm変換 → DB保存 → PDF再生成で位置確認
    """
    project = get_object_or_404(
        _user_project_qs(request.user),
        pk=project_id
    )
    
    # テンプレート取得
    _ensure_project_templates(project)
    
    if template_id:
        template = get_object_or_404(project.templates, pk=template_id)
    else:
        template = project.get_default_template()
    
    if not template:
        messages.error(request, 'テンプレートがありません')
        return redirect('project_detail', pk=project_id)
    
    # ===== GET: レイアウト編集画面表示 =====
    if request.method == 'GET':
        # default_positions から text/image layout を抽出
        default_pos = template.default_positions or {}
        
        # テンプレートサイズ取得（デフォルト A4）
        template_width_mm = default_pos.get('width_mm', 210.0)
        template_height_mm = default_pos.get('height_mm', 297.0)
        
        # text_layout と image_layout を取得
        text_layout = []
        image_layout = []
        
        # 既存スキーマから抽出（複数フォーマットに対応）
        if 'text_layout' in default_pos and isinstance(default_pos['text_layout'], list):
            text_layout = default_pos['text_layout']
        elif 'text' in default_pos and isinstance(default_pos['text'], list):
            text_layout = default_pos['text']
        
        if 'image_layout' in default_pos and isinstance(default_pos['image_layout'], list):
            image_layout = default_pos['image_layout']
        elif 'image' in default_pos and isinstance(default_pos['image'], list):
            image_layout = default_pos['image']
        
        # Template rendering用に px 座標を計算（mm → px）
        px_per_mm_x = 600.0 / template_width_mm
        px_per_mm_y = 848.0 / template_height_mm
        
        text_layout_with_px = []
        for text in text_layout:
            text_copy = dict(text)
            text_copy['x_px'] = text.get('x', 0) * px_per_mm_x
            text_copy['y_px'] = text.get('y', 0) * px_per_mm_y
            text_copy['w_px'] = text.get('w', 0) * px_per_mm_x
            text_copy['h_px'] = text.get('h', 0) * px_per_mm_y
            text_layout_with_px.append(text_copy)
        
        image_layout_with_px = []
        for image in image_layout:
            image_copy = dict(image)
            image_copy['x_px'] = image.get('x', 0) * px_per_mm_x
            image_copy['y_px'] = image.get('y', 0) * px_per_mm_y
            image_copy['w_px'] = image.get('w', 0) * px_per_mm_x
            image_copy['h_px'] = image.get('h', 0) * px_per_mm_y
            image_layout_with_px.append(image_copy)
        
        context = {
            'project': project,
            'template': template,
            'text_layout': json.dumps(text_layout, ensure_ascii=False),
            'image_layout': json.dumps(image_layout, ensure_ascii=False),
            'text_layout_objects': text_layout_with_px,
            'image_layout_objects': image_layout_with_px,
            'template_width_mm': template_width_mm,
            'template_height_mm': template_height_mm,
        }
        
        return render(request, 'projects/layout_editor.html', context)
    
    # ===== POST: 座標更新（JSON） =====
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            
            element_type = data.get('type')  # 'text' or 'image'
            element_key = data.get('key')
            x_mm = float(data.get('x'))
            y_mm = float(data.get('y'))
            w_mm = float(data.get('w'))
            h_mm = float(data.get('h'))
            
            if element_type not in ('text', 'image'):
                return JsonResponse({
                    'status': 'error',
                    'message': f'Invalid type: {element_type}'
                }, status=400)
            
            if not element_key:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Missing element key'
                }, status=400)
            
            # default_positions を取得（新規作成）
            default_positions = template.default_positions or {}
            
            # テンプレートサイズを保持
            if 'width_mm' not in default_positions:
                default_positions['width_mm'] = 210.0
            if 'height_mm' not in default_positions:
                default_positions['height_mm'] = 297.0
            
            # ===== 座標更新: source of truth は mm =====
            if element_type == 'text':
                # text_layout リストを取得または初期化
                text_layout = default_positions.get('text_layout', [])
                if isinstance(text_layout, str):
                    text_layout = json.loads(text_layout)
                
                # element_key に対応するアイテムを更新
                found = False
                for item in text_layout:
                    if item.get('key') == element_key:
                        # mm 値を丸めて保存（source of truth）
                        item['x'] = CoordinateConverter.round_mm(x_mm, 2)
                        item['y'] = CoordinateConverter.round_mm(y_mm, 2)
                        item['w'] = CoordinateConverter.round_mm(w_mm, 2)
                        item['h'] = CoordinateConverter.round_mm(h_mm, 2)
                        found = True
                        break
                
                if not found:
                    return JsonResponse({
                        'status': 'error',
                        'message': f'Text element "{element_key}" not found'
                    }, status=404)
                
                default_positions['text_layout'] = text_layout
            
            elif element_type == 'image':
                # image_layout リストを取得または初期化
                image_layout = default_positions.get('image_layout', [])
                if isinstance(image_layout, str):
                    image_layout = json.loads(image_layout)
                
                # element_key に対応するアイテムを更新
                found = False
                for item in image_layout:
                    if item.get('key') == element_key:
                        # mm 値を丸めて保存（source of truth）
                        item['x'] = CoordinateConverter.round_mm(x_mm, 2)
                        item['y'] = CoordinateConverter.round_mm(y_mm, 2)
                        item['w'] = CoordinateConverter.round_mm(w_mm, 2)
                        item['h'] = CoordinateConverter.round_mm(h_mm, 2)
                        found = True
                        break
                
                if not found:
                    return JsonResponse({
                        'status': 'error',
                        'message': f'Image element "{element_key}" not found'
                    }, status=404)
                
                default_positions['image_layout'] = image_layout
            
            # テンプレートを保存
            template.default_positions = default_positions
            template.save(update_fields=['default_positions', 'updated_at'])
            
            return JsonResponse({
                'status': 'success',
                'message': f'{element_type} "{element_key}" の座標を更新しました',
                'saved_data': {
                    'x_mm': CoordinateConverter.round_mm(x_mm, 2),
                    'y_mm': CoordinateConverter.round_mm(y_mm, 2),
                    'w_mm': CoordinateConverter.round_mm(w_mm, 2),
                    'h_mm': CoordinateConverter.round_mm(h_mm, 2),
                }
            })
        
        except json.JSONDecodeError as e:
            return JsonResponse({
                'status': 'error',
                'message': f'Invalid JSON: {str(e)}'
            }, status=400)
        
        except (KeyError, ValueError, TypeError) as e:
            return JsonResponse({
                'status': 'error',
                'message': f'Invalid data: {str(e)}'
            }, status=400)
        
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': f'Server error: {str(e)}'
            }, status=500)
