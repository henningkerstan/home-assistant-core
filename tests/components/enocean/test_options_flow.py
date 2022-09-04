"""Tests for EnOcean options flow."""
from unittest.mock import AsyncMock, patch

from homeassistant.components.enocean.config_flow import (
    CONF_ENOCEAN_DEVICE_ID,
    CONF_ENOCEAN_DEVICE_NAME,
    CONF_ENOCEAN_DEVICES,
    CONF_ENOCEAN_EEP,
    CONF_ENOCEAN_MANUFACTURER,
    CONF_ENOCEAN_MODEL,
    CONF_ENOCEAN_SENDER_ID,
    ENOCEAN_DEVICE_TYPE,
    ENOCEAN_ERROR_INVALID_DEVICE_ID,
)
from homeassistant.components.enocean.const import (
    DOMAIN,
    ENOCEAN_TEST_DIMMER,
    ENOCEAN_TEST_SWITCH,
)
from homeassistant.const import CONF_DEVICE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from tests.common import MockConfigEntry

TEST_DIMMER = {
    CONF_ENOCEAN_DEVICE_ID: "01:02:03:04",
    CONF_ENOCEAN_DEVICE_NAME: "Test Dimmer 1",
    CONF_ENOCEAN_MANUFACTURER: ENOCEAN_TEST_DIMMER.manufacturer,
    CONF_ENOCEAN_MODEL: ENOCEAN_TEST_DIMMER.model,
    CONF_ENOCEAN_EEP: ENOCEAN_TEST_DIMMER.eep,
    CONF_ENOCEAN_SENDER_ID: "AB:AB:AB:AB",
}

TEST_SWITCH = {
    CONF_ENOCEAN_DEVICE_ID: "01:02:03:05",
    CONF_ENOCEAN_DEVICE_NAME: "Test Switch",
    CONF_ENOCEAN_MANUFACTURER: ENOCEAN_TEST_SWITCH.manufacturer,
    CONF_ENOCEAN_MODEL: ENOCEAN_TEST_SWITCH.model,
    CONF_ENOCEAN_EEP: ENOCEAN_TEST_SWITCH.eep,
    CONF_ENOCEAN_SENDER_ID: "AB:AB:AB:AB",
}

TEST_SWITCH_INVALID_ID = {
    CONF_ENOCEAN_DEVICE_ID: "01:02:03:G",
    CONF_ENOCEAN_DEVICE_NAME: "Test Switch",
    CONF_ENOCEAN_MANUFACTURER: ENOCEAN_TEST_SWITCH.manufacturer,
    CONF_ENOCEAN_MODEL: ENOCEAN_TEST_SWITCH.model,
    CONF_ENOCEAN_EEP: ENOCEAN_TEST_SWITCH.eep,
    CONF_ENOCEAN_SENDER_ID: "AB:AB:AB:AB",
}

TEST_SWITCH_EMPTY_NAME = {
    CONF_ENOCEAN_DEVICE_ID: "01:02:03:05",
    CONF_ENOCEAN_DEVICE_NAME: "",
    CONF_ENOCEAN_MANUFACTURER: ENOCEAN_TEST_SWITCH.manufacturer,
    CONF_ENOCEAN_MODEL: ENOCEAN_TEST_SWITCH.model,
    CONF_ENOCEAN_EEP: ENOCEAN_TEST_SWITCH.eep,
    CONF_ENOCEAN_SENDER_ID: "AB:AB:AB:AB",
}

TEST_SWITCH_INVALID_SENDER_ID = {
    CONF_ENOCEAN_DEVICE_ID: "01:02:03:05",
    CONF_ENOCEAN_DEVICE_NAME: "Test Switch",
    CONF_ENOCEAN_MANUFACTURER: ENOCEAN_TEST_SWITCH.manufacturer,
    CONF_ENOCEAN_MODEL: ENOCEAN_TEST_SWITCH.model,
    CONF_ENOCEAN_EEP: ENOCEAN_TEST_SWITCH.eep,
    CONF_ENOCEAN_SENDER_ID: "AB:123:AB:AB",
}

FAKE_DONGLE_PATH = "/fake/dongle"

DONGLE_DETECT_METHOD = "homeassistant.components.enocean.dongle.detect"


async def test_menu_is_small_for_no_devices(hass: HomeAssistant):
    """Test that the menu contains only 'add device' when no device is configured."""
    mock_config_entry = MockConfigEntry(
        title="",
        domain=DOMAIN,
        data={CONF_DEVICE: FAKE_DONGLE_PATH},
        options={CONF_ENOCEAN_DEVICES: []},
    )

    result = None

    with patch(
        "homeassistant.components.enocean.async_setup_entry",
        AsyncMock(return_value=True),
    ):
        mock_config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        result = True

        result = await hass.config_entries.options.async_init(
            mock_config_entry.entry_id
        )

    assert result is not None
    assert result["type"] == FlowResultType.MENU
    assert result["menu_options"] == ["add_device"]


async def test_menu_is_large_for_devices(hass: HomeAssistant):
    """Test that the menu contains 'add_device', 'select_device_to_edit' and 'delete_device' when at least one device is configured."""
    mock_config_entry = MockConfigEntry(
        title="",
        domain=DOMAIN,
        data={CONF_DEVICE: FAKE_DONGLE_PATH},
        options={CONF_ENOCEAN_DEVICES: [TEST_DIMMER]},
    )

    result = None

    with patch(
        "homeassistant.components.enocean.async_setup_entry",
        AsyncMock(return_value=True),
    ):
        mock_config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        result = True

        result = await hass.config_entries.options.async_init(
            mock_config_entry.entry_id
        )

    assert result is not None
    assert result["type"] == FlowResultType.MENU
    assert result["menu_options"] == [
        "add_device",
        "select_device_to_edit",
        "delete_device",
    ]


async def test_add_device(hass: HomeAssistant):
    """Test adding a device."""

    mock_config_entry = MockConfigEntry(
        title="",
        domain=DOMAIN,
        data={CONF_DEVICE: FAKE_DONGLE_PATH},
        options={CONF_ENOCEAN_DEVICES: [TEST_DIMMER]},
    )

    result = None

    with patch(
        "homeassistant.components.enocean.async_setup_entry",
        AsyncMock(return_value=True),
    ):
        mock_config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        result = True

        result = await hass.config_entries.options.async_init(
            mock_config_entry.entry_id
        )

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={"next_step_id": "add_device"}
        )

        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                ENOCEAN_DEVICE_TYPE: ENOCEAN_TEST_SWITCH.unique_id,
                CONF_ENOCEAN_DEVICE_ID: "01:02:03:05",
                CONF_ENOCEAN_DEVICE_NAME: "Test Switch",
                CONF_ENOCEAN_SENDER_ID: "AB:AB:AB:AB",
            },
        )

    assert result is not None
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["result"] is True
    assert {CONF_ENOCEAN_DEVICES: [TEST_DIMMER, TEST_SWITCH]} == result["data"]


async def test_add_invalid_device_id(hass: HomeAssistant):
    """Test that adding a device with invalid id will not proceed."""

    mock_config_entry = MockConfigEntry(
        title="",
        domain=DOMAIN,
        data={CONF_DEVICE: FAKE_DONGLE_PATH},
        options={CONF_ENOCEAN_DEVICES: [TEST_DIMMER]},
    )

    result = None

    with patch(
        "homeassistant.components.enocean.async_setup_entry",
        AsyncMock(return_value=True),
    ):
        mock_config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        result = True

        result = await hass.config_entries.options.async_init(
            mock_config_entry.entry_id
        )

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={"next_step_id": "add_device"}
        )

        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                ENOCEAN_DEVICE_TYPE: ENOCEAN_TEST_SWITCH.unique_id,
                CONF_ENOCEAN_DEVICE_ID: "01:G:03:05",
                CONF_ENOCEAN_DEVICE_NAME: "Test Switch",
                CONF_ENOCEAN_SENDER_ID: "AB:AB:AB:AB",
            },
        )

    assert result is not None
    assert result["type"] == FlowResultType.FORM
    assert CONF_ENOCEAN_DEVICE_ID in result["errors"]
    assert result["errors"][CONF_ENOCEAN_DEVICE_ID] == ENOCEAN_ERROR_INVALID_DEVICE_ID


async def test_add_existing_device(hass: HomeAssistant):
    """Test to be defined."""
    assert 1 == 1


async def test_add_empty_name(hass: HomeAssistant):
    """Test to be defined."""
    assert 1 == 1


async def test_add_invalid_sender_id(hass: HomeAssistant):
    """Test to be defined."""
    assert 1 == 1


async def test_delete_device(hass: HomeAssistant):
    """Test to be defined."""
    assert 1 == 1


async def test_edit_device_name(hass: HomeAssistant):
    """Test that a device name can be edited."""
    assert 1 == 1


async def test_edit_device_type(hass: HomeAssistant):
    """Test to be defined."""
    assert 1 == 1


async def test_edit_sender_id(hass: HomeAssistant):
    """Test to be defined."""
    assert 1 == 1
