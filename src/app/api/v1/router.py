from fastapi import APIRouter

from app.api.v1.endpoints import api_keys, greek_room, suggestions, translations, tts

router = APIRouter()
router.include_router(api_keys.router, prefix="/api-keys", tags=["api-keys"])
router.include_router(
    greek_room.router,
    prefix="/tools/greek-room",
    tags=["tools:greek-room"],
)
router.include_router(suggestions.router, prefix="/suggestions", tags=["suggestions"])
router.include_router(
    translations.router, prefix="/translations", tags=["translations"]
)
# `/tts` is mirrored by fluent-api as `/ai/tts` (source-tts proposal §7.1). The
# two tails must stay siblings under one prefix on both services, because
# `generate` answers with a sibling-relative `audio_url` that the caller
# resolves against the URL it actually called.
router.include_router(tts.router, prefix="/tts", tags=["tts"])
