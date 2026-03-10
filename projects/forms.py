import json
import re
from typing import Any

from django import forms
from django.core.exceptions import ValidationError

from .constants import DEFAULT_FIELD_LABELS, DEFAULT_POSITIONS
from .models import Page, PageImage, Project, ProjectTemplate, validate_pdf

PT_PER_MM = 72 / 25.4
VALID_KEY_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]{0,63}$')
FIXED_IMAGE_KEYS = {'main_image', 'sub_image1', 'sub_image2'}
VALID_HEX_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')
HORIZONTAL_FONT_WEIGHTS = {'normal', 'medium', 'bold'}
HORIZONTAL_TEXT_ALIGNS = {'left', 'center', 'right'}
HAS_PROJECT_CATEGORY_FIELD = any(field.name == 'category' for field in Project._meta.get_fields())


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    widget = MultipleFileInput

    def clean(self, data, initial=None):
        if not data:
            return []
        if not isinstance(data, (list, tuple)):
            data = [data]
        cleaned_files = []
        errors = []
        for uploaded in data:
            try:
                cleaned_files.append(super().clean(uploaded, initial))
            except ValidationError as exc:
                errors.extend(exc.error_list)
        if errors:
            raise ValidationError(errors)
        return cleaned_files


def pt_to_mm(value: float) -> float:
    return round(float(value) / PT_PER_MM, 1)


def mm_to_pt(value: float) -> float:
    return round(float(value) * PT_PER_MM, 2)


def _positions_dict(
    project: Project | None,
    project_template: ProjectTemplate | None = None,
) -> dict[str, dict[str, Any]]:
    if project_template and project_template.default_positions:
        return project_template.default_positions
    if project and project.default_positions:
        return project.default_positions
    return DEFAULT_POSITIONS


def _is_same_as_default_positions(positions: dict[str, dict[str, Any]]) -> bool:
    return positions == DEFAULT_POSITIONS


class ProjectForm(forms.ModelForm):
    text_layout_json = forms.CharField(widget=forms.HiddenInput(), required=False)
    image_layout_json = forms.CharField(widget=forms.HiddenInput(), required=False)
    layout_target = forms.ChoiceField(required=False, label='レイアウト編集対象')
    template_files = MultipleFileField(
        required=False,
        label='テンプレートPDF',
        help_text='複数選択でまとめて登録できます（各100MB以下）。',
    )
    replace_template_target = forms.ChoiceField(required=False, label='差し替え対象テンプレート')
    replace_template_file = forms.FileField(
        required=False,
        label='差し替えPDF',
        help_text='選択した登録済みテンプレートを新しいPDFで差し替えます。',
    )
    default_template_target = forms.ChoiceField(required=False, label='既定テンプレート')
    delete_template_target = forms.ChoiceField(required=False, label='削除対象テンプレート')

    class Meta:
        model = Project
        fields = ['title', 'description']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        kwargs.pop('request_user', None)
        self.layout_target = str(kwargs.pop('layout_target', '') or '').strip()
        self.delete_requested = bool(kwargs.pop('delete_requested', False))
        super().__init__(*args, **kwargs)
        self.existing_templates = []
        template_choices = [('__project__', '基本サンプル')]
        replace_choices = [('', '選択してください')]
        default_choices = [('', '選択してください')]
        delete_choices = [('', '選択してください')]
        if getattr(self.instance, 'pk', None):
            self.existing_templates = list(self.instance.templates.order_by('-is_default', 'id'))
            for template in self.existing_templates:
                template_choices.append((str(template.id), template.name))
                replace_choices.append((str(template.id), template.name))
                default_choices.append((str(template.id), template.name))
                delete_choices.append((str(template.id), template.name))
        self.fields['layout_target'].choices = template_choices
        self.fields['replace_template_target'].choices = replace_choices
        self.fields['default_template_target'].choices = default_choices
        self.fields['delete_template_target'].choices = delete_choices
        if HAS_PROJECT_CATEGORY_FIELD:
            self.fields['category'] = forms.CharField(
                required=False,
                label='カテゴリ',
                initial=getattr(self.instance, 'category', ''),
                widget=forms.TextInput(attrs={'placeholder': '例: グルメ, 観光'}),
            )
        if not self.existing_templates:
            self.fields['replace_template_target'].disabled = True
            self.fields['replace_template_file'].disabled = True
            self.fields['default_template_target'].choices = [('', '登録済みテンプレートなし')]
            self.fields['default_template_target'].disabled = True
            self.fields['default_template_target'].help_text = 'テンプレート登録後に設定できます。'
            self.fields['delete_template_target'].choices = [('', '登録済みテンプレートなし')]
            self.fields['delete_template_target'].disabled = True
            self.fields['delete_template_target'].help_text = 'テンプレート登録後に削除できます。'
        else:
            default_template = next((t for t in self.existing_templates if t.is_default), self.existing_templates[0])
            self.fields['default_template_target'].initial = str(default_template.pk)
            self.fields['default_template_target'].help_text = 'プロジェクトで既定に使うテンプレートを選択します。'
            self.fields['delete_template_target'].help_text = '選択したテンプレートを削除します。'
        if self.layout_target:
            selected_target = self.layout_target
        else:
            selected_target = '__project__'
        valid_targets = {choice[0] for choice in template_choices}
        if selected_target not in valid_targets:
            selected_target = '__project__'
        self.fields['layout_target'].initial = selected_target

        selected_template = next((t for t in self.existing_templates if str(t.id) == selected_target), None)
        positions = _positions_dict(getattr(self, 'instance', None), selected_template)
        if _is_same_as_default_positions(positions):
            positions = {}

        text_rows: list[dict[str, Any]] = []
        image_rows: list[dict[str, Any]] = []
        for key, pos in positions.items():
            if key == 'icon_image':
                continue
            label = str(pos.get('label') or DEFAULT_FIELD_LABELS.get(key, key))
            row_base = {
                'key': key,
                'label': label,
                'x': pt_to_mm(pos.get('x', 0)),
                'y': pt_to_mm(pos.get('y', 0)),
                'w': pt_to_mm(pos.get('w', 120)),
                'h': pt_to_mm(pos.get('h', 80)),
            }
            if 'font_size' in pos:
                text_rows.append(
                    {
                        **row_base,
                        'font_size': int(pos.get('font_size', 12)),
                        'writing_mode': str(pos.get('writing_mode', 'horizontal')),
                        'font_family': str(pos.get('font_family', 'gothic')),
                        'horizontal_font_weight': str(pos.get('horizontal_font_weight', 'normal')),
                        'horizontal_text_color': str(pos.get('horizontal_text_color', '#000000')),
                        'horizontal_text_align': str(pos.get('horizontal_text_align', 'left')),
                    }
                )
            else:
                image_rows.append(row_base)

        self.fields['text_layout_json'].initial = json.dumps(text_rows, ensure_ascii=False)
        self.fields['image_layout_json'].initial = json.dumps(image_rows, ensure_ascii=False)

        for field in self.fields.values():
            if isinstance(field.widget, forms.HiddenInput):
                continue
            field.widget.attrs['class'] = 'form-control'

    def save(self, commit=True):
        instance = super().save(commit=False)
        if HAS_PROJECT_CATEGORY_FIELD and 'category' in self.cleaned_data:
            instance.category = self.cleaned_data['category']
        if commit:
            instance.save()
            self.save_m2m()
        return instance

    @staticmethod
    def _as_float(raw_value: Any, field_name: str, min_value: float) -> float:
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f'{field_name} は数値で入力してください。') from exc
        if value < min_value:
            raise ValidationError(f'{field_name} は {min_value} 以上で入力してください。')
        return value

    @staticmethod
    def _parse_rows(payload: str, row_type: str) -> list[dict[str, Any]]:
        try:
            rows = json.loads(payload or '[]')
        except json.JSONDecodeError as exc:
            raise ValidationError('配置データの形式が不正です。') from exc
        if not isinstance(rows, list):
            raise ValidationError('配置データの形式が不正です。')

        parsed: list[dict[str, Any]] = []
        seen_keys: set[str] = set()

        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                raise ValidationError(f'{row_type} {index} 行目の形式が不正です。')
            key = str(row.get('key', '')).strip()
            label = str(row.get('label', '')).strip()
            if not key or not VALID_KEY_RE.match(key):
                raise ValidationError(f'{row_type} {index} 行目: キーは英字開始の英数字/アンダースコアで入力してください。')
            if key in seen_keys:
                raise ValidationError(f'{row_type} {index} 行目: キー「{key}」が重複しています。')
            if not label:
                raise ValidationError(f'{row_type} {index} 行目: 項目名は必須です。')

            seen_keys.add(key)
            item: dict[str, Any] = {
                'key': key,
                'label': label,
                'x': ProjectForm._as_float(row.get('x'), f'{row_type} {index} 行目 X', 0),
                'y': ProjectForm._as_float(row.get('y'), f'{row_type} {index} 行目 Y', 0),
                'w': ProjectForm._as_float(row.get('w'), f'{row_type} {index} 行目 幅', 0.1),
                'h': ProjectForm._as_float(row.get('h'), f'{row_type} {index} 行目 高さ', 0.1),
            }
            if row_type == 'テキスト':
                font_size = int(ProjectForm._as_float(row.get('font_size'), f'{row_type} {index} 行目 文字サイズ', 1))
                writing_mode = str(row.get('writing_mode', 'horizontal')).strip().lower()
                font_family = str(row.get('font_family', 'gothic')).strip().lower()
                if writing_mode not in {'horizontal', 'vertical'}:
                    raise ValidationError(f'{row_type} {index} 行目: 文字方向が不正です。')
                if font_family not in {'gothic', 'mincho'}:
                    raise ValidationError(f'{row_type} {index} 行目: フォントが不正です。')
                horizontal_font_weight = str(row.get('horizontal_font_weight', 'normal')).strip().lower()
                horizontal_text_color = str(row.get('horizontal_text_color', '#000000')).strip()
                horizontal_text_align = str(row.get('horizontal_text_align', 'left')).strip().lower()
                if writing_mode == 'horizontal':
                    if horizontal_font_weight not in HORIZONTAL_FONT_WEIGHTS:
                        raise ValidationError(f'{row_type} {index} 行目: 横書き文字の太さが不正です。')
                    if not VALID_HEX_COLOR_RE.match(horizontal_text_color):
                        raise ValidationError(f'{row_type} {index} 行目: 横書き文字色は #RRGGBB 形式で入力してください。')
                    if horizontal_text_align not in HORIZONTAL_TEXT_ALIGNS:
                        raise ValidationError(f'{row_type} {index} 行目: 横書き文字の寄せ位置が不正です。')
                else:
                    horizontal_font_weight = 'normal'
                    horizontal_text_color = '#000000'
                    horizontal_text_align = 'left'
                item['font_size'] = font_size
                item['writing_mode'] = writing_mode
                item['font_family'] = font_family
                item['horizontal_font_weight'] = horizontal_font_weight
                item['horizontal_text_color'] = horizontal_text_color.upper()
                item['horizontal_text_align'] = horizontal_text_align
            parsed.append(item)

        return parsed

    def clean(self):
        cleaned_data = super().clean()
        text_rows = self._parse_rows(cleaned_data.get('text_layout_json', ''), 'テキスト')
        image_rows = self._parse_rows(cleaned_data.get('image_layout_json', ''), '画像')

        text_keys = {row['key'] for row in text_rows}
        image_keys = {row['key'] for row in image_rows}
        overlap = text_keys.intersection(image_keys)
        if overlap:
            raise ValidationError(f'テキストと画像で同じキーは使えません: {", ".join(sorted(overlap))}')

        uploaded_templates = cleaned_data.get('template_files') or []
        for uploaded_template in uploaded_templates:
            validate_pdf(uploaded_template)
        if not self.instance.pk and not uploaded_templates:
            raise ValidationError('テンプレートPDFを1つ以上アップロードしてください。')
        if self.instance.pk and not uploaded_templates:
            has_existing_templates = self.instance.templates.exists() or bool(self.instance.template_file)
            if not has_existing_templates:
                raise ValidationError('テンプレートPDFを1つ以上アップロードしてください。')

        cleaned_data['_text_rows'] = text_rows
        cleaned_data['_image_rows'] = image_rows
        cleaned_data['_template_files'] = uploaded_templates
        cleaned_data['_layout_target'] = cleaned_data.get('layout_target') or '__project__'

        replace_target_raw = str(cleaned_data.get('replace_template_target') or '').strip()
        replace_template_file = cleaned_data.get('replace_template_file')
        if replace_target_raw and not replace_template_file:
            raise ValidationError('テンプレートを差し替える場合は、差し替えPDFを選択してください。')
        if replace_template_file and not replace_target_raw:
            raise ValidationError('テンプレートを差し替える場合は、差し替え対象テンプレートを選択してください。')

        replace_target_template = None
        if replace_target_raw:
            if not self.instance.pk:
                raise ValidationError('テンプレートの差し替えは、作成済みプロジェクトでのみ利用できます。')
            if not replace_target_raw.isdigit():
                raise ValidationError('差し替え対象テンプレートが不正です。')
            replace_target_template = self.instance.templates.filter(pk=int(replace_target_raw)).first()
            if not replace_target_template:
                raise ValidationError('差し替え対象テンプレートが見つかりません。')
            validate_pdf(replace_template_file)
        cleaned_data['_replace_target_template'] = replace_target_template
        cleaned_data['_replace_template_file'] = replace_template_file

        default_target_raw = str(cleaned_data.get('default_template_target') or '').strip()
        default_target_template = None
        if default_target_raw:
            if not self.instance.pk:
                raise ValidationError('既定テンプレートの設定は、作成済みプロジェクトでのみ利用できます。')
            if not default_target_raw.isdigit():
                raise ValidationError('既定テンプレートの指定が不正です。')
            default_target_template = self.instance.templates.filter(pk=int(default_target_raw)).first()
            if not default_target_template:
                raise ValidationError('既定テンプレートに指定したテンプレートが見つかりません。')
        cleaned_data['_default_target_template'] = default_target_template

        delete_target_raw = str(cleaned_data.get('delete_template_target') or '').strip() if self.delete_requested else ''
        delete_target_template = None
        if delete_target_raw:
            if not self.instance.pk:
                raise ValidationError('テンプレートの削除は、作成済みプロジェクトでのみ利用できます。')
            if not delete_target_raw.isdigit():
                raise ValidationError('削除対象テンプレートの指定が不正です。')
            delete_target_template = self.instance.templates.filter(pk=int(delete_target_raw)).first()
            if not delete_target_template:
                raise ValidationError('削除対象テンプレートが見つかりません。')
            remaining_count = self.instance.templates.exclude(pk=delete_target_template.pk).count() + len(uploaded_templates)
            if remaining_count <= 0:
                raise ValidationError('テンプレートは最低1件必要です。削除する場合は先に別テンプレートを登録してください。')
            if default_target_template and default_target_template.pk == delete_target_template.pk:
                raise ValidationError('削除対象テンプレートは既定テンプレートに設定できません。')
        cleaned_data['_delete_target_template'] = delete_target_template
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        text_rows = self.cleaned_data.get('_text_rows', [])
        image_rows = self.cleaned_data.get('_image_rows', [])
        has_layout_updates = bool(text_rows or image_rows)

        positions: dict[str, dict[str, Any]] = {}
        if has_layout_updates:
            for index, row in enumerate(text_rows, start=1):
                positions[row['key']] = {
                    'label': row['label'],
                    'x': mm_to_pt(row['x']),
                    'y': mm_to_pt(row['y']),
                    'w': mm_to_pt(row['w']),
                    'h': mm_to_pt(row['h']),
                    'font_size': row['font_size'],
                    'writing_mode': row['writing_mode'],
                    'font_family': row['font_family'],
                    'horizontal_font_weight': row['horizontal_font_weight'],
                    'horizontal_text_color': row['horizontal_text_color'],
                    'horizontal_text_align': row['horizontal_text_align'],
                    'order': index,
                }

            for index, row in enumerate(image_rows, start=1):
                positions[row['key']] = {
                    'label': row['label'],
                    'x': mm_to_pt(row['x']),
                    'y': mm_to_pt(row['y']),
                    'w': mm_to_pt(row['w']),
                    'h': mm_to_pt(row['h']),
                    'order': index,
                }

        if commit:
            layout_target = str(self.cleaned_data.get('_layout_target') or '__project__')
            if layout_target == '__project__' and has_layout_updates:
                instance.default_positions = positions
            instance.save()
            if layout_target != '__project__' and has_layout_updates:
                target_template = instance.templates.filter(pk=layout_target).first()
                if target_template:
                    target_template.default_positions = positions
                    target_template.save(update_fields=['default_positions', 'updated_at'])
            uploaded_templates = self.cleaned_data.get('_template_files', [])
            existing_count = instance.templates.count()
            for index, uploaded_template in enumerate(uploaded_templates, start=1):
                filename = str(uploaded_template.name or '').strip()
                template_name = filename.rsplit('/', 1)[-1] if filename else f'テンプレート {existing_count + index}'
                template = ProjectTemplate.objects.create(
                    project=instance,
                    name=template_name,
                    template_file=uploaded_template,
                    default_positions=(positions if has_layout_updates else (instance.default_positions or DEFAULT_POSITIONS)),
                    is_default=(existing_count == 0 and index == 1),
                )
                if not instance.template_file:
                    instance.template_file = template.template_file
                    instance.save(update_fields=['template_file', 'updated_at'])
            replace_target_template = self.cleaned_data.get('_replace_target_template')
            replace_template_file = self.cleaned_data.get('_replace_template_file')
            if replace_target_template and replace_template_file:
                replace_target_template.template_file = replace_template_file
                replace_target_template.save(update_fields=['template_file', 'updated_at'])
                if replace_target_template.is_default or not instance.template_file:
                    instance.template_file = replace_target_template.template_file
                    instance.save(update_fields=['template_file', 'updated_at'])
            delete_target_template = self.cleaned_data.get('_delete_target_template')
            if delete_target_template:
                deleting_template = instance.templates.filter(pk=delete_target_template.pk).first()
                if deleting_template:
                    linked_pages = list(deleting_template.pages.values_list('pk', flat=True))
                    was_default = deleting_template.is_default
                    deleting_template.delete()
                    fallback_template = instance.templates.order_by('-is_default', 'id').first()
                    if linked_pages and fallback_template:
                        Page.objects.filter(pk__in=linked_pages).update(project_template=fallback_template, is_finalized=False)
                    if was_default and fallback_template:
                        instance.templates.update(is_default=False)
                        fallback_template.is_default = True
                        fallback_template.save(update_fields=['is_default', 'updated_at'])
            default_target_template = self.cleaned_data.get('_default_target_template')
            if default_target_template:
                instance.templates.update(is_default=False)
                selected_default = instance.templates.filter(pk=default_target_template.pk).first()
                if selected_default:
                    selected_default.is_default = True
                    selected_default.save(update_fields=['is_default', 'updated_at'])
            if not instance.templates.filter(is_default=True).exists():
                fallback_template = instance.templates.order_by('id').first()
                if fallback_template:
                    fallback_template.is_default = True
                    fallback_template.save(update_fields=['is_default', 'updated_at'])
            selected_default = instance.get_default_template()
            if selected_default and instance.template_file != selected_default.template_file:
                instance.template_file = selected_default.template_file
                instance.save(update_fields=['template_file', 'updated_at'])
        return instance


class PageForm(forms.ModelForm):
    class Meta:
        model = Page
        fields = ['page_name', 'project_template']

    def __init__(self, *args, **kwargs):
        self.project: Project | None = kwargs.pop('project', None)
        self.selected_template_id = str(kwargs.pop('selected_template_id', '') or '').strip()
        super().__init__(*args, **kwargs)

        if self.project is None and getattr(self.instance, 'project_id', None):
            self.project = self.instance.project
        if self.project:
            template_queryset = self.project.templates.order_by('-is_default', 'id')
        else:
            template_queryset = ProjectTemplate.objects.none()
        self.fields['project_template'].queryset = template_queryset
        self.fields['project_template'].required = True
        if not self.instance.pk and template_queryset.exists():
            self.fields['project_template'].initial = template_queryset.first()
        if self.selected_template_id.isdigit():
            selected_initial_template = template_queryset.filter(pk=int(self.selected_template_id)).first()
            if selected_initial_template:
                self.fields['project_template'].initial = selected_initial_template
                self.initial['project_template'] = selected_initial_template.pk
        selected_template = None
        if self.is_bound:
            template_id = str(self.data.get('project_template', '')).strip()
            if template_id.isdigit():
                selected_template = template_queryset.filter(pk=int(template_id)).first()
        if selected_template is None and self.selected_template_id.isdigit():
            selected_template = template_queryset.filter(pk=int(self.selected_template_id)).first()
        if selected_template is None and getattr(self.instance, 'project_template_id', None):
            selected_template = template_queryset.filter(pk=self.instance.project_template_id).first()
        if selected_template is None and template_queryset.exists():
            selected_template = template_queryset.first()

        self.text_meta: list[dict[str, str]] = []
        self.image_meta: list[dict[str, str]] = []
        self.text_fields_for_template: list[Any] = []
        self.image_fields_for_template: list[dict[str, Any]] = []

        positions = _positions_dict(self.project, selected_template)
        input_data = getattr(self.instance, 'input_data', {}) or {}
        existing_dynamic_images = {
            image.key: image
            for image in (self.instance.images.all() if getattr(self.instance, 'pk', None) else [])
        }

        for key, pos in positions.items():
            label = str(pos.get('label') or DEFAULT_FIELD_LABELS.get(key, key))
            if 'font_size' in pos:
                field_name = f'text__{key}'
                self.fields[field_name] = forms.CharField(
                    required=False,
                    label=label,
                    widget=forms.Textarea(attrs={'rows': 3}),
                )
                self.fields[field_name].initial = input_data.get(key, '')
                self.text_meta.append({'key': key, 'field_name': field_name})
                self.text_fields_for_template.append(self[field_name])
                continue

            field_name = f'image__{key}'
            clear_field = f'image_clear__{key}'
            self.fields[field_name] = forms.ImageField(required=False, label=label)
            self.fields[clear_field] = forms.BooleanField(required=False, label='削除')

            if key in FIXED_IMAGE_KEYS:
                current_image = getattr(self.instance, key, None)
                if current_image:
                    self.fields[field_name].help_text = f'現在: {current_image.name}'
            else:
                current_image = existing_dynamic_images.get(key)
                if current_image:
                    self.fields[field_name].help_text = f'現在: {current_image.image.name}'

            self.image_meta.append({'key': key, 'label': label, 'field_name': field_name, 'clear_field': clear_field})
            self.image_fields_for_template.append(
                {
                    'image_field': self[field_name],
                    'clear_field': self[clear_field],
                }
            )

        for name, field in self.fields.items():
            if isinstance(field, forms.BooleanField):
                field.widget.attrs['class'] = 'form-check-input'
            elif isinstance(field, forms.ImageField):
                field.widget.attrs['class'] = 'form-control-file'
            else:
                field.widget.attrs['class'] = 'form-control'

    def _save_images(self, instance: Page):
        dynamic_images = {image.key: image for image in instance.images.all()}
        configured_image_keys = {meta['key'] for meta in self.image_meta}

        save_instance = False
        for meta in self.image_meta:
            key = meta['key']
            uploaded = self.cleaned_data.get(meta['field_name'])
            clear = self.cleaned_data.get(meta['clear_field'])

            if key in FIXED_IMAGE_KEYS:
                current = getattr(instance, key)
                if clear and current:
                    current.delete(save=False)
                    setattr(instance, key, None)
                    save_instance = True
                if uploaded:
                    setattr(instance, key, uploaded)
                    save_instance = True
                continue

            current_dynamic = dynamic_images.get(key)
            if clear and current_dynamic:
                current_dynamic.image.delete(save=False)
                current_dynamic.delete()
                current_dynamic = None

            if uploaded:
                if current_dynamic:
                    if current_dynamic.image:
                        current_dynamic.image.delete(save=False)
                    current_dynamic.image = uploaded
                    current_dynamic.label = meta.get('label', current_dynamic.label)
                    current_dynamic.save(update_fields=['image', 'label', 'updated_at'])
                else:
                    PageImage.objects.create(page=instance, key=key, label=meta.get('label', ''), image=uploaded)
            elif current_dynamic and meta.get('label') and current_dynamic.label != meta.get('label'):
                current_dynamic.label = meta['label']
                current_dynamic.save(update_fields=['label', 'updated_at'])

        for key, dynamic_image in dynamic_images.items():
            if key not in configured_image_keys:
                dynamic_image.image.delete(save=False)
                dynamic_image.delete()

        if save_instance:
            instance.save()

    def save(self, commit=True):
        instance = super().save(commit=False)
        data = instance.input_data or {}
        for meta in self.text_meta:
            data[meta['key']] = self.cleaned_data.get(meta['field_name'], '')
        instance.input_data = data
        if self.changed_data:
            instance.is_finalized = False

        if commit:
            instance.save()
            self._save_images(instance)

        return instance
