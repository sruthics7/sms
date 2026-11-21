from django.urls import path

from . import views

app_name = "attendance"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("report/", views.full_report, name="full_report"),

    path("batches/", views.batch_list, name="batch_list"),
    path("batches/add/", views.batch_create, name="batch_create"),
    path("batches/<int:batch_id>/edit/", views.batch_update, name="batch_update"),
    path("batches/<int:batch_id>/delete/", views.batch_delete, name="batch_delete"),

    path("students/", views.student_list, name="student_list"),
    path("students/add/", views.student_create, name="student_create"),
    path("students/<int:student_id>/edit/", views.student_update, name="student_update"),
    path("students/<int:student_id>/delete/", views.student_delete, name="student_delete"),

    path("mark/", views.mark_select, name="mark_select"),
    path("batch/<int:batch_id>/mark/", views.mark_attendance, name="mark"),
    path("batch/<int:batch_id>/report/", views.batch_report, name="report"),
    path("student/<int:student_id>/", views.student_detail, name="student"),

    path("record/<int:record_id>/edit/", views.record_update, name="record_update"),
    path("record/<int:record_id>/delete/", views.record_delete, name="record_delete"),
]
