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
    path('projects/<int:project_id>/pdf/merged/', views.download_merged_pdf, name='project_pdf_merged'),
    path('projects/<int:project_id>/pdf/zip/', views.download_pages_zip, name='project_pdf_zip'),
    path('projects/<int:project_id>/csv/', views.download_pages_csv, name='project_pages_csv'),
    path('projects/<int:project_id>/csv/upload/', views.upload_project_csv, name='project_csv_upload'),
    path('projects/<int:project_id>/csv/format/', views.download_project_csv_format, name='project_csv_format'),
]
