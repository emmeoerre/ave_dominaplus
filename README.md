# 🌟 AVE Dominaplus Integration for Home Assistant

Control your AVE Dominaplus home automation system directly from Home Assistant! This integration uses WebSocket communication with the AVE webserver for a **completely asynchronous** and **100% local** setup.

---

## 📋 Requirements

- An **AVE webserver device** installed and accessible from your Home Assistant instance.
- Only tested with the **"autologin" setting** enabled in the webserver.
- **AVE Cloud configuration is NOT required**.
- **Alarm units** connected to the webserver (required for motion sensors and alarm zones).

## 🔎 Dependency transparency

This integration is intentionally lightweight and local-first:

- It communicates with the AVE webserver over local network protocols only (WebSocket + local HTTP endpoints).
- It uses asynchronous networking through the Home Assistant Python stack (`aiohttp`).
- XML payloads from AVE endpoints are parsed with `defusedxml` for safer parsing.
- It does not require AVE cloud APIs or a vendor cloud SDK.

---

## 🚀 Installation

1. Install the integration via HACS (recommended) or manually copy the files to your `custom_components` directory.
2. At this point Home Assistant may autodiscover the AVE webserver and show a configuration prompt. If you see it, open that prompt and continue from there.
3. If no autodiscovery prompt appears go to **Settings → Devices & Services → Add Integration**. Search for **"AVE Dominaplus"** and select it manually.
4. In the configuration prompt provide the webserver IP address and configure additional settings as needed.

### Configuration parameters

During setup/reconfigure you can tune these options:

- `ip_address`: IP address of the AVE webserver.
- `fetch_lights`: Enable on/off lights and dimmers.
- `on_off_lights_as_switch`: Expose family-1 on/off lights as `switch` instead of `light`.
- `fetch_covers`: Enable shutter/cover entities.
- `fetch_thermostats`: Enable thermostat climate entities and related offset entities.
- `fetch_scenarios`: Enable scenarios devices and related entities.
- `fetch_sensor_areas`: Enable alarm area binary sensors.
- `fetch_sensors`: Enable individual alarm sensor entities (discovered when they first report events).
- `get_entities_names`: If enabled, use AVE names for device labels instead of translated generated labels.

### Installation/network parameters

The integration assumes:

- Home Assistant can reach AVE webserver on local network.
- WebSocket endpoint is reachable on `ws://<ip_address>:14001`.
- Local HTTP endpoints like `/bridge.php`, `/revealcode.php`, and `/systeminfo.php` are reachable.
- AVE webserver autologin mode is enabled (current tested scenario).

---

## 🛠️ Supported Devices

### ✅ Switches (on/off lights)
- Synced with the **"Get lights"** flag.
- Supports turning on, off, and toggling.
- Config toggle allows to choose if they are exposed as lights entities or switch entities.

### ✅ Dimmers (non‑RGB)
- Discovered at startup when **Get lights** is enabled.
- Exposes brightness and supports on/off and level setting.

### ✅ Shutters (covers)
- Discovered when **Get covers** is enabled. Exposed as `cover` entities and support open/close/stop actions and basic position reporting.

### ✅ Alarm Areas
- Synced with the **"Get antitheft sensor areas"** flag.
- Provides motion sensor functionality.
- Includes **"Last cleared"** and **"Last revealed"** timestamps as attributes.
- *Note: "Armed" and "Triggered" states are not yet exposed as entities.*

### ✅ Individual Alarm Sensors
- Discovered when the first event is triggered.
- Synced with the **"Get individual antitheft sensors"** flag.
- The system does not provide names, so sensors are auto-named. It is recommended to set custom
   names after discovery.
- These sensors are sensitive and may trigger quickly; configure accordingly.

### ✅ Thermostats
- Discovered when **"Get thermostats"** is enabled in the config flow.
- For each thermostat the integration creates two entities:
  * a **climate** entity representing the controller
  * a **number** entity showing the current temperature offset of the device (–5 °C..+5 °C)

#### Climate entity behaviour
- `Mode` controls the combination of season and on/off state:
  * `Cool` for summer mode
  * `Heat` for winter mode
  * `Off` if the thermostat is powered off (support depends on the device)
- `Preset` is either `Schedule` (follow the schedule on the webserver)
  or `Manual` (immediate changes from Home Assistant). Changing the
  target temperature from HA will automatically switch the preset to
  `Manual`, mimicking the vendor app behaviour.
- `Fan mode` reflects the fancoil speed reported by the zone; it is **read‑only**.

#### Offset sensor
- A read‑only number sensor is created for each thermostat exposing the
  device’s current offset.
- The offset **cannot be modified from Home Assistant**; it must be set on the
  physical thermostat itself.  The sensor simply mirrors the value reported
  by the device.

### ✅ Scenarios
- Discovered at startup from `LI2` when **"Get scenarios"** is enabled.
- Each scenario gets its own device in Home Assistant with two entities:
  * a **button** entity to execute the scenario
  * a **binary_sensor** entity reporting whether the scenario is currently running

---

## 🔜 Not yet supported (contributors welcome!)

Other devices are not yet supported either for lack of time or lack of devices at hand

- **RGB Lights**
- **Areas**: Feel free to come with a plan to add AVE areas and device area assignments without clashing with the HA areas
- **Economizers**: Not yet supported
- **Metered outlets**: Not yet supported

---

## 🏷️ About Device Names

The **Use names from webserver** option controls device labels. When enabled,
supported endpoints use names from the Dominaplus configuration. When disabled,
the integration uses translated labels such as `Light 34`, `Shutter 12`, and
`Thermostat 7`.

Primary entities use the device name without repeating it. Secondary entities
use translated labels such as `Run`, `Running`, `Offset`, and `Status`.

Home Assistant assigns entity IDs when entities are first created. Upgrading the
integration does not rename existing entity IDs, so automations and dashboards
continue to work. New installations receive the cleaner naming scheme. Names set
by a user in Home Assistant are preserved for both entities and devices.

---

## ❓ Frequently asked questions

### I don’t see certain device types after installation
First verify the device type is listed under “Supported Devices” above. If
it is supported and still not visible, reconfigure the integration in Home
Assistant (Settings → Devices & Services → your AVE entry → ⋮ menu →
Reconfigure).  Items added in a newer version may not appear until the entry
has been re‑configured.


## ⚙️ Data update model

- Main state updates are push-based over WebSocket subscriptions.
- At connection/startup, the integration requests initial snapshots (device list and selected family/state queries).
- If WebSocket connectivity drops, the integration attempts reconnection.


## 💡 Example automations

### Motion area turns on a light

```yaml
automation:
  - alias: AVE - Turn on corridor light on alarm area motion
    triggers:
      - trigger: state
        entity_id: binary_sensor.ave_dominaplus_antitheft_area_12
        to: "on"
    actions:
      - action: light.turn_on
        target:
          entity_id: light.corridoio
```

### Close shutters when leaving home

```yaml
automation:
  - alias: AVE - Close shutters when everyone leaves
    triggers:
      - trigger: state
        entity_id: group.family
        to: not_home
    actions:
      - action: cover.close_cover
        target:
          entity_id:
            - cover.sala
            - cover.camera
            - cover.cucina
```


## 🧭 Use cases

- Keep existing AVE DominaPlus installation while adding richer automations in Home Assistant.
- Build mixed automations that combine AVE devices with non-AVE devices (presence, weather, voice assistants).
- Centralize climate, shutters, and lighting control in a single Home Assistant dashboard.


## ⚠️ Known Issues
### Multiple webservers for different plants
- Multiple webservers for different plants are not supported yet. Multiple controllers for the same plant are supported, but separate plant setups may cause device ID clashes. Support for multi‑plant setups is under development.

### Webserver connection after shutdown
- The integration attempts to re‑establish the WebSocket connection if it is lost. If the connection does not recover, manually reload the integration or restart Home Assistant.

### Individual sensor alarm states after power outage
- After a webserver or alarm unit reboot, sensors may require a brief arm/disarm cycle before they start reporting state updates. This behavior is caused by the alarm system firmware, not the integration.

### Duplicate entities after plant changes
- Duplicate entities may appear after changes to plants in the AVE DominaPlus configurator. This is especially likely if a device is deleted, which can change subsequent device IDs. A fix for this issue is tracked here: [#15](https://github.com/emmeoerre/ave_dominaplus/issues/15)


## 🗑️ Removal instructions

To remove the integration cleanly:

1. In Home Assistant go to **Settings → Devices & Services** and remove the AVE Dominaplus config entry.
2. If installed via HACS, uninstall it from HACS.
3. If installed manually, delete the folder `custom_components/ave_dominaplus`.
4. Restart Home Assistant.
5. Optionally review the entity/device registry for stale objects left by older versions and remove them.

## 🆘 How to ask for help

Before opening an issue:

* Make sure the integration is up to date.
* Check the **FAQ** and **Known Issues** sections above; your question may already be answered.

When creating a GitHub issue:

* Search for an existing issue describing the same problem and add additional information there instead
  of opening a duplicate.
* Do **not** post on unrelated issues; off-topic comments may be removed.
* Follow the template provided


---

## 🤝 Contributing & developing

Contributions are welcome! If you encounter issues or have feature requests, feel free to open an issue or submit a pull request on GitHub.
You can join our [discord server](https://discord.gg/PQ52jwV6BX)

Development setup and debugging guide (VS Code on Windows + WSL): [docs/development/vscode-windows.md](docs/development/vscode-windows.md)

---

## 📜 License

This project is licensed under the **MIT License**. See the `LICENSE` file for more details.
