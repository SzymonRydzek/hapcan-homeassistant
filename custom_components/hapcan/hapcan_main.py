"""
Module with base hapcan implementation.
"""
from ast import Constant
import socket
import asyncio
import logging
from tabnanny import check
from types import coroutine
from aiohttp import ClientSession

_LOGGER = logging.getLogger(__name__)

HAPCAN_FRAME_LEN = 15

HAPCAN_RELAY_FRAME_ID = "3020"
HAPCAN_RELAY_FRAME_RESP_ID = "3021"

HAPCAN_BUTTON_FRAME_ID = "3010"


class HAPCanRequest:
    """
    The class represents HAPCan request message. It constructs message,
    adds Start, checksum and stop fields. Also it sets the message type id.
    """

    STATUS_REQUEST = "StatusRequest"
    CONTROL_REQUEST = "ControlRequest"

    frame_type: Constant = "StatusRequest"

    # This field has ANY value
    transmitter_id = [0x12, 0x23]
    frame: list = [0xAA]
    frame_type_def: dict = {
        STATUS_REQUEST: [0x10, 0x90],
        CONTROL_REQUEST: [0x10, 0xA0],
    }

    def __init__(self, frame_type, payload) -> None:
        self.frame = [0xAA]
        self.frame_type = frame_type
        self.payload = payload

        self.frame.extend(self.frame_type_def[frame_type])
        self.frame.extend(self.transmitter_id)
        self.frame.extend(payload)

        chksum: int = 0
        for byte in self.frame[1:]:
            chksum += byte
        chksum &= 0xFF

        self.frame.append(chksum)
        self.frame.append(0xA5)  # appending STOP byte.

        _LOGGER.debug("[{}]".format(", ".join(hex(x) for x in self.frame)))

    def get_frame(self) -> list:
        return self.frame


class HAPCanResponse:
    """
    The class represent message received from HAPCan. It iterprets the content.
    """

    id: str = ""

    def __init__(self, message: list) -> None:
        self.message = message
        # Sanity check
        if len(self.message) < HAPCAN_FRAME_LEN:
            # Message too short, drop.
            _LOGGER.debug(
                "Message too short, expected: %d, got:%d",
                HAPCAN_FRAME_LEN,
                len(self.message),
            )
            return
        if self.message[0] != 0xAA and self.message[-1] != 0xA5:
            # Inconsistent message, drop.
            _LOGGER.debug(
                "Start and Stop bytes does not match, start: 0x%x, stop 0x%x"
                % (self.message[0], self.message[-1])
            )
            return
        # Calculate checksum
        chksum: int = 0
        for byte in self.message[1:-2]:
            chksum += byte
        chksum &= 0xFF
        if chksum != self.message[-2]:
            # Wrong checksum, drop
            _LOGGER.debug(
                "Checksum does not match, expected: 0x%x, calculated: 0x%x"
                % (self.message[-2], chksum)
            )
            return
        self.id = "%X%X" % (message[1], message[2])

    def get_id(self):
        return self.id


class HAPCanConnection:
    """
    HAPCan connection class
    """

    _relay_changed_callback = None
    _reconnection_timeout = 10
    closed = False
    connected = False
    loop = None
    reader = None
    writer = None
    HAPCanHandlers: dict = {}

    def __init__(self, session: ClientSession, host, port, loop) -> None:
        self.session = session
        self.host = host
        self.port = port
        self.loop = loop

        self.HAPCanHandlers = {
            HAPCAN_RELAY_FRAME_ID: self.relay_changed,
            HAPCAN_RELAY_FRAME_RESP_ID: self.relay_changed,
            HAPCAN_BUTTON_FRAME_ID: self.button_changed,
        }

    async def open(self):
        # self.hapcan_socket.connect((self.host, self.port))
        try:
            self.reader, self.writer = await asyncio.open_connection(
                self.host, self.port
            )
            self.connected = True
        except Exception as e:
            _LOGGER.error(
                "Unable establish connection to {} {} {}".format(self.host, self.port, e)
            )

    def close(self):
        _LOGGER.debug("Closing...")
        self.closed = True
        self.writer.close()
        self.connected = False

    async def send(self, payload: list):
        self.writer.write(bytes(payload))
        await self.writer.drain()

    async def _update_status(self):
        """Receive message and interpret it's content"""
        try:
            response = await self.reader.readexactly(HAPCAN_FRAME_LEN)
            _LOGGER.debug(
                "Frame received [{}]".format(", ".join(hex(x) for x in response))
            )
        except asyncio.IncompleteReadError:
            # incomplete frame, ignore
            _LOGGER.debug(
                "Incomplete frame received [{}]".format(
                    ", ".join(hex(x) for x in response)
                )
            )
            return
        hapcan_response = HAPCanResponse(response)

        if hapcan_response.get_id() in self.HAPCanHandlers:
            self.HAPCanHandlers[hapcan_response.get_id()](response)

    def relay_changed(self, frame):
        _LOGGER.debug("Relay state change handler")
        message = {
            "Node": frame[3],
            "Group": frame[4],
            "Channel": frame[7],
            "Status": frame[8],
            "Instr1": frame[10],
            "Instr2": frame[11],
            "Timer": frame[12],
        }
        if self._relay_changed_callback:
            _LOGGER.debug("Relay callback.")
            self._relay_changed_callback(message)

    def button_changed(self, frame):
        _LOGGER.debug("Button state change handler")
        pass

    async def monitor_status(
        self,
        relay_changed_callback=None,
    ):
        _LOGGER.debug("Setting callback to %s" % str(relay_changed_callback))
        self._relay_changed_callback = relay_changed_callback

        _LOGGER.info("Starting monitor_status loop")

        while not self.closed:
            _LOGGER.debug("Iteration... ")
            while not self.connected:
                _LOGGER.info("Not connected, re-connecting... ")
                await self.open()
                if not self.connected:
                    _LOGGER.warning("Not connected, sleeping for 10s... ")
                    await asyncio.sleep(self._reconnection_timeout)
                    continue
            # await self.start_monitoring()
            if not self.connected:
                _LOGGER.warning("Start monitoring failed, sleeping for 10s...")
                await asyncio.sleep(self._reconnection_timeout)
                continue
            while True:
                await self._update_status()
                _LOGGER.debug("Got status!")
                if not self.connected:
                    _LOGGER.info("Got connection broken, reconnecting!")
                    break
        _LOGGER.info("Closed, quit monitoring.")


class HAPCanBase:
    key: Constant = "0"
    _name: Constant = ""
    address: int = 0
    group: int = 0
    channel: int = 0
    connection: HAPCanConnection = None

    def __init__(
        self, key, name, address, group, channel, connection: HAPCanConnection
    ) -> None:
        #_LOGGER.setLevel(logging.DEBUG)
        _LOGGER.debug(
            "HAPCanBase instance created: key %s, name %s, addresss %s, group %s, channel %s",
            str(key),
            str(name),
            str(address),
            str(group),
            str(channel),
        )
        self.key = key
        self._name = name
        self.address = address
        self.group = group
        self.channel = channel
        self.connection = connection

    def _init(self):
        pass
    
    @property
    def name(self):
        return "{}".format(self._name)
    
    @name.setter
    def name(self, value: str) -> None:
        """Set Group name."""
        _LOGGER.debug("Setting the name to: %s", str(value))
        self._name = value

    async def _send_control_request(self, instruction) -> None:
        request = HAPCanRequest(HAPCanRequest.CONTROL_REQUEST, instruction)
        await self.connection.send(request.get_frame())
        del request

    async def _send_status_request(self, instruction) -> None:
        request = HAPCanRequest(HAPCanRequest.STATUS_REQUEST, instruction)
        await self.connection.send(request.get_frame())
        del request


class HAPCanEntity(HAPCanBase):
    @property
    def should_poll(self):
        return False

    # @property
    # def unique_id(self):
    #     return self.deviceid

    # @property
    # def name(self):
    #     return self._name

    # @property
    # def extra_state_attributes(self):
    #     return self._attrs

    # @property
    # def available(self):
    #     device: dict = self.registry.devices[self.deviceid]
    #     return device["available"]

    async def async_added_to_hass(self):
        _LOGGER.debug("HAPCanEntity added to hass")
        self._init()
