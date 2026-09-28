# Design diagrams

These Mermaid source diagrams describe the current implementation at a useful
review level. Render them in a Mermaid-capable viewer before including them in
the final PDF/Word report. They are source diagrams, not rendered UML artifacts.
The activity, sequence and ER views focus on the implemented paths; the use-case
view uses a flowchart representation rather than strict UML actor notation.

## Deployment and system architecture

```mermaid
flowchart LR
  B[Browser: Tailwind templates] --> D[Django on Windows via uv]
  D --> P[(PostgreSQL container)]
  D --> E[(Saved Parquet and JSON evidence)]
  subgraph Docker infrastructure
    P
    R[Redis: provisioned]
    M[Spark master] --> W[Spark worker]
  end
  G[Seeded generator on Windows] --> C[(Raw CSV and JSON)]
  C --> M
  W --> E
  C2[Step 5 accepted Parquet] --> PY[Independent Python pipeline]
  E --> C2
  PY --> E
```

Redis has no depicted job-queue edge because an application queue integration
has not been verified. The Spark services and host share mounted evidence paths.

## Logical data-flow diagram

```mermaid
flowchart TD
  Raw[Raw restaurant tables] --> Q[1. Spark schema and quality checks]
  Q --> Clean[(Accepted Parquet)]
  Q --> Rejected[(Quarantine with reasons)]
  Q --> QR[(Quality report)]
  Clean --> Import[2. Verified Django import]
  Import --> DB[(PostgreSQL domain tables)]
  Clean --> S[3. Spark SQL and historical features]
  S --> SM[4a. Spark model training and held-out predictions]
  Clean --> PM[4b. Independent Python features and models]
  SM --> Compare[5. Keyed prediction comparison]
  PM --> Compare
  S --> Analysis[6. Restaurant analytics]
  PM --> Analysis
  Analysis --> Review[7. Evidence-based review candidates]
  Compare --> Evidence[(Validated saved outputs)]
  Review --> Evidence
  U[Authenticated user] --> Scope[8. Role and location checks]
  DB --> Scope
  Evidence --> Scope
  Scope --> UI[9. Dashboard, simulation, report or export]
  UI --> U
```

## Entity relationships

```mermaid
erDiagram
  USER ||--o{ LOCATION_ACCESS : receives
  RESTAURANT ||--o{ LOCATION_ACCESS : scopes
  MENU_CATEGORY ||--o{ MENU_ITEM : contains
  RESTAURANT ||--o{ PRICING_HISTORY : records
  MENU_ITEM ||--o{ PRICING_HISTORY : priced_by
  RESTAURANT ||--o{ ORDER : receives
  CUSTOMER o|--o{ ORDER : places
  ORDERING_CHANNEL ||--o{ ORDER : classifies
  PROMOTION o|--o{ ORDER : tags
  ORDER ||--o{ ORDER_ITEM : contains
  MENU_ITEM ||--o{ ORDER_ITEM : purchased_as
  PROMOTION o|--o{ ORDER_ITEM : discounts
  ORDER_ITEM ||--o| RATING : receives
  PROMOTION ||--o{ PROMOTION_ITEM : includes
  MENU_ITEM ||--o{ PROMOTION_ITEM : eligible_for
  RESTAURANT ||--o{ INVENTORY : holds
  MENU_ITEM ||--o{ INVENTORY : measured_in
  RESTAURANT ||--o{ WASTAGE : records
  MENU_ITEM ||--o{ WASTAGE : measured_in
```

The diagram omits framework session/admin tables and field-level attributes.
Refer to the [data dictionary](../data_dictionary.md) and migrations for complete
constraints. An accepted order may have no accepted lines; this is tracked as
coverage rather than silently creating a line.

## Use-case view

```mermaid
flowchart LR
  Admin[Administrator] --> Login[Sign in]
  Analyst[Analyst] --> Login
  Regional[Regional manager] --> Login
  Manager[Restaurant manager] --> Login
  Login --> Auth[Authenticate and resolve scope]
  Auth --> Dash[Review scoped dashboards]
  Auth --> Sim[Run bounded what-if estimate]
  Auth --> Export[Download scoped reports and CSV]
  Auth --> Recs[Inspect recommendation evidence]
  Admin --> Accounts[Create accounts and assign roles]
  Admin --> Domain[Maintain domain records and grants]
  Operator[Technical operator] --> Jobs[Run generator, Spark and Python CLI jobs]
  Jobs --> Validate[Review reports, failures and model evidence]
```

The technical operator is a deployment responsibility, not an extra business
role. Administrators and analysts have network visibility; restaurant/regional
managers require explicit location grants. Superuser flags are a separate Django
privilege and cannot be granted through the normal account form.

## Processing activity

```mermaid
flowchart TD
  Start([Start with new output paths]) --> Schema[Validate schemas and source files]
  Schema --> Quality[Apply quality rules]
  Quality --> Split[Write accepted and quarantined records]
  Split --> Check{Counts and read-back checks pass?}
  Check -- No --> Fail[Record failure; investigate preserved output]
  Check -- Yes --> Features[Build cutoff-safe features]
  Features --> Train[Fit candidate models on training data]
  Train --> Select[Select using validation only]
  Select --> Test[Evaluate untouched held-out targets]
  Test --> Compare[Compare independent predictions by key]
  Compare --> Integrity{Lineage and consistency pass?}
  Integrity -- No --> Fail
  Integrity -- Yes --> Publish[Save review-only evidence]
  Publish --> Read[Display scoped summaries and limitations]
  Read --> End([Human review])
```

## Scoped report download sequence

```mermaid
sequenceDiagram
  actor User
  participant Browser
  participant Django
  participant Scope as Role/location service
  participant DB as PostgreSQL
  participant Evidence as Saved analytical evidence
  User->>Browser: Choose report
  Browser->>Django: Authenticated report request
  Django->>Scope: Resolve permitted restaurants
  Scope->>DB: Read account scope and location grants
  DB-->>Scope: Permitted locations
  Scope-->>Django: Scope
  alt No accessible locations
    Django-->>Browser: Access denied
  else Accessible scope
    Django->>Evidence: Validate report sources and read scoped rows
    alt Invalid or unavailable evidence
      Evidence-->>Django: Validation failure
      Django-->>Browser: Understandable unavailable response
    else Verified evidence
      Evidence-->>Django: Values and limitations
      Django-->>Browser: HTML attachment with private cache policy
    end
  end
```

The sequence deliberately has no retraining step in the HTTP request and no
unimplemented audit-event write. Add those only when their implementation is verified.
