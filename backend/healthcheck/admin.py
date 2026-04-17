from django.contrib import admin
from . import models
# Register your models here.

class ProjectAdmin(admin.ModelAdmin):
    list_display = [f.name for f in models.Project._meta.fields]
    search_fields = ['name']
    list_filter = ['is_use']
admin.site.register(models.Project, ProjectAdmin)

class URLAdmin(admin.ModelAdmin):
    list_display = [f.name for f in models.URL._meta.fields if f.name not in ['log']]
    search_fields = ['project__name']
    list_filter = ['is_healthy', 'project__name']
    autocomplete_fields = ['project']
admin.site.register(models.URL, URLAdmin)