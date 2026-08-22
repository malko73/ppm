from django.urls import path

from . import views

urlpatterns = [
    path('', views.ProjectListView.as_view(), name='project_list'),
    path('projects/new/', views.ProjectCreateView.as_view(), name='project_create'),
    path('projects/<int:pk>/', views.ProjectDetailView.as_view(), name='project_detail'),
    path('projects/<int:pk>/copy/', views.copy_project, name='project_copy'),
    path('projects/<int:pk>/edit/', views.ProjectUpdateView.as_view(), name='project_update'),
    path('projects/<int:pk>/delete/', views.ProjectDeleteView.as_view(), name='project_delete'),
    path('projects/<int:project_id>/pages/new/', views.PageCreateView.as_view(), name='page_create'),
    path('projects/<int:project_id>/pages/<int:pk>/edit/', views.PageUpdateView.as_view(), name='page_update'),
    path('projects/<int:project_id>/pages/<int:pk>/delete/', views.PageDeleteView.as_view(), name='page_delete'),
    path('projects/<int:project_id>/pages/<int:pk>/finalized/', views.toggle_page_finalized, name='page_toggle_finalized'),
    path('projects/<int:project_id>/pages/reorder/', views.reorder_pages, name='page_reorder'),
    path('projects/<int:project_id>/pages/<int:pk>/pdf/', views.download_single_page_pdf, name='page_pdf'),
    path('projects/<int:project_id>/pages/<int:pk>/preview/', views.page_preview, name='page_preview'),
    path('projects/<int:project_id>/pdf/merged/', views.download_merged_pdf, name='project_pdf_merged'),
    # ZIP は非同期生成: start → pending（ポーリング） → download
    path('projects/<int:project_id>/pdf/zip/start/', views.start_pages_zip, name='project_pdf_zip_start'),
    path('projects/<int:project_id>/pdf/zip/pending/', views.download_pending_zip, name='project_pdf_zip_pending'),
    path('projects/<int:project_id>/pdf/zip/poll/', views.poll_pages_zip, name='project_pdf_zip_poll'),
    path('projects/<int:project_id>/pdf/zip/', views.download_pages_zip, name='project_pdf_zip'),
    path('projects/<int:project_id>/csv/', views.download_pages_csv, name='project_pages_csv'),
    path('projects/<int:project_id>/csv/upload/', views.upload_project_csv, name='project_csv_upload'),
    path('projects/<int:project_id>/csv/format/', views.download_project_csv_format, name='project_csv_format'),
    # Layout Editor: P0 Vertical Slice
    path('projects/<int:project_id>/layout-editor/', views.layout_editor, name='layout_editor'),
    path('projects/<int:project_id>/templates/<int:template_id>/layout-editor/', views.layout_editor, name='layout_editor_template'),
    path('projects/<int:project_id>/templates/<int:template_id>/preview/', views.template_preview_image, name='template_preview'),
]
