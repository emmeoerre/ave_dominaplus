ave_dominaplus — Unreleased

Highlights
- Fix startup warnings about the deprecated `via_device` parameter, which Home Assistant removes in 2027.8 ([#38](https://github.com/emmeoerre/ave_dominaplus/issues/38)).
- Use the current parent-device API for both registry calls and entity metadata, registering the hub before its endpoints.
- Preserve existing device IDs, hierarchy, and custom names. Older Home Assistant versions continue to use the API they support.

After updating, restart Home Assistant. No manual device migration is needed.
