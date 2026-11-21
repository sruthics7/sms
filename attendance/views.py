import csv
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from .forms import AttendanceForm, BatchForm, StudentForm
from .models import Attendance, Batch, Student, percentage

LOW_THRESHOLD = 75


# --------------------------------------------------------------------------- helpers
def _parse_date(value, default):
    parsed = parse_date(value) if value else None
    return parsed or default


def _range(request):
    today = timezone.localdate()
    start = _parse_date(request.GET.get("from"), today.replace(day=1))
    end = _parse_date(request.GET.get("to"), today)
    if start > end:
        start, end = end, start
    return start, end


def _student_rows(students, start, end):
    """Annotate students with present/late/absent/excused counts and pct for a date range."""
    in_range = Q(records__date__range=(start, end))
    qs = students.annotate(
        present=Count("records", filter=in_range & Q(records__status=Attendance.PRESENT)),
        late=Count("records", filter=in_range & Q(records__status=Attendance.LATE)),
        absent=Count("records", filter=in_range & Q(records__status=Attendance.ABSENT)),
        excused=Count("records", filter=in_range & Q(records__status=Attendance.EXCUSED)),
    ).order_by("batch__name", "roll_no")
    rows = []
    for s in qs:
        s.pct = percentage(s.present, s.late, s.absent)
        rows.append(s)
    return rows


def _batch_summary(batch, start, end):
    return _student_rows(Student.objects.filter(batch=batch, is_active=True), start, end)


def _totals(rows):
    tot = {k: sum(getattr(s, k) for s in rows) for k in ("present", "late", "absent", "excused")}
    tot["pct"] = percentage(tot["present"], tot["late"], tot["absent"])
    return tot


def _group_by_batch(rows):
    groups = {}
    for s in rows:
        g = groups.setdefault(
            s.batch_id,
            {"batch": s.batch, "students": 0, "present": 0, "late": 0, "absent": 0, "excused": 0},
        )
        g["students"] += 1
        for k in ("present", "late", "absent", "excused"):
            g[k] += getattr(s, k)
    for g in groups.values():
        g["pct"] = percentage(g["present"], g["late"], g["absent"])
    return groups


def _form_page(request, form_class, instance, title, success_msg, success_url, initial=None):
    form = form_class(request.POST or None, instance=instance, initial=initial)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, success_msg)
        return redirect(success_url)
    return render(
        request,
        "attendance/form.html",
        {"form": form, "title": title, "cancel_url": success_url},
    )


def _delete_page(request, obj, title, warning, success_url):
    if request.method == "POST":
        label = str(obj)
        obj.delete()
        messages.success(request, f"Deleted {label}.")
        return redirect(success_url)
    return render(
        request,
        "attendance/confirm_delete.html",
        {"object": obj, "title": title, "warning": warning, "cancel_url": success_url},
    )


# --------------------------------------------------------------------------- dashboard
@login_required
def dashboard(request):
    today = timezone.localdate()
    month_start = today.replace(day=1)
    active = Student.objects.filter(is_active=True)
    total_students = active.count()

    counts = {
        r["status"]: r["n"]
        for r in Attendance.objects.filter(date=today, student__is_active=True)
        .values("status")
        .annotate(n=Count("id"))
    }
    present = counts.get(Attendance.PRESENT, 0)
    late = counts.get(Attendance.LATE, 0)
    absent = counts.get(Attendance.ABSENT, 0)
    excused = counts.get(Attendance.EXCUSED, 0)
    marked = present + late + absent + excused

    # last 7 days trend
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    per_day = {}
    for r in (
        Attendance.objects.filter(date__range=(days[0], today), student__is_active=True)
        .values("date", "status")
        .annotate(n=Count("id"))
    ):
        per_day.setdefault(r["date"], {})[r["status"]] = r["n"]
    trend = []
    for d in days:
        c = per_day.get(d, {})
        pct = percentage(c.get("P", 0), c.get("L", 0), c.get("A", 0))
        trend.append({"date": d, "pct": pct, "bar": int(round(pct)) if pct is not None else 0})

    # month-to-date per student / batch
    rows = _student_rows(active.select_related("batch"), month_start, today)
    month_by_batch = _group_by_batch(rows)
    low = sorted(
        (s for s in rows if s.pct is not None and s.pct < LOW_THRESHOLD), key=lambda s: s.pct
    )[:8]

    batches = list(
        Batch.objects.annotate(
            student_count=Count("students", filter=Q(students__is_active=True), distinct=True),
            marked_today=Count("students__records", filter=Q(students__records__date=today), distinct=True),
        )
    )
    for b in batches:
        b.month_pct = month_by_batch.get(b.pk, {}).get("pct")

    return render(
        request,
        "attendance/dashboard.html",
        {
            "today": today,
            "total_students": total_students,
            "total_batches": len(batches),
            "present": present,
            "late": late,
            "absent": absent,
            "excused": excused,
            "not_marked": max(total_students - marked, 0),
            "today_pct": percentage(present, late, absent),
            "trend": trend,
            "low": low,
            "batches": batches,
            "month_pct": _totals(rows)["pct"],
            "threshold": LOW_THRESHOLD,
        },
    )


# --------------------------------------------------------------------------- batches CRUD
@login_required
def batch_list(request):
    today = timezone.localdate()
    batches = Batch.objects.annotate(
        student_count=Count("students", filter=Q(students__is_active=True), distinct=True),
        marked_today=Count("students__records", filter=Q(students__records__date=today), distinct=True),
    )
    return render(request, "attendance/batch_list.html", {"batches": batches, "today": today})


@login_required
def batch_create(request):
    return _form_page(
        request, BatchForm, None, "Add batch", "Batch added.", reverse("attendance:batch_list")
    )


@login_required
def batch_update(request, batch_id):
    batch = get_object_or_404(Batch, pk=batch_id)
    return _form_page(
        request, BatchForm, batch, f"Edit {batch.name}", "Batch updated.", reverse("attendance:batch_list")
    )


@login_required
def batch_delete(request, batch_id):
    batch = get_object_or_404(Batch, pk=batch_id)
    n = batch.students.count()
    warning = f"This also deletes {n} student(s) and all of their attendance records." if n else ""
    return _delete_page(request, batch, f"Delete batch {batch.name}?", warning, reverse("attendance:batch_list"))


# --------------------------------------------------------------------------- students CRUD
@login_required
def student_list(request):
    qs = Student.objects.select_related("batch")
    q = request.GET.get("q", "").strip()
    batch_id = request.GET.get("batch", "")
    status = request.GET.get("status", "")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(roll_no__icontains=q) | Q(email__icontains=q))
    if batch_id.isdigit():
        qs = qs.filter(batch_id=batch_id)
    if status == "active":
        qs = qs.filter(is_active=True)
    elif status == "inactive":
        qs = qs.filter(is_active=False)
    return render(
        request,
        "attendance/student_list.html",
        {"students": qs, "batches": Batch.objects.all(), "q": q, "batch_id": batch_id, "status": status},
    )


@login_required
def student_create(request):
    batch_id = request.GET.get("batch", "")
    initial = {"batch": batch_id} if batch_id.isdigit() else None
    return _form_page(
        request, StudentForm, None, "Add student", "Student added.",
        reverse("attendance:student_list"), initial=initial,
    )


@login_required
def student_update(request, student_id):
    student = get_object_or_404(Student, pk=student_id)
    return _form_page(
        request, StudentForm, student, f"Edit {student.name}", "Student updated.",
        reverse("attendance:student_list"),
    )


@login_required
def student_delete(request, student_id):
    student = get_object_or_404(Student, pk=student_id)
    n = student.records.count()
    warning = f"This also deletes {n} attendance record(s)." if n else ""
    return _delete_page(
        request, student, f"Delete student {student.name}?", warning, reverse("attendance:student_list")
    )


# --------------------------------------------------------------------------- marking
@login_required
def mark_select(request):
    """Sidebar entry point: choose a batch (and date), then go to the marking screen."""
    today = timezone.localdate()
    day = min(_parse_date(request.GET.get("date"), today), today)
    batches = list(
        Batch.objects.annotate(
            student_count=Count("students", filter=Q(students__is_active=True), distinct=True),
            marked=Count("students__records", filter=Q(students__records__date=day), distinct=True),
        )
    )
    if len(batches) == 1 and "date" not in request.GET:
        return redirect(reverse("attendance:mark", args=[batches[0].pk]))
    return render(
        request,
        "attendance/mark_select.html",
        {"batches": batches, "day": day, "today": today},
    )


@login_required
def mark_attendance(request, batch_id):
    batch = get_object_or_404(Batch, pk=batch_id)
    students = list(batch.students.filter(is_active=True))
    today = timezone.localdate()
    day = _parse_date(request.POST.get("date") or request.GET.get("date"), today)
    if day > today:
        messages.error(request, "You can't mark attendance for a future date.")
        day = today

    if request.method == "POST":
        valid = {code for code, _ in Attendance.STATUS_CHOICES}
        with transaction.atomic():
            for s in students:
                status = request.POST.get(f"status_{s.pk}")
                if status not in valid:
                    continue
                Attendance.objects.update_or_create(
                    student=s,
                    date=day,
                    defaults={
                        "status": status,
                        "remark": request.POST.get(f"remark_{s.pk}", "")[:255],
                        "marked_by": request.user,
                    },
                )
        messages.success(request, f"Attendance saved for {batch.name} on {day:%d %b %Y}.")
        return redirect(f"{reverse('attendance:mark', args=[batch.pk])}?date={day.isoformat()}")

    existing = {a.student_id: a for a in Attendance.objects.filter(student__in=students, date=day)}
    rows = [
        {
            "student": s,
            "status": existing[s.pk].status if s.pk in existing else Attendance.PRESENT,
            "remark": existing[s.pk].remark if s.pk in existing else "",
        }
        for s in students
    ]
    return render(
        request,
        "attendance/mark.html",
        {
            "batch": batch,
            "rows": rows,
            "day": day,
            "today": today,
            "already_marked": bool(existing),
            "statuses": Attendance.STATUS_CHOICES,
        },
    )


# --------------------------------------------------------------------------- reports
@login_required
def batch_report(request, batch_id):
    batch = get_object_or_404(Batch, pk=batch_id)
    start, end = _range(request)
    rows = _batch_summary(batch, start, end)

    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="attendance_{batch.pk}_{start}_{end}.csv"'
        )
        writer = csv.writer(response)
        writer.writerow(["Roll No", "Name", "Present", "Late", "Absent", "Excused", "Attendance %"])
        for s in rows:
            writer.writerow([s.roll_no, s.name, s.present, s.late, s.absent, s.excused,
                             "" if s.pct is None else s.pct])
        return response

    return render(
        request,
        "attendance/report.html",
        {
            "batch": batch,
            "rows": rows,
            "start": start,
            "end": end,
            "first_id": rows[0].pk if rows else None,
        },
    )


@login_required
def full_report(request):
    """Everything on one page: totals, batch-wise summary and a day-wise register."""
    start, end = _range(request)
    batches = Batch.objects.all()
    batch_id = request.GET.get("batch", "")

    students = Student.objects.filter(is_active=True).select_related("batch")
    selected_batch = None
    if batch_id.isdigit():
        selected_batch = batches.filter(pk=batch_id).first()
        students = students.filter(batch_id=batch_id)

    rows = _student_rows(students, start, end)

    records = list(
        Attendance.objects.filter(
            student_id__in=[s.pk for s in rows], date__range=(start, end)
        ).values_list("student_id", "date", "status")
    )
    dates = sorted({d for _, d, _ in records})
    cell = {(sid, d): st for sid, d, st in records}
    for s in rows:
        s.cells = [cell.get((s.pk, d), "") for d in dates]

    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="full_report_{start}_{end}.csv"'
        writer = csv.writer(response)
        writer.writerow(
            ["Roll No", "Name", "Batch", "Present", "Late", "Absent", "Excused", "Attendance %"]
            + [d.isoformat() for d in dates]
        )
        for s in rows:
            writer.writerow(
                [s.roll_no, s.name, s.batch.name, s.present, s.late, s.absent, s.excused,
                 "" if s.pct is None else s.pct] + s.cells
            )
        return response

    totals = _totals(rows)
    return render(
        request,
        "attendance/full_report.html",
        {
            "rows": rows,
            "dates": dates,
            "totals": totals,
            "batch_groups": sorted(_group_by_batch(rows).values(), key=lambda g: g["batch"].name),
            "low_count": sum(1 for s in rows if s.pct is not None and s.pct < LOW_THRESHOLD),
            "batches": batches,
            "batch_id": batch_id,
            "selected_batch": selected_batch,
            "start": start,
            "end": end,
            "threshold": LOW_THRESHOLD,
        },
    )


@login_required
def student_detail(request, student_id):
    student = get_object_or_404(Student.objects.select_related("batch"), pk=student_id)
    start, end = _range(request)
    records = student.records.filter(date__range=(start, end))
    counts = {r["status"]: r["n"] for r in records.values("status").annotate(n=Count("id"))}
    present = counts.get(Attendance.PRESENT, 0)
    late = counts.get(Attendance.LATE, 0)
    absent = counts.get(Attendance.ABSENT, 0)

    # previous / next student in the same batch (same order as the batch report)
    ids = list(
        Student.objects.filter(batch=student.batch, is_active=True)
        .order_by("roll_no")
        .values_list("pk", flat=True)
    )
    idx = ids.index(student.pk) if student.pk in ids else None
    prev_id = ids[idx - 1] if idx else None
    next_id = ids[idx + 1] if idx is not None and idx + 1 < len(ids) else None

    return render(
        request,
        "attendance/student.html",
        {
            "prev_id": prev_id,
            "next_id": next_id,
            "position": idx + 1 if idx is not None else None,
            "total": len(ids),
            "student": student,
            "records": records,
            "start": start,
            "end": end,
            "present": present,
            "late": late,
            "absent": absent,
            "excused": counts.get(Attendance.EXCUSED, 0),
            "pct": percentage(present, late, absent),
        },
    )


# --------------------------------------------------------------------------- record edit / delete
@login_required
def record_update(request, record_id):
    record = get_object_or_404(Attendance.objects.select_related("student"), pk=record_id)
    back = reverse("attendance:student", args=[record.student_id])
    form = AttendanceForm(request.POST or None, instance=record)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.marked_by = request.user
        obj.save()
        messages.success(request, "Attendance record updated.")
        return redirect(back)
    return render(
        request,
        "attendance/form.html",
        {"form": form, "title": f"Edit record - {record.student.name}", "cancel_url": back},
    )


@login_required
def record_delete(request, record_id):
    record = get_object_or_404(Attendance.objects.select_related("student"), pk=record_id)
    back = reverse("attendance:student", args=[record.student_id])
    return _delete_page(request, record, "Delete this attendance record?", "", back)
