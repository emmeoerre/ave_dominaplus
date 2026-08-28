ave_dominaplus — v1.6.0

Highlights
- Cleaner, translated device and entity names while preserving existing IDs and user customizations.
- Thermostats now process all updates and remain off when season changes; the current season is exposed as an attribute ([#34](https://github.com/emmeoerre/ave_dominaplus/issues/34)).
- More reliable startup and connections through Home Assistant-managed background tasks and HTTP sessions.
- IPv6-only Zeroconf discoveries are ignored instead of creating unusable configurations ([#29](https://github.com/emmeoerre/ave_dominaplus/issues/29)).
