# api/ — HTTP boundary layer.
#
# Organized by API version (v1/, v2/, ...) to allow the contract to evolve
# without breaking existing callers.
#
# Each version directory contains:
#   router.py      — aggregates all endpoint routers for that version
#   endpoints/     — one module per domain (projects.py, api_keys.py, ...)
#
# main.py imports only api/v1/router.py, staying ignorant of individual
# endpoint files.
#
# Current state: active endpoints live in app/routers/ (legacy location).
# Migrate them here one domain at a time as each is refactored.
