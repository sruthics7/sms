from django.contrib import admin

from .models import Attendance, Batch, Student


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ("name", "description")
    search_fields = ("name",)


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("roll_no", "name", "batch", "email", "is_active")
    list_filter = ("batch", "is_active")
    search_fields = ("name", "roll_no", "email")


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("student", "date", "status", "marked_by")
    list_filter = ("status", "date", "student__batch")
    search_fields = ("student__name", "student__roll_no")
    date_hierarchy = "date"
