#!/usr/bin/env python

"""Unit tests run as PYTHONPATH=../../.. python3 ./test_chewie.py."""

from queue import Queue
import random
import time
import unittest
from unittest.mock import patch

import eventlet
from chewie.eap_state_machine import FullEAPStateMachine
from chewie.mac_address import MacAddress
from netils import build_byte_string

from tests.unit.faucet.test_valve import ValveTestBases


DOT1X_DP1_CONFIG = """
        dp_id: 1
        dot1x:
            nfv_intf: lo
            nfv_sw_port: 2
            radius_ip: 127.0.0.1
            radius_port: 1812
            radius_secret: SECRET"""


DOT1X_CONFIG = """
dps:
    s1:
        hardware: 'GenericTFM'
%s
        interfaces:
            p1:
                number: 1
                native_vlan: v100
                dot1x: True
            p2:
                number: 2
                native_vlan: v100
            p3:
                number: 3
                native_vlan: v100
vlans:
    v100:
        vid: 0x100
""" % DOT1X_DP1_CONFIG


FROM_SUPPLICANT = Queue()
TO_SUPPLICANT = Queue()
FROM_RADIUS = Queue()
TO_RADIUS = Queue()


def patch_things(func):
    """decorator to mock patch socket operations and random number generators"""

    @patch('faucet.faucet_dot1x.chewie.GreenPool.waitall', wait_all)
    @patch('faucet.faucet_dot1x.chewie.os.urandom', urandom_helper)
    @patch('faucet.faucet_dot1x.chewie.FullEAPStateMachine.nextId', nextId)
    @patch('faucet.faucet_dot1x.chewie.Chewie.get_next_radius_packet_id', get_next_radius_packet_id)
    @patch('faucet.faucet_dot1x.chewie.Chewie.radius_send', radius_send)
    @patch('faucet.faucet_dot1x.chewie.Chewie.radius_receive', radius_receive)
    @patch('faucet.faucet_dot1x.chewie.Chewie.eap_send', eap_send)
    @patch('faucet.faucet_dot1x.chewie.Chewie.eap_receive', eap_receive)
    @patch('faucet.faucet_dot1x.chewie.Chewie.open_socket', do_nothing)
    @patch('faucet.faucet_dot1x.chewie.Chewie.get_interface_info', do_nothing)
    @patch('faucet.faucet_dot1x.chewie.Chewie.join_multicast_group', do_nothing)
    def wrapper_patch(self):
        func(self)

    return wrapper_patch


def setup_generators(_supplicant_replies=None, _radius_replies=None):
    """decorator to setup the packets for the mocked socket (queues) to send"""
    def decorator_setup_gen(func):
        def wrapper_setup_gen(self):
            global SUPPLICANT_REPLY_GENERATOR  # pylint: disable=global-statement
            global RADIUS_REPLY_GENERATOR  # pylint: disable=global-statement
            global URANDOM_GENERATOR  # pylint: disable=global-statement

            SUPPLICANT_REPLY_GENERATOR = supplicant_replies_gen(_supplicant_replies)
            RADIUS_REPLY_GENERATOR = radius_replies_gen(_radius_replies)
            URANDOM_GENERATOR = urandom()
            func(self)
        return wrapper_setup_gen
    return decorator_setup_gen


def supplicant_replies_gen(replies):
    """generator for packets supplicant sends"""
    for reply in replies:
        yield reply


def radius_replies_gen(replies):
    """generator for packets radius sends"""
    for reply in replies:
        yield reply


def urandom():
    """generator for urandom"""
    _list = [b'\x87\xf5[\xa71\xeeOA;}\\t\xde\xd7.=',
             b'\xf7\xe0\xaf\xc7Q!\xa2\xa9\xa3\x8d\xf7\xc6\x85\xa8k\x06']
    for random_bytes in _list:
        yield random_bytes


URANDOM_GENERATOR = None  # urandom()


def urandom_helper(size):  # pylint: disable=unused-argument
    """helper for urandom_generator"""
    return next(URANDOM_GENERATOR)


SUPPLICANT_REPLY_GENERATOR = None  # supplicant_replies()
RADIUS_REPLY_GENERATOR = None  # radius_replies()


def eap_receive(chewie):  # pylint: disable=unused-argument
    """mocked chewie.eap_receive"""
    print('mocked eap_receive')
    got = FROM_SUPPLICANT.get()
    return got


def eap_send(chewie, data=None):  # pylint: disable=unused-argument
    """mocked chewie.eap_send"""
    print('mocked eap_send')
    if data:
        TO_SUPPLICANT.put(data)
    try:
        next_reply = next(SUPPLICANT_REPLY_GENERATOR)
    except StopIteration:
        return
    if next_reply:
        FROM_SUPPLICANT.put(next_reply)


def radius_receive(chewie):  # pylint: disable=unused-argument
    """mocked chewie.radius_receive"""
    print('mocked radius_receive')
    got = FROM_RADIUS.get()
    print('got RADIUS', got)
    return got


def radius_send(chewie, data):  # pylint: disable=unused-argument
    """mocked chewie.radius_send"""
    print('mocked radius_send')
    TO_RADIUS.put(data)
    try:
        next_reply = next(RADIUS_REPLY_GENERATOR)
    except StopIteration:
        return
    if next_reply:
        FROM_RADIUS.put(next_reply)


def do_nothing(chewie):  # pylint: disable=unused-argument
    """Mock function that does nothing.
     Typically used on socket opening/configuration operations"""
    pass


def nextId(eap_sm):  # pylint: disable=invalid-name
    """mocked FullEAPStateMachine.nextId"""
    if eap_sm.currentId is None:
        return 116
    _id = eap_sm.currentId + 1
    if _id > 255:
        return random.randint(0, 200)
    return _id


def get_next_radius_packet_id(chewie):
    """mocked Chewie.get_next_radius_packet_id"""
    if chewie.radius_id == -1:
        chewie.radius_id = 4
        return chewie.radius_id
    chewie.radius_id += 1
    if chewie.radius_id > 255:
        chewie.radius_id = 0
    return chewie.radius_id


def wait_all(greenpool):  # pylint: disable=unused-argument
    """mocked Chewie.pool.waitall()"""
    eventlet.sleep(10)


def auth_handler(client_mac, port_id_mac):  # pylint: disable=unused-argument
    """dummy handler for successful authentications"""
    print('Successful auth from MAC %s on port: %s' % (str(client_mac), str(port_id_mac)))


def failure_handler(client_mac, port_id_mac):  # pylint: disable=unused-argument
    """dummy handler for failed authentications"""
    print('failure from MAC %s on port: %s' % (str(client_mac), str(port_id_mac)))


def logoff_handler(client_mac, port_id_mac):  # pylint: disable=unused-argument
    """dummy handler for logoffs"""
    print('logoff from MAC %s on port: %s' % (str(client_mac), str(port_id_mac)))


class FaucetDot1XTest(ValveTestBases.ValveTestSmall):
    """Test chewie api"""

    no_radius_replies = []

    header = "0000000000010242ac17006f888e"
    sup_replies_success = [build_byte_string(header + "01000009027400090175736572"),
                           build_byte_string(
                               header + "010000160275001604103abcadc86714b2d75d09dd7ff53edf6b")]

    radius_replies_success = [build_byte_string(
        "0b040050e5e40d846576a2310755e906c4b2b5064f180175001604101a16a3baa37a0238f33384f6c11067425012ce61ba97026b7a05b194a930a922405218126aa866456add628e3a55a4737872cad6"),
                              build_byte_string(
                                  "02050032fb4c4926caa21a02f74501a65c96f9c74f06037500045012c060ca6a19c47d0998c7b20fd4d771c1010675736572")]

    sup_replies_logoff = [build_byte_string(header + "01000009027400090175736572"),
                          build_byte_string(
                              header + "010000160275001604103abcadc86714b2d75d09dd7ff53edf6b"),
                          build_byte_string("0000000000010242ac17006f888e01020000")]

    # packet id (0x84 is incorrect)
    sup_replies_failure_message_id = [build_byte_string(header + "01000009028400090175736572"),
                                      build_byte_string(header + "01000009029400090175736572"),
                                      build_byte_string(header + "01000009026400090175736572"),
                                      build_byte_string(header + "01000009025400090175736572")]

    # the first response has correct code, second is wrong and will be dropped by radius
    sup_replies_failure2_response_code = [build_byte_string(header + "01000009027400090175736572"),
                                          build_byte_string(header + "01000009037400090175736572")]

    def setUp(self):
        self.setup_valve(DOT1X_CONFIG)
        self.chewie = self.valve.dot1x.dot1x_speaker

        global FROM_SUPPLICANT  # pylint: disable=global-statement
        global TO_SUPPLICANT  # pylint: disable=global-statement
        global FROM_RADIUS  # pylint: disable=global-statement
        global TO_RADIUS  # pylint: disable=global-statement

        FROM_SUPPLICANT = Queue()
        TO_SUPPLICANT = Queue()
        FROM_RADIUS = Queue()
        TO_RADIUS = Queue()

    @patch_things
    @setup_generators(sup_replies_success, radius_replies_success)
    def test_success_dot1x(self):
        """Test success api"""

        FROM_SUPPLICANT.put(build_byte_string("0000000000010242ac17006f888e01010000"))
        time.sleep(1)

        self.assertEqual(
            self.chewie.get_state_machine('02:42:ac:17:00:6f',
                                          '00:00:00:00:00:01').currentState,
            FullEAPStateMachine.SUCCESS2)

    def test_port_status_changes(self):
        """test port status api"""
        # TODO what can actually be checked here?
        # the state machine tests already check the statemachine
        # could check that the preemptive identity request packet is sent. (once implemented)
        # for now just check api works under python version.

        self.chewie.port_down("00:00:00:00:00:01")

        self.chewie.port_up("00:00:00:00:00:01")

        self.chewie.port_down("00:00:00:00:00:01")

    @patch_things
    @setup_generators(sup_replies_logoff, radius_replies_success)
    def test_logoff_dot1x(self):
        """Test logoff"""

        self.chewie.get_state_machine(MacAddress.from_string('02:42:ac:17:00:6f'),
                                      MacAddress.from_string('00:00:00:00:00:01'))
        FROM_SUPPLICANT.put(build_byte_string("0000000000010242ac17006f888e01010000"))
        time.sleep(1)

        self.assertEqual(
            self.chewie.get_state_machine('02:42:ac:17:00:6f',
                                          '00:00:00:00:00:01').currentState,
            FullEAPStateMachine.LOGOFF2)

    @patch_things
    @setup_generators(sup_replies_failure_message_id, no_radius_replies)
    def test_failure_message_id_dot1x(self):
        """Test incorrect message id results in timeout_failure"""
        # TODO not convinced this is transitioning through the correct states.
        # (should be discarding all packets)
        # But end result is correct (both packets sent/received, and end state)

        self.chewie.get_state_machine(MacAddress.from_string('02:42:ac:17:00:6f'),
                                      MacAddress.from_string(
                                          '00:00:00:00:00:01')).DEFAULT_TIMEOUT = 0.5

        FROM_SUPPLICANT.put(build_byte_string("0000000000010242ac17006f888e01010000"))
        time.sleep(4)

        self.assertEqual(
            self.chewie.get_state_machine('02:42:ac:17:00:6f',
                                          '00:00:00:00:00:01').currentState,
            FullEAPStateMachine.TIMEOUT_FAILURE)


    @patch_things
    @setup_generators(sup_replies_failure2_response_code, no_radius_replies)
    def test_failure2_resp_code_dot1x(self):
        """Test incorrect eap.code results in timeout_failure2. RADIUS Server drops it.
        It is up to the supplicant to send another request - this supplicant doesnt"""

        self.chewie.get_state_machine(MacAddress.from_string('02:42:ac:17:00:6f'),
                                      MacAddress.from_string(
                                          '00:00:00:00:00:01')).DEFAULT_TIMEOUT = 0.5

        FROM_SUPPLICANT.put(build_byte_string("0000000000010242ac17006f888e01010000"))
        time.sleep(2)

        self.assertEqual(
            self.chewie.get_state_machine('02:42:ac:17:00:6f',
                                          '00:00:00:00:00:01').currentState,
            FullEAPStateMachine.TIMEOUT_FAILURE2)


if __name__ == "__main__":
    unittest.main()  # pytype: disable=module-attr
