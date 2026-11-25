# TrackEd Cebu

TrackEd Cebu is the CCCSP Scholarship Tracking and Eligibility System. Increment 1 provides student and CCCSP staff accounts, login/logout, role-specific dashboards, and profile management. Increment 2 adds the core feature, the **Allowance Status Tracker**. Increment 3 (PD3) hardens the core feature and the standard features: validation, access control, data integrity, custom error pages, and automated tests. Public registration creates student accounts; staff roles are assigned by an administrator.

## Requirements

- Python 3.12 or later
- PostgreSQL (local or hosted, including Supabase)

## Local setup (Windows PowerShell)

1. Create and activate a virtual environment, then install dependencies:

   ```powershell
   py -m venv venv
   .\venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

2. Create a local environment file and edit it with your PostgreSQL connection details:

   ```powershell
   Copy-Item .env.example .env
   ```

   Set `DJANGO_SECRET_KEY` to a private random value and set the `POSTGRES_*` values for your database. For Supabase, use the connection host and credentials from the project dashboard and set `POSTGRES_SSLMODE=require`. Do not commit `.env`.

3. Create the database named in `POSTGRES_DB` (for example, `tracked`) in PostgreSQL. On Supabase the database is already named `postgres`, so use `POSTGRES_DB=postgres`, the **Session pooler** host, and the user `postgres.<project-ref>` from the dashboard's Connect panel. Then apply migrations:

   ```powershell
   python manage.py migrate
   ```

   `migrate` also turns on Row Level Security for every table (see ISS-01 below). To apply it to an existing database without migrating, run `python manage.py enable_rls`.

4. Create an administrator and start the development server:

   ```powershell
   python manage.py createsuperuser
   python manage.py runserver
   ```

   Open `http://127.0.0.1:8000/`. Student registration is at `/register/`; the Django admin is at `/admin/`.

   With `DJANGO_DEBUG=False` (the default), Django's development server does not serve CSS. Start it with `python manage.py runserver --insecure` to see the styled pages, including the custom 404 and 500 error pages.

## Assigning the CCCSP Staff role

Sign in to `/admin/` with a superuser and open **Users**. The list shows each account's role and can be filtered by role. Tick one or more accounts, choose **Set selected accounts to CCCSP Staff** from the Action menu, and click **Go**. You can also edit a single account and set **Role** to **CCCSP Staff** in the **Account profile** section. Staff users can then log in at the regular login page and will be sent to the staff dashboard. Public sign-up cannot grant staff access.

## Core feature: Allowance Status Tracker

The Allowance Status Tracker is the main thing TrackEd Cebu exists to do: CCCSP staff record each scholar's allowance for an academic term and move it through processing, and scholars follow its progress using a reference number. It is a full vertical slice: models and migrations in PostgreSQL/Supabase (`allowances/models.py`), Django views, forms, and URLs (`allowances/views.py`, `forms.py`, `urls.py`), and templates the user clicks through (`allowances/templates/allowances/`).

### What each role can do

| Role | Access |
| --- | --- |
| CCCSP Staff | Create, view, update, and delete allowance records for any scholar; search and filter the full list; see per-status counts on the staff dashboard |
| Student | View only their own allowance records and status history; look up their own reference number; see their latest allowance on the student dashboard |

Anonymous visitors are redirected to the login page. A student who opens another scholar's record gets a 404.

### Pages

- `/allowances/` list with search, status filter, and pagination
- `/allowances/new/` create (staff)
- `/allowances/<id>/` detail with progress tracker and status history
- `/allowances/<id>/edit/` update (staff)
- `/allowances/<id>/delete/` delete with confirmation (staff)
- `/allowances/lookup/` look up a reference number such as `CCCSP-2026-ABC123`

### Data model

- `AllowanceRecord`: `scholar` (ForeignKey to User), `created_by` (ForeignKey to User), auto-generated unique `reference_number`, `academic_year`, `semester`, `amount`, `status`, `remarks`, timestamps.
- `StatusUpdate`: one row per status change, with a ForeignKey to `AllowanceRecord` and to the user who made the change.

### Business rules

- BR-A1: Only CCCSP staff can create, edit, or delete allowance records. Students are read-only.
- BR-A2: A scholar can have only one allowance record per academic year and semester.
- BR-A3: Academic year must look like `2026-2027` (second year = first year + 1). Amount must be between PHP 1.00 and PHP 50,000.00.
- BR-A4: New records always start as Pending. Status moves forward only: Pending, Under verification, Approved, Ready for release, Released. A record can be put On hold (a reason is required) and resumed later.
- BR-A5: Released records are locked and cannot be edited. Only Pending records can be deleted.
- BR-A6: Every status change is written to the record's status history.

## Hardening (PD3)

| Area | What is in place |
| --- | --- |
| Validation | Every form is validated on the server (forms use `novalidate`, so browser checks are never the only check). Academic year format and range, amount range, on-hold reason, remarks length, phone number format, required profile names. |
| Business rules | One record per scholar per term; status moves forward only; Released records are locked; only Pending records can be deleted. Update and delete re-check the record under `select_for_update()` so two staff members cannot race each other. |
| Messages | A success or error message after every create, update, delete, lookup, login, logout, registration, and profile save. |
| Error pages | `templates/404.html`, `403.html`, `403_csrf.html`, `400.html`, `500.html`. `DEBUG` comes only from `.env` and is off by default, so no debug or traceback page is shown. Bad or out-of-range IDs return the 404 page (`get_object_or_404`). |
| Access control | All core views need login; the staff role is checked inside the view (`staff_required`), not only by hiding buttons. Students get a 404 for another scholar's record. Profile pages always use the logged-in user, so there is no ID to change. Login `?next=` only allows same-site addresses. |
| HTTP methods and CSRF | Each view lists the methods it accepts (others get 405). Delete, update, and logout only change data on POST, and every POST form has `{% csrf_token %}`. |
| Database | Django ORM only; no `\|safe` on user input. Unique and check constraints for amount, status, semester, academic year, and role. `on_delete`: scholar `PROTECT`, creator and history author `SET_NULL`, status history `CASCADE`. Multi-step saves use `transaction.atomic()`. List pages use `select_related`. |
| Duplicate submissions | Every successful POST redirects; submit buttons are disabled after the first click. |
| Settings | Secrets and `DEBUG` in `.env` (never committed). HttpOnly/SameSite cookies, `X-Frame-Options: DENY`, nosniff, 8-hour sessions; HTTPS-only cookies can be turned on in `.env`. |
| Supabase (ISS-01) | Row Level Security is enabled on every table after each `migrate`. Django connects as the table owner, so the app is not affected, but Supabase's public API can no longer read the tables. |

## Run the tests

The tests use the PostgreSQL connection in `.env`. Django creates a separate temporary database named `test_<POSTGRES_DB>`, so your real data is not touched. The PostgreSQL user must be allowed to create databases (the default `postgres` user can).

```powershell
.\venv\Scripts\Activate.ps1
python manage.py test
```

Useful variations:

```powershell
python manage.py test allowances            # core feature only
python manage.py test accounts              # standard features only
python manage.py test allowances.tests.test_hardening   # PD3 hardening tests only
python manage.py test -v 2                  # list every test by name
```

On Supabase, the test database is created on the same project; if your plan does not allow creating databases, run the tests against a local PostgreSQL instead.

Test files:

- `allowances/tests/test_core_feature.py`: create, read, update, delete, lookup, list, and dashboard tests from PD2
- `allowances/tests/test_hardening.py`: PD3 checks for valid input, invalid input, login required, blocked access to another scholar's record, invalid IDs, HTTP methods, CSRF, database constraints, transactions, and the custom 500 page
- `accounts/tests.py`: registration, login/logout, dashboards, profile, and PD3 checks for the standard features

## Branching workflow

`main` holds stable code only; nothing is committed to it directly. `develop` is the integration branch. Work branches are created from `develop`, merged into `develop` with a pull request, and `develop` is merged into `main` with a pull request when an increment is done. Merged branches are kept.

| Prefix | Used for | PD3 branches |
| --- | --- | --- |
| `feature/` | new features (PD1, PD2) | `feature/1-account-feature`, `feature/2-allowance-status-tracker` |
| `fix/` | bug fixes from the issue list | `fix/iss-01-supabase-rls`, `fix/iss-03-staff-role-admin` |
| `hardening/` | hardening work | `hardening/error-pages-and-settings`, `hardening/access-control`, `hardening/data-integrity` |
| `test/` | automated tests | `test/core-feature-tests` |
