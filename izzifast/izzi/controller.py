#!/usr/bin/env python

import binascii
import socket 
import struct
import time
import datetime
import sys
import select
import logging
import threading
import serial
from numpy import median
from numpy import mean
from array import array
from collections import deque
from .const import *
from . import *

_LOGGER = logging.getLogger('izzicontroller')

class IzziBridge(object):
    def connect(self) -> bool:
        """Open connection to the bridge."""
        pass
    def disconnect(self) -> bool:
        """Close connection to the bridge."""
        pass
    def is_connected(self):
        """Returns weather there is an open socket."""
        pass

    def read_message(self, timeout=3) -> b'':
        """Read a message from the connection."""
        pass
        
    def write_message(self, message: b'') -> bool:
        """Write a message to the connection."""
        pass

class IzziSerialBridge(IzziBridge):
    """Implements an interface to send and receive messages from the Bridge."""

    STATUS_MESSAGE_LENGTH = 26

    def __init__(self, usbname: str) -> None:
        self.usbname = usbname

        self._serialport = None
        self.debug = False

    def connect(self) -> bool:
        """Open connection to the bridge."""

        if self._serialport is None:
            self._serialport = serial.Serial(self.usbname, 9600, timeout=0, parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE, bytesize=serial.EIGHTBITS)
            # Clear buffered data
            while True:
                ready = select.select([self._serialport], [], [], 0.1)
                if not ready[0]:
                    break
                self._serialport.read(1024)

        return True

    def disconnect(self) -> bool:
        """Close connection to the bridge."""

        self._serialport.close()
        self._serialport = None

        return True

    def is_connected(self):
        """Returns weather there is an open port."""
        
        return self._serialport is not None

    def read_message(self, timeout=3.0) -> b'':
        """Read a message from the connection."""

        if self._serialport is None:
            raise Exception('Broken pipe')

        message = b''
        remaining = self.STATUS_MESSAGE_LENGTH
        message_valid = False
        while remaining > 0:
            ready = select.select([self._serialport], [], [], timeout)
            if not ready[0]:
                message = None
                break
            if not message_valid:
                data = self._serialport.read(1)
                if struct.unpack_from('>B', data, 0)[0] != IZZI_STATUS_MESSAGE_ID:
                    continue
                message_valid = True
            else:
                data = self._serialport.read(remaining)
            remaining -= len(data)
            message += (data)
        
        # Debug message
        
        if message != None:
            _LOGGER.debug("RX %s", binascii.hexlify(message))
        return message

    def write_message(self, message: b'') -> bool:
        """Send a message."""

        if self._serialport is None:
            raise Exception('Not connected!')

        # Debug message
        #_LOGGER.debug("TX %s", "".join( str(x) for x in message))
        _LOGGER.debug("TX %s", str(binascii.hexlify(message)))
        # Send packet
        try:
            self._serialport.write(message)
        except Exception:
            return False
        return True

class IzziEthBridge(IzziBridge):
    """Implements an interface to send and receive messages from the Bridge."""

    CMD_STATUS_MESSAGE_LENGTH = 21
    MSG_STATUS_MESSAGE_LENGTH = 26

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port

        self._socket = None
        self._dummysocket = None
        self.debug = False

    def connect(self) -> bool:
        """Open connection to the bridge."""

        if self._socket is None:
            tcpsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            tcpsocket.connect((self.host, self.port))
            tcpsocket.setblocking(0)
            self._socket = tcpsocket
            # Clear buffered data
            while True:
                ready = select.select([self._socket], [], [], 0.01)
                if not ready[0]:
                    break
                self._socket.recv(1024)

        return True

    def disconnect(self) -> bool:
        """Close connection to the bridge."""
        if self._socket != None:
            self._socket.close()
        self._socket = None

        return True

    def is_connected(self):
        """Returns weather there is an open socket."""
        
        return self._socket is not None

    def read_message(self, timeout=3.0) -> b'':
        """Read a message from the connection."""

        if self._socket is None:
            raise Exception('Broken pipe')

        message = b''
        remaining = self.CMD_STATUS_MESSAGE_LENGTH
        message_valid = False
        invalid_message = b''
        while remaining > 0:
            # _LOGGER.debug("Read select")
            ready = select.select([self._socket], [], [], timeout)
            if not ready[0]:
                message = None
                # _LOGGER.debug("Select timeout")
                break
            if not message_valid:
                # _LOGGER.debug("Read recv(1)")
                data = self._socket.recv(1)
                is_cmd = struct.unpack_from('>B', data, 0)[0] == IZZI_COMMAND_MESSAGE_ID
                is_msg = struct.unpack_from('>B', data, 0)[0] == IZZI_STATUS_MESSAGE_ID
                # _LOGGER.debug("STRUCT UNPACKED: %s", struct.unpack_from('>B', data, 0))
                if not is_cmd and not is_msg:
                    # _LOGGER.debug("Read invalid msg id")
                    # _LOGGER.debug("invalid Data %s", binascii.hexlify(data))
                    # invalid_message += (data)
                    continue
                message_valid = True
                remaining = self.CMD_STATUS_MESSAGE_LENGTH if is_cmd else self.MSG_STATUS_MESSAGE_LENGTH
            else:
                # _LOGGER.debug("Read recv(%d)", remaining)
                data = self._socket.recv(remaining)
                # _LOGGER.debug("Data %s", binascii.hexlify(data))
            remaining -= len(data)
            message += (data)
        
        # Debug message
        
        # if message != None:
            # _LOGGER.debug("RX %s", binascii.hexlify(message))
        # _LOGGER.debug("INVALID RX %s", binascii.hexlify(invalid_message))
        return message

    def write_message(self, message: b'') -> bool:
        """Send a message."""

        if self._socket is None:
            raise Exception('Not connected!')

        # Debug message
        #_LOGGER.debug("TX %s", "".join( str(x) for x in message))
        #_LOGGER.debug("TX %s", str(binascii.hexlify(message)))
        # Send packet
        try:
            self._socket.sendall(message)
        except Exception:
            return False
        return True

class CfController(object):

    # exp. press = 0,014*(perc*perc)-0,18*perc

    CF_PARAMS_LENGTH = 5
    
    CF_CORRECTION_LENGTH = 5
    
    _module_enabled = False
    _params_supply = deque([], CF_PARAMS_LENGTH)
    _params_extract = deque([], CF_PARAMS_LENGTH)
    
    _corrections_supply = deque([], CF_CORRECTION_LENGTH)
    _corrections_extract = deque([], CF_CORRECTION_LENGTH)

    _params_max = 0.0
    
    _supply_speed = 0.0
    _supply_speed_correction = 0.0
    _supply_base_correction = 0
    _extract_speed = 0.0
    _extract_speed_correction = 0.0
    _extract_base_correction = 0
    
    _supply_exp_param = 0.0
    _extract_exp_param = 0.0
    
    
    def __init__(self):
        self._module_enabled = False
    
    def set_enabled(self, enabled : bool):
        self._module_enabled = enabled
        
    def set_params_max(self, params_max : float):
        self._params_max = params_max
        _LOGGER.debug("CF params max %f", self._params_max)
    
    def set_current_params(self, supply : float, extract : float):
        self._params_supply.append(supply)
        self._params_extract.append(extract)

    def get_supply_speed(self, exp_speed : int) -> int:
        if int(self._supply_speed) != exp_speed :
            self._supply_speed = float(exp_speed)
            supply_norm = self._supply_speed / 100.0
            self._supply_exp_param = max(0.0, self._params_max* (supply_norm*supply_norm*supply_norm) + 40.0 * supply_norm - 6.0)
            self._params_supply.clear()
            #self._supply_base_correction = 0
            self._corrections_supply.clear()
        
            _LOGGER.debug("Expected Supply CF params %f", self._supply_exp_param)
            
        target_val = self._supply_speed
        correction_limit = int(target_val / 4)
        if self._module_enabled :
        
            if len(self._params_supply) >= self.CF_PARAMS_LENGTH-1 :
                
                supply_param_avg = mean(self._params_supply)
        
                paramDiff = supply_param_avg - self._supply_exp_param
                
                # convert difference to percent and change sign
                diffPerc = (paramDiff / self._params_max) * -100.0
                # If speed higher allow bigger differences
                supply_norm = self._supply_speed / 100.0
                diffPerc = diffPerc * (0.4 * (1.0 - (supply_norm*supply_norm*supply_norm)) + 0.6)
                
                if abs(int(diffPerc)) > correction_limit :
                    diffPerc = (abs(diffPerc) / diffPerc) * correction_limit
                    
                self._supply_speed_correction = int(diffPerc)

                #
                self._corrections_supply.append(self._supply_speed_correction)
                if len(self._corrections_supply) >= self.CF_CORRECTION_LENGTH :
                    supply_correction_avg = mean(self._corrections_supply)
                    if abs(supply_correction_avg) > 1 :
                        self._supply_base_correction += abs(supply_correction_avg) / supply_correction_avg
                        if abs(self._supply_base_correction) > correction_limit :
                            self._supply_base_correction = correction_limit * abs(self._supply_base_correction) / self._supply_base_correction
                    self._corrections_supply.clear()
                    
                _LOGGER.debug("CF Supply diff %f, correction %d, avg %f, base %d", paramDiff, self._supply_speed_correction, supply_param_avg, self._supply_base_correction)
                
            target_val += self._supply_speed_correction + self._supply_base_correction
            if target_val > 100 :
                target_val = 100
            elif target_val < self._supply_speed/2 :
                target_val = self._supply_speed/2
        return int(target_val)
    
    def get_extract_speed(self, exp_speed : int) -> int:
        if int(self._extract_speed) != exp_speed :
            self._extract_speed = float(exp_speed)
            extract_norm = self._extract_speed / 100.0
            self._extract_exp_param = max(0.0, self._params_max* (extract_norm*extract_norm*extract_norm) + 40.0 * extract_norm - 6.0)
            self._params_extract.clear()
            #self._extract_base_correction = 0
            self._corrections_extract.clear()
        
            _LOGGER.debug("Expected Extract CF params %f", self._extract_exp_param)
        
        target_val = self._extract_speed
        correction_limit = int(target_val / 4)
        if self._module_enabled :
                
            if len(self._params_extract) >= self.CF_PARAMS_LENGTH-1 :
                
                extract_param_avg = mean(self._params_extract)
                
                paramDiff = extract_param_avg - self._extract_exp_param
                # convert difference to percent and change sign
                diffPerc = (paramDiff / self._params_max) * -100.0
                # If speed higher allow bigger differences
                extract_norm = self._extract_speed / 100.0
                diffPerc = diffPerc * (0.4 * (1.0 - (extract_norm*extract_norm*extract_norm)) + 0.6)
                
                if abs(int(diffPerc)) > correction_limit :
                    diffPerc = (abs(diffPerc) / diffPerc) * correction_limit
                    
                self._extract_speed_correction = int(diffPerc)

                #
                self._corrections_extract.append(self._extract_speed_correction)
                if len(self._corrections_extract) >= self.CF_CORRECTION_LENGTH :
                    extract_correction_avg = mean(self._corrections_extract)
                    if abs(extract_correction_avg) > 1 :
                        self._extract_base_correction += abs(extract_correction_avg) / extract_correction_avg
                        if abs(self._extract_base_correction) > correction_limit :
                            self._extract_base_correction = correction_limit * abs(self._extract_base_correction) / self._extract_base_correction
                    self._corrections_extract.clear()
                    
                _LOGGER.debug("CF Extract diff %f, correction %d avg %f, base %d", paramDiff, self._extract_speed_correction, extract_param_avg, self._extract_base_correction)
                
            target_val += self._extract_speed_correction + self._extract_base_correction
            if target_val > 100 :
                target_val = 100
            elif target_val < self._extract_speed/2 :
                target_val = self._extract_speed/2
        return int(target_val)
    
    def is_enabled(self) -> bool:
        return self._module_enabled
    
    def get_extract_correction(self) -> int:
        return int(self._extract_base_correction)
    
    def get_supply_correction(self) -> int:
        return int(self._supply_base_correction)
        

class IzziController(object):

    
    """Implements the commands to communicate with the IZZI 302 ERV ventilation unit."""
                    # Id of sensor,                      Value,    Index in status message array. Unpack type
    _sensors_data = {
                        IZZY_SENSOR_TEMPERATURE_SUPPLY_ID: [None, IZZI_STATUS_MSG_SUPPLY_AIR_TEMP_INDEX, '>b'],
                        IZZY_SENSOR_TEMPERATURE_EXTRACT_ID: [None, IZZI_STATUS_MSG_EXTRACT_AIR_TEMP_INDEX, '>b'],
                        IZZY_SENSOR_TEMPERATURE_EXHAUST_ID: [None, IZZI_STATUS_MSG_EXHAUST_AIR_TEMP_INDEX, '>b'],
                        IZZY_SENSOR_TEMPERATURE_OUTDOOR_ID: [None, IZZI_STATUS_MSG_OUTDOR_AIR_TEMP_INDEX, '>b'],
                        IZZY_SENSOR_BYPASS_STATE_ID: [None, IZZI_STATUS_MSG_BYPASS_STATE_INDEX, '>B'],
                        IZZI_SENSOR_HIGRO_CO2_STATUS_ID: [None, IZZI_STATUS_MSG_HIGRO_CO2_STATUS_INDEX, '>B'],
                        IZZY_SENSOR_COVER_STATE_ID: [None, IZZI_STATUS_MSG_COVER_STATE_INDEX, '>B'],
                        IZZY_SENSOR_DEFROST_STATE_ID: [None, IZZI_STATUS_MSG_DEFROST_STATE_INDEX, '>B'],
                        IZZY_SENSOR_HUMIDITY_ID: [None, IZZI_STATUS_MSG_HUMIDITY_STATE_INDEX, '>B'],
                        IZZI_SENSOR_PPM_STATE_ID: [None, IZZI_STATUS_MSG_PPM_STATE_INDEX, '>B'],
                        IZZI_SENSOR_CF_EXHAUST_SPEED_STATE_ID: [None, IZZI_STATUS_MSG_CF_EXHAUST_SPEED_STATE_INDEX, '>B'],
                        IZZI_SENSOR_CF_SUPPLY_SPEED_STATE_ID: [None, IZZI_STATUS_MSG_CF_SUPPLY_SPEED_STATE_INDEX, '>B'],
                        IZZI_SENSOR_HIGRO_CO2_STATUS_ID: [None, IZZI_STATUS_MSG_HIGRO_CO2_STATUS_INDEX, '>B'],
                    }

                    # Id of sensor,               Target value,    Index in command array, multiplier
    _cmd_data = {
                    IZZY_SENSOR_FAN_SUPPLY_SPEED_ID: [0, IZZI_CMD_MSG_SUPPLY_FAN_SPEED_INDEX, None],
                    IZZY_SENSOR_FAN_EXTRACT_SPEED_ID: [0, IZZI_CMD_MSG_EXTRACT_FAN_SPEED_INDEX, None],
                    IZZY_SENSOR_UNIT_STATE_ID: [IZZY_CMD_UNIT_STATE_OFF, IZZI_CMD_MSG_UNIT_STATE_INDEX, None],
                    IZZY_SENSOR_BYPASS_TEMP_ID: [22, IZZI_CMD_MSG_BYPASS_TEMP_INDEX, None],
                    IZZY_SENSOR_BYPASS_MODE_ID: [IZZY_CMD_BYPASS_MODE_AUTO, IZZI_CMD_MSG_BYPASS_MODE_INDEX, None],
                    IZZI_SENSOR_CURRENT_VENT_MODE_ID: [IZZI_CMD_NEW_VENT_MODE_SPEED_1, IZZI_CMD_MSG_CURRENT_VENT_MODE_INDEX, None],
                    IZZI_SENSOR_HIGRO_CO2_STATE_ID: [IZZI_STATUS_MSG_HIGRO_CO2_STATE_ON, IZZI_CMD_MSG_HIGRO_CO2_STATE_INDEX, None],
                    IZZI_SENSOR_SUPPLY_STATE_ID: [IZZY_CMD_SUPPLY_STATE_ON, IZZI_CMD_MSG_SUPPLY_STATE_INDEX, None],
                    IZZI_SENSOR_EXTRACT_STATE_ID: [IZZY_CMD_EXTRACT_STATE_ON, IZZI_CMD_MSG_EXTRACT_STATE_INDEX, None],
                }

                    # Id of sensor,           Target Value, Current value    
    _virtual_data = {
                        IZZY_SENSOR_VENT_MODE_ID: [IZZY_SENSOR_VENT_MODE_NONE, None],
                        IZZY_SENSOR_EFFICIENCY_ID: [0, None],
                        IZZY_SENSOR_CF_EXTRACT_CORRECTION_ID: [0, 0],
                        IZZY_SENSOR_CF_SUPPLY_CORRECTION_ID: [0, 0]
                    }

    """Callback function to invoke when sensor updates are received."""
    callback_sensor = None
    
    cf_controller = CfController()
    extract_correction = 0.0
    
    _command_message = array('B', [IZZI_COMMAND_MESSAGE_ID, 0x00, 0x00, 0x00, 0x00, 0x16, 0x05, 0x00, 0x16, IZZY_CMD_BYPASS_MODE_CLOSED, 0x28, 0x28, IZZY_CMD_UNIT_STATE_OFF, 0x00, 0x01, 0x00, 0x01, 0x01, 0x01, 0x00, 0x00])
    #                                                   64    00    00    00    00    16    05    00    16                           00    37    37                       00    18    01    00    01    01    01    00    00


    def __init__(self, bridge: IzziBridge, is_master : bool):

        self._bridge = bridge
        self._stopping = False
        self._connection_thread = None
        self._master_mode = is_master

    def connect(self):
        """Connect to the bridge. Disconnect existing clients if needed by default."""

        _LOGGER.info("IzziController connect")
        try:
            # Start connection thread
            self._connection_thread = threading.Thread(target=self._connection_thread_loop)
            self._connection_thread.start()
        except Exception as exc:
            _LOGGER.error(exc)
            raise Exception('Could start task.')

    def disconnect(self):
        """Disconnect from the bridge."""
    
        _LOGGER.info("IzziController disconnect")
    
        # Set the stopping flag
        self._stopping = True

        # Wait for the background thread to finish
        self._connection_thread.join()
        self._connection_thread = None

    def is_connected(self):
        """Returns whether there is a connection with the bridge."""

        return self._bridge.is_connected()

    def get_master_mode() -> bool:
        return self._master_mode
        
    def force_update(self, sensor_id):
        """Make sure state of sensor will be published."""
        sensor_obj = self._sensors_data.get(sensor_id)
        if sensor_obj != None:
            sensor_obj[0] = None
        sensor_obj = self._cmd_data.get(sensor_id)
        if sensor_obj != None:
            sensor_obj[0] = None
        sensor_obj = self._virtual_data.get(sensor_id)
        if sensor_obj != None:
            sensor_obj[1] = None
    
    def set_bypass_mode(self, mode : int) -> bool:
        if mode < 0 or mode > 2:
            return False
        self._cmd_data[IZZY_SENSOR_BYPASS_MODE_ID][0] = mode
        return True
        
    def get_bypass_mode(self) -> int:
        return self._cmd_data[IZZY_SENSOR_BYPASS_MODE_ID][0];
        
    def set_bypass_temp(self, temp : int) -> bool:
        if temp < 18 or temp > 26:
            return False
        self._cmd_data[IZZY_SENSOR_BYPASS_TEMP_ID][0] = temp
        return True
        
    def set_fan_speed(self, supply : int, extract : int) :
        if (supply < 0 and extract < 0) or supply > 100 or extract > 100:
            return False
        
        self._cmd_data[IZZY_SENSOR_FAN_SUPPLY_SPEED_ID][0] = supply
        self._cmd_data[IZZY_SENSOR_FAN_EXTRACT_SPEED_ID][0] = extract
        
        return True

    def get_supply_speed():
        return self._cmd_data[IZZY_SENSOR_FAN_SUPPLY_SPEED_ID][0]
        
    def get_extract_speed():
        return self._cmd_data[IZZY_SENSOR_FAN_EXTRACT_SPEED_ID][0]
    
    
    def set_vent_mode(self, mode : int) -> bool:
        if mode < IZZY_SENSOR_VENT_MODE_NONE or mode > IZZY_SENSOR_VENT_MODE_COOKER_HOOD:
            return False
        if mode == IZZY_SENSOR_VENT_MODE_NONE:
            self._cmd_data[IZZY_SENSOR_FAN_SUPPLY_SPEED_ID][2] = None
            self._cmd_data[IZZY_SENSOR_FAN_EXTRACT_SPEED_ID][2] = None
        elif mode == IZZY_SENSOR_VENT_MODE_FIREPLACE:
            self._cmd_data[IZZY_SENSOR_FAN_SUPPLY_SPEED_ID][2] = None
            self._cmd_data[IZZY_SENSOR_FAN_EXTRACT_SPEED_ID][2] = 0.8
        elif mode == IZZY_SENSOR_VENT_MODE_OPEN_WINDOW:
            self._cmd_data[IZZY_SENSOR_FAN_SUPPLY_SPEED_ID][2] = 0
            self._cmd_data[IZZY_SENSOR_FAN_EXTRACT_SPEED_ID][2] = None
        elif mode == IZZY_SENSOR_VENT_MODE_COOKER_HOOD:
            self._cmd_data[IZZY_SENSOR_FAN_SUPPLY_SPEED_ID][2] = None
            self._cmd_data[IZZY_SENSOR_FAN_EXTRACT_SPEED_ID][2] = 0.3
        
        self._virtual_data[IZZY_SENSOR_VENT_MODE_ID][0] = mode
        return True

    def set_vent_preset_mode(self, mode : int) -> bool:
        if mode < IZZI_CMD_NEW_VENT_MODE_OFF or mode > IZZI_CMD_NEW_VENT_MODE_AUTO:
            return False
        if mode == IZZI_CMD_NEW_VENT_MODE_OFF:
            self._cmd_data[IZZI_SENSOR_CURRENT_VENT_MODE_ID][0] = mode
        elif mode == IZZI_CMD_NEW_VENT_MODE_SPEED_1:
            self._cmd_data[IZZI_SENSOR_CURRENT_VENT_MODE_ID][0] = mode
        elif mode == IZZI_CMD_NEW_VENT_MODE_SPEED_2:
            self._cmd_data[IZZI_SENSOR_CURRENT_VENT_MODE_ID][0] = mode    
        elif mode == IZZI_CMD_NEW_VENT_MODE_SPEED_3:
            self._cmd_data[IZZI_SENSOR_CURRENT_VENT_MODE_ID][0] = mode
        elif mode == IZZI_CMD_NEW_VENT_MODE_VENT_MAX:
            self._cmd_data[IZZI_SENSOR_CURRENT_VENT_MODE_ID][0] = mode
        elif mode == IZZI_CMD_NEW_VENT_MODE_FIREPLACE:
            self._cmd_data[IZZI_SENSOR_CURRENT_VENT_MODE_ID][0] = mode
        elif mode == IZZI_CMD_NEW_VENT_MODE_AWAY:
            self._cmd_data[IZZI_SENSOR_CURRENT_VENT_MODE_ID][0] = mode
        elif mode == IZZI_CMD_NEW_VENT_MODE_AUTO:
            self._cmd_data[IZZI_SENSOR_CURRENT_VENT_MODE_ID][0] = mode

        self._cmd_data[IZZI_SENSOR_CURRENT_VENT_MODE_ID][0] = mode
        return True

    def set_cf_params_max(self, params_max : float) -> bool:
        self.cf_controller.set_params_max(params_max)
        self.cf_controller.set_enabled(True)
        return True
    
    def set_cf_params(self, supply : float, extract : float) -> bool:
        self.cf_controller.set_current_params(supply, extract)
        return True
        
    def is_cf_enabled(self) -> bool:
        return self.cf_controller.is_enabled()
        
    def set_unit_on(self, on : bool) :
        if on:
            self._cmd_data[IZZY_SENSOR_UNIT_STATE_ID][0] = IZZY_CMD_UNIT_STATE_ON
        else:
            self._cmd_data[IZZY_SENSOR_UNIT_STATE_ID][0] = IZZY_CMD_UNIT_STATE_OFF
        return True
        
    def _connection_thread_loop(self):
        self._stopping = False
        stat_msg_counter = 0
        last_cmd_timestamp = time.time()
            
        while not self._stopping:
        
            # Start connection
            if not self.is_connected():

                try:
                    _LOGGER.info("Trying connect to bridge")
                    # Connect or re-connect
                    if not self._bridge.connect():
                        time.sleep(5)
                        continue
                        
                    _LOGGER.info("Connection established")
                except Exception as exc:
                    _LOGGER.error(exc)
                    time.sleep(5)
                    continue;
            
            try:
                
                _LOGGER.debug("Reading message")
                status_message = self._bridge.read_message()
                if status_message == None:
                    self._bridge.disconnect()
                    _LOGGER.error("Can't read message, disconnecting")
                    continue
                
                command_id = struct.unpack_from('>B', status_message, IZZI_STATUS_MSG_ID_INDEX)[0]
                if (command_id == IZZI_STATUS_MESSAGE_ID):
                    stat_msg_counter += 1
                    _LOGGER.debug("STATUS MSG RX %s", str(binascii.hexlify(status_message)))
                    
                    timediff = time.time() - last_cmd_timestamp
                    last_cmd_timestamp = time.time()
                    
                    #_LOGGER.debug("Since last cmd %f", timediff)
                    
                    for sensor_id in self._sensors_data:
                        sensor_data = self._sensors_data[sensor_id];
                        sensor_current = struct.unpack_from(sensor_data[2], status_message, sensor_data[1])[0] 

                        if sensor_data[0] != sensor_current:
                            sensor_data[0] = sensor_current
                            if self.callback_sensor:
                                self.callback_sensor(sensor_id, sensor_data[0])
                    
                    #Calculate efficiency
                    try:
                        t1 = float(self._sensors_data[IZZY_SENSOR_TEMPERATURE_OUTDOOR_ID][0])
                        t2 = float(self._sensors_data[IZZY_SENSOR_TEMPERATURE_SUPPLY_ID][0])
                        t3 = float(self._sensors_data[IZZY_SENSOR_TEMPERATURE_EXTRACT_ID][0])
                        
                        if t3 != t1:
                            efficiency = ((t2 - t1) / (t3 - t1)) * 100.0
                            self._virtual_data[IZZY_SENSOR_EFFICIENCY_ID][0] = round(efficiency)
                        else:
                            self._virtual_data[IZZY_SENSOR_EFFICIENCY_ID][0] = 100
                                
                    except Exception as exc:
                        self._virtual_data[IZZY_SENSOR_EFFICIENCY_ID][0] = None
                        _LOGGER.error(exc)
                
                elif not self._master_mode and command_id == IZZI_COMMAND_MESSAGE_ID:
                    for sensor_id in self._cmd_data:
                        sensor_data = self._cmd_data[sensor_id]
                        sensor_data[0] = status_message[sensor_data[1]]
                    _LOGGER.debug("CMD RX %s", str(binascii.hexlify(status_message)))
                    
                for sensor_id in self._cmd_data:
                    sensor_data = self._cmd_data[sensor_id]
                    sensor_current = self._command_message[sensor_data[1]]
                    if sensor_data[0] is None:
                        sensor_data[0] = sensor_current
                        if self.callback_sensor:
                            self.callback_sensor(sensor_id, sensor_data[0])
                    
                        # Make sure we use up to date data
                    if sensor_data[2] is not None:
                        exp_sensor_val = int(float(sensor_data[0]) * sensor_data[2])
                    else:
                        exp_sensor_val = sensor_data[0]
                    
                    if self._cmd_data[IZZY_SENSOR_UNIT_STATE_ID][0] == IZZY_CMD_UNIT_STATE_ON and self._sensors_data[IZZY_SENSOR_COVER_STATE_ID][0] == 0:
                        if sensor_id == IZZY_SENSOR_FAN_SUPPLY_SPEED_ID:
                            exp_sensor_val = self.cf_controller.get_supply_speed(exp_sensor_val)
                            if exp_sensor_val < 15:
                                exp_sensor_val = 15
                        elif sensor_id == IZZY_SENSOR_FAN_EXTRACT_SPEED_ID:
                            exp_sensor_val = self.cf_controller.get_extract_speed(exp_sensor_val)
                            if exp_sensor_val < 15:
                                exp_sensor_val = 15
                        
                    if exp_sensor_val != sensor_current:
                        self._command_message[sensor_data[1]] = exp_sensor_val
                        if self.callback_sensor:
                            self.callback_sensor(sensor_id, self._command_message[sensor_data[1]])
                
                if self.cf_controller.is_enabled(): 
                    self._virtual_data[IZZY_SENSOR_CF_EXTRACT_CORRECTION_ID][0] = self.cf_controller.get_extract_correction()
                    self._virtual_data[IZZY_SENSOR_CF_SUPPLY_CORRECTION_ID][0] = self.cf_controller.get_supply_correction()
                    
                for sensor_id in self._virtual_data:
                    sensor_data = self._virtual_data[sensor_id]
                    if sensor_data[1] is None or sensor_data[0] != sensor_data[1]:
                        sensor_data[1] = sensor_data[0]
                        if self.callback_sensor:
                            self.callback_sensor(sensor_id, sensor_data[0])

                if stat_msg_counter >= 2:
                    stat_msg_counter = 0
                    if self._master_mode:
                        _LOGGER.debug("Writting msg %s", str(self._command_message))
                        time.sleep(0.2)
                        self._bridge.write_message(self._command_message)

            except Exception as exc:
                _LOGGER.error(exc)
                continue

        try:
            self._bridge.disconnect()
        except Exception as exc:
            _LOGGER.error(exc)
