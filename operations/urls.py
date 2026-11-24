from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("records/<slug:module>/new/", views.form_page, name="form_page"),
    path(
        "records/<slug:module>/<str:reference>/",
        views.need_detail,
        name="need_detail",
    ),
    path("records/<slug:module>/", views.records, name="records"),
]
