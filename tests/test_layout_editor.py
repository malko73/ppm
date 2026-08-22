"""
Test suite for Layout Editor (Issue #5 P0 Vertical Slice)

Focus: Coordinate system accuracy and data persistence
"""

import json
import pytest
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse

from projects.models import Project, ProjectTemplate
from projects.utils.coordinates import CoordinateConverter

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
        self.client.login(username='testuser', password='testpass123')
    
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
        
        # Check database
        self.template.refresh_from_db()
        text_layout = self.template.default_positions.get('text_layout', [])
        
        self.assertEqual(len(text_layout), 1)
        self.assertEqual(text_layout[0]['x'], 20.0)
        self.assertEqual(text_layout[0]['y'], 25.0)
        self.assertEqual(text_layout[0]['w'], 170.0)
        self.assertEqual(text_layout[0]['h'], 15.0)
    
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
        
        # Check database
        self.template.refresh_from_db()
        image_layout = self.template.default_positions.get('image_layout', [])
        
        self.assertEqual(len(image_layout), 1)
        self.assertEqual(image_layout[0]['x'], 20.0)
        self.assertEqual(image_layout[0]['y'], 260.0)
        self.assertEqual(image_layout[0]['w'], 170.0)
        self.assertEqual(image_layout[0]['h'], 35.0)
    
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
        
        self.client.login(username='otheruser', password='otherpass123')
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
        self.client.login(username='testuser', password='testpass123')
    
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
        
        # 4. Verify database has mm values
        self.template.refresh_from_db()
        text_layout = self.template.default_positions['text_layout'][0]
        
        self.assertAlmostEqual(text_layout['x'], x_mm, places=1)
        self.assertAlmostEqual(text_layout['y'], y_mm, places=1)
        
        # 5. Verify PDF conversion would work
        x_pt = CoordinateConverter.mm_to_pt(text_layout['x'])
        y_pt = CoordinateConverter.mm_to_pt(text_layout['y'])
        
        # Should be valid pt values
        self.assertGreater(x_pt, 0)
        self.assertGreater(y_pt, 0)
        
        # Source of truth: mm should be preserved in all layers
        # Browser px → mm (saved to DB) → pt (for PDF) → visual position match
