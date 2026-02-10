# CMS (Campus Management System)

CMS is a Django-based Campus Management System prototype, focused on a **Smart Attendance Management System**.

## Features
- Manage Data dashboard (Students, Courses, Enrollments, Face Data)
- Face Data upload:
  - Requires **5–10 photos per student**
  - Preview + delete per item
  - **Delete All Face Data** (with confirmation)
- Attendance marking:
  - Manual attendance + one-click “Mark All Present”
  - Photo-based face recognition marking
  - Live webcam attendance (continuous marking)
- Face recognition hardening / accuracy:
  - Trains only on enrolled students for a session’s course
  - Filters unusable images (no detectable face)
  - Strict gates to reduce false positives:
    - ambiguity guard (refuses to mark if top matches are too close)
    - strict threshold for photo mode

## Tech Stack
- Python + Django
- OpenCV (LBPHFaceRecognizer + Haar cascades)
- Bootstrap UI

## Setup (local)
1. Create & activate a virtual environment
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run migrations:
   ```bash
   python manage.py migrate
   ```
4. Start server:
   ```bash
   python manage.py runserver
   ```

## Notes for best face recognition accuracy
- Upload **6–10 clear photos per student** (good lighting, multiple angles)
- Ensure face data is not mixed between students
- If recognition is ambiguous, the system will refuse to mark to avoid mislabeling
