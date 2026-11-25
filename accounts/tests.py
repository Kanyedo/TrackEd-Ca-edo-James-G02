from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import AccountProfile

User = get_user_model()


class AccountFeatureTests(TestCase):
    def create_user(self, username, email, role=AccountProfile.Role.STUDENT):
        user = User.objects.create_user(
            username=username,
            email=email,
            password="StrongPassword!42",
            first_name="Sample",
            last_name="User",
        )
        user.account_profile.role = role
        user.account_profile.save()
        return user

    def test_registration_creates_hashed_student_account(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "username": "NewStudent",
                "first_name": "New",
                "last_name": "Student",
                "email": "STUDENT@example.com",
                "password1": "StrongPassword!42",
                "password2": "StrongPassword!42",
            },
        )

        self.assertRedirects(response, reverse("accounts:login"))
        user = User.objects.get(username="NewStudent")
        self.assertNotEqual(user.password, "StrongPassword!42")
        self.assertTrue(user.check_password("StrongPassword!42"))
        self.assertEqual(user.account_profile.role, AccountProfile.Role.STUDENT)
        self.assertEqual(user.email, "student@example.com")

    def test_registration_rejects_mismatched_passwords_and_duplicate_email(self):
        self.create_user("existing", "taken@example.com")
        data = {
            "username": "another",
            "first_name": "Another",
            "last_name": "Student",
            "email": "TAKEN@example.com",
            "password1": "StrongPassword!42",
            "password2": "DifferentPassword!42",
        }

        response = self.client.post(reverse("accounts:register"), data)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="another").exists())
        self.assertContains(response, "already exists")
        self.assertContains(response, "password")

    def test_registration_rejects_duplicate_username_case_insensitively(self):
        self.create_user("existing", "existing@example.com")
        response = self.client.post(
            reverse("accounts:register"),
            {
                "username": "EXISTING",
                "first_name": "Another",
                "last_name": "Student",
                "email": "another@example.com",
                "password1": "StrongPassword!42",
                "password2": "StrongPassword!42",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")
        self.assertEqual(User.objects.count(), 1)

    def test_registration_requires_fields_on_empty_submission(self):
        response = self.client.post(reverse("accounts:register"), {})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required")
        self.assertEqual(User.objects.count(), 0)

    def test_login_routes_each_role_and_rejects_invalid_credentials(self):
        student = self.create_user("student", "student@example.com")
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "student", "password": "StrongPassword!42"},
        )
        self.assertRedirects(response, reverse("accounts:student_dashboard"))

        self.client.post(reverse("accounts:logout"))
        staff = self.create_user("staff", "staff@example.com", AccountProfile.Role.STAFF)
        response = self.client.post(
            reverse("accounts:login"),
            {"username": staff.username, "password": "incorrect"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "username or password")

        response = self.client.post(
            reverse("accounts:login"),
            {"username": staff.username, "password": "StrongPassword!42"},
        )
        self.assertRedirects(response, reverse("accounts:staff_dashboard"))
        self.assertEqual(student.account_profile.role, AccountProfile.Role.STUDENT)

    def test_dashboard_access_is_login_and_role_protected(self):
        protected = reverse("accounts:student_dashboard")
        response = self.client.get(protected)
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={protected}")

        student = self.create_user("student", "student@example.com")
        self.client.force_login(student)
        staff_dashboard = reverse("accounts:staff_dashboard")
        response = self.client.get(staff_dashboard)
        self.assertRedirects(response, reverse("accounts:student_dashboard"))
        self.assertEqual(response.wsgi_request.user, student)

    def test_profile_update_only_changes_current_user(self):
        user = self.create_user("student", "student@example.com")
        other_user = self.create_user("other", "other@example.com")
        self.client.force_login(user)

        response = self.client.post(
            reverse("accounts:profile"),
            {
                "user-first_name": "Updated",
                "user-last_name": "Student",
                "user-email": "updated@example.com",
                "profile-phone_number": "09171234567",
                "profile-school_name": "Cebu Example College",
            },
        )

        self.assertRedirects(response, reverse("accounts:profile"))
        user.refresh_from_db()
        other_user.refresh_from_db()
        self.assertEqual(user.first_name, "Updated")
        self.assertEqual(user.email, "updated@example.com")
        self.assertEqual(user.account_profile.phone_number, "09171234567")
        self.assertEqual(other_user.email, "other@example.com")

    def test_empty_profile_submission_does_not_clear_details(self):
        user = self.create_user("student", "student@example.com")
        user.account_profile.phone_number = "09171234567"
        user.account_profile.save()
        self.client.force_login(user)

        response = self.client.post(reverse("accounts:profile"), {})

        self.assertEqual(response.status_code, 200)
        user.account_profile.refresh_from_db()
        self.assertEqual(user.account_profile.phone_number, "09171234567")
        self.assertContains(response, "Please correct the errors below.")

    def test_logout_ends_session(self):
        user = self.create_user("student", "student@example.com")
        self.client.force_login(user)

        response = self.client.post(reverse("accounts:logout"))

        self.assertRedirects(response, reverse("accounts:login"))
        self.assertNotIn("_auth_user_id", self.client.session)


class AccountHardeningTests(TestCase):
    """PD3 hardening checks for the standard features."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="student",
            email="student@example.com",
            password="StrongPassword!42",
            first_name="Sample",
            last_name="User",
        )

    def profile_payload(self, **overrides):
        data = {
            "user-first_name": "Sample",
            "user-last_name": "User",
            "user-email": "student@example.com",
            "profile-phone_number": "",
            "profile-school_name": "",
        }
        data.update(overrides)
        return data

    def test_login_ignores_next_urls_to_other_sites(self):
        for evil in ("https://evil.example/", "//evil.example/", "javascript:alert(1)"):
            with self.subTest(next=evil):
                response = self.client.post(
                    reverse("accounts:login"),
                    {"username": "student", "password": "StrongPassword!42", "next": evil},
                )
                self.assertRedirects(response, reverse("accounts:student_dashboard"))
                self.client.post(reverse("accounts:logout"))

    def test_logout_by_get_is_refused(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:logout"))
        self.assertEqual(response.status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)

    def test_profile_rejects_blank_names(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:profile"),
            self.profile_payload(**{"user-first_name": "  ", "user-last_name": ""}),
        )
        self.assertContains(response, "This field is required")
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Sample")

    def test_profile_rejects_invalid_phone_number(self):
        self.client.force_login(self.user)
        for bad in ("abc", "12", "0917<script>"):
            with self.subTest(phone=bad):
                response = self.client.post(
                    reverse("accounts:profile"),
                    self.profile_payload(**{"profile-phone_number": bad}),
                )
                self.assertContains(response, "Enter a valid phone number")
        self.user.account_profile.refresh_from_db()
        self.assertEqual(self.user.account_profile.phone_number, "")

    def test_profile_accepts_valid_phone_number(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:profile"),
            self.profile_payload(**{"profile-phone_number": " 0917 123 4567 "}),
            follow=True,
        )
        self.assertContains(response, "Your profile has been updated.")
        self.user.account_profile.refresh_from_db()
        self.assertEqual(self.user.account_profile.phone_number, "0917 123 4567")

    def test_database_rejects_unknown_role(self):
        from django.db import IntegrityError, transaction

        profile = self.user.account_profile
        profile.role = "admin"
        with self.assertRaises(IntegrityError), transaction.atomic():
            profile.save()

    def test_registration_cannot_grant_staff_role(self):
        self.client.post(
            reverse("accounts:register"),
            {
                "username": "sneaky",
                "first_name": "Sneaky",
                "last_name": "User",
                "email": "sneaky@example.com",
                "password1": "StrongPassword!42",
                "password2": "StrongPassword!42",
                "role": "staff",
                "account_profile-role": "staff",
            },
        )
        sneaky = User.objects.get(username="sneaky")
        self.assertEqual(sneaky.account_profile.role, AccountProfile.Role.STUDENT)

    def test_admin_bulk_action_sets_staff_role(self):
        admin_user = User.objects.create_superuser("admin", "admin@example.com", "StrongPassword!42")
        self.client.force_login(admin_user)
        response = self.client.post(
            reverse("admin:auth_user_changelist"),
            {"action": "make_staff", "_selected_action": [self.user.pk]},
            follow=True,
        )
        self.assertContains(response, "set to CCCSP Staff")
        self.user.account_profile.refresh_from_db()
        self.assertEqual(self.user.account_profile.role, AccountProfile.Role.STAFF)

    def test_debug_flag_is_read_from_env_and_defaults_to_off(self):
        import os
        from unittest import mock

        from config.settings import env_bool

        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(env_bool("DJANGO_DEBUG"))
        for raw, expected in (("True", True), ("1", True), ("false", False), ("", False)):
            with self.subTest(raw=raw), mock.patch.dict(os.environ, {"DJANGO_DEBUG": raw}):
                self.assertEqual(env_bool("DJANGO_DEBUG"), expected)


class RowLevelSecurityTests(TestCase):
    """ISS-01: every table has Row Level Security turned on after migrate."""

    def test_all_tables_have_rls_enabled(self):
        from django.db import connection

        if connection.vendor != "postgresql":
            self.skipTest("Row Level Security is a PostgreSQL feature.")
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.relname FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT c.relrowsecurity
                """
            )
            without_rls = [row[0] for row in cursor.fetchall()]
        self.assertEqual(without_rls, [])
        self.assertIn("allowances_allowancerecord", connection.introspection.table_names())
