# Authentication & Authorization

## Overview

The system uses **JWT (JSON Web Tokens)** for stateless authentication and
**Role-Based Access Control (RBAC)** for authorization. All data is isolated per
firm using **PostgreSQL Row-Level Security (RLS)**.

---

## Authentication Flow

```
1. Engineer opens browser → lands on /login
2. Submits email + password
3. API validates credentials → creates JWT access token + refresh token
4. Access token: returned in JSON body (stored in memory by frontend)
5. Refresh token: set as httpOnly cookie (inaccessible to JavaScript → CSRF-safe)
6. Frontend sends access token as: Authorization: Bearer <token>
7. Access token expires in 15 minutes
8. Frontend auto-refreshes by calling POST /auth/refresh (using httpOnly cookie)
9. Logout: DELETE /auth/logout invalidates refresh token in Redis

Why two tokens:
- Short-lived access token minimizes exposure if intercepted
- httpOnly cookie for refresh token prevents XSS token theft
- Server-side invalidation via Redis allows true logout
```

---

## JWT Token Structure

### Access Token Payload
```json
{
  "sub": "usr_abc123",
  "firm_id": "firm_xyz789",
  "role": "senior_engineer",
  "exp": 1706123456,
  "iat": 1706122556,
  "type": "access"
}
```

### Refresh Token Payload
```json
{
  "sub": "usr_abc123",
  "firm_id": "firm_xyz789",
  "jti": "refresh_unique_id_12345",
  "exp": 1706727356,
  "iat": 1706122556,
  "type": "refresh"
}
```

`jti` (JWT ID) is stored in Redis. On logout, the `jti` is removed from Redis.
The refresh endpoint checks Redis before issuing a new access token.

---

## Role-Based Access Control (RBAC)

### Roles

```
firm_admin
  ├── Manage all users in firm (create, deactivate, change roles)
  ├── Manage firm settings (jurisdiction, CAD output, rule overrides)
  ├── All project operations (create, read, update, archive)
  └── View all design sessions and download all outputs

senior_engineer
  ├── Create projects, view all firm projects
  ├── Run designs, approve designs submitted by engineers
  ├── Assign engineers to projects
  └── Cannot manage users or firm settings

engineer
  ├── Create projects (auto-assigned as owner)
  ├── View own projects + projects assigned to them
  ├── Run full design pipeline on their projects
  └── Cannot view other engineers' unassigned projects

viewer
  ├── View projects they are explicitly assigned to (read-only)
  ├── Download output files for assigned projects
  └── Cannot create projects or run designs
```

### Permission Matrix

| Action | firm_admin | senior_engineer | engineer | viewer |
|--------|-----------|----------------|---------|--------|
| Create project | ✓ | ✓ | ✓ | ✗ |
| View any project | ✓ | ✓ | own+assigned | assigned |
| Upload plot DWG | ✓ | ✓ | own+assigned | ✗ |
| Run interview | ✓ | ✓ | own+assigned | ✗ |
| Submit design job | ✓ | ✓ | own+assigned | ✗ |
| Approve design | ✓ | ✓ | own | ✗ |
| Download outputs | ✓ | ✓ | own+assigned | assigned |
| Manage users | ✓ | ✗ | ✗ | ✗ |
| Edit firm settings | ✓ | ✗ | ✗ | ✗ |
| Override rules | ✓ | ✗ | ✗ | ✗ |

### FastAPI RBAC Implementation

```python
# src/civilengineer/auth/rbac.py

from enum import Enum
from functools import lru_cache


class Permission(str, Enum):
    # Project permissions
    PROJECT_CREATE    = "project:create"
    PROJECT_READ      = "project:read"
    PROJECT_UPDATE    = "project:update"
    PROJECT_DELETE    = "project:delete"
    # Design permissions
    DESIGN_SUBMIT     = "design:submit"
    DESIGN_APPROVE    = "design:approve"
    DESIGN_READ       = "design:read"
    DESIGN_DOWNLOAD   = "design:download"
    # Admin permissions
    USER_MANAGE       = "user:manage"
    FIRM_SETTINGS     = "firm:settings"
    RULES_OVERRIDE    = "rules:override"


ROLE_PERMISSIONS: dict[UserRole, set[Permission]] = {
    UserRole.FIRM_ADMIN: set(Permission),  # All permissions
    UserRole.SENIOR_ENGINEER: {
        Permission.PROJECT_CREATE, Permission.PROJECT_READ,
        Permission.PROJECT_UPDATE,
        Permission.DESIGN_SUBMIT, Permission.DESIGN_APPROVE,
        Permission.DESIGN_READ, Permission.DESIGN_DOWNLOAD,
    },
    UserRole.ENGINEER: {
        Permission.PROJECT_CREATE, Permission.PROJECT_READ,
        Permission.PROJECT_UPDATE,
        Permission.DESIGN_SUBMIT, Permission.DESIGN_APPROVE,
        Permission.DESIGN_READ, Permission.DESIGN_DOWNLOAD,
    },
    UserRole.VIEWER: {
        Permission.PROJECT_READ,
        Permission.DESIGN_READ, Permission.DESIGN_DOWNLOAD,
    },
}


# FastAPI dependency
def require_permission(permission: Permission):
    async def check(current_user: User = Depends(get_current_user)):
        if permission not in ROLE_PERMISSIONS[current_user.role]:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user
    return check
```

---

## Multi-Tenancy: PostgreSQL Row-Level Security

This is the **defense-in-depth** layer. Even if application code has a bug,
the database enforces firm isolation.

```sql
-- Enable RLS on all data tables
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE design_jobs ENABLE ROW LEVEL SECURITY;

-- Policy: can only see rows where firm_id matches the session variable
CREATE POLICY projects_firm_isolation
    ON projects
    USING (firm_id = current_setting('app.firm_id', true));

CREATE POLICY jobs_firm_isolation
    ON design_jobs
    USING (firm_id = current_setting('app.firm_id', true));
```

The API middleware sets this variable on every request:

```python
# src/civilengineer/api/middleware/firm_context.py

@app.middleware("http")
async def set_firm_context(request: Request, call_next):
    # Set PostgreSQL session variable from JWT claims
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    payload = verify_token(token)
    if payload:
        async with get_db_session() as session:
            await session.execute(
                text("SET LOCAL app.firm_id = :firm_id"),
                {"firm_id": payload.firm_id}
            )
    return await call_next(request)
```

---

## API Authentication Endpoints

```
POST /api/auth/login
    Body: {email, password}
    Returns: {access_token, token_type}
    Cookie: refresh_token (httpOnly, Secure, SameSite=Strict)

POST /api/auth/refresh
    Cookie: refresh_token (read automatically)
    Returns: {access_token, token_type} (new access token)

DELETE /api/auth/logout
    Header: Authorization: Bearer <token>
    Cookie: refresh_token
    Action: Invalidates refresh token in Redis, clears cookie
    Returns: 204 No Content

POST /api/auth/forgot-password
    Body: {email}
    Action: Sends password reset email (rate limited: 3/hour)

POST /api/auth/reset-password
    Body: {reset_token, new_password}
    Action: Validates reset token, updates password, invalidates all refresh tokens
```

---

## Password Requirements

- Minimum 8 characters
- At least one uppercase, one lowercase, one digit
- No common passwords (checked against list of top 10,000 passwords)
- bcrypt with cost factor 12

```python
# src/civilengineer/auth/password.py
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)
```

---

## Security Headers

Nginx and FastAPI enforce:

```
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Content-Security-Policy: default-src 'self'; ...
```

---

## Rate Limiting

Via Nginx + Redis:

```
Login endpoint:         5 requests/minute per IP
Password reset:         3 requests/hour per email
API (authenticated):    300 requests/minute per user
Design job submit:      10 jobs/hour per firm (soft limit)
File upload:            50 MB/minute per user
```

---

## Session Management

| Scenario | Behavior |
|----------|----------|
| Normal browser close | Refresh token persists (7 days), re-login not required |
| Explicit logout | Refresh token invalidated in Redis immediately |
| Password change | All refresh tokens for user invalidated |
| Account deactivated | All tokens rejected at next validation |
| Role changed | Takes effect on next token refresh (max 15 min delay) |
| Suspicious activity | firm_admin can invalidate all user tokens via admin panel |

---

## Optional: Google OAuth

For firms with Google Workspace:

```
GET /api/auth/google               → Redirect to Google OAuth consent
GET /api/auth/google/callback      → Handle OAuth callback, issue JWT
```

Only allowed for email domains pre-registered by firm_admin. Users created
via Google OAuth are auto-assigned `engineer` role until upgraded by admin.
