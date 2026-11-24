from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.ProjectLoginView.as_view(), name="login"),
    path("access/", views.access_map, name="access_map"),
    path("", views.overview, name="overview"),
    path(
        "password/change/",
        views.ProjectPasswordChangeView.as_view(),
        name="password_change",
    ),
    path("logout/", LogoutView.as_view(next_page="login"), name="logout"),
    path("denied/", views.access_denied, name="access_denied"),
]
