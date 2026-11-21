from django.conf import settings
from django.db import models


class Batch(models.Model):
    """A class / batch / course group that students belong to."""

    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "batches"

    def __str__(self):
        return self.name


class Student(models.Model):
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name="students")
    roll_no = models.CharField(max_length=30)
    name = models.CharField(max_length=150)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["batch__name", "roll_no"]
        constraints = [
            models.UniqueConstraint(fields=["batch", "roll_no"], name="unique_roll_per_batch")
        ]

    def __str__(self):
        return f"{self.roll_no} - {self.name}"


class Attendance(models.Model):
    PRESENT = "P"
    ABSENT = "A"
    LATE = "L"
    EXCUSED = "E"
    STATUS_CHOICES = [
        (PRESENT, "Present"),
        (ABSENT, "Absent"),
        (LATE, "Late"),
        (EXCUSED, "Excused"),
    ]

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="records")
    date = models.DateField()
    status = models.CharField(max_length=1, choices=STATUS_CHOICES, default=PRESENT)
    remark = models.CharField(max_length=255, blank=True)
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "student__roll_no"]
        constraints = [
            models.UniqueConstraint(fields=["student", "date"], name="one_record_per_student_per_day")
        ]
        indexes = [models.Index(fields=["date"])]

    def __str__(self):
        return f"{self.student} {self.date} {self.get_status_display()}"


def percentage(present, late, absent):
    """Late counts as attended; excused days are left out of the total."""
    total = present + late + absent
    if not total:
        return None
    return round((present + late) * 100 / total, 1)
