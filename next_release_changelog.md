ave_dominaplus — v1.6.1

Highlights
- Fix Home Assistant's "Entity has an area but no name of its own" warnings after the 1.6.0 naming update.
- On setup, move legacy area assignments from unnamed switches, lights, covers, and thermostats to their AVE device when its area is unset or matches. The entity then inherits the device's area.
- Preserve existing entity IDs, custom names, and room assignments. Conflicting area assignments are left intact for manual resolution.

After updating, restart Home Assistant to apply the migration. No separate repair script is needed.

If a warning remains because the entity and device have conflicting areas, select the intended area on the AVE device and clear the entity's area. If the entity needs a separate area, give it its own name in Home Assistant's entity settings instead.
