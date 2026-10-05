# GEOSIX

**A layered vertical-cadastre engine for 3D ULPIN generation and volumetric property governance.**

GEOSIX models property as a hierarchy — parcel, building, floor, unit — and layers
vertical, volumetric and governance concerns on top of it: bounding-box geometry per
unit, topological validation between neighbouring units, cadastral ownership with
effective-dated history, and a checksummed vertical code (VDC) that encodes a parcel's
identity together with its position in that hierarchy.

---

## Table of contents

- [What it does](#what-it-does)
- [Technology](#technology)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [API](#api)
- [Project structure](#project-structure)
- [Testing](#testing)
- [Continuous integration](#continuous-integration)
- [Deployment](#deployment)
- [Documentation](#documentation)
- [Design notes and known limitations](#design-notes-and-known-limitations)
- [License](#license)

---

## What it does

| Capability | Summary |
|---|---|
| **Cadastral hierarchy** | Parcels (ULPIN-keyed) own buildings, which own floors, which own units. Referential integrity and cascading deletes are enforced in PostgreSQL. |
| **Authentic cadastral geometry** | Per-unit axis-aligned bounding boxes stored in PostGIS with database-level `CHECK` constraints enforcing `min < max` on every axis, so an inverted box cannot be persisted. |
| **Topological validation** | Geometry, overlap, gap and elevation checks for a building or a single unit, with configurable tolerances. Runs against the real database. |
| **Volumetric visualisation** | Browser-based 3D viewer (React Three Fiber) for unit geometry, with orbit controls and colour-coded validation state. |
| **Ownership and governance** | Owners and effective-dated ownership interests over a parcel *or* a unit, with transfers and revocations that retain history rather than overwriting it. |
| **Vertical codes (VDC)** | A single ASCII string encoding parcel, property domain, vertical level, unit identifier and a checksum, with independent parser, validator, generator and checksum verifier. |
| **ULPIN interoperability** | Validates India's 14-character national parcel identifier and derives a local key from it, so vertical codes can sit beneath a nationally recognised parcel. |
| **GeoJSON import** | Bulk import of parcel boundaries and building footprints, with dry-run preview, per-feature outcomes, bounded request size, and per-feature savepoints so one bad feature cannot abort a batch. |
| **Authentication and RBAC** | JWT access/refresh tokens, bcrypt password hashing, persisted login throttling, password reset by email, and ordered `reader` / `editor` / `admin` permission tiers. |

---

## Technology

**Backend** — Python 3.11+, FastAPI, SQLAlchemy 2 (declarative, `Mapped[]`), Alembic,
Pydantic v2 / pydantic-settings, GeoAlchemy2, `python-jose` (JWT), Passlib + bcrypt,
Shapely. Data layer: PostgreSQL 16 with PostGIS 3.4.

**Frontend** — React 19, TypeScript, Vite, React Router 7, React Three Fiber + Three.js.
Tests with Vitest and Testing Library; lint with oxlint.

**Infrastructure** — Docker Compose for local development (PostGIS, backend, nginx
frontend), GitLab CI with eight jobs across four stages.

---

## Quick start

### Prerequisites

- Python 3.11+
- Node.js 18+ and npm
- Docker with the Compose plugin (only for the containerised path)
- PostgreSQL 16 + PostGIS 3.4, either via Compose or an existing instance

### Option A — full stack with Docker Compose

The fastest route. Defaults need no configuration; Compose ships with working
local-development values.

```bash
git clone https://code.swecha.org/saharsha1/3d-ulpin-vertical-property-mapping.git
cd 3d-ulpin-vertical-property-mapping
cp .env.example .env
docker compose up --build
```

- Frontend (nginx, with SPA routing and an `/api/` reverse proxy): <http://localhost:8080>
- API documentation (Swagger): <http://localhost:8000/docs>

Database migrations are an explicit step and are **not** applied automatically on
container start:

```bash
docker compose exec backend alembic upgrade head
```

### Option B — backend and frontend running locally

Start only the database, then run each application on the host:

```bash
docker compose up -d postgres
```

**Backend**

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

export DATABASE_URL="postgresql+psycopg://geosix:geosix_password@localhost:5432/geosix_dev"
alembic upgrade head
uvicorn app.main:app --reload
```

The API is then on <http://localhost:8000>, with Swagger at `/docs` and ReDoc at
`/redoc`.

**Frontend** (in a second terminal)

```bash
cd frontend
npm install
npm run dev
```

The frontend runs on <http://localhost:5173> and proxies API calls to the backend.

---

## Configuration

Copy `.env.example` to `.env` in the repository root for Compose, or to
`backend/.env` when running the backend directly. Every setting has a documented
default, so the stack starts unconfigured.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://geosix:geosix_password@localhost:5432/geosix_dev` | SQLAlchemy connection string |
| `DEBUG` | `true` | Set `false` in production |
| `JWT_SECRET_KEY` | development placeholder | Token signing key — **must** be replaced when `DEBUG=false` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access-token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh-token lifetime |
| `BCRYPT_ROUNDS` | `12` | Password hashing cost; keep at 12 in production |
| `LOGIN_MAX_ATTEMPTS` | `5` | Failed logins before lockout |
| `LOGIN_LOCKOUT_MINUTES` | `15` | Lockout duration |
| `CORS_ORIGINS` | `["http://localhost:8080"]` | Allowed browser origins |
| `SMTP_HOST` | *(empty)* | Empty disables password-reset delivery |

The application **fails closed** on production misconfiguration: with `DEBUG=false`
it refuses to start while `JWT_SECRET_KEY` still holds the documented development
value. Flipping `DEBUG` alone therefore cannot ship a development secret.

> **Password reset requires `SMTP_HOST`.** When it is unset the endpoint still
> returns its generic anti-enumeration response and logs that delivery is disabled,
> so recovery silently does not work. See [docs/authentication.md](docs/authentication.md).

---

## API

Base URL `/api/v1`. Full request/response reference: [docs/api.md](docs/api.md).

| Group | Endpoints | Notes |
|---|---|---|
| Health | `/api/v1/health`, `/api/health` | Liveness and database connectivity |
| Authentication | `/api/v1/auth/*` | `register`, `login`, `refresh`, `logout`, `me`, `forgot-password`, `reset-password`, `users`, `users/{id}/role` |
| Parcels | `/api/v1/parcels/*` | ULPIN-keyed cadastral parcels |
| Buildings, floors, units | `/api/v1/*` | The cadastral hierarchy |
| 3D geometry | `/api/v1/units/{unit_id}/geometry` | `GET` reads the bounding box, `PUT` replaces it; requires `reader` |
| 3D topology | `/api/v1/topology/validate/*` | `building/{id}`, `unit/{id}`, `overlaps`, `gaps` |
| GeoJSON import | `/api/v1/parcels/import`, `/api/v1/buildings/import` | Editor-protected, dry-run capable |
| Ownership | `/api/v1/ownership/*` | Owners and effective-dated interests |
| VDC | `/api/v1/vdc/generate`, `/validate`, `/parse` | Vertical code generation, parsing and validation; requires `editor` |

### Error format

Errors share one envelope, documented in [docs/api.md](docs/api.md):

```json
{ "error_code": "ERROR_CODE", "message": "Human-readable detail", "details": {} }
```

Response headers that carry protocol meaning — `Retry-After` on `429`,
`WWW-Authenticate` on `401` — are always preserved alongside it.

---

## Project structure

```
.
├── backend/
│   ├── alembic/versions/     # 10 revisions forming a single linear history
│   ├── app/
│   │   ├── api/v1/           # routers: auth, parcels, buildings, floors, units,
│   │   │                     #   geometry, topology, ownership, import, vdc, health
│   │   ├── core/             # settings, database, security, dependencies, audit
│   │   ├── models/           # SQLAlchemy models
│   │   ├── schemas/          # Pydantic request/response models
│   │   ├── services/         # business logic
│   │   └── validators/       # VDC, geometry, overlap, gap and elevation checks
│   ├── scripts/              # data audits and tooling
│   └── tests/                # unit and integration suites
├── frontend/
│   └── src/
│       ├── app/              # auth and theme contexts
│       ├── components/       # layout, feedback, ui, validation, visualization
│       ├── features/         # lazy-loaded management features per entity
│       ├── lib/              # api-error, theme, validation reporting
│       ├── pages/            # auth pages and application pages
│       ├── routes/           # public and authenticated layouts
│       ├── services/         # typed API clients
│       └── types/            # shared TypeScript types
├── docs/                     # specifications and guides (see below)
├── scripts/smoke-test.sh     # post-deployment health smoke test
├── 3d-visualization/         # reserved area for 3D rendering work
├── ai-geospatial/            # reserved area for AI/geospatial work
└── docker-compose.yml
```

Management pages are **lazy-loaded** so their services, validation and dialog
modules stay out of the initial bundle.

---

## Testing

| Suite | Command | Count |
|---|---|---|
| Backend | `cd backend && pytest` | **1544** |
| Frontend | `cd frontend && npm test` | **435** (48 files) |
| Backend coverage | `pytest --cov=app --cov-report=term-missing --cov-fail-under=80` | **94.31%** |

Current coverage stands at **94.31%**, against a CI floor of 80%.

### Integration tests

The suite under `backend/tests/integration/` runs against a **real** PostGIS
database and is skipped automatically when `TEST_DATABASE_URL` is unset, so a plain
`pytest` works without one. To include it:

```bash
docker compose up -d postgres

createdb geosix_test
export TEST_DATABASE_URL="postgresql+psycopg://USER:PASSWORD@localhost:5432/geosix_test"
DATABASE_URL="$TEST_DATABASE_URL" alembic upgrade head

cd backend && pytest                      # everything
cd backend && pytest -m integration       # integration only
```

Practical notes:

- Use a **dedicated throwaway database**. Tests deliberately exercise `DELETE`
  cascades and archive operations.
- Each test runs inside a transaction that is rolled back, so runs are
  order-independent and leave no rows.
- Service-layer code calls `session.commit()`. The `db_session` fixture binds the
  session with `join_transaction_mode="conditional_savepoint"`, so those commits
  release savepoints rather than persisting data. **Do not call `rollback()`** on
  that fixture from a test; it deassociates the outer transaction and a later write
  would really commit. The fixture fails loudly if you do.
- Bcrypt runs at `bcrypt_rounds = 12` in production; the test session lowers the live
  cost to 4 and restores it afterwards.

### Linting and builds

```bash
cd backend  && ruff check app tests && ruff format --check app tests
cd frontend && npm run lint && npx tsc --noEmit && npm run build
python3 -m compileall -q backend/app
```

---

## Continuous integration

GitLab CI runs eight jobs across four stages. A pipeline runs for merge requests and
for pushes to branches without an open MR; pushes to branches that already have one
are suppressed to avoid duplicate work.

| Stage | Jobs |
|---|---|
| `validate` | `ci:validate` — parses `.gitlab-ci.yml` and fails on undefined stages or jobs without a script |
| `lint` | `backend:lint` (ruff check + format), `frontend:lint` |
| `test` | `backend:test` (schema contract, then full suite with coverage gate), `frontend:test` |
| `build` | `backend:build`, `frontend:build`, `images:build` |

`backend:test` migrates a PostGIS service database before running, enforces the 80%
coverage floor, and round-trips the schema with `alembic downgrade heads` followed by
`alembic upgrade head`.

`images:build` builds both Dockerfiles and then *runs* the resulting images to prove
they work: the backend must refuse a development JWT secret in production mode and
accept a strong one, nginx must validate the shipped configuration, and neither image
may run as `root`. It builds without contacting a registry, and it requires a runner
in privileged mode so it can run Docker-in-Docker.

---

## Deployment

`docker-compose.yml` defines three services: `postgres` (PostGIS 16), `backend`
(multi-stage, non-root) and `frontend` (nginx with SPA routing and an `/api/` reverse
proxy). Both application images are multi-stage builds and run as a non-root user.

`scripts/smoke-test.sh` performs a post-deployment health check.

Container registry publishing is intentionally **not** configured, because the
repository has no registry or publishing contract. The full deployment checklist,
backup and restore procedure, and troubleshooting guidance are in
[docs/deployment.md](docs/deployment.md).

---

## Documentation

| Document | Contents |
|---|---|
| [architecture.md](docs/architecture.md) | Directory structure, key files, theme system, auth flow |
| [api.md](docs/api.md) | Every endpoint, error format, headers, how to add endpoints |
| [development.md](docs/development.md) | Contributor workflow, conventions, adding endpoints and pages |
| [authentication.md](docs/authentication.md) | JWT, RBAC tiers, throttling, password reset |
| [property-management.md](docs/property-management.md) | Parcel, building, floor and unit workflows |
| [geometry-validation.md](docs/geometry-validation.md) | Bounding-box constraints and validation |
| [overlap-detection.md](docs/overlap-detection.md) | Overlap algorithm and configuration |
| [gap-detection.md](docs/gap-detection.md) | Gap detection and tolerances |
| [topology-api.md](docs/topology-api.md) | Topology validation request/response reference |
| [topology-validation-dashboard.md](docs/topology-validation-dashboard.md) | Dashboard behaviour |
| [topology-test-dataset.md](docs/topology-test-dataset.md) | Deterministic validation dataset |
| [unit-bounding-box-storage.md](docs/unit-bounding-box-storage.md) | Storage model for unit geometry |
| [ownership-specification.md](docs/ownership-specification.md) | Ownership data and temporal semantics |
| [geojson-import.md](docs/geojson-import.md) | Import formats, limits, savepoint behaviour |
| [deployment.md](docs/deployment.md) | Deployment, backup/restore, troubleshooting |
| [vdc-specification.md](docs/vdc-specification.md) | Vertical DNA Code grammar and algorithms |
| [ulpin-interoperability.md](docs/ulpin-interoperability.md) | Relationship to India's national ULPIN, and its limits |

---

## Design notes and known limitations

**GEOSIX extends ULPIN; it does not issue it.** India's national parcel identifier
(ULPIN/Bhu-Aadhaar) is a 14-character code maintained by the Department of Land
Resources under DILRMP. GEOSIX validates that structure and derives a local parcel
key from it, so a vertical code can be anchored to a nationally recognised parcel.
GEOSIX is not part of that programme, assigns no ULPIN, and never verifies a ULPIN
against the national registry. The VDC itself is a project convention authored by
no standards body. See [docs/ulpin-interoperability.md](docs/ulpin-interoperability.md).

**Ownership writes are role-gated.** Registering an owner, editing a profile, granting
an interest, transferring and revoking all require the `editor` role or above; deleting
an owner requires `admin`, because deletion can destroy history a dispute depends on. A
valid login alone is never treated as write permission — a `reader` receives
`403 INSUFFICIENT_ROLE`.

**Ownership transfers are implemented; revocation is present but conservative.**
Consult [docs/ownership-specification.md](docs/ownership-specification.md) for the
exact temporal semantics, including what happens when a subject's interests overlap.

**Unit geometry and footprints live in different frames.** Unit AABBs are in a local
metric frame (metres); parcel and building footprints are SRID 4326 degrees. The two
are never mixed, and three CHECK constraints plus a
`DIMENSION_EXCEEDS_LOCAL_FRAME` validation issue keep degrees out of unit geometry —
a box in degrees satisfies `x_min < x_max` just as well as one in metres. A small
degree span still evades this bound; see
[docs/unit-bounding-box-storage.md](docs/unit-bounding-box-storage.md).

**Migrations are a single linear history.** Eleven revisions converge into one head
through two explicit no-op merge revisions (`0006_merge_ownership_geometry` and
`0007_merge_rbac_and_ownership`), each added when two independently developed
branches each introduced a numbered revision. They carry no schema change; they exist
so `alembic upgrade head` is always unambiguous. `test_database.py` asserts the graph
stays single-headed, which is what catches the next fork.

**Database migrations never run automatically on container start.** They are an
explicit deployment step, so a failed migration cannot silently half-apply during a
rollout.

**Password reset is inert without SMTP.** See the configuration note above.

---

## License

Proprietary — GEOSIX Project.