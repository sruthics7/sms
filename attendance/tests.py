from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Attendance, Batch, Student, percentage


class AttendanceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("teacher", password="pw")
        self.batch = Batch.objects.create(name="Batch A")
        self.s1 = Student.objects.create(batch=self.batch, roll_no="1", name="Asha")
        self.s2 = Student.objects.create(batch=self.batch, roll_no="2", name="Ben")
        self.today = timezone.localdate()

    # ---- core
    def test_percentage(self):
        self.assertEqual(percentage(3, 1, 1), 80.0)
        self.assertIsNone(percentage(0, 0, 0))

    def test_unique_record_per_day(self):
        Attendance.objects.create(student=self.s1, date=self.today)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Attendance.objects.create(student=self.s1, date=self.today)

    def test_login_required(self):
        for name in ("dashboard", "batch_list", "student_list", "full_report"):
            resp = self.client.get(reverse(f"attendance:{name}"))
            self.assertEqual(resp.status_code, 302, name)

    def test_mark_and_update(self):
        self.client.force_login(self.user)
        url = reverse("attendance:mark", args=[self.batch.pk])
        data = {"date": self.today.isoformat(), f"status_{self.s1.pk}": "P", f"status_{self.s2.pk}": "A"}
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(Attendance.objects.get(student=self.s2).status, "A")
        data[f"status_{self.s2.pk}"] = "L"
        self.client.post(url, data)
        self.assertEqual(Attendance.objects.filter(date=self.today).count(), 2)
        self.assertEqual(Attendance.objects.get(student=self.s2).status, "L")

    def test_future_date_rejected(self):
        self.client.force_login(self.user)
        url = reverse("attendance:mark", args=[self.batch.pk])
        future = self.today + timedelta(days=3)
        self.client.post(url, {"date": future.isoformat(), f"status_{self.s1.pk}": "P"})
        self.assertFalse(Attendance.objects.filter(date=future).exists())

    def test_batch_report_and_csv(self):
        self.client.force_login(self.user)
        Attendance.objects.create(student=self.s1, date=self.today, status="P")
        Attendance.objects.create(student=self.s1, date=self.today - timedelta(days=1), status="A")
        url = reverse("attendance:report", args=[self.batch.pk])
        qs = f"?from={(self.today - timedelta(days=2)).isoformat()}&to={self.today.isoformat()}"
        self.assertContains(self.client.get(url + qs), "50.0%")
        csv_resp = self.client.get(url + qs + "&export=csv")
        self.assertEqual(csv_resp["Content-Type"], "text/csv")
        self.assertIn("Asha", csv_resp.content.decode())

    def test_student_detail(self):
        self.client.force_login(self.user)
        Attendance.objects.create(student=self.s1, date=self.today, status="P")
        resp = self.client.get(reverse("attendance:student", args=[self.s1.pk]))
        self.assertContains(resp, "100.0%")

    # ---- dashboard
    def test_dashboard(self):
        self.client.force_login(self.user)
        Attendance.objects.create(student=self.s1, date=self.today, status="P")
        Attendance.objects.create(student=self.s2, date=self.today, status="A")
        resp = self.client.get(reverse("attendance:dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["total_students"], 2)
        self.assertEqual(resp.context["absent"], 1)
        self.assertEqual(resp.context["today_pct"], 50.0)
        self.assertEqual(len(resp.context["trend"]), 7)

    def test_dashboard_empty(self):
        self.client.force_login(self.user)
        Batch.objects.all().delete()
        self.assertEqual(self.client.get(reverse("attendance:dashboard")).status_code, 200)

    # ---- full report
    def test_full_report(self):
        self.client.force_login(self.user)
        yesterday = self.today - timedelta(days=1)
        Attendance.objects.create(student=self.s1, date=self.today, status="P")
        Attendance.objects.create(student=self.s1, date=yesterday, status="A")
        Attendance.objects.create(student=self.s2, date=self.today, status="L")
        url = reverse("attendance:full_report")
        qs = f"?from={yesterday.isoformat()}&to={self.today.isoformat()}"
        resp = self.client.get(url + qs)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["dates"]), 2)
        asha = next(s for s in resp.context["rows"] if s.name == "Asha")
        self.assertEqual(asha.cells, ["A", "P"])
        self.assertEqual(resp.context["totals"]["pct"], 66.7)
        csv_resp = self.client.get(url + qs + "&export=csv")
        self.assertIn("Asha", csv_resp.content.decode())
        filtered = self.client.get(url + qs + f"&batch={self.batch.pk}")
        self.assertEqual(len(filtered.context["rows"]), 2)

    # ---- CRUD
    def test_batch_crud(self):
        self.client.force_login(self.user)
        self.client.post(reverse("attendance:batch_create"), {"name": "Batch B", "description": "x"})
        b = Batch.objects.get(name="Batch B")
        self.client.post(reverse("attendance:batch_update", args=[b.pk]), {"name": "Batch C", "description": ""})
        b.refresh_from_db()
        self.assertEqual(b.name, "Batch C")
        self.client.post(reverse("attendance:batch_delete", args=[b.pk]))
        self.assertFalse(Batch.objects.filter(pk=b.pk).exists())

    def test_student_crud_and_duplicate_roll(self):
        self.client.force_login(self.user)
        url = reverse("attendance:student_create")
        data = {"batch": self.batch.pk, "roll_no": "3", "name": "Cara", "email": "", "phone": "", "is_active": "on"}
        self.client.post(url, data)
        cara = Student.objects.get(name="Cara")
        resp = self.client.post(url, data)  # duplicate roll in same batch
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Student.objects.filter(roll_no="3").count(), 1)
        data["name"] = "Cara K"
        self.client.post(reverse("attendance:student_update", args=[cara.pk]), data)
        cara.refresh_from_db()
        self.assertEqual(cara.name, "Cara K")
        self.client.post(reverse("attendance:student_delete", args=[cara.pk]))
        self.assertFalse(Student.objects.filter(pk=cara.pk).exists())

    def test_student_list_filters(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("attendance:student_list") + "?q=asha")
        self.assertEqual([s.name for s in resp.context["students"]], ["Asha"])

    def test_record_edit_and_delete(self):
        self.client.force_login(self.user)
        rec = Attendance.objects.create(student=self.s1, date=self.today, status="A")
        url = reverse("attendance:record_update", args=[rec.pk])
        self.client.post(url, {"date": self.today.isoformat(), "status": "E", "remark": "sick"})
        rec.refresh_from_db()
        self.assertEqual((rec.status, rec.remark), ("E", "sick"))
        # moving onto a day that already has a record is rejected
        other = Attendance.objects.create(student=self.s1, date=self.today - timedelta(days=1))
        self.client.post(url, {"date": other.date.isoformat(), "status": "P", "remark": ""})
        rec.refresh_from_db()
        self.assertEqual(rec.date, self.today)
        self.client.post(reverse("attendance:record_delete", args=[rec.pk]))
        self.assertFalse(Attendance.objects.filter(pk=rec.pk).exists())

    def test_student_prev_next_and_report_links(self):
        self.client.force_login(self.user)
        first = self.client.get(reverse("attendance:student", args=[self.s1.pk]))
        self.assertIsNone(first.context["prev_id"])
        self.assertEqual(first.context["next_id"], self.s2.pk)
        self.assertEqual((first.context["position"], first.context["total"]), (1, 2))
        last = self.client.get(reverse("attendance:student", args=[self.s2.pk]))
        self.assertEqual(last.context["prev_id"], self.s1.pk)
        self.assertIsNone(last.context["next_id"])
        report = self.client.get(reverse("attendance:report", args=[self.batch.pk]))
        self.assertEqual(report.context["first_id"], self.s1.pk)
        self.assertContains(report, "View one by one")
