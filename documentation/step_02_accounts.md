# Step 2: Database and account foundation

## Plan and scope

The original roadmap separated database setup and authentication. The Step 1
handoff combined them into Step 2; this document records that adjustment.
Use an AbstractUser model in the first migration, PostgreSQL for development,
Django sessions for authentication, and Tailwind CDN for the web interface.
Usernames identify login accounts; customers in the future restaurant dataset
are separate entities and will not automatically become application users.

## Access policy

| Action | Administrator | Restaurant Manager | Regional Manager | Analyst |
| --- | --- | --- | --- | --- |
| Sign in and view home | Yes | Yes | Yes | Yes |
| List and create accounts | Yes | No | No | No |
| Assign business roles to new accounts | Yes | No | No | No |
| Assign Django staff/superuser flags | Superuser only | No | No | No |

Registration is administrator-managed. A business administrator may create
another administrator but cannot grant Django staff or superuser flags through
the account form. Account modification, deactivation, and password resets are
available to superusers through Django admin. No public signup or email reset
delivery is configured. Restaurant and region data scoping belongs to the domain
model step, before any restaurant analytics is exposed.

## Implementation

- `apps.accounts.User` extends Django AbstractUser with a constrained role.
- The role is the source of truth for business access; no duplicate role groups.
- Built-in login handles password hashing, inactive accounts, and safe redirects.
- Logout and account creation require POST and CSRF verification.
- Server-side account administration checks apply to GET and POST requests.
- Account creation uses Django password validators and an explicit field list.
- User administration in Django admin is restricted to superusers.
- The root ignored `.env` activates PostgreSQL and stores a random Django key.

## Verify

```powershell
uv run python dine_iq/manage.py check
uv run python dine_iq/manage.py makemigrations --check --dry-run
uv run python dine_iq/manage.py test apps.accounts
```

Tests use a separate PostgreSQL test database, not the application database.
Browser styling depends on the Tailwind CDN being reachable. This development
foundation does not yet include login rate limiting or production deployment.
