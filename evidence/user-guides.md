# User guides

## Basic user

1. Register and sign in. Registration creates only a BASIC_USER.
2. Browse listed equipment and review serviceable and available quantities.
3. Open New request. Enter a purpose, due date, and one to three distinct items.
4. Submit. The request remains pending; submission does not reserve a unit.
5. Browse and track your own history. Cancel only a pending or approved request before issue.
6. Edit name and contact details in Profile.

## Administrator

1. Create the initial administrator with the create_admin management command.
2. Use the dashboard for live counts and charts.
3. Filter requests with the status dropdown, then open Review to see the request and available-unit counts in a popup card. Approve only when every requested item has enough available physical units; approval reserves those asset codes. Reject with a reason.
4. Confirm release on the approved request.
5. Use Returns to record each unit and its condition. Damage opens maintenance.
6. Open and close maintenance records. Issued or reserved units cannot enter maintenance.
7. Register categories and catalog items, then register each physical unit in Inventory. You can register up to 100 at once; the system gives each one a unique numbered asset code and marks it available. Archive catalog data rather than deleting referenced records.
8. Deactivate accounts, inspect audit history, export loan reports, and change operating limits.

## Setup and maintenance

Create a virtual environment, install requirements, apply migrations, create an admin, optionally run `python manage.py seed_demo` for fictional sample data, and start the development server. The seed command prompts for passwords and is safe to rerun without duplicating the sample dataset. Back up the database before changes. Apply migrations after model changes. Keep secrets out of source control. Use PostgreSQL for real concurrent approvals.

