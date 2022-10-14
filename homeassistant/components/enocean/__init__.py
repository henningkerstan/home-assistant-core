"""Support for EnOcean devices."""
from __future__ import annotations

from copy import deepcopy

from enocean.utils import combine_hex, from_hex_string, to_hex_string
import voluptuous as vol

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_DEVICE, EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.typing import ConfigType

from .config_flow import (
    CONF_ENOCEAN_DEVICE_ID,
    CONF_ENOCEAN_DEVICE_NAME,
    CONF_ENOCEAN_DEVICES,
    CONF_ENOCEAN_EEP,
    CONF_ENOCEAN_MANUFACTURER,
    CONF_ENOCEAN_MODEL,
    CONF_ENOCEAN_SENDER_ID,
)
from .const import DATA_ENOCEAN, DOMAIN, ENOCEAN_DONGLE, LOGGER, PLATFORMS
from .dongle import EnOceanDongle
from .enocean_supported_device_type import (
    EEP_A5_02_0A,
    EEP_A5_02_0B,
    EEP_A5_02_01,
    EEP_A5_02_1A,
    EEP_A5_02_1B,
    EEP_A5_02_02,
    EEP_A5_02_03,
    EEP_A5_02_04,
    EEP_A5_02_05,
    EEP_A5_02_06,
    EEP_A5_02_07,
    EEP_A5_02_08,
    EEP_A5_02_09,
    EEP_A5_02_10,
    EEP_A5_02_11,
    EEP_A5_02_12,
    EEP_A5_02_13,
    EEP_A5_02_14,
    EEP_A5_02_15,
    EEP_A5_02_16,
    EEP_A5_02_17,
    EEP_A5_02_18,
    EEP_A5_02_19,
    EEP_A5_04_01,
    EEP_A5_04_02,
    EEP_A5_12_01,
    EEP_D2_01_07,
    EEP_D2_01_11,
    EEP_D2_01_13,
    EEP_D2_01_14,
    EEP_F6_02_01,
    EEP_F6_10_00,
    ELTAKO_FUD61,
    EnOceanSupportedDeviceType,
)

CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: vol.Schema({vol.Required(CONF_DEVICE): cv.string})}, extra=vol.ALLOW_EXTRA
)


# upcoming code is part of platform import to be deleted in a future version
class EnOceanPlatformConfig:
    """An EnOcean platform configuration entry."""

    platform: Platform
    config: ConfigType

    def __init__(self, platform: Platform, config: ConfigType) -> None:
        """Create a new EnOcean platform configuration entry."""
        self.platform = platform
        self.config = config


class EnOceanImportConfig:
    """An EnOcean import configuration."""

    new_unique_ids: list[str]
    old_unique_ids: dict[str, str]
    device_type: EnOceanSupportedDeviceType
    device_name: str
    sender_id: str | None

    def __init__(
        self,
        device_type: EnOceanSupportedDeviceType,
        new_unique_ids: list[str],
        old_unique_ids: dict[str, str],
        sender_id: str | None = None,
        device_name: str = "",
    ) -> None:
        """Create a new EnOcean import configuration."""
        self.new_unique_ids = new_unique_ids
        self.old_unique_ids = old_unique_ids
        self.device_type = device_type
        self.sender_id = sender_id
        self.device_name = device_name


# upcoming code is part of platform import to be deleted in a future version
# map from EnOcean id strings to platform configs
_enocean_platform_configs: dict[str, list[EnOceanPlatformConfig]] = {}


# upcoming code is part of platform import to be deleted in a future version
def register_platform_config_for_migration_to_config_entry(
    platform_config: EnOceanPlatformConfig,
):
    """Register an EnOcean platform configuration for importing it to the config entry."""

    dev_id = platform_config.config.get(CONF_ENOCEAN_DEVICE_ID, None)

    if not dev_id:
        LOGGER.warning(
            "Cannot register platform configuration with no EnOcean id for import"
        )
        return

    device_id = to_hex_string(dev_id).upper()

    if device_id not in _enocean_platform_configs:
        _enocean_platform_configs[device_id] = [platform_config]
    else:
        _enocean_platform_configs[device_id].append(platform_config)


# upcoming code is part of platform import to be deleted in a future version
def _get_entity_for_unique_id(ent_reg: entity_registry.EntityRegistry, unique_id):
    """Obtain an entity id even for those 'enocean' platform entities, which never had a device_class set.

    For some reason, this does not seem to be possible with the built-in async_get_entity_id(...) function.
    """
    for key in ent_reg.entities:
        ent = ent_reg.entities.get(key, None)
        if not ent:
            continue

        if ent.platform != "enocean":
            continue

        if ent.unique_id == unique_id:
            return ent

    return None


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the EnOcean component."""
    # support for text-based configuration (legacy)
    if DOMAIN not in config:
        return True

    if hass.config_entries.async_entries(DOMAIN):
        # We can only have one dongle. If there is already one in the config,
        # there is no need to import the yaml based config.
        return True

    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_IMPORT}, data=config[DOMAIN]
        )
    )

    return True


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> bool:
    """Set up an EnOcean dongle for the given entry."""
    enocean_data = hass.data.setdefault(DATA_ENOCEAN, {})
    usb_dongle = EnOceanDongle(hass, config_entry.data[CONF_DEVICE])
    await usb_dongle.async_setup()
    enocean_data[ENOCEAN_DONGLE] = usb_dongle

    config_entry.async_on_unload(config_entry.add_update_listener(async_reload_entry))
    async_cleanup_device_registry(hass=hass, entry=config_entry)
    forward_entry_setup_to_platforms(hass=hass, entry=config_entry)

    return _setup_yaml_import(hass, _enocean_platform_configs)


# upcoming code is part of platform import to be deleted in a future version
def _setup_yaml_import(
    hass: HomeAssistant,
    enocean_platform_configs: dict[str, list[EnOceanPlatformConfig]],
) -> bool:
    """Set up the yaml import."""
    enocean_devices_to_add: list[dict[str, str]] = []
    ent_reg = entity_registry.async_get(hass)

    # map from device id (hex) to list of (new) unique_ids
    new_unique_ids: dict[str, list[str]] = {}

    # map from device id (hex) to map from new unique_id to old unique_id
    old_unique_ids: dict[str, dict[str, str]] = {}

    # map from device id (hex) to map from (new) unique_id to old entity
    old_entities: dict[str, dict[str, entity_registry.RegistryEntry]] = {}

    @callback
    def _schedule_yaml_import(_):
        """Schedule platform configuration import 2s after HA is fully started."""
        if not enocean_platform_configs or len(enocean_platform_configs) < 1:
            return
        async_call_later(hass, 2, _import_yaml)

    @callback
    def _import_yaml(_):
        """Import platform configuration to config entry."""
        LOGGER.warning(
            "EnOcean platform configurations were found in your configuration.yaml. Configuring EnOcean via configuration.yaml is deprecated and will be removed in a future release. Now starting automatic import to config entry... "
        )

        # get the unique config_entry and the devices configured in it
        conf_entries = hass.config_entries.async_entries(DOMAIN)
        if not len(conf_entries) == 1:
            LOGGER.warning(
                "Cannot import platform configurations to config entry - no config entry found"
            )
            return
        config_entry = conf_entries[0]

        configured_enocean_devices = deepcopy(
            config_entry.options.get(CONF_ENOCEAN_DEVICES, [])
        )

        # process the enocean platform configs by EnOcean id
        for device_id, configs in enocean_platform_configs.items():
            # skip configured devices
            if _is_configured(
                device_id=device_id,
                configured_enocean_devices=configured_enocean_devices,
            ):
                LOGGER.debug(
                    "Skipping already configured EnOcean device %s",
                    device_id,
                )
                continue

            new_unique_ids[device_id] = []
            old_unique_ids[device_id] = {}
            old_entities[device_id] = {}

            import_config = _get_import_config(
                dev_id_string=device_id, platform_configs=configs
            )

            if import_config is None:
                continue

            new_unique_ids[device_id] = import_config.new_unique_ids
            old_unique_ids[device_id] = import_config.old_unique_ids

            enocean_devices_to_add.append(
                {
                    CONF_ENOCEAN_DEVICE_ID: device_id,
                    CONF_ENOCEAN_EEP: import_config.device_type.eep,
                    CONF_ENOCEAN_MANUFACTURER: import_config.device_type.manufacturer,
                    CONF_ENOCEAN_MODEL: import_config.device_type.model,
                    CONF_ENOCEAN_DEVICE_NAME: import_config.device_name,
                    CONF_ENOCEAN_SENDER_ID: import_config.sender_id,
                }
            )

            LOGGER.debug(
                "Scheduling EnOcean device %s for import as '%s %s' [EEP %s]",
                device_id,
                import_config.device_type.manufacturer,
                import_config.device_type.model,
                import_config.device_type.eep,
            )

        if len(enocean_devices_to_add) < 1:
            LOGGER.warning(
                "Import of EnOcean platform configurations completed (no new devices)"
            )
            return

        # append devices to config_entry and update
        for device in enocean_devices_to_add:
            configured_enocean_devices.append(device)

        hass.config_entries.async_update_entry(
            entry=config_entry,
            options={CONF_ENOCEAN_DEVICES: configured_enocean_devices},
        )

        async_call_later(hass, 5, _remove_new_entities_and_update_old_entities)

    async def _remove_new_entities_and_update_old_entities(self):
        """Remove those new entities for which an old entity exists and set both the new unique_id and a device on the old entity."""
        for device in enocean_devices_to_add:
            device_id = device[CONF_ENOCEAN_DEVICE_ID]
            LOGGER.debug("Updating entities for imported EnOcean device %s", device_id)

            for new_unique_id in new_unique_ids[device_id]:
                old_unique_id = old_unique_ids[device_id][new_unique_id]

                new_entity = _get_entity_for_unique_id(ent_reg, new_unique_id)
                old_entity = _get_entity_for_unique_id(ent_reg, old_unique_id)

                if new_entity is None:
                    LOGGER.warning(
                        "No new entity with unique id '%s' found", new_unique_id
                    )
                    continue

                if old_entity is None:
                    LOGGER.warning(
                        "No old entity with unique id '%s' found", old_unique_id
                    )
                    continue

                ent_reg.async_remove(new_entity.entity_id)
                LOGGER.debug(
                    "Removed new entity '%s' with unique_id '%s' from entity registry",
                    new_entity.entity_id,
                    new_unique_id,
                )

                ent_reg.async_update_entity(
                    entity_id=old_entity.entity_id,
                    new_unique_id=new_unique_id,
                    device_id=new_entity.device_id,
                )

                LOGGER.debug(
                    "Updated old entity '%s' in entity registry: Its new unique_id is '%s' (previously '%s') and its device_id is '%s' (previously NULL). You need to restart Home Assistant for this entity to show up in the UI",
                    old_entity.entity_id,
                    new_unique_id,
                    old_unique_id,
                    new_entity.device_id,
                )

        LOGGER.warning(
            "Import of EnOcean platform configurations completed. Please delete them from your configuration.yaml and restart Home Assistant"
        )

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _schedule_yaml_import)

    return True


def _is_configured(device_id: str, configured_enocean_devices):
    """Check if an EnOcean device with the given id was already configured."""
    for device in configured_enocean_devices:
        if device[CONF_ENOCEAN_DEVICE_ID] == device_id:
            return True

    return False


def _get_import_config(
    dev_id_string: str,
    platform_configs: list[EnOceanPlatformConfig],
) -> EnOceanImportConfig | None:
    """Return a list of EnOcean import configurations for the supplied EnOcean platform configurations."""

    # ensure that only one platform is configured for this device
    platform = platform_configs[0].platform
    for platform_config in platform_configs:
        if platform_config.platform != platform:
            LOGGER.warning(
                "Cannot import EnOcean device '%s' because it has different platforms"
            )
            return None

    if platform == Platform.BINARY_SENSOR.value:
        return _get_binary_sensor_import_config(
            device_id=dev_id_string, configs=platform_configs
        )

    if platform == Platform.LIGHT.value:
        return _get_light_import_config(
            device_id=dev_id_string, configs=platform_configs
        )

    if platform == Platform.SWITCH.value:
        return _get_switch_import_config(
            device_id=dev_id_string,
            configs=platform_configs,
        )

    if platform == Platform.SENSOR.value:
        return _get_sensor_import_config(
            device_id=dev_id_string,
            configs=platform_configs,
        )

    return None


def _get_binary_sensor_import_config(
    device_id: str, configs: list[EnOceanPlatformConfig]
) -> EnOceanImportConfig:
    """Return an import config for a binary sensor."""
    device_id_as_list = from_hex_string(device_id)
    config = configs[0].config

    device_name = config.get(CONF_ENOCEAN_DEVICE_NAME, "").strip()
    if device_name == "":
        device_name = "Imported EnOcean binary sensor " + device_id

    device_class = config.get("device_class", None)

    if len(configs) > 1:
        LOGGER.warning(
            "Cannot import more than one platform config for 'binary sensor' EnOcean device %s (invalid configuration.yaml). Will use the first platform config with name '%s' and device class '%s'",
            device_id,
            device_name,
            device_class,
        )

    new_unique_id = device_id + "-" + Platform.BINARY_SENSOR.value + "-0"

    if device_class is None:
        old_unique_id = str(combine_hex(device_id_as_list)) + "-None"
    else:
        old_unique_id = str(combine_hex(device_id_as_list)) + "-" + device_class

    return EnOceanImportConfig(
        new_unique_ids=[new_unique_id],
        old_unique_ids={new_unique_id: old_unique_id},
        device_type=EEP_F6_02_01,
        device_name=device_name,
        sender_id="",
    )


def _get_light_import_config(
    device_id: str, configs: list[EnOceanPlatformConfig]
) -> EnOceanImportConfig:
    """Return an import config for a light."""
    device_id_as_list = from_hex_string(device_id)
    config = configs[0].config

    device_name = config.get(CONF_ENOCEAN_DEVICE_NAME, "").strip()
    if device_name == "":
        device_name = "Imported EnOcean light " + device_id

    sender_id_as_list = config.get(CONF_ENOCEAN_SENDER_ID, None)

    sender_id: str = ""
    if sender_id_as_list is not None:
        sender_id = to_hex_string(sender_id_as_list).upper()

    if len(configs) > 1:
        LOGGER.warning(
            "Cannot import more than one platform config for 'light' EnOcean device '%s' (invalid configuration.yaml). Will use the first platform config with sender id '%s'",
            device_id,
            sender_id,
        )

    new_unique_id = device_id + "-" + Platform.LIGHT.value + "-0"
    old_unique_id = str(combine_hex(device_id_as_list))

    return EnOceanImportConfig(
        new_unique_ids=[new_unique_id],
        old_unique_ids={new_unique_id: old_unique_id},
        device_type=ELTAKO_FUD61,
        sender_id=sender_id_as_list,
        device_name=device_name,
    )


def _get_switch_import_config(
    device_id: str,
    configs: list[EnOceanPlatformConfig],
) -> EnOceanImportConfig:
    """Return an import config for a switch."""
    device_id_as_list = from_hex_string(device_id)

    # 1 channel device
    device_type = EEP_D2_01_07
    max_channel = 0

    new_unique_ids = []
    old_unique_ids = {}

    device_name = ""

    # iterate configs to determine unique ids and required channels
    for config in configs:
        if device_name == "":
            device_name = config.config.get("name", "")

        channel = config.config.get("channel", 0)
        max_channel = max(max_channel, channel)

        new_unique_id = device_id + "-" + Platform.SWITCH.value + "-" + str(channel)
        new_unique_ids.append(new_unique_id)

        old_unique_id = str(combine_hex(device_id_as_list)) + "-" + str(channel)
        old_unique_ids[new_unique_id] = old_unique_id

    if device_name == "":
        device_name = "Imported EnOcean switch " + device_id

    if max_channel < 2:
        device_type = EEP_D2_01_11
    elif max_channel < 4:
        device_type = EEP_D2_01_13
    elif max_channel < 8:
        device_type = EEP_D2_01_14
    else:
        LOGGER.warning(
            "Import of EnOcean switch '%s' will be incomplete: too many channels (%i). Only 1, 2, 4, or 8 channels are supported; importer will configure 8 channels",
            device_id,
            max_channel + 1,
        )
        device_type = EEP_D2_01_14

    return EnOceanImportConfig(
        new_unique_ids=new_unique_ids,
        old_unique_ids=old_unique_ids,
        device_type=device_type,
        device_name=device_name,
        sender_id="",
    )


def _get_sensor_import_config(
    device_id: str,
    configs: list[EnOceanPlatformConfig],
) -> EnOceanImportConfig | None:
    """Return an import config for a switch."""
    device_id_as_list = from_hex_string(device_id)
    device_id_as_number = combine_hex(device_id_as_list)

    # first config defines device name
    config0 = configs[0]
    device_name = config0.config.get("name", "").strip()
    device_class = config0.config.get("device_class", "")

    if device_name == "":
        device_name = "Imported EnOcean " + device_class + " sensor " + device_id

    new_unique_id = device_id + "-" + device_class
    old_unique_id = str(device_id_as_number) + "-" + device_class

    if device_class == "power":
        if len(configs) > 1:
            LOGGER.warning(
                "EnOcean device %s will be imported as power sensor (EEP A5-12-01); the other configurations will not be imported and must be imported manually",
                device_id,
            )
        return EnOceanImportConfig(
            device_type=EEP_A5_12_01,
            new_unique_ids=[new_unique_id],
            old_unique_ids={new_unique_id: old_unique_id},
            device_name=device_name,
        )

    if device_class == "windowhandle":
        if len(configs) > 1:
            LOGGER.warning(
                "EnOcean device %s will be imported as window handle sensor (EEP F6-10-00); the other configurations will not be imported and must be imported manually",
                device_id,
            )

        return EnOceanImportConfig(
            device_type=EEP_F6_10_00,
            new_unique_ids=[new_unique_id],
            old_unique_ids={new_unique_id: old_unique_id},
            device_name=device_name,
        )

    # only remaining sensor types are temperature sensors and combined temperature/humidity sensors
    humidity_config = None
    temperature_config = None

    if device_class == "humidity":
        humidity_config = config0
        temperature_config = _get_temperature_platform_config(configs)

    if device_class == "temperature":
        # find humidity sensor (if any)
        temperature_config = config0
        humidity_config = _get_humidity_platform_config(configs)

    if temperature_config is not None:
        # get additional config data
        min_temp = temperature_config.config.get("min_temp", 0)
        max_temp = temperature_config.config.get("max_temp", 40)
        range_from = temperature_config.config.get("range_from", 255)
        range_to = temperature_config.config.get("range_to", 0)

        # step 1: check if a humidity sensor is configured
        # then it can be either  A5-04-01/02 Temperature and Humidity sensors
        # or one of the room panels A5-10-10 - A5-10-14 with humidity sensor
        # but since we cannot differentiate A5-04-01/02 and the room operating panels  using the configuration data,
        # we will just configure A5-04-01/02
        if humidity_config is not None:
            device_type = None

            if range_from != 0 or range_to != 250:
                LOGGER.warning(
                    "Cannot import EnOcean device %s temperature/humidity sensor combination: unsupported range %i - %i",
                    device_id,
                    range_from,
                    range_to,
                )
                return None

            if min_temp == 0 and max_temp == 40:
                device_type = EEP_A5_04_01

            if min_temp == -20 and max_temp == 60:
                device_type = EEP_A5_04_02

            if device_type is None:
                LOGGER.warning(
                    "Cannot import EnOcean device %s temperature/humidity sensor combination: unsupported scale %i°C - %i°C",
                    device_id,
                    range_from,
                    range_to,
                )
                return None

            new_unique_id_temperature = device_id + "-temperature"
            new_unique_id_humidity = device_id + "-humidity"

            old_unique_id_temperature = device_id_as_number + "-temperature"
            old_unique_id_humidity = device_id_as_number + "-humidity"

            return EnOceanImportConfig(
                device_type=device_type,
                new_unique_ids=[
                    new_unique_id_temperature,
                    new_unique_id_humidity,
                ],
                old_unique_ids={
                    new_unique_id_temperature: old_unique_id_temperature,
                    new_unique_id_humidity: old_unique_id_humidity,
                },
                device_name=device_name,
            )

        # find correct temperature sensor (still TODO!)
        device_type = None

        # there are two valid ranges:
        # 1: 255-0 (default) -> A5-02 temperature sensors
        # 2: 0-250 (alternative) -> A5-04-01/02 temperature/humidity sensor, or A5-10-10 - A5-10-14 room operating panels (with temperature/humidity) or A5-20-01 (BI-DIR)
        range_variant = 0  # (invalid)
        if range_from == 255 and range_to == 0:
            range_variant = 1
        elif range_from == 0 and range_to == 250:
            range_variant = 2

        if range_variant == 0:  # (invalid)
            LOGGER.warning(
                "Cannot import EnOcean device %s temperature/humidity sensor combination: unsupported range %i - %i",
                device_id,
                range_from,
                range_to,
            )
            return None

        if range_variant == 1:  # (255-0) -> A5-02 temperature sensors
            device_type = _get_a5_02_device_type(min_temp=min_temp, max_temp=max_temp)
            if device_type is None:
                LOGGER.warning(
                    "Cannot import EnOcean device %s temperature/humidity sensor combination: unsupported scale %i°C - %i°C",
                    device_id,
                    range_from,
                    range_to,
                )
                return None

            return EnOceanImportConfig(
                device_type=device_type,
                new_unique_ids=[new_unique_id],
                old_unique_ids={new_unique_id: old_unique_id},
                device_name=device_name,
            )

        # range_variant ==  (0-250)

        return None
    return None


def _get_temperature_platform_config(configs: list[EnOceanPlatformConfig]):
    for config in configs:
        if config.config.get("device_class", "") == "temperature":
            return config


def _get_humidity_platform_config(configs: list[EnOceanPlatformConfig]):
    for config in configs:
        if config.config.get("device_class", "") == "humidity":
            return config


def _get_a5_02_device_type(
    min_temp: int, max_temp: int
) -> EnOceanSupportedDeviceType | None:
    if (min_temp, max_temp) == (-40, 0):
        return EEP_A5_02_01
    if (min_temp, max_temp) == (-30, 10):
        return EEP_A5_02_02
    if (min_temp, max_temp) == (-20, 20):
        return EEP_A5_02_03
    if (min_temp, max_temp) == (-10, 30):
        return EEP_A5_02_04
    if (min_temp, max_temp) == (0, 40):
        return EEP_A5_02_05
    if (min_temp, max_temp) == (10, 50):
        return EEP_A5_02_06
    if (min_temp, max_temp) == (20, 60):
        return EEP_A5_02_07
    if (min_temp, max_temp) == (30, 70):
        return EEP_A5_02_08
    if (min_temp, max_temp) == (40, 80):
        return EEP_A5_02_09
    if (min_temp, max_temp) == (50, 90):
        return EEP_A5_02_0A
    if (min_temp, max_temp) == (60, 100):
        return EEP_A5_02_0B
    if (min_temp, max_temp) == (-60, 20):
        return EEP_A5_02_10
    if (min_temp, max_temp) == (-50, 30):
        return EEP_A5_02_11
    if (min_temp, max_temp) == (-40, 40):
        return EEP_A5_02_12
    if (min_temp, max_temp) == (-30, 50):
        return EEP_A5_02_13
    if (min_temp, max_temp) == (-20, 60):
        return EEP_A5_02_14
    if (min_temp, max_temp) == (-10, 70):
        return EEP_A5_02_15
    if (min_temp, max_temp) == (0, 80):
        return EEP_A5_02_16
    if (min_temp, max_temp) == (10, 90):
        return EEP_A5_02_17
    if (min_temp, max_temp) == (20, 100):
        return EEP_A5_02_18
    if (min_temp, max_temp) == (30, 110):
        return EEP_A5_02_19
    if (min_temp, max_temp) == (40, 120):
        return EEP_A5_02_1A
    if (min_temp, max_temp) == (50, 130):
        return EEP_A5_02_1B

    return None


@callback
def async_cleanup_device_registry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Remove entries from device registry if device is removed."""

    device_registry = dr.async_get(hass)
    hass_devices = dr.async_entries_for_config_entry(
        registry=device_registry,
        config_entry_id=entry.entry_id,
    )

    device_ids = [
        dev["id"].upper() for dev in entry.options.get(CONF_ENOCEAN_DEVICES, [])
    ]

    for hass_device in hass_devices:
        for item in hass_device.identifiers:
            domain = item[0]
            device_id = (str(item[1]).split("-", maxsplit=1)[0]).upper()
            if DOMAIN == domain and device_id not in device_ids:
                LOGGER.debug(
                    "Removing Home Assistant device %s and associated entities for unconfigured EnOcean device %s",
                    hass_device.id,
                    device_id,
                )
                device_registry.async_update_device(
                    hass_device.id, remove_config_entry_id=entry.entry_id
                )
                break


def forward_entry_setup_to_platforms(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Forward entry setup to all implemented platforms."""
    for platform in PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry=entry, domain=platform)
        )


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload EnOcean config entry."""
    enocean_dongle = hass.data[DATA_ENOCEAN][ENOCEAN_DONGLE]
    enocean_dongle.unload()

    if unload_platforms := await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    ):
        hass.data.pop(DATA_ENOCEAN)

    return unload_platforms
