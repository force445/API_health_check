from django.urls import path
from . import views

urlpatterns = [
    path('', view=views.dashboard_view, name='dashboard'),
    path('check-now/', view=views.trigger_check_now_view, name='check_now'),
    path('urls/<int:url_id>/check-now/', view=views.trigger_check_now_view, name='check_url_now'),
]
