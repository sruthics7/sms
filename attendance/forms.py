from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Attendance, Batch, Student


class BatchForm(forms.ModelForm):
    class Meta:
        model = Batch
        fields = ["name", "description"]


class StudentForm(forms.ModelForm):
    class Meta:
        model = Student
        fields = ["batch", "roll_no", "name", "email", "phone", "is_active"]


class AttendanceForm(forms.ModelForm):
    """Edit a single existing attendance record."""

    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))

    class Meta:
        model = Attendance
        fields = ["date", "status", "remark"]

    def clean_date(self):
        day = self.cleaned_data["date"]
        if day > timezone.localdate():
            raise ValidationError("Date can't be in the future.")
        return day

    def clean(self):
        cleaned = super().clean()
        day = cleaned.get("date")
        if day and (
            Attendance.objects.filter(student_id=self.instance.student_id, date=day)
            .exclude(pk=self.instance.pk)
            .exists()
        ):
            self.add_error("date", "This student already has a record for that date.")
        return cleaned
