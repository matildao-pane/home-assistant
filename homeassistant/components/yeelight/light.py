"""Light platform support for yeelight."""
import logging

import voluptuous as vol
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.service import extract_entity_ids
from homeassistant.util.color import (
    color_temperature_mired_to_kelvin as mired_to_kelvin,
    color_temperature_kelvin_to_mired as kelvin_to_mired)
from homeassistant.const import CONF_HOST, ATTR_ENTITY_ID
from homeassistant.core import callback
from homeassistant.components.light import (
    ATTR_BRIGHTNESS, ATTR_HS_COLOR, ATTR_TRANSITION, ATTR_COLOR_TEMP,
    ATTR_FLASH, FLASH_SHORT, FLASH_LONG, ATTR_EFFECT, SUPPORT_BRIGHTNESS,
    SUPPORT_COLOR, SUPPORT_TRANSITION, SUPPORT_COLOR_TEMP, SUPPORT_FLASH,
    SUPPORT_EFFECT, Light)
import homeassistant.util.color as color_util
from homeassistant.components.yeelight import (
    CONF_TRANSITION, DATA_YEELIGHT, CONF_MODE_MUSIC,
    CONF_SAVE_ON_CHANGE, CONF_CUSTOM_EFFECTS, DATA_UPDATED,
    YEELIGHT_SERVICE_SCHEMA, DOMAIN, ATTR_TRANSITIONS,
    YEELIGHT_FLOW_TRANSITION_SCHEMA, _transitions_config_parser,
    ACTION_RECOVER)

DEPENDENCIES = ['yeelight']

_LOGGER = logging.getLogger(__name__)

SUPPORT_YEELIGHT = (SUPPORT_BRIGHTNESS |
                    SUPPORT_TRANSITION |
                    SUPPORT_FLASH)

SUPPORT_YEELIGHT_WHITE_TEMP = (SUPPORT_YEELIGHT |
                               SUPPORT_COLOR_TEMP)

SUPPORT_YEELIGHT_RGB = (SUPPORT_YEELIGHT |
                        SUPPORT_COLOR |
                        SUPPORT_EFFECT |
                        SUPPORT_COLOR_TEMP)

ATTR_MODE = 'mode'

SERVICE_SET_MODE = 'set_mode'
SERVICE_START_FLOW = 'start_flow'

EFFECT_DISCO = "Disco"
EFFECT_TEMP = "Slow Temp"
EFFECT_STROBE = "Strobe epilepsy!"
EFFECT_STROBE_COLOR = "Strobe color"
EFFECT_ALARM = "Alarm"
EFFECT_POLICE = "Police"
EFFECT_POLICE2 = "Police2"
EFFECT_CHRISTMAS = "Christmas"
EFFECT_RGB = "RGB"
EFFECT_RANDOM_LOOP = "Random Loop"
EFFECT_FAST_RANDOM_LOOP = "Fast Random Loop"
EFFECT_LSD = "LSD"
EFFECT_SLOWDOWN = "Slowdown"
EFFECT_WHATSAPP = "WhatsApp"
EFFECT_FACEBOOK = "Facebook"
EFFECT_TWITTER = "Twitter"
EFFECT_STOP = "Stop"

YEELIGHT_EFFECT_LIST = [
    EFFECT_DISCO,
    EFFECT_TEMP,
    EFFECT_STROBE,
    EFFECT_STROBE_COLOR,
    EFFECT_ALARM,
    EFFECT_POLICE,
    EFFECT_POLICE2,
    EFFECT_CHRISTMAS,
    EFFECT_RGB,
    EFFECT_RANDOM_LOOP,
    EFFECT_FAST_RANDOM_LOOP,
    EFFECT_LSD,
    EFFECT_SLOWDOWN,
    EFFECT_WHATSAPP,
    EFFECT_FACEBOOK,
    EFFECT_TWITTER,
    EFFECT_STOP]


def _cmd(func):
    """Define a wrapper to catch exceptions from the bulb."""
    def _wrap(self, *args, **kwargs):
        import yeelight
        try:
            _LOGGER.debug("Calling %s with %s %s", func, args, kwargs)
            return func(self, *args, **kwargs)
        except yeelight.BulbException as ex:
            _LOGGER.error("Error when calling %s: %s", func, ex)

    return _wrap


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the Yeelight bulbs."""
    from yeelight.enums import PowerMode

    data_key = '{}_lights'.format(DATA_YEELIGHT)

    if not discovery_info:
        return

    if data_key not in hass.data:
        hass.data[data_key] = []

    device = hass.data[DATA_YEELIGHT][discovery_info[CONF_HOST]]
    _LOGGER.debug("Adding %s", device.name)

    custom_effects = discovery_info[CONF_CUSTOM_EFFECTS]
    light = YeelightLight(device, custom_effects=custom_effects)

    hass.data[data_key].append(light)
    add_entities([light], True)

    def service_handler(service):
        """Dispatch service calls to target entities."""
        params = {key: value for key, value in service.data.items()
                  if key != ATTR_ENTITY_ID}

        entity_ids = extract_entity_ids(hass, service)
        target_devices = [light for light in hass.data[data_key]
                          if light.entity_id in entity_ids]

        for target_device in target_devices:
            if service.service == SERVICE_SET_MODE:
                target_device.set_mode(**params)
            elif service.service == SERVICE_START_FLOW:
                params[ATTR_TRANSITIONS] = \
                    _transitions_config_parser(params[ATTR_TRANSITIONS])
                target_device.start_flow(**params)

    service_schema_set_mode = YEELIGHT_SERVICE_SCHEMA.extend({
        vol.Required(ATTR_MODE):
            vol.In([mode.name.lower() for mode in PowerMode])
    })
    hass.services.register(
        DOMAIN, SERVICE_SET_MODE, service_handler,
        schema=service_schema_set_mode)

    service_schema_start_flow = YEELIGHT_SERVICE_SCHEMA.extend(
        YEELIGHT_FLOW_TRANSITION_SCHEMA
    )
    hass.services.register(
        DOMAIN, SERVICE_START_FLOW, service_handler,
        schema=service_schema_start_flow)


class YeelightLight(Light):
    """Representation of a Yeelight light."""

    def __init__(self, device, custom_effects=None):
        """Initialize the Yeelight light."""
        self.config = device.config
        self._device = device

        self._supported_features = SUPPORT_YEELIGHT
        self._available = False

        self._brightness = None
        self._color_temp = None
        self._is_on = None
        self._hs = None

        self._min_mireds = None
        self._max_mireds = None

        if custom_effects:
            self._custom_effects = custom_effects
        else:
            self._custom_effects = {}

    @callback
    def _schedule_immediate_update(self, ipaddr):
        if ipaddr == self.device.ipaddr:
            self.async_schedule_update_ha_state(True)

    async def async_added_to_hass(self):
        """Handle entity which will be added."""
        async_dispatcher_connect(
            self.hass, DATA_UPDATED, self._schedule_immediate_update
        )

    @property
    def should_poll(self):
        """No polling needed."""
        return False

    @property
    def available(self) -> bool:
        """Return if bulb is available."""
        return self._available

    @property
    def supported_features(self) -> int:
        """Flag supported features."""
        return self._supported_features

    @property
    def effect_list(self):
        """Return the list of supported effects."""
        return YEELIGHT_EFFECT_LIST + self.custom_effects_names

    @property
    def color_temp(self) -> int:
        """Return the color temperature."""
        return self._color_temp

    @property
    def name(self) -> str:
        """Return the name of the device if any."""
        return self.device.name

    @property
    def is_on(self) -> bool:
        """Return true if device is on."""
        return self._is_on

    @property
    def brightness(self) -> int:
        """Return the brightness of this light between 1..255."""
        return self._brightness

    @property
    def min_mireds(self):
        """Return minimum supported color temperature."""
        return self._min_mireds

    @property
    def max_mireds(self):
        """Return maximum supported color temperature."""
        return self._max_mireds

    @property
    def custom_effects(self):
        """Return dict with custom effects."""
        return self._custom_effects

    @property
    def custom_effects_names(self):
        """Return list with custom effects names."""
        return list(self.custom_effects.keys())

    def _get_hs_from_properties(self):
        rgb = self._properties.get('rgb', None)
        color_mode = self._properties.get('color_mode', None)
        if not rgb or not color_mode:
            return None

        color_mode = int(color_mode)
        if color_mode == 2:  # color temperature
            temp_in_k = mired_to_kelvin(self._color_temp)
            return color_util.color_temperature_to_hs(temp_in_k)
        if color_mode == 3:  # hsv
            hue = int(self._properties.get('hue'))
            sat = int(self._properties.get('sat'))
            return (hue / 360 * 65536, sat / 100 * 255)

        rgb = int(rgb)
        blue = rgb & 0xff
        green = (rgb >> 8) & 0xff
        red = (rgb >> 16) & 0xff

        return color_util.color_RGB_to_hs(red, green, blue)

    @property
    def hs_color(self) -> tuple:
        """Return the color property."""
        return self._hs

    @property
    def _properties(self) -> dict:
        if self._bulb is None:
            return {}
        return self._bulb.last_properties

    @property
    def device(self):
        """Return yeelight device."""
        return self._device

    # F821: https://github.com/PyCQA/pyflakes/issues/373
    @property
    def _bulb(self) -> 'yeelight.Bulb':  # noqa: F821
        bulb = self.device.bulb

        if bulb:
            self._available = True
            return bulb

        self._available = False
        return None

    def set_music_mode(self, mode) -> None:
        """Set the music mode on or off."""
        if mode:
            self._bulb.start_music()
        else:
            self._bulb.stop_music()

    def update(self) -> None:
        """Update properties from the bulb."""
        import yeelight
        try:
            if self._bulb.bulb_type == yeelight.BulbType.Color:
                self._supported_features = SUPPORT_YEELIGHT_RGB
            elif self._bulb.bulb_type == yeelight.BulbType.WhiteTemp:
                if self._device.is_nightlight_enabled:
                    self._supported_features = SUPPORT_YEELIGHT
                else:
                    self._supported_features = SUPPORT_YEELIGHT_WHITE_TEMP

            if self._min_mireds is None:
                model_specs = self._bulb.get_model_specs()
                self._min_mireds = \
                    kelvin_to_mired(model_specs['color_temp']['max'])
                self._max_mireds = \
                    kelvin_to_mired(model_specs['color_temp']['min'])

            self._is_on = self._properties.get('power') == 'on'

            if self._device.is_nightlight_enabled:
                bright = self._properties.get('nl_br', None)
            else:
                bright = self._properties.get('bright', None)

            if bright:
                self._brightness = round(255 * (int(bright) / 100))

            temp_in_k = self._properties.get('ct', None)
            if temp_in_k:
                self._color_temp = kelvin_to_mired(int(temp_in_k))

            self._hs = self._get_hs_from_properties()

            self._available = True
        except yeelight.BulbException as ex:
            if self._available:  # just inform once
                _LOGGER.error("Unable to update bulb status: %s", ex)
            self._available = False

    @_cmd
    def set_brightness(self, brightness, duration) -> None:
        """Set bulb brightness."""
        if brightness:
            _LOGGER.debug("Setting brightness: %s", brightness)
            self._bulb.set_brightness(brightness / 255 * 100,
                                      duration=duration)

    @_cmd
    def set_rgb(self, rgb, duration) -> None:
        """Set bulb's color."""
        if rgb and self.supported_features & SUPPORT_COLOR:
            _LOGGER.debug("Setting RGB: %s", rgb)
            self._bulb.set_rgb(rgb[0], rgb[1], rgb[2], duration=duration)

    @_cmd
    def set_colortemp(self, colortemp, duration) -> None:
        """Set bulb's color temperature."""
        if colortemp and self.supported_features & SUPPORT_COLOR_TEMP:
            temp_in_k = mired_to_kelvin(colortemp)
            _LOGGER.debug("Setting color temp: %s K", temp_in_k)

            self._bulb.set_color_temp(temp_in_k, duration=duration)

    @_cmd
    def set_default(self) -> None:
        """Set current options as default."""
        self._bulb.set_default()

    @_cmd
    def set_flash(self, flash) -> None:
        """Activate flash."""
        if flash:
            from yeelight import (RGBTransition, SleepTransition, Flow,
                                  BulbException)
            if self._bulb.last_properties["color_mode"] != 1:
                _LOGGER.error("Flash supported currently only in RGB mode.")
                return

            transition = int(self.config[CONF_TRANSITION])
            if flash == FLASH_LONG:
                count = 1
                duration = transition * 5
            if flash == FLASH_SHORT:
                count = 1
                duration = transition * 2

            red, green, blue = color_util.color_hs_to_RGB(*self._hs)

            transitions = list()
            transitions.append(
                RGBTransition(255, 0, 0, brightness=10, duration=duration))
            transitions.append(SleepTransition(
                duration=transition))
            transitions.append(
                RGBTransition(red, green, blue, brightness=self.brightness,
                              duration=duration))

            flow = Flow(count=count, transitions=transitions)
            try:
                self._bulb.start_flow(flow)
            except BulbException as ex:
                _LOGGER.error("Unable to set flash: %s", ex)

    @_cmd
    def set_effect(self, effect) -> None:
        """Activate effect."""
        if effect:
            from yeelight import (Flow, BulbException)
            from yeelight.transitions import (disco, temp, strobe, pulse,
                                              strobe_color, alarm, police,
                                              police2, christmas, rgb,
                                              randomloop, lsd, slowdown)
            if effect == EFFECT_STOP:
                self._bulb.stop_flow()
                return

            effects_map = {
                EFFECT_DISCO: disco,
                EFFECT_TEMP: temp,
                EFFECT_STROBE: strobe,
                EFFECT_STROBE_COLOR: strobe_color,
                EFFECT_ALARM: alarm,
                EFFECT_POLICE: police,
                EFFECT_POLICE2: police2,
                EFFECT_CHRISTMAS: christmas,
                EFFECT_RGB: rgb,
                EFFECT_RANDOM_LOOP: randomloop,
                EFFECT_LSD: lsd,
                EFFECT_SLOWDOWN: slowdown,
            }

            if effect in self.custom_effects_names:
                flow = Flow(**self.custom_effects[effect])
            elif effect in effects_map:
                flow = Flow(count=0, transitions=effects_map[effect]())
            elif effect == EFFECT_FAST_RANDOM_LOOP:
                flow = Flow(count=0, transitions=randomloop(duration=250))
            elif effect == EFFECT_WHATSAPP:
                flow = Flow(count=2, transitions=pulse(37, 211, 102))
            elif effect == EFFECT_FACEBOOK:
                flow = Flow(count=2, transitions=pulse(59, 89, 152))
            elif effect == EFFECT_TWITTER:
                flow = Flow(count=2, transitions=pulse(0, 172, 237))

            try:
                self._bulb.start_flow(flow)
            except BulbException as ex:
                _LOGGER.error("Unable to set effect: %s", ex)

    def turn_on(self, **kwargs) -> None:
        """Turn the bulb on."""
        import yeelight
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        colortemp = kwargs.get(ATTR_COLOR_TEMP)
        hs_color = kwargs.get(ATTR_HS_COLOR)
        rgb = color_util.color_hs_to_RGB(*hs_color) if hs_color else None
        flash = kwargs.get(ATTR_FLASH)
        effect = kwargs.get(ATTR_EFFECT)

        duration = int(self.config[CONF_TRANSITION])  # in ms
        if ATTR_TRANSITION in kwargs:  # passed kwarg overrides config
            duration = int(kwargs.get(ATTR_TRANSITION) * 1000)  # kwarg in s

        self.device.turn_on(duration=duration)

        if self.config[CONF_MODE_MUSIC] and not self._bulb.music_mode:
            try:
                self.set_music_mode(self.config[CONF_MODE_MUSIC])
            except yeelight.BulbException as ex:
                _LOGGER.error("Unable to turn on music mode,"
                              "consider disabling it: %s", ex)

        try:
            # values checked for none in methods
            self.set_rgb(rgb, duration)
            self.set_colortemp(colortemp, duration)
            self.set_brightness(brightness, duration)
            self.set_flash(flash)
            self.set_effect(effect)
        except yeelight.BulbException as ex:
            _LOGGER.error("Unable to set bulb properties: %s", ex)
            return

        # save the current state if we had a manual change.
        if self.config[CONF_SAVE_ON_CHANGE] and (brightness
                                                 or colortemp
                                                 or rgb):
            try:
                self.set_default()
            except yeelight.BulbException as ex:
                _LOGGER.error("Unable to set the defaults: %s", ex)
                return
        self.device.update()

    def turn_off(self, **kwargs) -> None:
        """Turn off."""
        duration = int(self.config[CONF_TRANSITION])  # in ms
        if ATTR_TRANSITION in kwargs:  # passed kwarg overrides config
            duration = int(kwargs.get(ATTR_TRANSITION) * 1000)  # kwarg in s

        self.device.turn_off(duration=duration)
        self.device.update()

    def set_mode(self, mode: str):
        """Set a power mode."""
        import yeelight

        try:
            self._bulb.set_power_mode(yeelight.enums.PowerMode[mode.upper()])
            self.device.update()
        except yeelight.BulbException as ex:
            _LOGGER.error("Unable to set the power mode: %s", ex)

    def start_flow(self, transitions, count=0, action=ACTION_RECOVER):
        """Start flow."""
        import yeelight

        try:
            flow = yeelight.Flow(
                count=count,
                action=yeelight.Flow.actions[action],
                transitions=transitions)

            self._bulb.start_flow(flow)
            self.device.update()
        except yeelight.BulbException as ex:
            _LOGGER.error("Unable to set effect: %s", ex)
