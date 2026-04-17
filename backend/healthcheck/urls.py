from django.urls import path
from . import views

urlpatterns = [
    path('', view=views.dashboard_view, name='dashboard'),
]
