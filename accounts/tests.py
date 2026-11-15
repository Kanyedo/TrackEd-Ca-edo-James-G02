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
