# Copyright 2014 Cloudbase Solutions Srl
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import binascii
import mock
import netifaces
import struct
import socket
import unittest

from cloudbaseinit.utils import dhcp
from oslo.config import cfg

CONF = cfg.CONF


class DHCPUtilsTests(unittest.TestCase):

    def test_get_dhcp_request_data(self):

        fake_mac_address = '010203040506'
        fake_mac_address_a = fake_mac_address.encode('ascii', 'strict')
        fake_mac_address_b = bytearray(binascii.unhexlify(fake_mac_address_a))

        data = b'\x01'
        data += b'\x01'
        data += b'\x06'
        data += b'\x00'
        data += struct.pack('!L', 9999)
        data += b'\x00\x00'
        data += b'\x00\x00'
        data += b'\x00\x00\x00\x00'
        data += b'\x00\x00\x00\x00'
        data += b'\x00\x00\x00\x00'
        data += b'\x00\x00\x00\x00'
        data += fake_mac_address_b
        data += b'\x00' * 10
        data += b'\x00' * 64
        data += b'\x00' * 128
        data += dhcp._DHCP_COOKIE
        data += b'\x35\x01\x01'
        data += b'\x3c' + struct.pack('b',
                                      len('fake id')) + 'fake id'.encode(
                                          'ascii')
        data += b'\x3d\x07\x01'
        data += fake_mac_address_b
        data += b'\x37' + struct.pack('b', len([100]))
        data += struct.pack('b', 100)
        data += dhcp._OPTION_END

        response = dhcp._get_dhcp_request_data(
            id_req=9999, mac_address=fake_mac_address,
            requested_options=[100], vendor_id='fake id')
        self.assertEqual(response, data)

    @mock.patch('struct.unpack')
    def _test_parse_dhcp_reply(self, mock_unpack, message_type,
                               id_reply, equals_cookie):
        fake_data = 236 * b"1"
        if equals_cookie:
            fake_data += dhcp._DHCP_COOKIE + b'11'
        else:
            fake_data += b'111111'
        fake_data += b'fake'
        fake_data += dhcp._OPTION_END

        mock_unpack.side_effect = [(message_type, None), (id_reply, None),
                                   (100, None), (4, None)]

        response = dhcp._parse_dhcp_reply(data=fake_data, id_req=9999)

        if message_type != 2:
            self.assertEqual(response, (False, {}))
        elif id_reply != 9999:
            self.assertEqual(response, (False, {}))
        elif fake_data[236:240] != dhcp._DHCP_COOKIE:
            self.assertEqual(response, (False, {}))
        else:
            self.assertEqual(response, (True, {100: b'fake'}))

    def test_parse_dhcp_reply(self):
        self._test_parse_dhcp_reply(message_type=2, id_reply=9999,
                                    equals_cookie=True)

    def test_parse_dhcp_reply_other_message_type(self):
        self._test_parse_dhcp_reply(message_type=3, id_reply=9999,
                                    equals_cookie=True)

    def test_parse_dhcp_reply_other_reply(self):
        self._test_parse_dhcp_reply(message_type=3, id_reply=111,
                                    equals_cookie=True)

    def test_parse_dhcp_reply_other_than_cookie(self):
        self._test_parse_dhcp_reply(message_type=3, id_reply=111,
                                    equals_cookie=False)

    @mock.patch('netifaces.ifaddresses')
    @mock.patch('netifaces.interfaces')
    def test_get_mac_address_by_local_ip(self, mock_interfaces,
                                         mock_ifaddresses):
        fake_addresses = {}
        fake_addresses[netifaces.AF_INET] = [{'addr': 'fake address'}]
        fake_addresses[netifaces.AF_LINK] = [{'addr': 'fake mac'}]

        mock_interfaces.return_value = ['fake interface']
        mock_ifaddresses.return_value = fake_addresses

        response = dhcp._get_mac_address_by_local_ip('fake address')

        mock_interfaces.assert_called_once_with()
        mock_ifaddresses.assert_called_once_with('fake interface')
        self.assertEqual(response,
                         fake_addresses[netifaces.AF_LINK][0]['addr'])

    @mock.patch('random.randint')
    @mock.patch('socket.socket')
    @mock.patch('cloudbaseinit.utils.dhcp._get_mac_address_by_local_ip')
    @mock.patch('cloudbaseinit.utils.dhcp._get_dhcp_request_data')
    @mock.patch('cloudbaseinit.utils.dhcp._parse_dhcp_reply')
    def test_get_dhcp_options(self, mock_parse_dhcp_reply,
                              mock_get_dhcp_request_data,
                              mock_get_mac_address_by_local_ip, mock_socket,
                              mock_randint):
        mock_randint.return_value = 'fake int'
        mock_socket().getsockname.return_value = ['fake local ip']
        mock_get_mac_address_by_local_ip.return_value = 'fake mac'
        mock_get_dhcp_request_data.return_value = 'fake data'
        mock_parse_dhcp_reply.return_value = (True, 'fake replied options')

        response = dhcp.get_dhcp_options(
            dhcp_host='fake host', requested_options=['fake option'])

        mock_randint.assert_called_once_with(0, 2 ** 32 - 1)
        mock_socket.assert_called_with(socket.AF_INET, socket.SOCK_DGRAM)
        mock_socket().bind.assert_called_once_with(('', 68))
        mock_socket().settimeout.assert_called_once_with(5)
        mock_socket().connect.assert_called_once_with(('fake host', 67))
        mock_socket().getsockname.assert_called_once_with()
        mock_get_mac_address_by_local_ip.assert_called_once_with(
            'fake local ip')
        mock_get_dhcp_request_data.assert_called_once_with('fake int',
                                                           'fake mac',
                                                           ['fake option'],
                                                           'cloudbase-init')
        mock_socket().send.assert_called_once_with('fake data')
        mock_socket().recv.assert_called_once_with(1024)
        mock_parse_dhcp_reply.assert_called_once_with(mock_socket().recv(),
                                                      'fake int')
        mock_socket().close.assert_called_once_with()
        self.assertEqual(response, 'fake replied options')
