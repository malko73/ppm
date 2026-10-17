"""
Test suite for Layout Editor (Issue #5 P0 Vertical Slice)

Focus: Coordinate system accuracy and data persistence
"""

import io
import json
import tempfile

import pytest
from django.core.files.base import ContentFile
from django.test import Client, TestCase, override_settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from pypdf import PdfReader
from reportlab.pdfgen import canvas as reportlab_canvas

from projects.models import Page, Project, ProjectTemplate
from projects.services.pdf_renderer import PDFRenderService
from projects.utils.coordinates import POINTS_PER_MM, CoordinateConverter

User = get_user_model()


class CoordinateConverterTest(TestCase):
    """座標変換ユーティリティのテスト"""
    
    def test_mm_to_px_horizontal(self):
        """mm → px (horizontal axis)"""
        # A4: 210mm width → 600px display
        x_mm = 105.0
        x_px = CoordinateConverter.mm_to_px(x_mm, 'x')
        self.assertAlmostEqual(x_px, 300.0, places=1)
    
    def test_mm_to_px_vertical(self):
        """mm → px (vertical axis)"""
        # A4: 297mm height → 848px display
        y_mm = 148.5
        y_px = CoordinateConverter.mm_to_px(y_mm, 'y')
        self.assertAlmostEqual(y_px, 424.0, places=1)
    
    def test_px_to_mm_horizontal(self):
        """px → mm (horizontal axis) - reverse transformation"""
        x_px = 300.0
        x_mm = CoordinateConverter.px_to_mm(x_px, 'x')
        self.assertAlmostEqual(x_mm, 105.0, places=1)
    
    def test_px_to_mm_vertical(self):
        """px → mm (vertical axis) - reverse transformation"""
        y_px = 424.0
        y_mm = CoordinateConverter.px_to_mm(y_px, 'y')
        self.assertAlmostEqual(y_mm, 148.5, places=1)
    
    def test_mm_to_pt(self):
        """mm → pt conversion for PDF rendering"""
        x_mm = 10.0
        x_pt = CoordinateConverter.mm_to_pt(x_mm)
        self.assertAlmostEqual(x_pt, 28.35, places=2)
    
    def test_pt_to_mm(self):
        """pt → mm conversion (reverse)"""
        x_pt = 28.35
        x_mm = CoordinateConverter.pt_to_mm(x_pt)
        self.assertAlmostEqual(x_mm, 10.0, places=2)
    
    def test_round_mm(self):
        """mm value rounding for storage"""
        value = 15.12345
        rounded = CoordinateConverter.round_mm(value, 2)
        self.assertEqual(rounded, 15.12)
    
    def test_custom_template_size(self):
        """Scale factors for non-A4 templates"""
        # Custom: 200mm × 300mm
        px_per_mm_x, px_per_mm_y = CoordinateConverter.get_scale_factors(200.0, 300.0)
        
        # 200mm → 600px means 3px/mm
        self.assertAlmostEqual(px_per_mm_x, 3.0, places=2)
        
        # 300mm → 848px means ~2.827 px/mm
        self.assertAlmostEqual(px_per_mm_y, 2.827, places=2)


class LayoutEditorViewTest(TestCase):
    """レイアウトエディタビューのテスト"""
    
    def setUp(self):
        # Create test user
        self.user = User.objects.create_superuser(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create test project
        self.project = Project.objects.create(
            user=self.user,
            title='Test Project',
            description='Test Description'
        )
        
        # Create test template
        self.template = ProjectTemplate.objects.create(
            project=self.project,
            name='Test Template',
            is_default=True,
            default_positions={
                'width_mm': 210.0,
                'height_mm': 297.0,
                'text_layout': [
                    {
                        'key': 'title',
                        'label': 'タイトル',
                        'x': 15.0,
                        'y': 22.5,
                        'w': 180.0,
                        'h': 18.0,
                        'font_size': 24,
                    }
                ],
                'image_layout': [
                    {
                        'key': 'main_image',
                        'label': 'メイン画像',
                        'x': 15.0,
                        'y': 250.0,
                        'w': 180.0,
                        'h': 40.0,
                    }
                ]
            }
        )
        
        self.client = Client(enforce_csrf_checks=False)
        self.assertTrue(
            self.client.login(email='test@example.com', password='testpass123'),
            'client.login failed: CustomUser.USERNAME_FIELD is email, not username',
        )
    
    def test_layout_editor_get(self):
        """GET: レイアウトエディタページが正常に表示される"""
        url = reverse('layout_editor', kwargs={'project_id': self.project.pk})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'projects/layout_editor.html')
        
        # Context check
        self.assertEqual(response.context['project'], self.project)
        self.assertEqual(response.context['template'], self.template)
        self.assertEqual(response.context['template_width_mm'], 210.0)
        self.assertEqual(response.context['template_height_mm'], 297.0)
        
        # JSON data should be present
        text_layout = json.loads(response.context['text_layout'])
        image_layout = json.loads(response.context['image_layout'])
        
        self.assertEqual(len(text_layout), 1)
        self.assertEqual(text_layout[0]['key'], 'title')
        
        self.assertEqual(len(image_layout), 1)
        self.assertEqual(image_layout[0]['key'], 'main_image')
    
    def test_layout_editor_post_text_update(self):
        """POST: テキスト要素の座標を mm で更新"""
        url = reverse('layout_editor', kwargs={'project_id': self.project.pk})
        
        payload = {
            'type': 'text',
            'key': 'title',
            'x': 20.0,
            'y': 25.0,
            'w': 170.0,
            'h': 15.0,
        }
        
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json'
        )
        
        # Check response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        
        # Verify saved values (mm)
        self.assertEqual(data['saved_data']['x_mm'], 20.0)
        self.assertEqual(data['saved_data']['y_mm'], 25.0)
        self.assertEqual(data['saved_data']['w_mm'], 170.0)
        self.assertEqual(data['saved_data']['h_mm'], 15.0)
        
        # Check database: canonical flat pt, no legacy container
        self.template.refresh_from_db()
        positions = self.template.default_positions
        self.assertNotIn('text_layout', positions)
        self.assertNotIn('image_layout', positions)

        title = positions['title']
        self.assertAlmostEqual(title['x'], 20.0 * POINTS_PER_MM, places=2)
        self.assertAlmostEqual(title['y'], 25.0 * POINTS_PER_MM, places=2)
        self.assertAlmostEqual(title['w'], 170.0 * POINTS_PER_MM, places=2)
        self.assertAlmostEqual(title['h'], 15.0 * POINTS_PER_MM, places=2)
        # existing text fields survive a coordinate-only save
        self.assertEqual(title['font_size'], 24)
        self.assertIn('font_size', title)
    
    def test_layout_editor_post_image_update(self):
        """POST: 画像要素の座標を mm で更新"""
        url = reverse('layout_editor', kwargs={'project_id': self.project.pk})
        
        payload = {
            'type': 'image',
            'key': 'main_image',
            'x': 20.0,
            'y': 260.0,
            'w': 170.0,
            'h': 35.0,
        }
        
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        
        # Check database: canonical flat pt, image has no font_size
        self.template.refresh_from_db()
        positions = self.template.default_positions
        self.assertNotIn('image_layout', positions)

        image = positions['main_image']
        self.assertNotIn('font_size', image)
        self.assertAlmostEqual(image['x'], 20.0 * POINTS_PER_MM, places=2)
        self.assertAlmostEqual(image['y'], 260.0 * POINTS_PER_MM, places=2)
        self.assertAlmostEqual(image['w'], 170.0 * POINTS_PER_MM, places=2)
        self.assertAlmostEqual(image['h'], 35.0 * POINTS_PER_MM, places=2)
    
    def test_layout_editor_post_invalid_element(self):
        """POST: 存在しない要素を更新しようとするとエラー"""
        url = reverse('layout_editor', kwargs={'project_id': self.project.pk})
        
        payload = {
            'type': 'text',
            'key': 'nonexistent',
            'x': 10.0,
            'y': 10.0,
            'w': 100.0,
            'h': 10.0,
        }
        
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertEqual(data['status'], 'error')
        self.assertIn('not found', data['message'])
    
    def test_layout_editor_post_invalid_json(self):
        """POST: 不正な JSON でエラー"""
        url = reverse('layout_editor', kwargs={'project_id': self.project.pk})
        
        response = self.client.post(
            url,
            data='invalid json',
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data['status'], 'error')
    
    def test_layout_editor_permission(self):
        """権限がないユーザーはアクセスできない"""
        other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='otherpass123'
        )
        
        self.assertTrue(
            self.client.login(email='other@example.com', password='otherpass123'),
            'client.login failed: CustomUser.USERNAME_FIELD is email, not username',
        )
        url = reverse('layout_editor', kwargs={'project_id': self.project.pk})
        
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)


class LayoutEditorIntegrationTest(TestCase):
    """統合テスト: 座標系の一貫性確認"""
    
    def setUp(self):
        self.user = User.objects.create_superuser(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.project = Project.objects.create(
            user=self.user,
            title='Integration Test Project'
        )
        
        self.template = ProjectTemplate.objects.create(
            project=self.project,
            name='Integration Template',
            is_default=True,
            default_positions={
                'width_mm': 210.0,
                'height_mm': 297.0,
                'text_layout': [
                    {
                        'key': 'title',
                        'label': 'Title',
                        'x': 10.0,
                        'y': 10.0,
                        'w': 100.0,
                        'h': 10.0,
                    }
                ]
            }
        )
        
        self.client = Client(enforce_csrf_checks=False)
        self.assertTrue(
            self.client.login(email='test@example.com', password='testpass123'),
            'client.login failed: CustomUser.USERNAME_FIELD is email, not username',
        )
    
    def test_coordinate_roundtrip(self):
        """Coordinate roundtrip: px → mm → storage → PDF"""
        
        # 1. Simulate browser px coordinate
        px_left = 300.0  # Center horizontal
        px_top = 424.0   # Center vertical
        
        # 2. Convert to mm (what JavaScript should do)
        x_mm = CoordinateConverter.px_to_mm(px_left, 'x')
        y_mm = CoordinateConverter.px_to_mm(px_top, 'y')
        
        # Should be A4 center: ~105mm, ~148.5mm
        self.assertAlmostEqual(x_mm, 105.0, places=1)
        self.assertAlmostEqual(y_mm, 148.5, places=1)
        
        # 3. Send to server
        url = reverse('layout_editor', kwargs={'project_id': self.project.pk})
        payload = {
            'type': 'text',
            'key': 'title',
            'x': x_mm,
            'y': y_mm,
            'w': 50.0,
            'h': 15.0,
        }
        
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        
        # 4. Verify database holds canonical pt values
        self.template.refresh_from_db()
        title = self.template.default_positions['title']

        self.assertAlmostEqual(title['x'], x_mm * POINTS_PER_MM, places=2)
        self.assertAlmostEqual(title['y'], y_mm * POINTS_PER_MM, places=2)
        self.assertNotIn('text_layout', self.template.default_positions)

        # 5. Verify PDF conversion is consistent with the stored value
        x_pt = CoordinateConverter.mm_to_pt(x_mm)
        y_pt = CoordinateConverter.mm_to_pt(y_mm)

        self.assertAlmostEqual(title['x'], x_pt, places=2)
        self.assertAlmostEqual(title['y'], y_pt, places=2)

        # Source of truth: browser px → mm (editor) → pt (canonical storage)
        # → PDF render, all describing the same position


class BulkSaveCanonicalTest(TestCase):
    """Bulk save must persist the canonical flat pt schema (not editor mm rows)."""

    def setUp(self):
        self.user = User.objects.create_superuser(
            username='bulkuser', email='bulk@example.com', password='bulkpass123'
        )
        self.project = Project.objects.create(user=self.user, title='Bulk Save Project')
        self.template = ProjectTemplate.objects.create(
            project=self.project,
            name='Bulk Template',
            is_default=True,
            default_positions={
                'width_mm': 210.0,
                'height_mm': 297.0,
                'text_layout': [
                    {'key': 'title', 'label': 'タイトル', 'x': 15.0, 'y': 22.5,
                     'w': 180.0, 'h': 18.0, 'font_size': 24,
                     'writing_mode': 'horizontal-tb'},
                ],
                'image_layout': [
                    {'key': 'main_image', 'label': 'メイン画像', 'x': 15.0, 'y': 250.0,
                     'w': 180.0, 'h': 40.0},
                ],
                # a canonical key the editor never renders must survive the save
                'fixed_note': {'label': '固定注記', 'x': 100.0, 'y': 500.0, 'w': 200.0, 'h': 30.0},
            },
        )
        self.client = Client(enforce_csrf_checks=False)
        self.assertTrue(self.client.login(email='bulk@example.com', password='bulkpass123'))

    def test_bulk_save_writes_canonical_pt(self):
        url = reverse('layout_editor', kwargs={'project_id': self.project.pk})
        payload = {
            'bulk_save': True,
            'text_layout': [
                {'key': 'title', 'label': 'タイトル', 'x': 20.0, 'y': 30.0, 'w': 170.0, 'h': 20.0,
                 'font_size': 20, 'font_family': 'mincho', 'font_weight': 'bold',
                 'color': '#ff0000', 'text_align': 'center', 'writing_mode': 'horizontal-tb'},
            ],
            'image_layout': [
                {'key': 'main_image', 'label': 'メイン画像', 'x': 10.0, 'y': 240.0,
                 'w': 190.0, 'h': 45.0},
            ],
        }
        response = self.client.post(url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')

        self.template.refresh_from_db()
        positions = self.template.default_positions

        # legacy containers are gone, canonical keys remain flat
        for legacy_key in ('text_layout', 'image_layout', 'width_mm', 'height_mm'):
            self.assertNotIn(legacy_key, positions)
        self.assertIn('fixed_note', positions)
        self.assertEqual(positions['fixed_note']['x'], 100.0)

        title = positions['title']
        self.assertAlmostEqual(title['x'], 20.0 * POINTS_PER_MM, places=2)
        self.assertAlmostEqual(title['w'], 170.0 * POINTS_PER_MM, places=2)
        self.assertEqual(title['font_size'], 20)
        self.assertEqual(title['font_family'], 'mincho')
        self.assertEqual(title['horizontal_font_weight'], 'bold')
        self.assertEqual(title['horizontal_text_color'], '#FF0000')
        self.assertEqual(title['horizontal_text_align'], 'center')
        self.assertEqual(title['writing_mode'], 'horizontal')

        image = positions['main_image']
        self.assertNotIn('font_size', image)
        self.assertAlmostEqual(image['x'], 10.0 * POINTS_PER_MM, places=2)

    def test_vertical_font_weight_roundtrip(self):
        """vertical-rl / light must survive GET->save without becoming normal."""
        self.template.default_positions = {
            'title': {'label': 'タイトル', 'x': 100.0, 'y': 50.0, 'w': 200.0, 'h': 300.0,
                      'font_size': 24, 'writing_mode': 'vertical'},
        }
        self.template.save()

        url = reverse('layout_editor', kwargs={'project_id': self.project.pk})
        response = self.client.get(url)
        rows = json.loads(response.context['text_layout'])
        self.assertEqual(rows[0]['writing_mode'], 'vertical-rl')
        self.assertEqual(rows[0]['font_weight'], 'light')

        self.client.post(
            url,
            data=json.dumps({'bulk_save': True, 'text_layout': rows, 'image_layout': []}),
            content_type='application/json',
        )
        self.template.refresh_from_db()
        title = self.template.default_positions['title']
        self.assertEqual(title['writing_mode'], 'vertical')
        self.assertEqual(title['vertical_font_weight'], 'light')
        self.assertNotIn('font_weight', title)

    def test_get_after_save_returns_mm_rows(self):
        url = reverse('layout_editor', kwargs={'project_id': self.project.pk})
        payload = {
            'bulk_save': True,
            'text_layout': [
                {'key': 'title', 'label': 'タイトル', 'x': 20.0, 'y': 30.0, 'w': 170.0, 'h': 20.0,
                 'font_size': 20, 'writing_mode': 'horizontal-tb'},
            ],
            'image_layout': [
                {'key': 'main_image', 'label': 'メイン画像', 'x': 10.0, 'y': 240.0,
                 'w': 190.0, 'h': 45.0},
            ],
        }
        self.client.post(url, data=json.dumps(payload), content_type='application/json')

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        text_rows = json.loads(response.context['text_layout'])
        image_rows = json.loads(response.context['image_layout'])
        title = next(row for row in text_rows if row['key'] == 'title')
        self.assertAlmostEqual(title['x'], 20.0, delta=0.2)
        self.assertAlmostEqual(title['w'], 170.0, delta=0.2)
        self.assertEqual(title['font_size'], 20)
        self.assertIn(next(row for row in image_rows if row['key'] == 'main_image'), image_rows)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix='ppm-test-media-'))
class LayoutEditorRenderTest(TestCase):
    """Regression: an editor-saved layout must actually reach the rendered PDF.

    Before canonical persistence, saving through the layout editor produced
    zero drawable positions; the overlay canvas ended up with no page and
    ``PDFRenderService`` raised IndexError (HTTP 500).
    """

    def setUp(self):
        buffer = io.BytesIO()
        pdf_canvas = reportlab_canvas.Canvas(buffer, pagesize=(595.28, 841.89))
        pdf_canvas.setFont('Helvetica', 12)
        pdf_canvas.drawString(40, 800, 'BASE TEMPLATE')
        pdf_canvas.showPage()
        pdf_canvas.save()
        self.template_bytes = buffer.getvalue()

        self.user = User.objects.create_superuser(
            username='renderuser', email='render@example.com', password='renderpass123'
        )
        self.project = Project.objects.create(user=self.user, title='Render Project')
        self.project.template_file.save(
            'template.pdf', ContentFile(self.template_bytes), save=True
        )
        self.template = ProjectTemplate.objects.create(
            project=self.project,
            name='Render Template',
            template_file=self.project.template_file.name,
            is_default=True,
            default_positions={
                'width_mm': 210.0,
                'height_mm': 297.0,
                'text_layout': [
                    {'key': 'title', 'label': 'タイトル', 'x': 15.0, 'y': 22.5,
                     'w': 180.0, 'h': 18.0, 'font_size': 24},
                ],
                'image_layout': [],
            },
        )
        self.page = Page.objects.create(
            project=self.project,
            project_template=self.template,
            page_number=1,
            input_data={'title': 'LAYOUT EDITOR SAVED'},
        )
        self.client = Client(enforce_csrf_checks=False)
        self.assertTrue(self.client.login(email='render@example.com', password='renderpass123'))

    def test_render_after_editor_save(self):
        url = reverse('layout_editor', kwargs={'project_id': self.project.pk})
        payload = {
            'bulk_save': True,
            'text_layout': [
                {'key': 'title', 'label': 'タイトル', 'x': 20.0, 'y': 30.0, 'w': 170.0, 'h': 20.0,
                 'font_size': 20, 'font_family': 'gothic', 'writing_mode': 'horizontal-tb'},
            ],
            'image_layout': [],
        }
        response = self.client.post(url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 200)

        self.template.refresh_from_db()
        self.page.project_template = self.template

        output = PDFRenderService.render_single_page_bytes(self.project, self.page)
        self.assertEqual(output[:4], b'%PDF')
        reader = PdfReader(io.BytesIO(output))
        self.assertEqual(len(reader.pages), 1)

        text = reader.pages[0].extract_text() or ''
        self.assertIn('LAYOUT EDITOR SAVED', text)
        self.assertIn('BASE TEMPLATE', text)


