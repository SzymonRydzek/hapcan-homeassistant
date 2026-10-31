# HAPCAN for Home Assistant

Custom integration for the [HAPCAN](https://github.com/hapcan) home automation
bus, connected through the HAPCAN Ethernet interface.

Supported:

- **Lights** on bistable relay modules (one relay channel per light). State
  follows the bus, including changes made with wall buttons.
- **Blinds** on monostable relay modules, driven by short pulses on an up and
  a down channel (e.g. Mobilus motors with contact inputs). Optional travel
  times give a position estimate; wall-button pulses update it too.

The connection reconnects by itself, entities show as unavailable while the
bus is unreachable, and every module is asked for its state after each
(re)connect.

## Installation

HACS → Integrations → ⋮ → Custom repositories → add this repository as an
*Integration*, install **HAPCAN**, restart Home Assistant.

## Configuration (`configuration.yaml`)

```yaml
hapcan:
  host: 192.168.1.50
  port: 1008

light:
  - platform: hapcan
    devices:
      1:
        name: "Kitchen"
        address: 0x0c     # node of the interface/module path used on your bus
        group: 0xF4       # relay module group
        channel: 1        # relay channel 1-6

cover:
  - platform: hapcan
    # how the motors stop mid-way: none | opposite | same (default none);
    # a device can override it
    stop_method: opposite
    devices:
      1:
        name: "Living room"
        address: 0x0c
        group: 0x8A
        channel_up: 4
        channel_down: 3
        # optional starting values; can be changed in the UI instead
        travel_time_up: 28      # seconds, fully closed -> fully open
        travel_time_down: 26    # seconds, fully open -> fully closed
```

The numeric key of each device is part of its unique ID: do not renumber
devices, or Home Assistant will create new entities.

### Travel times in the UI

Every blind gets two settings entities, *<name> travel time up* and
*<name> travel time down* (seconds, 0 = not set), in the entity list and on
dashboards. A value set there is kept across restarts and overrides the YAML
value.

Stop and position control (`set_cover_position`) appear once both travel
times are set and the stop method is not `none`. Without travel times a blind
is reported as open or closed after a full movement; stop is not offered then,
because a stop pulse sent to a blind that has already stopped would start it
again.

## Development

```bash
python -m pytest tests
```

The protocol, connection and blind model modules have no Home Assistant
imports and are tested on their own.
