import re
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import AccountProfile

from allowances.models import AllowanceRecord, StatusUpdate

User = get_user_model()
PASSWORD = "StrongPassword!42"


class AllowanceTestCase(TestCase):
    def make_user(self, username, role=AccountProfile.Role.STUDENT):
        user = User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password=PASSWORD,
            first_name=username.title(),
            last_name="Tester",
        )
        user.account_profile.role = role
        user.account_profile.save()
        return user

    def setUp(self):
        self.staff = self.make_user("staffer", AccountProfile.Role.STAFF)
        self.student = self.make_user("maria")
        self.other = self.make_user("juan")

    def make_record(self, scholar=None, **overrides):
        data = {
            "scholar": scholar or self.student,
            "created_by": self.staff,
            "academic_year": "2026-2027",
            "semester": "1st",
            "amount": Decimal("3500.00"),
        }
        data.update(overrides)
        record = AllowanceRecord.objects.create(**data)
        record.log_status(self.staff, "Allowance record created.")
        return record

    def create_payload(self, **overrides):
        data = {
            "scholar": self.student.pk,
            "academic_year": "2026-2027",
            "semester": "1st",
            "amount": "3500.00",
            "remarks": "",
        }
        data.update(overrides)
        return data

    def update_payload(self, record, **overrides):
        data = {
            "academic_year": record.academic_year,
            "semester": record.semester,
            "amount": str(record.amount),
            "status": record.status,
            "remarks": "",
        }
        data.update(overrides)
        return data


class AccessControlTests(AllowanceTestCase):
    def test_anonymous_users_are_sent_to_login(self):
        record = self.make_record()
        for name, args in (
            ("allowances:list", []),
            ("allowances:create", []),
            ("allowances:lookup", []),
            ("allowances:detail", [record.pk]),
            ("allowances:update", [record.pk]),
            ("allowances:delete", [record.pk]),
        ):
            with self.subTest(url=name):
                response = self.client.get(reverse(name, args=args))
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("accounts:login"), response["Location"])

    def test_student_cannot_create_edit_or_delete(self):
        record = self.make_record()
        self.client.login(username="maria", password=PASSWORD)

        response = self.client.post(
            reverse("allowances:create"),
            self.create_payload(academic_year="2027-2028"),
        )
        self.assertRedirects(response, reverse("allowances:list"))
        self.assertEqual(AllowanceRecord.objects.count(), 1)

        self.client.post(
            reverse("allowances:update", args=[record.pk]),
            self.update_payload(record, status="verifying"),
        )
        self.client.post(reverse("allowances:delete", args=[record.pk]))
        record.refresh_from_db()
        self.assertEqual(record.status, AllowanceRecord.Status.PENDING)
        self.assertTrue(AllowanceRecord.objects.filter(pk=record.pk).exists())

    def test_student_sees_only_their_own_records(self):
        mine = self.make_record(self.student)
        theirs = self.make_record(self.other)
        self.client.login(username="maria", password=PASSWORD)

        response = self.client.get(reverse("allowances:list"))
        self.assertContains(response, mine.reference_number)
        self.assertNotContains(response, theirs.reference_number)

        self.assertEqual(
            self.client.get(reverse("allowances:detail", args=[mine.pk])).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse("allowances:detail", args=[theirs.pk])).status_code,
            404,
        )

    def test_staff_sees_every_record(self):
        mine = self.make_record(self.student)
        theirs = self.make_record(self.other)
        self.client.login(username="staffer", password=PASSWORD)
        response = self.client.get(reverse("allowances:list"))
        self.assertContains(response, mine.reference_number)
        self.assertContains(response, theirs.reference_number)


class CreateTests(AllowanceTestCase):
    def setUp(self):
        super().setUp()
        self.client.login(username="staffer", password=PASSWORD)

    def test_staff_creates_record_saved_to_database(self):
        response = self.client.post(reverse("allowances:create"), self.create_payload())
        record = AllowanceRecord.objects.get()
        self.assertRedirects(response, reverse("allowances:detail", args=[record.pk]))
        self.assertEqual(record.scholar, self.student)
        self.assertEqual(record.created_by, self.staff)
        self.assertEqual(record.status, AllowanceRecord.Status.PENDING)
        self.assertEqual(record.amount, Decimal("3500.00"))
        self.assertRegex(record.reference_number, r"^CCCSP-\d{4}-[A-Z0-9]{6}$")
        self.assertEqual(StatusUpdate.objects.filter(record=record).count(), 1)

    def test_reference_numbers_are_unique(self):
        first = self.make_record(self.student, semester="1st")
        second = self.make_record(self.student, semester="2nd")
        self.assertNotEqual(first.reference_number, second.reference_number)

    def test_invalid_amount_is_rejected(self):
        for bad in ("0", "-50", "50000.01", "abc", ""):
            with self.subTest(amount=bad):
                response = self.client.post(
                    reverse("allowances:create"), self.create_payload(amount=bad)
                )
                self.assertEqual(response.status_code, 200)
                self.assertFalse(AllowanceRecord.objects.exists())

    def test_invalid_academic_year_is_rejected(self):
        for bad in ("2026", "2026-2028", "26-27", "abcd-efgh"):
            with self.subTest(year=bad):
                response = self.client.post(
                    reverse("allowances:create"),
                    self.create_payload(academic_year=bad),
                )
                self.assertEqual(response.status_code, 200)
                self.assertFalse(AllowanceRecord.objects.exists())

    def test_scholar_is_required_and_must_be_a_student(self):
        response = self.client.post(
            reverse("allowances:create"), self.create_payload(scholar="")
        )
        self.assertContains(response, "Choose the scholar")
        response = self.client.post(
            reverse("allowances:create"), self.create_payload(scholar=self.staff.pk)
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(AllowanceRecord.objects.exists())

    def test_one_record_per_scholar_per_term(self):
        self.make_record(self.student)
        response = self.client.post(reverse("allowances:create"), self.create_payload())
        self.assertContains(response, "already has an allowance record")
        self.assertEqual(AllowanceRecord.objects.count(), 1)


class UpdateAndDeleteTests(AllowanceTestCase):
    def setUp(self):
        super().setUp()
        self.client.login(username="staffer", password=PASSWORD)
        self.record = self.make_record()

    def update(self, **overrides):
        return self.client.post(
            reverse("allowances:update", args=[self.record.pk]),
            self.update_payload(self.record, **overrides),
        )

    def test_valid_status_change_updates_record_and_writes_history(self):
        response = self.update(status="verifying", remarks="Documents received.")
        self.assertRedirects(
            response, reverse("allowances:detail", args=[self.record.pk])
        )
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, AllowanceRecord.Status.VERIFYING)
        latest = self.record.status_updates.first()
        self.assertEqual(latest.status, AllowanceRecord.Status.VERIFYING)
        self.assertEqual(latest.changed_by, self.staff)

    def test_editing_amount_without_status_change_adds_no_history(self):
        self.update(amount="4000.00")
        self.record.refresh_from_db()
        self.assertEqual(self.record.amount, Decimal("4000.00"))
        self.assertEqual(self.record.status_updates.count(), 1)

    def test_status_cannot_skip_steps(self):
        response = self.update(status="released")
        self.assertContains(response, "Select a valid choice")
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, AllowanceRecord.Status.PENDING)

    def test_on_hold_requires_a_reason(self):
        response = self.update(status="on_hold", remarks="")
        self.assertContains(response, "Please explain why")
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, AllowanceRecord.Status.PENDING)

        self.update(status="on_hold", remarks="Missing enrollment form.")
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, AllowanceRecord.Status.ON_HOLD)

    def test_scholar_cannot_be_changed_on_edit(self):
        payload = self.update_payload(self.record, scholar=self.other.pk)
        self.client.post(reverse("allowances:update", args=[self.record.pk]), payload)
        self.record.refresh_from_db()
        self.assertEqual(self.record.scholar, self.student)

    def test_released_record_is_locked(self):
        self.record.status = AllowanceRecord.Status.RELEASED
        self.record.save()
        response = self.client.get(reverse("allowances:update", args=[self.record.pk]))
        self.assertRedirects(
            response, reverse("allowances:detail", args=[self.record.pk])
        )
        self.client.post(
            reverse("allowances:update", args=[self.record.pk]),
            self.update_payload(self.record, amount="9999.00"),
        )
        self.record.refresh_from_db()
        self.assertEqual(self.record.amount, Decimal("3500.00"))

    def test_pending_record_can_be_deleted(self):
        response = self.client.post(reverse("allowances:delete", args=[self.record.pk]))
        self.assertRedirects(response, reverse("allowances:list"))
        self.assertFalse(AllowanceRecord.objects.filter(pk=self.record.pk).exists())
        self.assertFalse(StatusUpdate.objects.exists())

    def test_processing_record_cannot_be_deleted(self):
        self.record.status = AllowanceRecord.Status.VERIFYING
        self.record.save()
        self.client.post(reverse("allowances:delete", args=[self.record.pk]))
        self.assertTrue(AllowanceRecord.objects.filter(pk=self.record.pk).exists())


class LookupAndListTests(AllowanceTestCase):
    def test_student_can_look_up_their_own_reference(self):
        record = self.make_record()
        self.client.login(username="maria", password=PASSWORD)
        response = self.client.post(
            reverse("allowances:lookup"),
            {"reference": record.reference_number.lower()},
        )
        self.assertRedirects(response, reverse("allowances:detail", args=[record.pk]))

    def test_student_cannot_look_up_someone_elses_reference(self):
        theirs = self.make_record(self.other)
        self.client.login(username="maria", password=PASSWORD)
        response = self.client.post(
            reverse("allowances:lookup"), {"reference": theirs.reference_number}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No allowance record was found")

    def test_bad_reference_format_is_rejected(self):
        self.client.login(username="maria", password=PASSWORD)
        response = self.client.post(reverse("allowances:lookup"), {"reference": "12345"})
        self.assertContains(response, "Enter a reference number like")

    def test_list_filters_by_status_and_search(self):
        pending = self.make_record(self.student, semester="1st")
        approved = self.make_record(
            self.other, semester="2nd", status=AllowanceRecord.Status.APPROVED
        )
        self.client.login(username="staffer", password=PASSWORD)

        response = self.client.get(reverse("allowances:list"), {"status": "approved"})
        self.assertContains(response, approved.reference_number)
        self.assertNotContains(response, pending.reference_number)

        response = self.client.get(reverse("allowances:list"), {"q": "maria"})
        self.assertContains(response, pending.reference_number)
        self.assertNotContains(response, approved.reference_number)

    def test_detail_shows_progress_and_history(self):
        record = self.make_record()
        self.client.login(username="maria", password=PASSWORD)
        response = self.client.get(reverse("allowances:detail", args=[record.pk]))
        self.assertContains(response, "Status history")
        self.assertContains(response, "Under verification")
        steps = response.context["steps"]
        self.assertEqual(steps[0]["state"], "current")
        self.assertEqual(steps[-1]["state"], "todo")


class DashboardIntegrationTests(AllowanceTestCase):
    def test_student_dashboard_shows_their_allowance(self):
        record = self.make_record()
        self.make_record(self.other)
        self.client.login(username="maria", password=PASSWORD)
        response = self.client.get(reverse("accounts:student_dashboard"))
        self.assertContains(response, record.reference_number)
        self.assertEqual(response.context["allowance_summary"]["total"], 1)

    def test_staff_dashboard_shows_counts_by_status(self):
        self.make_record(self.student)
        self.make_record(self.other)
        self.client.login(username="staffer", password=PASSWORD)
        response = self.client.get(reverse("accounts:staff_dashboard"))
        summary = response.context["allowance_summary"]
        self.assertEqual(summary["total"], 2)
        pending = next(row for row in summary["rows"] if row["value"] == "pending")
        self.assertEqual(pending["count"], 2)
        self.assertContains(response, reverse("allowances:create"))
