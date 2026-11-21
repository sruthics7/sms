# Student Attendance (Django app)

Teachers mark daily attendance per batch, view reports by date range, and export CSV.

## Install

1. Copy the `attendance/` folder into your Django project.
2. `settings.py`:
   ```python
   INSTALLED_APPS += ["attendance"]
   LOGIN_URL = "/admin/login/"   # or your own login URL
   ```
   Make sure `django.contrib.messages` and `django.contrib.auth` are enabled (default).
3. Root `urls.py`:
   ```python
   from django.urls import include, path
   urlpatterns += [path("attendance/", include("attendance.urls"))]
   ```
4. `python manage.py makemigrations attendance && python manage.py migrate`
5. Add batches and students in the admin, then open `/attendance/`.

## Rules
- Statuses: Present, Late, Absent, Excused.
- Percentage = (Present + Late) / (Present + Late + Absent). Excused days are ignored.
- One record per student per day; re-saving a date updates it.
- Future dates are rejected. Below 75% is highlighted in reports.

## Run tests
`python manage.py test attendance`
