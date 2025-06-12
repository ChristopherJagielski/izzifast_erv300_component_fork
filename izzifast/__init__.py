"""Support to control a Zehnder ComfoAir Q350/450/600 ventilation unit."""
import logging

#from pycomfoconnect import Bridge, ComfoConnect
import voluptuous as vol

from homeassistant.const import (
    CONF_TYPE,
    CONF_HOST,
    CONF_NAME,
    CONF_PORT,
    EVENT_HOMEASSISTANT_STOP,
)
from homeassistant.helpers import discovery
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.dispatcher import *
from .izzi.controller import IzziEthBridge, IzziSerialBridge, IzziController
from .izzi.const import IZZY_SENSOR_EXTRACT_CORRECTION_STATE_ID

_LOGGER = logging.getLogger(__name__)

CONF_MODE = "mode"
CONF_CORRECTION = "extract_correction"
CONF_BYPASS_MODE = "bypass_mode"
CONF_BYPASS_TEMP = "bypass_temp"
CONF_CF_PARAMS_MAX = "cf_params_max"

DOMAIN = "izzifast"

SIGNAL_IZZIFAST_UPDATE_RECEIVED = "izzifast_update_received_{}"

DEFAULT_NAME = "iZZi ERV 302"
DEFAULT_PORT = 8234
DEFAULT_CORRECTION = 0.0
DEFAULT_BYPASS_TEMP = 23
DEFAULT_BYPASS_MODE = "auto"
DEFAULT_CF_PARAMS_MAX = 0.0

CONF_TYPE_SERIAL = "serial"
CONF_TYPE_TCP = "tcp"

CONF_MODE_MASTER = "master"
CONF_MODE_SLAVE = "slave"

bypass_mode_list = ["auto", "open", "closed"]
vent_mode_list = ["none", "fireplace", "open windows", "cooker hood"]
vent_preset_mode_list = ["off", "Speed-1", "Speed-2", "Speed-3", "Ventilate", "Fireplace", "Away", "Auto"]

DEVICE = None

SERIAL_SCHEMA = {
    vol.Required(CONF_TYPE): CONF_TYPE_SERIAL,
    vol.Required(CONF_PORT): cv.string,
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_MODE, default=CONF_MODE_MASTER): cv.string,
    vol.Optional(CONF_CORRECTION, default=DEFAULT_CORRECTION): vol.All(vol.Coerce(int), vol.Range(min=-50, max=50)),
    vol.Optional(CONF_BYPASS_MODE, default=DEFAULT_BYPASS_MODE): vol.In(bypass_mode_list),
    vol.Optional(CONF_BYPASS_TEMP, default=DEFAULT_BYPASS_TEMP): vol.All(vol.Coerce(int), vol.Range(min=17, max=24)),
    vol.Optional(CONF_CF_PARAMS_MAX, default=DEFAULT_CF_PARAMS_MAX): vol.All(vol.Coerce(int), vol.Range(min=0, max=500)),
}

ETHERNET_SCHEMA = {
    vol.Required(CONF_TYPE): CONF_TYPE_TCP,
    vol.Required(CONF_HOST): cv.string,
    vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.positive_int,
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_MODE, default=CONF_MODE_MASTER): cv.string,
    vol.Optional(CONF_CORRECTION, default=DEFAULT_CORRECTION): vol.All(vol.Coerce(int), vol.Range(min=-50, max=50)),
    vol.Optional(CONF_BYPASS_MODE, default=DEFAULT_BYPASS_MODE): vol.In(bypass_mode_list),
    vol.Optional(CONF_BYPASS_TEMP, default=DEFAULT_BYPASS_TEMP): vol.All(vol.Coerce(int), vol.Range(min=17, max=24)),
    vol.Optional(CONF_CF_PARAMS_MAX, default=DEFAULT_CF_PARAMS_MAX): vol.All(vol.Coerce(int), vol.Range(min=0, max=500)),
}


CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Any(SERIAL_SCHEMA, ETHERNET_SCHEMA)
}, extra=vol.ALLOW_EXTRA)

ATTR_MODE_NAME = "mode"
ATTR_TEMP_NAME = "temp"
ATTR_CORRECTION_NAME = "value"
BYPASS_DEFAULT_NAME = "auto"
TEMP_DEFAULT_VAL = 23
CORRECTION_DEFAULT_VAL = 0
VENT_DEFAULT_NAME = "none"
VENT_PRESET_DEFAULT_NAME = "Speed-1"

ATTR_SUPPLY_NAME = "supply"
ATTR_EXTRACT_NAME = "extract"

def setup(hass, config):
    """Set up the izzi bridge."""

    conf = config[DOMAIN]
    type = conf[CONF_TYPE]
    name = conf[CONF_NAME]
    mode = conf[CONF_MODE]
    is_master = False
    
    correction = conf[CONF_CORRECTION]
    bypass_temp = conf[CONF_BYPASS_TEMP]
    bypass_mode = conf[CONF_BYPASS_MODE]
    cf_max_params = conf[CONF_CF_PARAMS_MAX]

    if CONF_TYPE_TCP == type:
        _LOGGER.debug("Setting up Ethernet bridge")
        host = conf[CONF_HOST]
        port = conf[CONF_PORT]
        bridge = IzziEthBridge(host, port)
    elif CONF_TYPE_SERIAL == type:
        _LOGGER.debug("Setting up Serial bridge")
        port = conf[CONF_PORT]
        bridge = IzziSerialBridge(port)
    else:
        _LOGGER.error("Wrong bridge type '%s'", type)
        return false
    
    
    if CONF_MODE_MASTER == mode:
        is_master = True
        _LOGGER.debug("Setting up controler as master")
    elif CONF_MODE_SLAVE == mode:
        is_master = False
        _LOGGER.debug("Setting up controler as slave")
    else:
        is_master = True
        _LOGGER.error("Wrong controller mode, defaulting to master")
    
    # Setup Izzi Bridge
    izzibridge = IzzifastBridge(hass, bridge, name, correction, is_master)
    hass.data[DOMAIN] = izzibridge

    izzibridge.set_bypass_temp(bypass_temp);
    izzibridge.set_bypass_mode(bypass_mode_list.index(bypass_mode));
    izzibridge.set_cf_params_max(cf_max_params);
    
    # Start connection with bridge
    izzibridge.connect()

    # Schedule disconnect on shutdown
    def _shutdown(_event):
        izzibridge.disconnect()

    hass.bus.listen_once(EVENT_HOMEASSISTANT_STOP, _shutdown)
    
    def handle_set_bypass_mode(call):
        """Handle the service call."""
        try:
            mode = call.data.get(ATTR_MODE_NAME, BYPASS_DEFAULT_NAME)
            if izzibridge.set_bypass_mode(bypass_mode_list.index(mode)) != True:
                _LOGGER.error("Bypass mode invalid %s", mode)
        except Exception:
            _LOGGER.error("Bypass mode failed %s", mode)
            
    def handle_set_bypass_temp(call):
        """Handle the service call."""
        try:
            temp = call.data.get(ATTR_TEMP_NAME, TEMP_DEFAULT_VAL)
            if izzibridge.set_bypass_temp(int(temp)) != True:
                _LOGGER.error("Bypass temp invalid %d", temp)
        except Exception:
            _LOGGER.error("Bypass temp failed %d", temp)
                
    def handle_set_correction(call):
        """Handle the service call."""
        try:
            value = call.data.get(ATTR_CORRECTION_NAME, CORRECTION_DEFAULT_VAL)
            if izzibridge.set_correction(int(value)) != True:
                _LOGGER.error("Correction invalid %d", value)
        except Exception:
            _LOGGER.error("Correction set failed %d", value)
            
    def handle_set_cf_params(call):
        """Handle the service call."""
        try:
            supply_pd = call.data.get(ATTR_SUPPLY_NAME, 0)
            extract_pd = call.data.get(ATTR_EXTRACT_NAME, 0)
            if izzibridge.set_cf_params(float(supply_pd), float(extract_pd)) != True:
                _LOGGER.error("CF params invalid %f:%f", supply_pd, extract_pd)
        except Exception:
            _LOGGER.error("CF params set failed %s:%s", str(supply_pd), str(extract_pd))
    def handle_set_cf_supply_param(call):
        """Handle the service call."""
        try:
            supply_pd = call.data.get(ATTR_SUPPLY_NAME, 0)
            if izzibridge.set_cf_supply_param(float(supply_pd)) != True:
                _LOGGER.error("CF supply param invalid %f", supply_pd)
        except Exception:
            _LOGGER.error("CF supply param set failed %s", str(supply_pd)) 
            
    def handle_set_cf_extract_param(call):
        """Handle the service call."""
        try:
            extract_pd = call.data.get(ATTR_EXTRACT_NAME, 0)
            if izzibridge.set_cf_extract_param(float(extract_pd)) != True:
                _LOGGER.error("CF extract param invalid %f", extract_pd)
        except Exception:
            _LOGGER.error("CF extract param set failed %s", str(extract_pd))    
            
    def handle_set_vent_mode(call):
        """Handle the service call."""
        try:
            mode = call.data.get(ATTR_MODE_NAME, VENT_DEFAULT_NAME)
            if izzibridge.set_vent_mode(vent_mode_list.index(mode)) != True:
                _LOGGER.error("Vent mode invalid to %s", mode)
        except Exception:
            _LOGGER.error("Vent mode failed %s", mode)

    def handle_set_vent_preset_mode(call):
        """Handle the service call."""
        try:
            mode = call.data.get(ATTR_MODE_NAME, VENT_PRESET_DEFAULT_NAME)
            if izzibridge.set_vent_preset_mode(vent_preset_mode_list.index(mode)) != True:
                _LOGGER.error("Vent mode invalid to %s", mode)
        except Exception:
            _LOGGER.error("Vent mode failed %s", mode)            
    
    def handle_set_speed_raw(call):
        """Handle the service call."""
        try:
            supply = value = call.data.get(ATTR_SUPPLY_NAME, -1)
            extract = call.data.get(ATTR_EXTRACT_NAME, -1)
            if extract < 0 or supply < 0:
                _LOGGER.error("Raw speed missing supply or extract attribute")
                
            if izzibridge.set_fan_speed_raw(int(supply), int(extract)) != True:
                _LOGGER.error("Raw speed invalid supply %d, extract %d", supply, extract)
        except Exception:
            _LOGGER.error("Raw speed set failed %d", value)
            
    if is_master :    
        hass.services.register(DOMAIN, "bypass_mode", handle_set_bypass_mode)
        hass.services.register(DOMAIN, "bypass_temp", handle_set_bypass_temp)
        hass.services.register(DOMAIN, "correction", handle_set_correction)
        hass.services.register(DOMAIN, "vent_custom_mode", handle_set_vent_mode)
        hass.services.register(DOMAIN, "vent_preset_mode", handle_set_vent_preset_mode)
        hass.services.register(DOMAIN, "speed_raw", handle_set_speed_raw)
        hass.services.register(DOMAIN, "cf_params", handle_set_cf_params)
        # Load platforms
        discovery.load_platform(hass, "fan", DOMAIN, {}, config)

    discovery.load_platform(hass, "sensor", DOMAIN, {}, config)
    discovery.load_platform(hass, "binary_sensor", DOMAIN, {}, config)

    return True


class IzzifastBridge:
    """Representation of a IZZI bridge."""

    def __init__(self, hass, bridge, name, correction, is_master):
        """Initialize the IZZI bridge."""
        self.data = {}
        self.name = name
        self.hass = hass
        self.unique_id = "_iZZi_302_ERV_FE"
        self.correction = correction
        self.speed = 0

        self.controller = IzziController(
            bridge=bridge,
            is_master=is_master
        )
        self.controller.callback_sensor = self.sensor_callback
        
        self.sensor_callback(IZZY_SENSOR_EXTRACT_CORRECTION_STATE_ID, self.correction)

    def connect(self):
        """Connect with the bridge."""
        _LOGGER.debug("Connecting with bridge")
        self.controller.connect()

    def disconnect(self):
        """Disconnect from the bridge."""
        _LOGGER.debug("Disconnecting from bridge")
        self.controller.disconnect()
 
    def force_update(self, sensor):
        if sensor == IZZY_SENSOR_EXTRACT_CORRECTION_STATE_ID :
            self.sensor_callback(IZZY_SENSOR_EXTRACT_CORRECTION_STATE_ID, self.correction)
        else:
            self.controller.force_update(sensor)

    def set_bypass_mode(self, mode) -> bool:
        return self.controller.set_bypass_mode(mode)
        
    def set_cf_max_param(self, param_max : float) -> bool:
        return self.controller.set_cf_max_param(param_max)
            
    def set_vent_mode(self, mode) -> bool:
        return self.controller.set_vent_mode(mode)
            
    def set_vent_preset_mode(self, mode) -> bool:
        return self.controller.set_vent_preset_mode(mode)
        
    def set_bypass_temp(self, temp) -> bool:
        return self.controller.set_bypass_temp(temp)
    
    def set_fan_on(self, isOn : bool) -> bool:
        self.controller.set_unit_on(isOn)
        return True
    
    def set_correction(self, correction : int) -> bool:
        if correction < -50 or correction > 50:
            return False
        self.correction = correction
        self.sensor_callback(IZZY_SENSOR_EXTRACT_CORRECTION_STATE_ID, self.correction)
        return self.set_fan_speed(self.speed);
        
    def set_fan_speed(self, speed : int) -> bool:
        if speed < 20 or speed > 100:
            return False
            
        self.speed = speed
        if not self.controller.is_cf_enabled() :
            if self.correction > 0:
                self.controller.set_fan_speed(speed - round(((abs(self.correction)/100.0)*speed)), speed)
            else:
                self.controller.set_fan_speed(speed, speed - round(((abs(self.correction)/100.0)*speed)))
        else:
            self.controller.set_fan_speed(speed, speed)
        return True

    def set_fan_speed_raw(self, supply : int, extract : int) -> bool:
        return self.controller.set_fan_speed(supply, extract)
        
    def set_cf_params(self, supply : float, extract : float) -> bool:
        return self.controller.set_cf_params(supply, extract)

    def set_cf_params_max(self, max_param : float) -> bool:
        return self.controller.set_cf_params_max(max_param)
        
    def sensor_callback(self, var, value):
        """Notify listeners that we have received an update."""
        _LOGGER.debug("Received update for %s: %s", var, value)
        dispatcher_send(
            self.hass, SIGNAL_IZZIFAST_UPDATE_RECEIVED.format(var), value
        )
