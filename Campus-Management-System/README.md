# Campus Management System (CMS)

A Django-based Campus Management System with:

- Attendance Management (manual + face recognition)
- Faculty Dashboard + Attendance Center
- Automated absent email notifications (student + parent)
- Food Ordering module with order confirmation emails
- Production-ready configuration for deployment (Gunicorn + WhiteNoise)

---

## Tech Stack

- Python 3.10+ (works with Python 3.10/3.11)
- Django 5.x
- SQLite (default)
- Gunicorn (production WSGI server)
- WhiteNoise (static files in production)
- OpenCV + NumPy + Pillow (face recognition)

---

## Project Setup (Local Development)

### 1) Clone and enter the project

```bash
git clone <YOUR_REPO_URL>
cd "Campus Management System"
```

### 2) Create and activate a virtual environment

Windows PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\activate
```

### 3) Install dependencies

```powershell
python -m pip install -r requirements.txt
```

### 4) Run migrations

```powershell
python manage.py migrate
```

### 5) Collect static (optional locally, required on Render)

```powershell
python manage.py collectstatic --noinput
```

### 6) Create an admin user

```powershell
python manage.py createsuperuser
```

### 7) Run the dev server

```powershell
python manage.py runserver
```

Open:

- http://127.0.0.1:8000/

---

## Default Roles / Access Model (No Passwords)

This project uses Django authentication (`auth_user`) and role-based access patterns.

- **Superuser (Admin)**
  - Full access to Django Admin.
  - Can manage master data (students, courses, faculty, stalls, menu items, etc.).
  - Can view and modify any records.

- **Faculty / Instructor**
  - Access to faculty dashboards and attendance tools.
  - Can create/mark sessions for their assigned courses (as configured in the database).

- **Student**
  - Access to student-facing pages (e.g., student dashboard / food ordering).
  - Food ordering is restricted to student accounts via authorization decorators.

- **Vendor**
  - Access to vendor dashboard for managing food orders.
  - Vendor capabilities are typically controlled by group membership (e.g., `VENDOR`).

Create a superuser via:

```powershell
python manage.py createsuperuser
```

---

## Database

### Default (local)

The project uses SQLite by default:

- `db.sqlite3` in the project root

### Notes

- SQLite is fine for development and small deployments.
- For larger production usage, Postgres is recommended.

---

## SMTP / Email Configuration (Gmail)

The system sends:

- Attendance absent notifications (to student + parent)
- Food order confirmation emails

### Required environment variables

Set these environment variables in the terminal/session where you run the server:

- `SMARTLPU_EMAIL_HOST_USER` (example: `workspace.6091@gmail.com`)
- `SMARTLPU_EMAIL_HOST_PASSWORD` (Gmail App Password)
- `SMARTLPU_DEFAULT_FROM_EMAIL` (example: `workspace.6091@gmail.com`)

#### Windows PowerShell (current terminal session)

```powershell
$env:SMARTLPU_EMAIL_HOST_USER="workspace.6091@gmail.com"
$env:SMARTLPU_EMAIL_HOST_PASSWORD="YOUR_GMAIL_APP_PASSWORD"
$env:SMARTLPU_DEFAULT_FROM_EMAIL="workspace.6091@gmail.com"
```

#### Make it persistent (recommended on Windows)

```powershell
setx SMARTLPU_EMAIL_HOST_USER "workspace.6091@gmail.com"
setx SMARTLPU_EMAIL_HOST_PASSWORD "YOUR_GMAIL_APP_PASSWORD"
setx SMARTLPU_DEFAULT_FROM_EMAIL "workspace.6091@gmail.com"
```

After `setx`, **close and reopen** terminals/VS Code so new processes inherit the variables.

### Gmail requirements

- Enable 2-Step Verification on the Gmail account.
- Create an **App Password** for Mail.
- Use the App Password as `SMARTLPU_EMAIL_HOST_PASSWORD`.

### Quick SMTP test

```powershell
.\venv\Scripts\python -c "import os,django; os.environ.setdefault('DJANGO_SETTINGS_MODULE','smartlpu.settings'); django.setup(); from django.core.mail import send_mail; from django.conf import settings; print('HOST_USER=',settings.EMAIL_HOST_USER,'FROM=',settings.DEFAULT_FROM_EMAIL,'PWD_LEN=',len(settings.EMAIL_HOST_PASSWORD or '')); send_mail('CMS SMTP Test','This is a test email from CMS (Django).',settings.DEFAULT_FROM_EMAIL,[settings.EMAIL_HOST_USER],fail_silently=False); print('SENT_OK')"
```

---

## Attendance Module

### Marking attendance

- Manual marking (checkbox-based)
- Face Recognition marking:
  - Photo upload
  - Live webcam capture

### Absent email notifications

When a session is saved:

- Absentees are detected.
- Absent emails are sent to:
  - `Student.email`
  - `Student.parent_email`

If email is not configured, you will see a warning message on the UI.

### Email content

Absent email content includes:

- Student Name
- UID
- Roll No
- Course details
- Session date/time/room/label

---

## Face Recognition Workflow (Attendance)

The attendance system supports face recognition using OpenCV (LBPH recognizer).

### A) Add Face Data (Enroll faces)

Before face-based attendance can work reliably, you must add face images for each student.

Recommended capture guidance:

- Capture **5-10 clear photos per student**.
- Use good lighting and front-facing angle.
- Avoid heavy blur.
- Prefer one student per capture while building the dataset.

### B) Photo Upload marking

Use the Photo Upload option when:

- You have an image from phone/classroom camera.
- You want to mark using a single photo.

Notes:

- Group photos may work depending on recognition quality.
- The app uses a confidence threshold; if no confident match is found, it will prompt you to improve face data.

### C) Live Webcam marking

Use Live Webcam when:

- Students are present in front of the camera sequentially.

Suggested workflow:

- Start camera.
- Capture/mark each student.
- For next student, repeat capture.

The UI shows a small counter/status (e.g., “Last marked: X”) to confirm continuous marking.

---

## Food Ordering Module

### Order confirmation email

After a successful order placement, the system attempts to send an email to:

- `order.student.email` (if set)
- `order.ordered_by_user.email` (if set)

If the email cannot be sent, a warning message appears in the UI with the reason.

---

## Deployment (Render)

This repository includes `render.yaml` for Render deployment.

### Important note about SQLite on Render

- For SQLite to persist across deploys/restarts on Render, you need a **Persistent Disk**.
- Render Persistent Disks generally require a **paid plan**.
- If you deploy SQLite on a Free plan without a disk, the database can be reset.

### Settings used for production

`smartlpu/settings.py` is configured for production-friendly deployment:

- `SECRET_KEY` from env: `SMARTLPU_SECRET_KEY`
- `DEBUG` from env: `SMARTLPU_DEBUG` (`"0"` recommended on production)
- `ALLOWED_HOSTS` from env: `SMARTLPU_ALLOWED_HOSTS`
- Static files served by WhiteNoise:
  - `STATICFILES_STORAGE = whitenoise.storage.CompressedManifestStaticFilesStorage`

### Recommended Render environment variables

- `SMARTLPU_DEBUG=0`
- `SMARTLPU_SECRET_KEY=<generated>`
- `SMARTLPU_ALLOWED_HOSTS=<your-service>.onrender.com`
- `SMARTLPU_CSRF_TRUSTED_ORIGINS=https://<your-service>.onrender.com`

Email:

- `SMARTLPU_EMAIL_HOST_USER=<gmail>`
- `SMARTLPU_EMAIL_HOST_PASSWORD=<app_password>`
- `SMARTLPU_DEFAULT_FROM_EMAIL=<gmail>`

SQLite (only if you have a persistent disk):

- `SMARTLPU_SQLITE_PATH=/var/data/db.sqlite3`

### Render build/start commands

- Build:
  - `pip install -r requirements.txt`
  - `python manage.py collectstatic --noinput`
  - `python manage.py migrate`
- Start:
  - `gunicorn smartlpu.wsgi:application`

---

## Troubleshooting

### Emails not sending

- Confirm environment variables are visible to the running server process.
- Restart terminal/VS Code after using `setx`.
- Confirm Gmail App Password is used (not normal Gmail password).

---

## Common Deployment Errors (and Fixes)

### CSRF verification failed

Symptoms:

- Login or form submit fails on Render with CSRF error.

Fix:

- Set `SMARTLPU_CSRF_TRUSTED_ORIGINS` to include your exact Render domain:

```text
SMARTLPU_CSRF_TRUSTED_ORIGINS=https://<your-service>.onrender.com
```

### DisallowedHost / Invalid HTTP_HOST header

Symptoms:

- Page shows `DisallowedHost` error.

Fix:

- Set `SMARTLPU_ALLOWED_HOSTS` to your Render hostname:

```text
SMARTLPU_ALLOWED_HOSTS=<your-service>.onrender.com
```

### Static files not loading (404 on CSS/JS)

Fix checklist:

- Ensure `whitenoise` is installed.
- Ensure `WhiteNoiseMiddleware` is enabled (already enabled in `settings.py`).
- Ensure `collectstatic` runs during build:

```bash
python manage.py collectstatic --noinput
```

If you update static assets, redeploy so Render rebuilds and re-runs `collectstatic`.

### WhiteNoise / static files

- Ensure `whitenoise` is installed (`pip install -r requirements.txt`).
- Ensure `collectstatic` runs in production.

---

## Notes

- Keep secrets (SMTP password, SECRET_KEY) out of git. Use environment variables.
