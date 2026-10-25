# System diagrams

## MTV application architecture

```mermaid
flowchart LR
  Student[Basic user] --> URL[Named URL patterns]
  Admin[Administrator] --> URL
  URL --> Guard[Role and active-account guard]
  Guard --> View[Custom Django view]
  View --> Forms[Server-side form validation]
  View --> Service[Atomic workflow service]
  Forms --> ORM[Django ORM models]
  Service --> ORM
  ORM --> DB[(SQLite demo or PostgreSQL)]
  Service --> Audit[Audit log]
  View --> Templates[Role-aware inherited templates]
  Templates --> Student
  Templates --> Admin
```

## Core entity relationships

```mermaid
erDiagram
  USER ||--o{ BORROW_REQUEST : owns
  USER ||--o{ LOAN : releases
  CATEGORY ||--o{ CATALOG_ITEM : groups
  CATALOG_ITEM ||--o{ EQUIPMENT_UNIT : identifies
  BORROW_REQUEST ||--|{ REQUEST_ITEM : contains
  CATALOG_ITEM ||--o{ REQUEST_ITEM : requested
  REQUEST_ITEM ||--o{ UNIT_ALLOCATION : allocates
  EQUIPMENT_UNIT ||--o{ UNIT_ALLOCATION : assigned
  BORROW_REQUEST ||--o| LOAN : becomes
  UNIT_ALLOCATION ||--o| RETURN_RECORD : returned
  EQUIPMENT_UNIT ||--o{ MAINTENANCE_RECORD : serviced
  USER ||--o{ AUDIT_LOG : acts
```

## Request and equipment lifecycle

```mermaid
stateDiagram-v2
  [*] --> Pending
  Pending --> Approved: all units reserved atomically
  Pending --> Rejected
  Pending --> Cancelled
  Approved --> Issued: release recorded
  Approved --> Cancelled: reserved units freed
  Issued --> PartiallyReturned: one or more units returned
  Issued --> Returned: all units returned
  PartiallyReturned --> Returned: final outstanding unit returned
  state Issued {
    [*] --> WithinDueDate
    WithinDueDate --> Overdue: due date passed and units outstanding
  }
```

Overdue is a computed label and does not replace the request workflow status.

