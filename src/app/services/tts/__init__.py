"""
services/tts — Source-text speech synthesis and its artifact store.

Module map (source-tts proposal §7–§10):

  provider.py         provider-neutral synthesis seam (§8.1)
  gemini_provider.py  the Gemini implementation of that seam (§8.2)
  recipe.py           canonical recipe + HMAC artifact identity (§9.1)
  artifacts.py        R2 object store: sidecars, audio, receipts (§9.3)
  service.py          the request-facing service used by the endpoints (§7.1)

The pieces are deliberately separate: hashing, buffering and transcoding live
outside the provider so a future provider (a custom low-resource model, say)
is one new module and a config change, with no fluent-web or fluent-api edit.
"""
