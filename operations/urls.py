from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("records/<slug:module>/new/", views.form_page, name="form_page"),
    path(
        "records/requests/<str:reference>/decide/",
        views.request_decide,
        name="request_decide",
    ),
    path(
        "records/orders/<str:reference>/review/",
        views.order_review,
        name="order_review",
    ),
    path(
        "records/orders/<str:reference>/approve/",
        views.order_approve,
        name="order_approve",
    ),
    path(
        "records/orders/<str:reference>/resubmit/",
        views.order_resubmit,
        name="order_resubmit",
    ),
    path(
        "records/quotations/<str:reference>/select/",
        views.quotation_select,
        name="quotation_select",
    ),
    path(
        "records/issues/<str:reference>/acknowledge/",
        views.issue_acknowledge,
        name="issue_acknowledge",
    ),
    path(
        "records/invoices/<str:reference>/handoff/",
        views.invoice_handoff,
        name="invoice_handoff",
    ),
    path(
        "records/invoices/<str:reference>/review/",
        views.invoice_review,
        name="invoice_review",
    ),
    path(
        "records/<slug:module>/<str:reference>/",
        views.need_detail,
        name="need_detail",
    ),
    path("records/<slug:module>/", views.records, name="records"),
]
