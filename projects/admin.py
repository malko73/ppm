from django.contrib import admin

from .models import Page, PageImage, Project, ProjectTemplate

HAS_PROJECT_CATEGORY_FIELD = any(field.name == 'category' for field in Project._meta.get_fields())


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'updated_at')
    search_fields = ('title', 'user__email')
    list_filter = ()
    filter_horizontal = ('participants',)

    if HAS_PROJECT_CATEGORY_FIELD:
        list_display = ('title', 'category', 'user', 'updated_at')
        search_fields = ('title', 'category', 'user__email')
        list_filter = ('category',)


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = (
        'project',
        'project_template',
        'page_number',
        'order',
        'page_name',
        'updated_at',
    )
    list_filter = ('project', 'project_template')
    search_fields = ('page_name', 'project__title')


@admin.register(ProjectTemplate)
class ProjectTemplateAdmin(admin.ModelAdmin):
    list_display = ('project', 'name', 'is_default', 'updated_at')
    list_filter = ('project', 'is_default')
    search_fields = ('name', 'project__title')


@admin.register(PageImage)
class PageImageAdmin(admin.ModelAdmin):
    list_display = ('page', 'key', 'updated_at')
    list_filter = ('page__project',)
    search_fields = ('key', 'label', 'page__project__title', 'page__page_name')
