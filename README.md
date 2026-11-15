# TrackEd Cebu

TrackEd Cebu is the CCCSP Scholarship Tracking and Eligibility System. This first increment provides student and CCCSP staff accounts, login/logout, role-specific dashboards, and profile management. Public registration creates student accounts; staff roles are assigned by an administrator.

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

3. Create the database named in `POSTGRES_DB` (for example, `tracked`) in PostgreSQL, then apply migrations:

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
