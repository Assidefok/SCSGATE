# ADR-0001: SCSGATE centralizes UX; MQTT retains technical ownership

Status: Accepted for v0.4.

## Decision

SCSGATE presents inventory, learning, editing, synchronization, health, and
repair. MQTT Discovery continues to own actuator entities. SCSGATE republishes
enriched retained Discovery using existing topics and `unique_id`; it does not
add `light`, `switch`, or `cover` platforms.

## Consequences

Existing entity IDs, user names, areas, labels, and automation references stay
attached because MQTT entity identity does not change. Adding `device` metadata
groups previously ungrouped entities. Firmware can still publish poor
non-retained payloads, so SCSGATE monitors and restores metadata. A second
gateway cannot be safely managed until firmware offers a gateway-specific MQTT
namespace.

This follows Home Assistant registry ownership: one config entry owns a device.
SCSGATE centralizes UX without pretending its config entry owns MQTT entities.
