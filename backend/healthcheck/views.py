from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import redirect, render
from django.urls import reverse

from . import services


@staff_member_required(login_url="admin:login")
def dashboard_view(request):
    context = services.build_dashboard_context(
        request.GET.get("project"),
        request.GET.get("is_healthy"),
        request.GET.get("tag"),
    )
    return render(request, "healthcheck/dashboard.html", context)


@staff_member_required(login_url="admin:login")
def trigger_check_now_view(request, url_id=None):
    if request.method != "POST":
        return redirect("dashboard")

    next_url = request.POST.get("next") or reverse("dashboard")
    checked_url = services.queue_health_check(url_id)

    if checked_url is None:
        messages.success(request, "Ran a health check for all active services.")
    else:
        messages.success(request, f"Ran a health check for {checked_url.name}.")

    return redirect(next_url)
