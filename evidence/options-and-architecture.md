# System evidence

## Roles and requirements

The application has exactly BASIC_USER and ADMIN roles. Basic users register, browse active equipment, create requests with up to three distinct items, edit personal contact fields, view their own history, and cancel before issue. Admins review and allocate requests, release and return units, manage maintenance, accounts, inventory, reports, audit history, and operating limits.

## MTV design

Browser submits to named URL patterns. Role-protected views call validation forms and transaction services. Services use Django ORM models, atomic transactions, and audit entries. Views render inherited server-side templates. SQLite supports a local demo; PostgreSQL is recommended for parallel approvals because SQLite ignores row-level select-for-update locks.

## Workflow

Pending can become approved, rejected, or cancelled. Approved can become issued or cancelled. Issued can become partially returned, then returned. Overdue is a computed label only when units remain after the due date.

## Options comparison

| Option | Benefits | Costs |
|---|---|---|
| Django server rendered application | Built-in authentication, ORM, forms, migrations, and simple deployment; fits the course and a small campus process | Requires explicit role checks and careful workflow services; SQLite concurrency is limited |
| JavaScript single-page app plus REST API | Rich client interaction and reusable API for other clients | More components, duplicated validation, API authentication choices, and larger maintenance/test burden |

Django is recommended for this scope. Revisit a separate client/API if multiple clients, offline use, or real integration requirements emerge.

## Database relationship outline

User owns requests. Requests contain unique catalog item lines. Lines allocate physical units. A unit can have one active allocation. Each request has at most one loan. Allocations have at most one return record. Units have maintenance history. Audit events reference actor and record.

## Architecture diagram

Browser -> URL -> Role-protected view -> Form validation -> Transaction service -> ORM models -> Database
Transaction service -> Audit log
View -> Server-rendered templates -> Browser

## Privacy and professional judgment

Use fictional identities only. A borrower can query only their own history. Passwords use Django authentication hashing; templates escape user values; state changes use POST and CSRF. Keep secrets outside version control, limit collected contact data, protect backups, and define retention with the institution. Republic Act No. 10173 (Data Privacy Act of 2012) and its implementing rules are relevant frameworks for personal information processed in the Philippines; the institution must determine lawful basis, notice, retention, and security obligations for an actual deployment. See the National Privacy Commission's [Act and IRR page](https://privacy.gov.ph/the-data-privacy-act-and-its-irr/) and [official Act text](https://privacy.gov.ph/data-privacy-act-/). The pages implement some privacy safeguards, but this coursework prototype has not undergone a legal or institutional compliance audit.

Use accessible labels and text status, keyboard navigation, responsive tables, and avoid color-only signals. WCAG 2.2 is a current W3C Recommendation and a useful design/testing reference; the application has not been audited for conformance. See the [WCAG 2.2 standard](https://www.w3.org/TR/WCAG22/). Review availability accommodations and do not prioritize users based on protected characteristics. Declare reused code, third-party assets, and AI assistance under instructor rules.

## Emerging technology evaluation

A QR code could speed asset identification at the return counter. Browser camera support is compatible, but needs accessible labels and durable tags. QR scans must reveal no borrower identity and must require admin authentication for actions. Test usability and scan error rates first; keep manual asset-code entry. Recommendation: defer adoption until observation shows a measurable return-desk problem.

## Testing and known limitations

Automated tests cover allocation exclusivity, cancellation release, issue and return, and damage. Run acceptance sessions with representative users and record anonymized outcomes, fixes, and retests. The group must create authentic team records, peer evaluations, usability evidence, source-control history, instructor-specific compliance analysis, and tested PostgreSQL concurrency evidence. Do not represent templates in this folder as completed team work.

