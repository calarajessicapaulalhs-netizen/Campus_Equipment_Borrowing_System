# IT 401W Project A: Campus Equipment Borrowing and Inventory System

A Django application with exactly two application roles: BASIC_USER and ADMIN. The custom management side uses the group's own Django views, forms, templates, URL routes, and ORM operations. No Django admin URLs or admin interface generator are used.

## Requirements

- Python 3.10 or newer
- Django 6.1.2, pinned in requirements.txt
- SQLite for a single-user classroom demonstration

SQLite does not implement row-level SELECT FOR UPDATE locking. Workflow services use atomic transactions, row locks, and a conditional unique allocation constraint. Use PostgreSQL and run parallel approval testing before multi-admin deployment.

## Set up

1. Create and activate a virtual environment.
2. Install dependencies with: python -m pip install -r requirements.txt
3. Apply migrations with: python manage.py migrate
4. Create the first administrator interactively with: python manage.py create_admin
5. Optionally create the fictional demonstration dataset with: python manage.py seed_demo
6. Start the server with: python manage.py runserver
7. Visit http://127.0.0.1:8000/

The seed command uses the existing active admin as the recorded administrator and asks for one shared password for the fictional accounts `demo_borrower01` through `demo_borrower08`. It creates 3 categories, 6 catalog items, 18 units, 20 requests, 13 loans, 4 maintenance records, rejected and cancelled requests, two overdue loans, and a partial damaged return. It is repeatable: if the demo requests already exist, it leaves the dataset unchanged. No passwords or real student identities are stored in the source.

## Configuration

Set DJANGO_SECRET_KEY to a long random secret and DJANGO_DEBUG=0 outside local development. Set DJANGO_ALLOWED_HOSTS to a comma-separated list. Do not commit secrets. The development default is for local classroom use only. Times use Asia/Manila.

## Workflows

- Registration creates only BASIC_USER. Profile editing omits role and account activation fields.
- Basic users browse equipment, submit up to three different item lines, see only their own request history, and cancel pending or approved requests before issue.
- Admins review requests and atomically reserve units, issue approved requests, record individual unit returns, manage maintenance, activate/deactivate accounts, edit and archive the catalog, retire units, inspect audit entries, configure limits, and export loan reports.
- State changes use POST and CSRF. Protected actions check role and active account status. Overdue is calculated from the due date and outstanding allocations.
- Defaults are seven calendar days and three units per requested catalog item.

## Verification

Run python manage.py check and python manage.py test. The tests cover unit reservation and release on cancellation, last-unit conflict handling, issue/return, and damaged returns.

## Evidence

The evidence folder includes MTV, data model, and workflow diagrams; system design and options comparison; user guides; technology evaluation; privacy and professional judgment notes; and team/demo templates. Replace all placeholders and perform actual usability/acceptance testing, contribution records, and PostgreSQL concurrency demonstration before submission.

## Limitations

This is a course-project implementation, not a fully hardened production service. Confirm institutional retention and privacy requirements with the instructor or data protection officer. SQLite is unsuitable for proving concurrent row-lock behavior. The group must capture authentic user feedback and explain the limits and decisions during the presentation.



python manage.py create_admin
