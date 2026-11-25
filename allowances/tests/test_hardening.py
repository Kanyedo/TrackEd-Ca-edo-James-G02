"""PD3 hardening tests for the Allowance Status Tracker (core feature).

Each class maps to a part of the PD3 checklist:

* ValidInputTests          - valid input is saved and redirects (PRG)
* InvalidInputTests        - server-side validation and business rules
* LoginRequiredTests       - every core view needs a logged-in user
* OtherUsersRecordTests    - changing the ID in the URL does not expose or
                             change another scholar's record
* InvalidUrlAndMethodTests - bad IDs give the custom 404; delete/update are
                             POST-only; CSRF is enforced
* DataIntegrityTests       - database constraints and transaction.atomic()
* ErrorPageTests           - custom 500 page, no debug traceback
"""

from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import path, reverse

from accounts.models import AccountProfile
from allowances.models import AllowanceRecord, StatusUpdate

User = get_user_model()
PASSWORD = "StrongPassword!42"


def boom(request):
    raise RuntimeError("Simulated server error")


# URLconf used only by ErrorPageTests to trigger a real 500 error.
urlpatterns = [path("boom/", boom)]


class HardeningTestCase(TestCase):
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


class ValidInputTests(HardeningTestCase):
    def test_valid_create_saves_record_and_redirects_with_success_message(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("allowances:create"), self.create_payload(), follow=True
        )
        record = AllowanceRecord.objects.get()
        self.assertRedirects(response, reverse("allowances:detail", args=[record.pk]))
        self.assertContains(response, f"Allowance record {record.reference_number} was created.")
        self.assertEqual(record.status, AllowanceRecord.Status.PENDING)

    def test_on_hold_then_resume_keeps_full_history(self):
        record = self.make_record()
        self.client.force_login(self.staff)
        url = reverse("allowances:update", args=[record.pk])
        self.client.post(url, self.update_payload(record, status="on_hold", remarks="Missing COR."))
        record.refresh_from_db()
        self.client.post(url, self.update_payload(record, status="verifying", remarks="COR received."))
        record.refresh_from_db()
        self.assertEqual(record.status, AllowanceRecord.Status.VERIFYING)
        self.assertEqual(
            list(record.status_updates.order_by("changed_at", "id").values_list("status", flat=True)),
            ["pending", "on_hold", "verifying"],
        )


class InvalidInputTests(HardeningTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.staff)

    def test_academic_year_too_far_back_or_ahead_is_rejected(self):
        for bad in ("1999-2000", "2090-2091"):
            with self.subTest(year=bad):
                response = self.client.post(
                    reverse("allowances:create"), self.create_payload(academic_year=bad)
                )
                self.assertContains(response, "Academic year must start between")
                self.assertContains(response, "Please correct the errors below.")
        self.assertFalse(AllowanceRecord.objects.exists())

    def test_whitespace_only_reason_does_not_count_for_on_hold(self):
        record = self.make_record()
        response = self.client.post(
            reverse("allowances:update", args=[record.pk]),
            self.update_payload(record, status="on_hold", remarks="    "),
        )
        self.assertContains(response, "Please explain why")
        record.refresh_from_db()
        self.assertEqual(record.status, AllowanceRecord.Status.PENDING)

    def test_overlong_remarks_are_rejected(self):
        response = self.client.post(
            reverse("allowances:create"), self.create_payload(remarks="x" * 1001)
        )
        self.assertContains(response, "1000 characters or fewer")
        self.assertFalse(AllowanceRecord.objects.exists())

    def test_tampered_status_on_create_is_ignored(self):
        """A hand-crafted POST cannot create a record that is already Released."""
        self.client.post(reverse("allowances:create"), self.create_payload(status="released"))
        self.assertEqual(AllowanceRecord.objects.get().status, AllowanceRecord.Status.PENDING)

    def test_non_numeric_scholar_id_is_rejected_without_crashing(self):
        response = self.client.post(
            reverse("allowances:create"), self.create_payload(scholar="abc")
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(AllowanceRecord.objects.exists())

    def test_user_input_is_escaped_in_pages(self):
        record = self.make_record(remarks="<script>alert('x')</script>")
        response = self.client.get(reverse("allowances:detail", args=[record.pk]))
        self.assertNotContains(response, "<script>alert('x')</script>")
        self.assertContains(response, "&lt;script&gt;")


class LoginRequiredTests(HardeningTestCase):
    def test_anonymous_post_cannot_create_update_or_delete(self):
        record = self.make_record()
        login_url = reverse("accounts:login")
        for url, data in (
            (reverse("allowances:create"), self.create_payload(semester="2nd")),
            (reverse("allowances:update", args=[record.pk]), self.update_payload(record, status="verifying")),
            (reverse("allowances:delete", args=[record.pk]), {}),
            (reverse("allowances:lookup"), {"reference": record.reference_number}),
        ):
            with self.subTest(url=url):
                response = self.client.post(url, data)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response["Location"].startswith(login_url))
        record.refresh_from_db()
        self.assertEqual(record.status, AllowanceRecord.Status.PENDING)
        self.assertEqual(AllowanceRecord.objects.count(), 1)

    def test_login_redirects_back_to_requested_page(self):
        record = self.make_record()
        detail = reverse("allowances:detail", args=[record.pk])
        response = self.client.post(
            f"{reverse('accounts:login')}?next={detail}",
            {"username": "maria", "password": PASSWORD},
        )
        self.assertRedirects(response, detail)


class OtherUsersRecordTests(HardeningTestCase):
    """A student must not reach another scholar's record by editing the URL."""

    def setUp(self):
        super().setUp()
        self.theirs = self.make_record(self.other)
        self.client.force_login(self.student)

    def test_student_gets_404_for_another_scholars_record(self):
        response = self.client.get(reverse("allowances:detail", args=[self.theirs.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "404.html")
        self.assertNotContains(response, self.theirs.reference_number, status_code=404)

    def test_student_cannot_edit_or_delete_another_scholars_record_by_id(self):
        self.client.post(
            reverse("allowances:update", args=[self.theirs.pk]),
            self.update_payload(self.theirs, status="verifying", amount="1.00"),
        )
        self.client.post(reverse("allowances:delete", args=[self.theirs.pk]))
        self.theirs.refresh_from_db()
        self.assertEqual(self.theirs.status, AllowanceRecord.Status.PENDING)
        self.assertEqual(self.theirs.amount, Decimal("3500.00"))

    def test_student_cannot_edit_their_own_record_either(self):
        mine = self.make_record(self.student)
        response = self.client.post(
            reverse("allowances:update", args=[mine.pk]),
            self.update_payload(mine, amount="49999.00"),
            follow=True,
        )
        self.assertContains(response, "Only CCCSP staff can do that.")
        mine.refresh_from_db()
        self.assertEqual(mine.amount, Decimal("3500.00"))

    def test_student_list_search_never_shows_other_scholars(self):
        response = self.client.get(
            reverse("allowances:list"), {"q": self.theirs.reference_number}
        )
        self.assertEqual(list(response.context["page_obj"].object_list), [])
        self.assertContains(response, "No records match your filters")

    def test_student_cannot_open_another_users_profile_by_id(self):
        # The profile page has no ID in the URL: it always edits request.user.
        response = self.client.get(reverse("accounts:profile"), {"id": self.other.pk})
        self.assertEqual(response.context["user_form"].instance, self.student)


class InvalidUrlAndMethodTests(HardeningTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.staff)

    def test_missing_or_out_of_range_ids_show_custom_404(self):
        for pk in (999999, 2**63 + 10):
            for name in ("allowances:detail", "allowances:update", "allowances:delete"):
                with self.subTest(pk=pk, view=name):
                    response = self.client.get(reverse(name, args=[pk]))
                    self.assertEqual(response.status_code, 404)
                    self.assertTemplateUsed(response, "404.html")

    def test_non_numeric_id_and_unknown_page_show_custom_404(self):
        for url in ("/allowances/abc/", "/allowances/1/hack/", "/no-such-page/"):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 404)
                self.assertContains(response, "Page not found", status_code=404)
                self.assertNotContains(response, "Traceback", status_code=404)

    def test_bad_query_parameters_do_not_crash_the_list(self):
        response = self.client.get(
            reverse("allowances:list"), {"page": "xyz", "status": "bogus", "q": "x" * 500}
        )
        self.assertEqual(response.status_code, 200)

    def test_get_on_delete_only_shows_confirmation(self):
        record = self.make_record()
        response = self.client.get(reverse("allowances:delete", args=[record.pk]))
        self.assertContains(response, "Yes, delete")
        self.assertTrue(AllowanceRecord.objects.filter(pk=record.pk).exists())

    def test_other_http_methods_are_refused(self):
        record = self.make_record()
        for method in ("put", "patch", "delete"):
            for name in ("allowances:update", "allowances:delete"):
                with self.subTest(method=method, view=name):
                    response = getattr(self.client, method)(reverse(name, args=[record.pk]))
                    self.assertEqual(response.status_code, 405)
        self.assertEqual(self.client.post(reverse("allowances:list")).status_code, 405)
        self.assertTrue(AllowanceRecord.objects.filter(pk=record.pk).exists())

    def test_post_without_csrf_token_is_rejected(self):
        record = self.make_record()
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.staff)
        response = csrf_client.post(reverse("allowances:delete", args=[record.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Your form has expired", status_code=403)
        self.assertTrue(AllowanceRecord.objects.filter(pk=record.pk).exists())

    def test_every_post_form_has_a_csrf_token(self):
        record = self.make_record()
        for url in (
            reverse("allowances:create"),
            reverse("allowances:update", args=[record.pk]),
            reverse("allowances:delete", args=[record.pk]),
            reverse("allowances:lookup"),
            reverse("accounts:profile"),
        ):
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), "csrfmiddlewaretoken")

    def test_list_query_count_does_not_grow_with_records(self):
        self.make_record(self.student)
        with CaptureQueriesContext(connection) as few:
            self.client.get(reverse("allowances:list"))
        for index in range(6):
            scholar = self.make_user(f"scholar{index}")
            self.make_record(scholar)
        with CaptureQueriesContext(connection) as many:
            self.client.get(reverse("allowances:list"))
        self.assertEqual(len(few), len(many))


class DataIntegrityTests(HardeningTestCase):
    def test_database_rejects_out_of_range_amount(self):
        for amount in (Decimal("-5.00"), Decimal("0.00"), Decimal("50000.01")):
            with self.subTest(amount=amount):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    AllowanceRecord.objects.create(
                        scholar=self.student,
                        academic_year="2026-2027",
                        semester="1st",
                        amount=amount,
                    )

    def test_database_rejects_unknown_status_and_bad_year(self):
        for overrides in ({"status": "paid"}, {"semester": "3rd"}, {"academic_year": "abcd"}):
            with self.subTest(**overrides):
                data = {
                    "scholar": self.student,
                    "academic_year": "2026-2027",
                    "semester": "1st",
                    "amount": Decimal("100.00"),
                }
                data.update(overrides)
                with self.assertRaises(IntegrityError), transaction.atomic():
                    AllowanceRecord.objects.create(**data)

    def test_database_rejects_duplicate_term(self):
        self.make_record()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_record()

    def test_failed_history_write_rolls_back_the_new_record(self):
        self.client.force_login(self.staff)
        with mock.patch.object(
            AllowanceRecord, "log_status", side_effect=RuntimeError("history write failed")
        ):
            with self.assertRaises(RuntimeError), self.assertLogs("django.request", "ERROR"):
                self.client.post(reverse("allowances:create"), self.create_payload())
        self.assertFalse(AllowanceRecord.objects.exists())
        self.assertFalse(StatusUpdate.objects.exists())

    def test_failed_history_write_rolls_back_the_status_change(self):
        record = self.make_record()
        self.client.force_login(self.staff)
        with mock.patch.object(
            AllowanceRecord, "log_status", side_effect=RuntimeError("history write failed")
        ):
            with self.assertRaises(RuntimeError), self.assertLogs("django.request", "ERROR"):
                self.client.post(
                    reverse("allowances:update", args=[record.pk]),
                    self.update_payload(record, status="verifying"),
                )
        record.refresh_from_db()
        self.assertEqual(record.status, AllowanceRecord.Status.PENDING)

    def test_scholar_with_allowances_cannot_be_deleted(self):
        from django.db.models import ProtectedError

        self.make_record()
        with self.assertRaises(ProtectedError):
            self.student.delete()

    def test_deleting_staff_keeps_records_and_history(self):
        record = self.make_record()
        self.staff.delete()
        record.refresh_from_db()
        self.assertIsNone(record.created_by)
        self.assertIsNone(record.status_updates.get().changed_by)

    @mock.patch("allowances.views.AllowanceRecord.can_delete", new_callable=mock.PropertyMock)
    def test_delete_rechecks_status_inside_the_transaction(self, can_delete):
        """If the record left Pending after the page loaded, the delete is refused."""
        record = self.make_record()
        self.client.force_login(self.staff)
        can_delete.side_effect = [True, False]  # first check passes, locked re-check fails
        response = self.client.post(reverse("allowances:delete", args=[record.pk]), follow=True)
        self.assertContains(response, "Only Pending allowances can be deleted.")
        self.assertTrue(AllowanceRecord.objects.filter(pk=record.pk).exists())


@override_settings(ROOT_URLCONF="allowances.tests.test_hardening", DEBUG=False)
class ErrorPageTests(TestCase):
    def test_server_error_shows_custom_500_page_without_traceback(self):
        client = Client(raise_request_exception=False)
        with self.assertLogs("django.request", "ERROR") as logs:
            response = client.get("/boom/")
        self.assertIn("Internal Server Error: /boom/", logs.output[0])
        self.assertEqual(response.status_code, 500)
        self.assertTemplateUsed(response, "500.html")
        self.assertContains(response, "Something went wrong on our side", status_code=500)
        self.assertNotContains(response, "Traceback", status_code=500)
        self.assertNotContains(response, "Simulated server error", status_code=500)
