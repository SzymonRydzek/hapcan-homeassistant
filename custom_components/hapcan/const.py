"""Constants for the HAPCAN integration."""

DOMAIN = "hapcan"
DEFAULT_PORT = 1004

SIGNAL_RELAY_UPDATED = "hapcan.relay_updated"
SIGNAL_CONNECTION = "hapcan.connection"

CONF_HAPCAN_GROUP = "group"
CONF_HAPCAN_CHANNEL = "channel"
CONF_HAPCAN_CHANNEL_UP = "channel_up"
CONF_HAPCAN_CHANNEL_DOWN = "channel_down"
CONF_TRAVEL_TIME_UP = "travel_time_up"
CONF_TRAVEL_TIME_DOWN = "travel_time_down"
CONF_STOP_METHOD = "stop_method"

STOP_NONE = "none"
STOP_OPPOSITE = "opposite"
STOP_SAME = "same"

# Length of the pulse sent to a monostable relay to start a blind.
PULSE_SECONDS = 0.2
