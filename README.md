# TrackEd Cebu

TrackEd Cebu is the CCCSP Scholarship Tracking and Eligibility System. Increment 1 provides student and CCCSP staff accounts, login/logout, role-specific dashboards, and profile management. Increment 2 adds the core feature, the **Allowance Status Tracker**. Public registration creates student accounts; staff roles are assigned by an administrator.

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

4. Create an administrator and start the development server:

   ```powershell
   python manage.py createsuperuser
   python manage.py runserver
   ```

   Open `http://127.0.0.1:8000/`. Student registration is at `/register/`; the Django admin is at `/admin/`.

## Assigning the CCCSP Staff role

Sign in to `/admin/` with a superuser, open **Users**, and edit the account. In the **Account profile** section, set **Role** to **CCCSP Staff**. Staff users can then log in at the regular login page and will be sent to the staff dashboard. Public sign-up cannot grant staff access.

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

### Run the tests

```powershell
python manage.py test
```

## Branching workflow

`main` holds stable code only. `develop` is the integration branch. Each feature is built on a `feature/<name>` branch created from `develop`, merged into `develop` with a pull request, and `develop` is merged into `main` with a pull request when an increment is done. Merged feature branches are kept.
