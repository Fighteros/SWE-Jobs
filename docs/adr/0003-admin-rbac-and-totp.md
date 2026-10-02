# ADR 0003: Admin RBAC and TOTP

Date: 2026-10-02
Status: Accepted

## Context

Admins need varied privileges (read-only, manage, destructive). We need a model
that is auditable, enforces least privilege, and protects high-risk operations
without blocking safe read access.

## Decision

1. Authorization uses reusable roles mapped to named permissions via
   `security.admin_role_permissions`. Multiple roles produce the union of their
   permissions.
2. No per-account permission overrides initially.
3. The seeded super-admin is an `admin_accounts` row assigned the `super_admin`
   role — not a separate account type or table.
4. Account states: `invited → pending_totp → active → suspended | disabled`.
5. TOTP is mandatory for all admin accounts. Sensitive role/security operations
   require recent TOTP.
6. Invariants (enforced transactionally):
   - The final active super-admin cannot be disabled or demoted.
   - An admin cannot grant privileges beyond their own authority.
   - Role changes increment `authz_version`.
   - Role changes revoke relevant refresh-token families.
   - Every role/account/security change creates an audit event.
7. High-risk controls are withheld until job/queue correctness is fixed.

## Consequences

- A stable permission-key vocabulary is defined (e.g. `jobs.read`, `jobs.manage`,
  `system.destructive`).
- Audit events are mandatory for all security-relevant mutations.
- The frontend gates UI by permissions, but the backend is the authority.
