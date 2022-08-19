"""Support for EnOcean roller shutters."""
from __future__ import annotations

import asyncio
import logging

from enocean.protocol.packet import Packet  # pylint: disable=import-error
from enocean.utils import combine_hex  # pylint: disable=import-error
import voluptuous as vol  # pylint: disable=import-error

from homeassistant.components.cover import (
    ATTR_POSITION,
    DEVICE_CLASSES_SCHEMA,
    PLATFORM_SCHEMA,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.const import CONF_DEVICE_CLASS, CONF_ID, CONF_NAME
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.dispatcher import dispatcher_send
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import SIGNAL_SEND_MESSAGE
from .device import EnOceanEntity

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "EnOcean roller shutter"

CONF_SENDER_ID = "sender_id"
WATCHDOG_TIMEOUT = "watchdog_timeout"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_ID): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Required(CONF_SENDER_ID): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_DEVICE_CLASS): DEVICE_CLASSES_SCHEMA,
        vol.Optional(WATCHDOG_TIMEOUT, default=5): int,
    }
)


def setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the Cover platform for EnOcean."""
    dev_id = config.get(CONF_ID)
    sender_id = config.get(CONF_SENDER_ID)
    dev_name = config[CONF_NAME]
    device_class = config.get(CONF_DEVICE_CLASS)
    if device_class is None:
        device_class = CoverDeviceClass.BLIND
    watchdog_timeout = config[WATCHDOG_TIMEOUT]
    add_entities(
        [EnOceanCover(sender_id, dev_id, dev_name, device_class, watchdog_timeout)]
    )


class EnOceanCover(EnOceanEntity, CoverEntity):
    """Representation of an EnOcean Cover (EEP D2-05-00)."""

    def __init__(self, sender_id, dev_id, dev_name, device_class, watchdog_timeout):
        """Initialize the EnOcean Cover."""
        super().__init__(dev_id, dev_name)
        self._attr_device_class = device_class
        self._position = None
        self._is_closed = None
        self._is_opening = False
        self._is_closing = False
        self._sender_id = sender_id
        self._dev_name = dev_name
        self._attr_name = dev_name
        self._attr_unique_id = f"{combine_hex(dev_id)}-{device_class}"
        self._state_changed_by_command = False
        self._watchdog_enabled = False
        self._watchdog_seconds_remaining = 0
        self._watchdog_timeout = watchdog_timeout
        self._attr_supported_features = (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.STOP
            | CoverEntityFeature.SET_POSITION
        )

    @property
    def current_cover_position(self) -> int | None:
        """Return the current cover position."""
        return self._position

    @property
    def is_opening(self) -> bool | None:
        """Return if the cover is opening or not."""
        return self._is_opening

    @property
    def is_closing(self) -> bool | None:
        """Return if the cover is closing or not."""
        return self._is_closing

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed or not."""
        return self._is_closed

    def open_cover(self, **kwargs) -> None:
        """Open the cover."""
        self._state_changed_by_command = True
        self._is_opening = True
        self._is_closing = False
        self.start_or_feed_watchdog()

        telegram = [0xD2, 0, 0, 0, 1]
        telegram.extend(self._sender_id)
        telegram.extend([0x00])
        self.send_telegram(telegram)

    def close_cover(self, **kwargs) -> None:
        """Close the cover."""
        self._state_changed_by_command = True
        self._is_opening = False
        self._is_closing = True
        self.start_or_feed_watchdog()

        telegram = [0xD2, 100, 0, 0, 1]
        telegram.extend(self._sender_id)
        telegram.extend([0x00])
        self.send_telegram(telegram)

    def set_cover_position(self, **kwargs) -> None:
        """Set the cover position."""
        self._state_changed_by_command = True

        if kwargs[ATTR_POSITION] == self._position:
            self._is_opening = False
            self._is_closing = False
        elif kwargs[ATTR_POSITION] > self._position:
            self._is_opening = True
            self._is_closing = False
        elif kwargs[ATTR_POSITION] < self._position:
            self._is_opening = False
            self._is_closing = True

        self.start_or_feed_watchdog()

        telegram = [0xD2, 100 - kwargs[ATTR_POSITION], 0, 0, 1]
        telegram.extend(self._sender_id)
        telegram.extend([0x00])
        self.send_telegram(telegram)

    def stop_cover(self, **kwargs) -> None:
        """Stop any cover movement."""
        self.stop_watchdog()
        self._state_changed_by_command = True
        self._is_opening = False
        self._is_closing = False

        telegram = [0xD2, 2]
        telegram.extend(self._sender_id)
        telegram.extend([0x00])
        self.send_telegram(telegram)

    def value_changed(self, packet):
        """Fire an event with the data that have changed.

        This method is called when there is an incoming packet associated
        with this platform.
        """
        # position is inversed in Home Assistant and in EnOcean:
        # 0 means 'closed' in Home Assistant and 'open' in EnOcean
        # 100 means 'open' in Home Assistant and 'closed' in EnOcean

        new_position = 100 - packet.data[1]

        if self._position is not None:
            if self._state_changed_by_command:
                self._state_changed_by_command = False
            elif new_position in (0, 100, self._position):
                self._is_opening = False
                self._is_closing = False
                self.stop_watchdog()
            elif new_position > self._position:
                self._is_opening = True
                self._is_closing = False
                self.start_or_feed_watchdog()
            elif new_position < self._position:
                self._is_opening = False
                self._is_closing = True
                self.start_or_feed_watchdog()

        self._position = new_position
        if self._position == 0:
            self._is_closed = True
        else:
            self._is_closed = False

        self.schedule_update_ha_state()

    def send_telegram(self, data):
        """Send a telegram via the EnOcean dongle to only this device."""
        # optional data contains: number of subtelegrams (fixed to 3 for sending),
        # destination id, max dBm (0xFF) for sending and security level 0
        packet = Packet(0x01, data=data, optional=[3] + self.dev_id + [0xFF, 0])
        dispatcher_send(self.hass, SIGNAL_SEND_MESSAGE, packet)

    def start_or_feed_watchdog(self):
        """Start or feed the 'movement stop' watchdog."""
        self._watchdog_seconds_remaining = self._watchdog_timeout

        if self._watchdog_enabled:
            return

        self._watchdog_enabled = True
        self.hass.create_task(self.watchdog())

    def stop_watchdog(self):
        """Stop the 'movement stop' watchdog."""
        self._watchdog_enabled = False

    async def watchdog(self):
        """Watchdog to check if the cover movement stopped.

        After watchdog time expired, the watchdog queries the current status.
        """

        while 1:
            await asyncio.sleep(1)

            if not self._watchdog_enabled:
                return

            if self._watchdog_seconds_remaining == 0:
                telegram = [0xD2, 3]
                telegram.extend(self._sender_id)
                telegram.extend([0x00])
                self.send_telegram(telegram)
                await asyncio.sleep(2)

                self._watchdog_seconds_remaining = self._watchdog_timeout
                continue

            self._watchdog_seconds_remaining -= 1
