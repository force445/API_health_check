"""
URL configuration for backend project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include

admin.site.login_template = 'admin/custom-login.html'
admin.site.index_template = 'admin/custom-index.html'
admin.site.site_title = "Http Health Check"
admin.site.site_header = "Http Health Check"


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('healthcheck.urls'))
]

from django.conf import settings
from django.conf.urls.static import static

urlpatterns+=static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
