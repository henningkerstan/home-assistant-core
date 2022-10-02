"""Support for EnOcean sensors."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from enocean.utils import from_hex_string, to_hex_string
import voluptuous as vol

from homeassistant.components.sensor import (
    PLATFORM_SCHEMA,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CONF_DEVICE_CLASS,
    CONF_ID,
    CONF_NAME,
    PERCENTAGE,
    STATE_CLOSED,
    STATE_OPEN,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .config_flow import (
    CONF_ENOCEAN_DEVICE_ID,
    CONF_ENOCEAN_DEVICE_NAME,
    CONF_ENOCEAN_DEVICES,
    CONF_ENOCEAN_EEP,
    CONF_ENOCEAN_MANUFACTURER,
    CONF_ENOCEAN_MODEL,
)
from .const import LOGGER, PERMUNDO_PSC234
from .device import EnOceanEntity
from .enocean_supported_device_type import EnOceanSupportedDeviceType

CONF_MAX_TEMP = "max_temp"
CONF_MIN_TEMP = "min_temp"
CONF_RANGE_FROM = "range_from"
CONF_RANGE_TO = "range_to"

DEFAULT_NAME = "EnOcean sensor"

SENSOR_TYPE_HUMIDITY = "humidity"
SENSOR_TYPE_POWER = "powersensor"
SENSOR_TYPE_TEMPERATURE = "temperature"
SENSOR_TYPE_WINDOWHANDLE = "windowhandle"


@dataclass
class EnOceanSensorEntityDescriptionMixin:
    """Mixin for required keys."""

    unique_id: Callable[[list[int]], str | None]


@dataclass
class EnOceanSensorEntityDescription(
    SensorEntityDescription, EnOceanSensorEntityDescriptionMixin
):
    """Describes EnOcean sensor entity."""


SENSOR_DESC_TEMPERATURE = EnOceanSensorEntityDescription(
    key=SENSOR_TYPE_TEMPERATURE,
    name="Temperature",
    native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    icon="mdi:thermometer",
    device_class=SensorDeviceClass.TEMPERATURE,
    state_class=SensorStateClass.MEASUREMENT,
    unique_id=lambda dev_id_string: f"{dev_id_string}-{SENSOR_TYPE_TEMPERATURE}",
)

SENSOR_DESC_HUMIDITY = EnOceanSensorEntityDescription(
    key=SENSOR_TYPE_HUMIDITY,
    name="Humidity",
    native_unit_of_measurement=PERCENTAGE,
    icon="mdi:water-percent",
    device_class=SensorDeviceClass.HUMIDITY,
    state_class=SensorStateClass.MEASUREMENT,
    unique_id=lambda dev_id_string: f"{dev_id_string}-{SENSOR_TYPE_HUMIDITY}",
)

SENSOR_DESC_POWER = EnOceanSensorEntityDescription(
    key=SENSOR_TYPE_POWER,
    name="Power",
    native_unit_of_measurement=UnitOfPower.WATT,
    icon="mdi:power-plug",
    device_class=SensorDeviceClass.POWER,
    state_class=SensorStateClass.MEASUREMENT,
    unique_id=lambda dev_id_string: f"{dev_id_string}-{SENSOR_TYPE_POWER}",
)

SENSOR_DESC_WINDOWHANDLE = EnOceanSensorEntityDescription(
    key=SENSOR_TYPE_WINDOWHANDLE,
    name="WindowHandle",
    icon="mdi:window-open-variant",
    unique_id=lambda dev_id_string: f"{dev_id_string}-{SENSOR_TYPE_WINDOWHANDLE}",
)


PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_ID): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_DEVICE_CLASS, default=SENSOR_TYPE_POWER): cv.string,
        vol.Optional(CONF_MAX_TEMP, default=40): vol.Coerce(int),
        vol.Optional(CONF_MIN_TEMP, default=0): vol.Coerce(int),
        vol.Optional(CONF_RANGE_FROM, default=255): cv.positive_int,
        vol.Optional(CONF_RANGE_TO, default=0): cv.positive_int,
    }
)


def setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up an EnOcean sensor device."""
    dev_id: list[int] = config[CONF_ID]
    dev_name: str = config[CONF_NAME]
    sensor_type: str = config[CONF_DEVICE_CLASS]

    entities: list[EnOceanSensor] = []
    if sensor_type == SENSOR_TYPE_TEMPERATURE:
        temp_min: int = config[CONF_MIN_TEMP]
        temp_max: int = config[CONF_MAX_TEMP]
        range_from: int = config[CONF_RANGE_FROM]
        range_to: int = config[CONF_RANGE_TO]
        entities = [
            EnOceanTemperatureSensor(
                dev_id,
                dev_name,
                SENSOR_DESC_TEMPERATURE,
                scale_min=temp_min,
                scale_max=temp_max,
                range_from=range_from,
                range_to=range_to,
            )
        ]

    elif sensor_type == SENSOR_TYPE_HUMIDITY:
        entities = [EnOceanHumiditySensor(dev_id, dev_name, SENSOR_DESC_HUMIDITY)]

    elif sensor_type == SENSOR_TYPE_POWER:
        entities = [EnOceanPowerSensor(dev_id, dev_name, SENSOR_DESC_POWER)]

    elif sensor_type == SENSOR_TYPE_WINDOWHANDLE:
        entities = [EnOceanWindowHandle(dev_id, dev_name, SENSOR_DESC_WINDOWHANDLE)]

    add_entities(entities)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up entry."""
    devices = config_entry.options.get(CONF_ENOCEAN_DEVICES, [])

    for device in devices:
        eep = device[CONF_ENOCEAN_EEP]
        device_id = from_hex_string(device[CONF_ENOCEAN_DEVICE_ID])
        device_name = device[CONF_ENOCEAN_DEVICE_NAME]
        device_type = EnOceanSupportedDeviceType(
            manufacturer=device[CONF_ENOCEAN_MANUFACTURER],
            model=device[CONF_ENOCEAN_MODEL],
            eep=device[CONF_ENOCEAN_EEP],
        )

        # Temperature sensors (EEP A5-02-)
        if eep[0:5] == "A5-02":
            min_temp, max_temp = _get_a5_02_min_max_temp(eep)

            async_add_entities(
                [
                    EnOceanTemperatureSensor(
                        device_id,
                        device_name,
                        SENSOR_DESC_TEMPERATURE,
                        scale_min=min_temp,
                        scale_max=max_temp,
                        range_from=255,
                        range_to=0,
                        dev_type=device_type,
                        name=None,
                    )
                ]
            )
            continue

        # Room Operating Panels (EEP A5-10-01 to A5-10-14)
        if eep[0:5] == "A5-10":

            eep_type = int(eep[6:8], 16)
            LOGGER.debug("EEP A5-10 type")

            if eep_type < 0x01 or eep_type > 0x14:
                continue  # should not happen (EEP not available)

            if eep_type >= 0x10:
                async_add_entities(
                    [
                        EnOceanTemperatureSensor(
                            dev_id=device_id,
                            dev_name=device_name,
                            description=SENSOR_DESC_TEMPERATURE,
                            scale_min=0,
                            scale_max=40,
                            range_from=0,
                            range_to=255,
                            dev_type=device_type,
                            name="Temperature",
                        ),
                        EnOceanHumiditySensor(
                            dev_id=device_id,
                            dev_name=device_name,
                            description=SENSOR_DESC_HUMIDITY,
                            dev_type=device_type,
                            name="Humidity",
                        ),
                    ]
                )
                continue

            async_add_entities(
                [
                    EnOceanTemperatureSensor(
                        device_id,
                        device_name,
                        SENSOR_DESC_TEMPERATURE,
                        scale_min=0,
                        scale_max=40,
                        range_from=255,
                        range_to=0,
                        dev_type=device_type,
                        name="Temperature",
                    )
                ]
            )
            continue

        # The Permundo PSC234 also sends A5-12-01 messages (but uses natively
        # D2-01-09); as there is not (yet) a way to define multiple EEPs per
        # EnOcean device, but this device was previously supported in this
        # combination, we allow it manually here
        if (
            eep == PERMUNDO_PSC234.eep
            and device[CONF_ENOCEAN_MANUFACTURER] == PERMUNDO_PSC234.manufacturer
            and device[CONF_ENOCEAN_MODEL] == PERMUNDO_PSC234.model
        ):
            async_add_entities(
                [
                    EnOceanPowerSensor(
                        device_id,
                        device_name,
                        SENSOR_DESC_POWER,
                        dev_type=PERMUNDO_PSC234,
                        name="Power usage",
                    )
                ]
            )


class EnOceanSensor(EnOceanEntity, RestoreEntity, SensorEntity):
    """Representation of an  EnOcean sensor device such as a power meter."""

    def __init__(
        self,
        dev_id,
        dev_name,
        description: EnOceanSensorEntityDescription,
        dev_type: EnOceanSupportedDeviceType = EnOceanSupportedDeviceType(),
        name=None,
    ):
        """Initialize the EnOcean sensor device."""
        super().__init__(dev_id, dev_name, dev_type, name)
        self.entity_description = description
        self._attr_unique_id = description.unique_id(to_hex_string(dev_id).upper())

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        # If not None, we got an initial value.
        await super().async_added_to_hass()
        if self._attr_native_value is not None:
            return

        if (state := await self.async_get_last_state()) is not None:
            self._attr_native_value = state.state

    def value_changed(self, packet):
        """Update the internal state of the sensor."""


# pylint: disable-next=hass-invalid-inheritance # needs fixing
class EnOceanPowerSensor(EnOceanSensor):
    """Representation of an EnOcean power sensor.

    EEPs (EnOcean Equipment Profiles):
    - A5-12-01 (Automated Meter Reading, Electricity)
    """

    def value_changed(self, packet):
        """Update the internal state of the sensor."""
        if packet.rorg != 0xA5:
            return
        packet.parse_eep(0x12, 0x01)
        if packet.parsed["DT"]["raw_value"] == 1:
            # this packet reports the current value
            raw_val = packet.parsed["MR"]["raw_value"]
            divisor = packet.parsed["DIV"]["raw_value"]
            self._attr_native_value = raw_val / (10**divisor)
            self.schedule_update_ha_state()


class EnOceanTemperatureSensor(EnOceanSensor):
    """Representation of an EnOcean temperature sensor device.

    EEPs (EnOcean Equipment Profiles):
    - A5-02-01 to A5-02-1B All 8 Bit Temperature Sensors of A5-02
    - A5-10-01 to A5-10-14 (Room Operating Panels)
    - A5-04-01 (Temp. and Humidity Sensor, Range 0°C to +40°C and 0% to 100%)
    - A5-04-02 (Temp. and Humidity Sensor, Range -20°C to +60°C and 0% to 100%)
    - A5-10-10 (Temp. and Humidity Sensor and Set Point)
    - A5-10-12 (Temp. and Humidity Sensor, Set Point and Occupancy Control)
    - 10 Bit Temp. Sensors are not supported (A5-02-20, A5-02-30)

    For the following EEPs the scales must be set to "0 to 250":
    - A5-04-01
    - A5-04-02
    - A5-10-10 to A5-10-14
    """

    def __init__(
        self,
        dev_id: list[int],
        dev_name: str,
        description: EnOceanSensorEntityDescription,
        *,
        scale_min,
        scale_max,
        range_from,
        range_to,
        dev_type: EnOceanSupportedDeviceType = EnOceanSupportedDeviceType(),
        name=None,
    ):
        """Initialize the EnOcean temperature sensor device."""
        super().__init__(dev_id, dev_name, description, dev_type, name)
        self._scale_min = scale_min
        self._scale_max = scale_max
        self.range_from = range_from
        self.range_to = range_to

    def value_changed(self, packet):
        """Update the internal state of the sensor."""
        if packet.data[0] != 0xA5:
            return
        temp_scale = self._scale_max - self._scale_min
        temp_range = self.range_to - self.range_from
        raw_val = packet.data[3]
        temperature = temp_scale / temp_range * (raw_val - self.range_from)
        temperature += self._scale_min
        self._attr_native_value = round(temperature, 1)
        self.schedule_update_ha_state()

class EnOceanHumiditySensor(EnOceanSensor):
    """Representation of an EnOcean humidity sensor device.

    EEPs (EnOcean Equipment Profiles):
    - A5-04-01 (Temp. and Humidity Sensor, Range 0°C to +40°C and 0% to 100%)
    - A5-04-02 (Temp. and Humidity Sensor, Range -20°C to +60°C and 0% to 100%)
    - A5-10-10 to A5-10-14 (Room Operating Panels)
    """

    def value_changed(self, packet):
        """Update the internal state of the sensor."""
        if packet.rorg != 0xA5:
            return
        humidity = packet.data[2] * 100 / 250
        self._attr_native_value = round(humidity, 1)
        self.schedule_update_ha_state()


# pylint: disable-next=hass-invalid-inheritance # needs fixing
class EnOceanWindowHandle(EnOceanSensor):
    """Representation of an EnOcean window handle device.

    EEPs (EnOcean Equipment Profiles):
    - F6-10-00 (Mechanical handle / Hoppe AG)
    """

    def value_changed(self, packet):
        """Update the internal state of the sensor."""
        action = (packet.data[1] & 0x70) >> 4

        if action == 0x07:
            self._attr_native_value = STATE_CLOSED
        if action in (0x04, 0x06):
            self._attr_native_value = STATE_OPEN
        if action == 0x05:
            self._attr_native_value = "tilt"

        self.schedule_update_ha_state()


def _get_a5_02_min_max_temp(eep: str):
    """Determine the min and max temp for an A5-02-XX temperature sensor."""
    sensor_range_type = int(eep[6:8], 16)

    if sensor_range_type in range(0x01, 0x0B):
        multiplier = sensor_range_type - 0x01
        min_temp = -40 + multiplier * 10
        max_temp = multiplier * 10
        return min_temp, max_temp

    if sensor_range_type in range(0x10, 0x1B):
        multiplier = sensor_range_type - 0x10
        min_temp = -60 + multiplier * 10
        max_temp = 20 + multiplier * 10
        return min_temp, max_temp

    LOGGER.warning(
        "Unsupported A5-02-XX temperature sensor with EEP %s; using default values (min_temp = 0, max_temp = 40)",
        eep,
    )
    return 0, 40


def _get_a5_10_min_max_temp(eep: str):
    """Determine the min and max temp for an A5-10-XX temperature sensor."""
    sensor_range_type = int(eep[6:8], 16)

    if sensor_range_type in range(0x01, 0x0B):
        multiplier = sensor_range_type - 0x01
        min_temp = -40 + multiplier * 10
        max_temp = multiplier * 10
        return min_temp, max_temp

    if sensor_range_type in range(0x10, 0x1B):
        multiplier = sensor_range_type - 0x10
        min_temp = -60 + multiplier * 10
        max_temp = 20 + multiplier * 10
        return min_temp, max_temp

    LOGGER.warning(
        "Unsupported A5-02-XX temperature sensor with EEP %s; using default values (min_temp = 0, max_temp = 40)",
        eep,
    )
    return 0, 40
