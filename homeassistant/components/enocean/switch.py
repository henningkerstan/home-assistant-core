"""Support for EnOcean switches."""
from __future__ import annotations

from typing import Any

from enocean.utils import from_hex_string, to_hex_string
import voluptuous as vol

from homeassistant.components.switch import PLATFORM_SCHEMA, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ID, CONF_NAME, Platform
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .config_flow import (
    CONF_ENOCEAN_DEVICE_TYPE_ID,
    CONF_ENOCEAN_DEVICES,
)
from .device import EnOceanEntity
from .importer import (
    EnOceanPlatformConfig,
    register_platform_config_for_migration_to_config_entry,
)
from .supported_device_type import (
    EnOceanSupportedDeviceType,
    get_supported_enocean_device_types,
)

CONF_CHANNEL = "channel"
DEFAULT_NAME = ""

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_ID): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_CHANNEL, default=0): cv.positive_int,
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the EnOcean switch platform."""
    register_platform_config_for_migration_to_config_entry(
        EnOceanPlatformConfig(platform=Platform.SWITCH.value, config=config)
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entry."""
    devices = entry.options.get(CONF_ENOCEAN_DEVICES, [])

    for device in devices:
        device_type_id = device[CONF_ENOCEAN_DEVICE_TYPE_ID]
        device_type = get_supported_enocean_device_types()[device_type_id]
        eep = device_type.eep

        if eep[0:5] == "D2-01":
            device_id = from_hex_string(device["id"])

            # number of switches depends on EEP's TYPE value:
            num_switches = 0
            eep_type = int(eep[6:8], 16)

            if eep_type in range(0x00, 0x10):
                num_switches = 1
            elif eep_type in range(0x10, 0x13):
                num_switches = 2
            elif eep_type == 0x13:
                num_switches = 4
            elif eep_type == 0x14:
                num_switches = 8

            switches = []

            if num_switches == 1:
                switches.append(
                    EnOceanSwitch(
                        dev_id=device_id,
                        dev_name=device["name"],
                        channel=0,
                        dev_type=device_type,
                        name="Switch",
                    ),
                )
            else:
                for channel in range(0, num_switches):
                    switches.append(
                        EnOceanSwitch(
                            dev_id=device_id,
                            dev_name=device["name"],
                            channel=channel,
                            dev_type=device_type,
                            name="Switch " + str(channel + 1),
                        ),
                    )
            async_add_entities(switches)


class EnOceanSwitch(EnOceanEntity, SwitchEntity):
    """Representation of an EnOcean switch device."""

    def __init__(
        self,
        dev_id,
        dev_name,
        channel,
        dev_type: EnOceanSupportedDeviceType = EnOceanSupportedDeviceType(),
        name=None,
    ) -> None:
        """Initialize the EnOcean switch device."""
        super().__init__(dev_id, dev_name, dev_type, name)
        self._light = None
        self._on_state = False
        self._on_state2 = False
        self.channel = channel
        self._attr_unique_id = (
            f"{to_hex_string(dev_id).upper()}-{Platform.SWITCH.value}-{channel}"
        )

    @property
    def is_on(self) -> bool | None:
        """Return whether the switch is on or off."""
        return self._on_state

    def turn_on(self, **kwargs: Any) -> None:
        """Turn on the switch."""
        optional = [0x03]
        optional.extend(self.dev_id)
        optional.extend([0xFF, 0x00])
        self.send_command(
            data=[0xD2, 0x01, self.channel & 0xFF, 0x64, 0x00, 0x00, 0x00, 0x00, 0x00],
            optional=optional,
            packet_type=0x01,
        )
        self._on_state = True

    def turn_off(self, **kwargs: Any) -> None:
        """Turn off the switch."""
        optional = [0x03]
        optional.extend(self.dev_id)
        optional.extend([0xFF, 0x00])
        self.send_command(
            data=[0xD2, 0x01, self.channel & 0xFF, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
            optional=optional,
            packet_type=0x01,
        )
        self._on_state = False

    def value_changed(self, packet):
        """Update the internal state of the switch."""
        if packet.data[0] == 0xA5:
            # power meter telegram, turn on if > 10 watts
            packet.parse_eep(0x12, 0x01)
            if packet.parsed["DT"]["raw_value"] == 1:
                raw_val = packet.parsed["MR"]["raw_value"]
                divisor = packet.parsed["DIV"]["raw_value"]
                watts = raw_val / (10**divisor)
                if watts > 1:
                    self._on_state = True
                    self.schedule_update_ha_state()
        elif packet.data[0] == 0xD2:
            # actuator status telegram
            packet.parse_eep(0x01, 0x01)
            if packet.parsed["CMD"]["raw_value"] == 4:
                channel = packet.parsed["IO"]["raw_value"]
                output = packet.parsed["OV"]["raw_value"]
                if channel == self.channel:
                    self._on_state = output > 0
                    self.schedule_update_ha_state()
