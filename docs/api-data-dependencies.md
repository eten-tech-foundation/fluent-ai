# API Data Dependencies (to be served via HTTP, not cross-schema reads)

As of the DB-ownership separation, `fluent-ai` no longer has any read access to
API-owned (`public`) tables. The following code read API tables directly and was
removed. Each item must be re-implemented as an HTTP call to fluent-api
(authenticated via the service principal) when the feature that needs it is
built. The AI→API base URL is future config — note `FLUENT_AI_URL` is the
reverse (API→AI) direction, not this one.

| Data needed | Old direct-read site (removed) | Replacement |
|---|---|---|
| `public.projects` list | `src/app/crud/projects.py::get_projects` via a read-only `internal/project.py` ORM model | `GET /projects` on fluent-api |
| Single project | (scaffolded in `routers/projects.py`) | `GET /projects/{id}` on fluent-api |

Removed supporting code: `src/app/internal/project.py`, `src/app/crud/projects.py`,
`src/app/routers/projects.py`, `src/app/schemas/projects.py` (DTOs — keep a copy
if reused as the HTTP response model), and the former read-only base ORM class in
`src/app/db/base.py` that those external models inherited from.

No other `public`/operational table was read by this service at separation time.
