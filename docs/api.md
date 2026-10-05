# GEOSIX API

## Base URL

```
http://localhost:8000
```

## Documentation

- **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **OpenAPI JSON:** [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

## API Prefix

All endpoints are under `/api/v1`.

## Endpoints

### Health

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/v1/health` | No | Service health check |
| GET | `/api/v1` | No | API version metadata |

### Authentication

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/v1/auth/register` | No | Create account |
| POST | `/api/v1/auth/login` | No | Get tokens |
| POST | `/api/v1/auth/refresh` | No | Refresh tokens |
| POST | `/api/v1/auth/logout` | Yes | Logout |
| GET | `/api/v1/auth/me` | Yes | Current user |
| POST | `/api/v1/auth/forgot-password` | No | Request a reset email (JSON `{ "email": "..." }`) |
| POST | `/api/v1/auth/reset-password` | No | Complete reset with a single-use token |
| GET | `/api/v1/auth/users` | Admin | List users |
| PATCH | `/api/v1/auth/users/{user_id}/role` | Admin | Assign a user role |

### 3D Geometry

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/v1/units/{unit_id}/geometry` | No | Read a unit's persisted 3D bounding box and derived volume, centroid, and dimensions |
| PUT | `/api/v1/units/{unit_id}/geometry` | No | Create or replace a unit's 3D bounding-box geometry |

### 3D Topology Validation

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/v1/topology/validate/building/{building_id}` | Editor | Run geometry, overlap, gap, and elevation checks for a building |
| POST | `/api/v1/topology/validate/unit/{unit_id}` | Editor | Validate one unit's 3D geometry |
| POST | `/api/v1/topology/validate/overlaps` | Editor | Check overlaps for supplied unit IDs |
| POST | `/api/v1/topology/validate/gaps` | Editor | Check gaps for supplied unit IDs and tolerance range |

See [3D Topology Validation API](topology-api.md) for request and response details.

### GeoJSON Import

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/v1/parcels/import?dry_run=true` | Editor | Preview or upsert parcel features by ULPIN |
| POST | `/api/v1/buildings/import?dry_run=true` | Editor | Preview or upsert building footprints under parcels |

Both endpoints accept a GeoJSON `FeatureCollection`, process up to 500 features per
request, and reject request bodies larger than 10 MiB. `dry_run` defaults to `true`;
set it to `false` to persist valid features. Outcomes and validation reasons are
returned individually. Parcel imports accept Polygon or MultiPolygon geometries;
building imports accept Polygon geometries only. Building features may specify
`parcel_id` in properties or use the request-level `parcel_id` query parameter.

See [GeoJSON Import](geojson-import.md) for property requirements, examples,
savepoint behavior, and report semantics.

### Ownership

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/v1/ownership/owners` | `editor` role | Register an owner |
| GET | `/api/v1/ownership/owners` | Yes | Search and paginate owners |
| GET | `/api/v1/ownership/owners/{owner_id}` | Yes | Retrieve an owner profile |
| PATCH | `/api/v1/ownership/owners/{owner_id}` | `editor` role | Update an owner profile |
| DELETE | `/api/v1/ownership/owners/{owner_id}` | `editor` role | Delete an owner only when no ownership history exists |
| POST | `/api/v1/ownership/interests` | `editor` role | Grant a parcel or unit interest |
| POST | `/api/v1/ownership/transfers` | `editor` role | Atomically replace a subject's complete allocation |
| POST | `/api/v1/ownership/interests/{interest_id}/revocations` | `editor` role | Close an interest while retaining history |
| GET | `/api/v1/ownership/parcels/{parcel_id}/interests` | Yes | List parcel interests |
| GET | `/api/v1/ownership/units/{unit_id}/interests` | Yes | List unit interests |
| GET | `/api/v1/ownership/owners/{owner_id}/interests` | Yes | List an owner's interests |

Ownership writes require the `editor` role or above; deleting an owner requires `admin`, because it can destroy history a dispute depends on. A valid login alone is never treated as write permission -- a `reader` receives `403 INSUFFICIENT_ROLE`. See [Ownership Specification](ownership-specification.md) for the data and temporal semantics.

## Error Format

```json
{
  "error_code": "ERROR_CODE",
  "message": "Human-readable message",
  "details": {}
}
```

Feature 12 uses this envelope for validation, not-found, conflict, and server errors. The current authentication 401/403 paths intentionally retain their legacy `{"detail": ...}` response.

## Headers

| Header | Description |
|--------|-------------|
| `X-Request-ID` | Unique request identifier |
| `X-Response-Time` | Server response time |
| `Authorization` | `Bearer <token>` for authenticated requests |

## Adding New Endpoints

1. Create router file in `backend/app/api/v1/`
2. Define endpoints with Pydantic schemas
3. Register router in `backend/app/main.py`
4. Add OpenAPI tags for organization
