# GEOSIX Ownership Specification

- **Document:** Ownership Specification
- **Specification version:** 1.0
- **Date:** 2026-09-30
- **Status:** Draft — project engineering convention
- **Purpose:** Define the GEOSIX ownership registration and effective-dated allocation data model.

## 1. Scope and terminology

This document describes project ownership/governance records for a parcel or unit. It is not a legal title, deed, land registry, proof-of-ownership, or government registration system. The project does not store deeds, signatures, valuation, tax, disputes, or legal determinations.

The existing VDC specification defines GEOSIX's project-level Vertical DNA Code and ULPIN representation. ULPIN identifies a parcel within that convention; VDC encodes parcel/domain/level/unit/checksum. Neither value is a government-issued identifier by virtue of this project specification. Ownership records refer directly to persisted parcel or unit UUIDs; they do not infer rights from ULPIN or VDC text.

An **owner** is an ownership-record party of kind `individual` or `organization`. An **ownership interest** is an owner's integer share of one subject for a half-open effective interval. `identifier` is an opaque, optional project identifier. It has no implied government, legal, or verification semantics. Contact metadata is optional application data, not an identity assertion.

## 2. Subject references

An interest belongs to exactly one subject: either a parcel or a unit. The database stores nullable `parcel_id` and `unit_id` UUID foreign keys, plus a check requiring exactly one to be non-null. The API represents that pair as `subject_type` (`parcel` or `unit`) and `subject_id`.

This design preserves PostgreSQL foreign-key integrity and makes parcel/unit joins and indexes direct. A polymorphic type-and-ID pair would not provide a normal FK to both existing tables and could leave dangling references. Separate interest tables would duplicate shared history and allocation rules. Asset FKs use restrictive deletion so existing ownership history is not silently cascaded away. Asset archival and hierarchy deletion must respect those references.

## 3. Owners and shares

Owner kinds are `individual` and `organization`. Ownership shares are integer basis points in the range 1 through 10000, where 10000 basis points represent 100%. For any one subject and instant, total active allocation cannot exceed 10000. The model permits an unallocated remainder; it does not imply that the recorded interests are exhaustive legal claims.

## 4. Effective dating and history

Intervals are half-open: `[valid_from, valid_to)`. `valid_from` is required and timezone-aware. `valid_to = NULL` means no known end; otherwise the row is active from `valid_from` up to, but not including, `valid_to`. The database requires `valid_from < valid_to` when `valid_to` exists.

Current queries evaluate at the current UTC instant by default. Historical queries include closed rows, and an `effective_at` query includes intervals active at that instant. Closed rows are immutable through normal APIs and are retained for history; corrections require an explicitly designed append-only correction process outside this work item.

## 5. Grant semantics

A grant appends an ownership interest from its effective timestamp. The owner may not already have an overlapping interval for the same subject. The resulting complete set of intervals must satisfy the 10000-basis-point ceiling at every instant. A grant may leave part of the subject unallocated.

## 6. Complete transfer semantics

A transfer replaces the complete allocation active for one subject at its effective timestamp. The request supplies the full resulting allocation, not merely a delta. The service closes every interest active at that instant at `valid_to = effective_at`, marks those rows `transferred`, and creates the complete replacement interests beginning at that same instant. The sum of replacement basis points must equal the previous allocation total; each owner may appear once. This permits a partial transfer by listing the transferor's remaining share in the replacement allocation.

All closes and inserts occur in one database transaction. If validation or persistence fails, none of the old rows are closed and no new rows are retained. The operation serializes on the stable subject row before reading current allocation.

## 7. Revocation semantics

Revocation closes the selected open interval at a timezone-aware effective timestamp and changes its disposition to `revoked`. It does not delete the row. Revocation must occur after `valid_from`; repeating revocation against a closed row is rejected. This records a project data disposition and does not make a legal claim about the reason or effect of revocation.

## 8. Integrity and concurrency

Database checks enforce valid kind/status values, exactly one subject, `1 <= share_basis_points <= 10000`, and valid interval ordering. Foreign keys enforce real owner, parcel, and unit references. The aggregate share rule and same-owner interval non-overlap are validated by the service because a row-level check cannot inspect sibling rows.

Every mutation first locks the subject's parcel or unit row with PostgreSQL `SELECT ... FOR UPDATE`, then loads current interests, validates the proposed resulting intervals, performs changes, and commits once. All mutation paths must use this lock protocol so competing requests cannot both validate against stale allocations. The same-owner overlap validation is mandatory even if a database exclusion constraint is added later.

## 9. Deletion and access boundaries

An owner with any ownership history cannot be deleted. Ownership foreign keys restrict deletion of referenced owners and assets. Parcel/unit records should be archived or otherwise lifecycle-managed rather than cascading their ownership history away.

Authorization uses the platform's existing ordered role tiers. Reads require an authenticated `reader`. Writes that mutate cadastral data -- registering an owner, editing a profile, granting an interest, transferring, and revoking -- require the `editor` role or above. Deleting an owner requires `admin`, because deletion can destroy history that a dispute depends on. Authentication alone is never treated as write authorization: a `reader` receives `403 INSUFFICIENT_ROLE`.
