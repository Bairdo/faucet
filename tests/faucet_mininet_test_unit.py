#!/usr/bin/env python

"""Mininet tests for FAUCET."""

# pylint: disable=missing-docstring
# pylint: disable=too-many-arguments

import os
import random
import re
import shutil
import signal
import socket
import threading
import time
import unittest

from SimpleHTTPServer import SimpleHTTPRequestHandler
from BaseHTTPServer import HTTPServer

import ipaddress
import scapy.all
import yaml

from mininet.log import error, output
from mininet.net import Mininet


import faucet_mininet_test_base
import faucet_mininet_test_util
import faucet_mininet_test_topo

from datetime import datetime

from mininet.cli import CLI

class QuietHTTPServer(HTTPServer):

    allow_reuse_address = True

    def handle_error(self, _request, _client_address):
        return


class PostHandler(SimpleHTTPRequestHandler):

    def log_message(self, _format, *_args):
        return

    def _log_post(self):
        content_len = int(self.headers.getheader('content-length', 0))
        content = self.rfile.read(content_len).strip()
        if content and hasattr(self.server, 'influx_log'):
            with open(self.server.influx_log, 'a') as influx_log:
                influx_log.write(content + '\n')


class InfluxPostHandler(PostHandler):

    def do_POST(self):
        self._log_post()
        return self.send_response(204)


class SlowInfluxPostHandler(PostHandler):

    def do_POST(self):
        self._log_post()
        time.sleep(self.server.timeout * 3)
        return self.send_response(500)


class FaucetTest(faucet_mininet_test_base.FaucetTestBase):

    pass


@unittest.skip('currently flaky')
class FaucetAPITest(faucet_mininet_test_base.FaucetTestBase):
    """Test the Faucet API."""

    NUM_DPS = 0

    def setUp(self):
        self.tmpdir = self._tmpdir_name()
        name = 'faucet'
        self._set_var_path(name, 'FAUCET_CONFIG', 'config/testconfigv2-simple.yaml')
        self._set_var_path(name, 'FAUCET_LOG', 'faucet.log')
        self._set_var_path(name, 'FAUCET_EXCEPTION_LOG', 'faucet-exception.log')
        self._set_var_path(name, 'API_TEST_RESULT', 'result.txt')
        self.results_file = self.env[name]['API_TEST_RESULT']
        shutil.copytree('config', os.path.join(self.tmpdir, 'config'))
        self.dpid = str(0xcafef00d)
        self._set_prom_port(name)
        self.of_port = faucet_mininet_test_util.find_free_port(
            self.ports_sock, self._test_name())
        self.topo = faucet_mininet_test_topo.FaucetSwitchTopo(
            self.ports_sock,
            dpid=self.dpid,
            n_untagged=7,
            test_name=self._test_name())
        self.net = Mininet(
            self.topo,
            controller=faucet_mininet_test_topo.FaucetAPI(
                name=name,
                tmpdir=self.tmpdir,
                env=self.env[name],
                port=self.of_port))
        self.net.start()
        self.reset_all_ipv4_prefix(prefix=24)
        self.wait_for_tcp_listen(self._get_controller(), self.of_port)

    def test_api(self):
        for _ in range(10):
            try:
                with open(self.results_file, 'r') as results:
                    result = results.read().strip()
                    self.assertEqual('pass', result, result)
                    return
            except IOError:
                time.sleep(1)
        self.fail('no result from API test')


class FaucetUntaggedTest(FaucetTest):
    """Basic untagged VLAN test."""

    N_UNTAGGED = 4
    N_TAGGED = 0
    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
"""

    CONFIG = """
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def setUp(self):
        super(FaucetUntaggedTest, self).setUp()
        self.topo = self.topo_class(
            self.ports_sock, self._test_name(), [self.dpid],
            n_tagged=self.N_TAGGED, n_untagged=self.N_UNTAGGED)
        self.start_net()

    def test_untagged(self):
        """All hosts on the same untagged VLAN should have connectivity."""
        self.ping_all_when_learned()
        self.flap_all_switch_ports()
        self.gauge_smoke_test()
        self.prometheus_smoke_test()


class FaucetUntaggedLogRotateTest(FaucetUntaggedTest):

    def test_untagged(self):
        faucet_log = self.env['faucet']['FAUCET_LOG']
        self.assertTrue(os.path.exists(faucet_log))
        os.rename(faucet_log, faucet_log + '.old')
        self.assertTrue(os.path.exists(faucet_log + '.old'))
        self.flap_all_switch_ports()
        self.assertTrue(os.path.exists(faucet_log))


class FaucetUntaggedMeterParseTest(FaucetUntaggedTest):

    REQUIRES_METERS = True
    CONFIG_GLOBAL = """
meters:
    lossymeter:
        meter_id: 1
        entry:
            flags: "KBPS"
            bands:
                [
                    {
                        type: "DROP",
                        rate: 1000
                    }
                ]
acls:
    lossyacl:
        - rule:
            actions:
                meter: lossymeter
                allow: 1
vlans:
    100:
        description: "untagged"
"""


class FaucetUntaggedApplyMeterTest(FaucetUntaggedMeterParseTest):

    CONFIG = """
        interfaces:
            %(port_1)d:
                acl_in: lossyacl
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""


class FaucetUntaggedHairpinTest(FaucetUntaggedTest):

    CONFIG = """
        interfaces:
            %(port_1)d:
                hairpin: True
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def test_untagged(self):
        # Create macvlan interfaces, with one in a seperate namespace,
        # to force traffic between them to be hairpinned via FAUCET.
        first_host, second_host = self.net.hosts[:2]
        macvlan1_intf = 'macvlan1'
        macvlan1_ipv4 = '10.0.0.100'
        macvlan2_intf = 'macvlan2'
        macvlan2_ipv4 = '10.0.0.101'
        netns = first_host.name
        self.add_macvlan(first_host, macvlan1_intf)
        first_host.cmd('ip address add %s/24 brd + dev %s' % (macvlan1_ipv4, macvlan1_intf))
        self.add_macvlan(first_host, macvlan2_intf)
        macvlan2_mac = self.get_host_intf_mac(first_host, macvlan2_intf)
        first_host.cmd('ip netns add %s' % netns)
        first_host.cmd('ip link set %s netns %s' % (macvlan2_intf, netns))
        for exec_cmd in (
                ('ip address add %s/24 brd + dev %s' % (
                    macvlan2_ipv4, macvlan2_intf),
                 'ip link set %s up' % macvlan2_intf)):
            first_host.cmd('ip netns exec %s %s' % (netns, exec_cmd))
        self.one_ipv4_ping(first_host, macvlan2_ipv4, intf=macvlan1_intf)
        self.one_ipv4_ping(first_host, second_host.IP())
        first_host.cmd('ip netns del %s' % netns)
        # Verify OUTPUT:IN_PORT flood rules are exercised.
        self.wait_nonzero_packet_count_flow(
            {u'in_port': self.port_map['port_1'],
             u'dl_dst': u'ff:ff:ff:ff:ff:ff'},
            table_id=self.FLOOD_TABLE, actions=[u'OUTPUT:IN_PORT'])
        self.wait_nonzero_packet_count_flow(
            {u'in_port': self.port_map['port_1'], u'dl_dst': macvlan2_mac},
            table_id=self.ETH_DST_TABLE, actions=[u'OUTPUT:IN_PORT'])


class FaucetUntaggedGroupHairpinTest(FaucetUntaggedHairpinTest):

    CONFIG = """
        group_table: True
        interfaces:
            %(port_1)d:
                hairpin: True
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
    """


class FaucetUntaggedTcpIPv4IperfTest(FaucetUntaggedTest):

    def test_untagged(self):
        iperf_port = faucet_mininet_test_util.find_free_port(
            self.ports_sock, self._test_name())
        first_host, second_host = self.net.hosts[:2]
        second_host_ip = ipaddress.ip_address(unicode(second_host.IP()))
        for _ in range(3):
            self.ping_all_when_learned()
            self.one_ipv4_ping(first_host, second_host_ip)
            self.verify_iperf_min(
                ((first_host, self.port_map['port_1']),
                 (second_host, self.port_map['port_2'])),
                1, second_host_ip, iperf_port)
            self.flap_all_switch_ports()


class FaucetUntaggedTcpIPv6IperfTest(FaucetUntaggedTest):

    def test_untagged(self):
        iperf_port = faucet_mininet_test_util.find_free_port(
            self.ports_sock, self._test_name())
        first_host, second_host = self.net.hosts[:2]
        first_host_ip = ipaddress.ip_interface(u'fc00::1:1/112')
        second_host_ip = ipaddress.ip_interface(u'fc00::1:2/112')
        self.add_host_ipv6_address(first_host, first_host_ip)
        self.add_host_ipv6_address(second_host, second_host_ip)
        for _ in range(3):
            self.ping_all_when_learned()
            self.one_ipv6_ping(first_host, second_host_ip.ip)
            self.verify_iperf_min(
                ((first_host, self.port_map['port_1']),
                 (second_host, self.port_map['port_2'])),
                1, second_host_ip.ip, iperf_port)
            self.flap_all_switch_ports()


class FaucetSanityTest(FaucetUntaggedTest):
    """Sanity test - make sure test environment is correct before running all tess."""

    def verify_dp_port_healthy(self, dp_port, retries=5, min_mbps=100):
        for _ in range(retries):
            port_desc = self.get_port_desc_from_dpid(self.dpid, dp_port)
            port_name = port_desc['name']
            port_state = port_desc['state']
            port_config = port_desc['config']
            port_speed_mbps = (port_desc['curr_speed'] * 1e3) / 1e6
            error('DP %u is %s, at %u mbps\n' % (dp_port, port_name, port_speed_mbps))
            if port_speed_mbps <= min_mbps:
                error('port speed %u below minimum %u mbps\n' % (
                    port_speed_mbps, min_mbps))
            elif port_config != 0:
                error('port config %u must be 0 (all clear)' % port_config)
            elif not (port_state == 0 or port_state == 4):
                error('state %u must be 0 (all flags clear or live)\n' % (
                    port_state))
            else:
                return
            time.sleep(1)
        self.fail('DP port %u not healthy (%s)' % (dp_port, port_desc))

    def test_portmap(self):
        for i, host in enumerate(self.net.hosts):
            in_port = 'port_%u' % (i + 1)
            dp_port = self.port_map[in_port]
            if in_port in self.switch_map:
                error('verifying cabling for %s: host %s -> dp %u\n' % (
                    in_port, self.switch_map[in_port], dp_port))
            else:
                error('verifying host %s -> dp %s\n' % (
                    in_port, dp_port))
            self.verify_dp_port_healthy(dp_port)
            self.require_host_learned(host, in_port=dp_port)


class FaucetUntaggedPrometheusGaugeTest(FaucetUntaggedTest):
    """Testing Gauge Prometheus"""

    GAUGE_CONFIG_DBS = """
    prometheus:
        type: 'prometheus'
        prometheus_addr: '127.0.0.1'
        prometheus_port: %(gauge_prom_port)d
"""
    config_ports = {'gauge_prom_port': None}

    def get_gauge_watcher_config(self):
        return """
    port_stats:
        dps: ['faucet-1']
        type: 'port_stats'
        interval: 5
        db: 'prometheus'
"""

    def _start_gauge_check(self):
        if not self.gauge_controller.listen_port(self.config_ports['gauge_prom_port']):
            return 'gauge not listening on prometheus port'
        return None

    def test_untagged(self):
        self.wait_dp_status(1, controller='gauge')
        self.assertIsNotNone(self.scrape_prometheus_var(
            'faucet_pbr_version', any_labels=True, controller='gauge', retries=3))
        labels = {'port_name': '1'}
        last_p1_bytes_in = 0
        for _ in range(2):
            updated_counters = False
            for _ in range(self.DB_TIMEOUT * 3):
                self.ping_all_when_learned()
                p1_bytes_in = self.scrape_prometheus_var(
                    'of_port_rx_bytes', labels=labels, controller='gauge', retries=3)
                if p1_bytes_in is not None and p1_bytes_in > last_p1_bytes_in:
                    updated_counters = True
                    last_p1_bytes_in = p1_bytes_in
                    break
                time.sleep(1)
            if not updated_counters:
                self.fail(msg='Gauge Prometheus counters not increasing')


class FaucetUntaggedInfluxTest(FaucetUntaggedTest):
    """Basic untagged VLAN test with Influx."""

    GAUGE_CONFIG_DBS = """
    influx:
        type: 'influx'
        influx_db: 'faucet'
        influx_host: '127.0.0.1'
        influx_port: %(gauge_influx_port)d
        influx_user: 'faucet'
        influx_pwd: ''
        influx_retries: 1
""" + """
        influx_timeout: %u
""" % FaucetUntaggedTest.DB_TIMEOUT
    config_ports = {'gauge_influx_port': None}
    influx_log = None
    server_thread = None
    server = None

    def get_gauge_watcher_config(self):
        return """
    port_stats:
        dps: ['faucet-1']
        type: 'port_stats'
        interval: 2
        db: 'influx'
    port_state:
        dps: ['faucet-1']
        type: 'port_state'
        interval: 2
        db: 'influx'
    flow_table:
        dps: ['faucet-1']
        type: 'flow_table'
        interval: 2
        db: 'influx'
"""

    def setupInflux(self):
        self.influx_log = os.path.join(self.tmpdir, 'influx.log')
        if self.server:
            self.server.influx_log = self.influx_log
            self.server.timeout = self.DB_TIMEOUT

    def setUp(self):
        self.handler = InfluxPostHandler
        super(FaucetUntaggedInfluxTest, self).setUp()
        self.setupInflux()

    def tearDown(self):
        if self.server:
            self.server.shutdown()
            self.server.socket.close()
        super(FaucetUntaggedInfluxTest, self).tearDown()

    def _wait_error_shipping(self, timeout=None):
        if timeout is None:
            timeout = self.DB_TIMEOUT * 3
        gauge_log_name = self.env['gauge']['GAUGE_LOG']
        for _ in range(timeout):
            with open(gauge_log_name) as gauge_log:
                log_content = gauge_log.read()
            if re.search('error shipping', log_content):
                return
            time.sleep(1)
        self.fail('Influx error not noted in %s: %s' % (gauge_log, log_content))

    def _verify_influx_log(self):
        self.assertTrue(os.path.exists(self.influx_log))
        observed_vars = set()
        with open(self.influx_log) as influx_log:
            influx_log_lines = influx_log.readlines()
        for point_line in influx_log_lines:
            point_fields = point_line.strip().split()
            self.assertEqual(3, len(point_fields), msg=point_fields)
            ts_name, value_field, timestamp_str = point_fields
            timestamp = int(timestamp_str)
            value = float(value_field.split('=')[1])
            ts_name_fields = ts_name.split(',')
            self.assertGreater(len(ts_name_fields), 1)
            observed_vars.add(ts_name_fields[0])
            label_values = {}
            for label_value in ts_name_fields[1:]:
                label, value = label_value.split('=')
                label_values[label] = value
            if ts_name.startswith('flow'):
                self.assertTrue('inst_count' in label_values, msg=point_line)
                if 'vlan_vid' in label_values:
                    self.assertEqual(
                        int(label_values['vlan']), int(value) ^ 0x1000)
        self.verify_no_exception(self.env['gauge']['GAUGE_EXCEPTION_LOG'])
        self.assertEqual(set([
            'dropped_in', 'dropped_out', 'bytes_out', 'flow_packet_count',
            'errors_in', 'bytes_in', 'flow_byte_count', 'port_state_reason',
            'packets_in', 'packets_out']), observed_vars)

    def _wait_influx_log(self):
        for _ in range(self.DB_TIMEOUT * 3):
            if os.path.exists(self.influx_log):
                return
            time.sleep(1)
        return

    def _start_gauge_check(self):
        influx_port = self.config_ports['gauge_influx_port']
        try:
            self.server = QuietHTTPServer(
                (faucet_mininet_test_util.LOCALHOST, influx_port), self.handler)
            self.server.timeout = self.DB_TIMEOUT
            self.server_thread = threading.Thread(
                target=self.server.serve_forever)
            self.server_thread.daemon = True
            self.server_thread.start()
            return None
        except socket.error:
            return 'cannot start Influx test server'

    def test_untagged(self):
        self.ping_all_when_learned()
        self.hup_gauge()
        self.flap_all_switch_ports()
        self._wait_influx_log()
        self._verify_influx_log()


class FaucetUntaggedInfluxDownTest(FaucetUntaggedInfluxTest):

    def _start_gauge_check(self):
        return None

    def test_untagged(self):
        self.ping_all_when_learned()
        self._wait_error_shipping()
        self.verify_no_exception(self.env['gauge']['GAUGE_EXCEPTION_LOG'])


class FaucetUntaggedInfluxUnreachableTest(FaucetUntaggedInfluxTest):

    GAUGE_CONFIG_DBS = """
    influx:
        type: 'influx'
        influx_db: 'faucet'
        influx_host: '127.0.0.2'
        influx_port: %(gauge_influx_port)d
        influx_user: 'faucet'
        influx_pwd: ''
        influx_timeout: 2
"""

    def _start_gauge_check(self):
        return None

    def test_untagged(self):
        self.gauge_controller.cmd(
            'route add 127.0.0.2 gw 127.0.0.1 lo')
        self.ping_all_when_learned()
        self._wait_error_shipping()
        self.verify_no_exception(self.env['gauge']['GAUGE_EXCEPTION_LOG'])


class FaucetUntaggedInfluxTooSlowTest(FaucetUntaggedInfluxTest):

    def setUp(self):
        self.handler = SlowInfluxPostHandler
        super(FaucetUntaggedInfluxTest, self).setUp()
        self.setupInflux()

    def test_untagged(self):
        self.ping_all_when_learned()
        self._wait_influx_log()
        self.assertTrue(os.path.exists(self.influx_log))
        self._wait_error_shipping()
        self.verify_no_exception(self.env['gauge']['GAUGE_EXCEPTION_LOG'])


class FaucetNailedForwardingTest(FaucetUntaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
acls:
    1:
        - rule:
            dl_dst: "0e:00:00:00:02:02"
            actions:
                output:
                    port: b2
        - rule:
            dl_type: 0x806
            dl_dst: "ff:ff:ff:ff:ff:ff"
            arp_tpa: "10.0.0.2"
            actions:
                output:
                    port: b2
        - rule:
            actions:
                allow: 0
    2:
        - rule:
            dl_dst: "0e:00:00:00:01:01"
            actions:
                output:
                    port: b1
        - rule:
            dl_type: 0x806
            dl_dst: "ff:ff:ff:ff:ff:ff"
            arp_tpa: "10.0.0.1"
            actions:
                output:
                    port: b1
        - rule:
            actions:
                allow: 0
    3:
        - rule:
            actions:
                allow: 0
    4:
        - rule:
            actions:
                allow: 0
"""

    CONFIG = """
        interfaces:
            b1:
                number: %(port_1)d
                native_vlan: 100
                acl_in: 1
            b2:
                number: %(port_2)d
                native_vlan: 100
                acl_in: 2
            b3:
                number: %(port_3)d
                native_vlan: 100
                acl_in: 3
            b4:
                number: %(port_4)d
                native_vlan: 100
                acl_in: 4
"""

    def test_untagged(self):
        first_host, second_host = self.net.hosts[0:2]
        first_host.setMAC('0e:00:00:00:01:01')
        second_host.setMAC('0e:00:00:00:02:02')
        self.one_ipv4_ping(
            first_host, second_host.IP(), require_host_learned=False)
        self.one_ipv4_ping(
            second_host, first_host.IP(), require_host_learned=False)


class FaucetNailedFailoverForwardingTest(FaucetNailedForwardingTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
acls:
    1:
        - rule:
            dl_dst: "0e:00:00:00:02:02"
            actions:
                output:
                    failover:
                        group_id: 1001
                        ports: [b2, b3]
        - rule:
            dl_type: 0x806
            dl_dst: "ff:ff:ff:ff:ff:ff"
            arp_tpa: "10.0.0.2"
            actions:
                output:
                    failover:
                        group_id: 1002
                        ports: [b2, b3]
        - rule:
            actions:
                allow: 0
    2:
        - rule:
            dl_dst: "0e:00:00:00:01:01"
            actions:
                output:
                    port: b1
        - rule:
            dl_type: 0x806
            dl_dst: "ff:ff:ff:ff:ff:ff"
            arp_tpa: "10.0.0.1"
            actions:
                output:
                    port: b1
        - rule:
            actions:
                allow: 0
    3:
        - rule:
            dl_dst: "0e:00:00:00:01:01"
            actions:
                output:
                    port: b1
        - rule:
            dl_type: 0x806
            dl_dst: "ff:ff:ff:ff:ff:ff"
            arp_tpa: "10.0.0.1"
            actions:
                output:
                    port: b1
        - rule:
            actions:
                allow: 0
    4:
        - rule:
            actions:
                allow: 0
"""

    def test_untagged(self):
        first_host, second_host, third_host = self.net.hosts[0:3]
        first_host.setMAC('0e:00:00:00:01:01')
        second_host.setMAC('0e:00:00:00:02:02')
        third_host.setMAC('0e:00:00:00:02:02')
        third_host.setIP(second_host.IP())
        self.one_ipv4_ping(
            first_host, second_host.IP(), require_host_learned=False)
        self.one_ipv4_ping(
            second_host, first_host.IP(), require_host_learned=False)
        self.set_port_down(self.port_map['port_2'])
        self.one_ipv4_ping(
            first_host, third_host.IP(), require_host_learned=False)
        self.one_ipv4_ping(
            third_host, first_host.IP(), require_host_learned=False)


class FaucetUntaggedLLDPBlockedTest(FaucetUntaggedTest):

    def test_untagged(self):
        self.ping_all_when_learned()
        self.assertTrue(self.verify_lldp_blocked())


class FaucetUntaggedCDPTest(FaucetUntaggedTest):

    def test_untagged(self):
        self.ping_all_when_learned()
        self.assertFalse(self.is_cdp_blocked())


class FaucetUntaggedLLDPUnblockedTest(FaucetUntaggedTest):

    CONFIG = """
        drop_lldp: False
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def test_untagged(self):
        self.ping_all_when_learned()
        self.assertFalse(self.verify_lldp_blocked())


class FaucetZodiacUntaggedTest(FaucetUntaggedTest):
    """Zodiac has only 3 ports available, and one controller so no Gauge."""

    RUN_GAUGE = False
    N_UNTAGGED = 3

    def test_untagged(self):
        """All hosts on the same untagged VLAN should have connectivity."""
        self.ping_all_when_learned()
        self.flap_all_switch_ports()
        self.ping_all_when_learned()


class FaucetTaggedAndUntaggedVlanTest(FaucetTest):
    """Test mixture of tagged and untagged hosts on the same VLAN."""

    N_TAGGED = 1
    N_UNTAGGED = 3

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "mixed"
"""

    CONFIG = """
        interfaces:
            %(port_1)d:
                tagged_vlans: [100]
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def setUp(self):
        super(FaucetTaggedAndUntaggedVlanTest, self).setUp()
        self.topo = self.topo_class(
            self.ports_sock, self._test_name(), [self.dpid],
            n_tagged=1, n_untagged=3)
        self.start_net()

    def test_untagged(self):
        """Test connectivity including after port flapping."""
        self.ping_all_when_learned()
        self.flap_all_switch_ports()
        self.ping_all_when_learned()


class FaucetZodiacTaggedAndUntaggedVlanTest(FaucetUntaggedTest):

    RUN_GAUGE = False
    N_TAGGED = 1
    N_UNTAGGED = 2
    CONFIG_GLOBAL = """
vlans:
    100:
        description: "mixed"
"""

    CONFIG = """
        interfaces:
            %(port_1)d:
                tagged_vlans: [100]
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def test_untagged(self):
        """Test connectivity including after port flapping."""
        self.ping_all_when_learned()
        self.flap_all_switch_ports()
        self.ping_all_when_learned()


class FaucetUntaggedMaxHostsTest(FaucetUntaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
        max_hosts: 2
"""

    CONFIG = """
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""
    def test_untagged(self):
        self.net.pingAll()
        learned_hosts = [
            host for host in self.net.hosts if self.host_learned(host)]
        self.assertEqual(2, len(learned_hosts))
        self.assertEqual(2, self.scrape_prometheus_var(
            'vlan_hosts_learned', {'vlan': '100'}))
        self.assertGreater(
            self.scrape_prometheus_var(
                'vlan_learn_bans', {'vlan': '100'}), 0)


class FaucetMaxHostsPortTest(FaucetUntaggedTest):

    MAX_HOSTS = 3
    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
"""

    CONFIG = """
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
                max_hosts: 3
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def test_untagged(self):
        first_host, second_host = self.net.hosts[:2]
        self.ping_all_when_learned()
        for i in range(10, 10+(self.MAX_HOSTS*2)):
            mac_intf = 'mac%u' % i
            mac_ipv4 = '10.0.0.%u' % i
            self.add_macvlan(second_host, mac_intf)
            second_host.cmd('ip address add %s/24 brd + dev %s' % (
                mac_ipv4, mac_intf))
            second_host.cmd('ping -c1 -I%s %s &' % (mac_intf, first_host.IP()))
        flows = self.get_matching_flows_on_dpid(
            self.dpid,
            {u'dl_vlan': u'100', u'in_port': int(self.port_map['port_2'])},
            table_id=self.ETH_SRC_TABLE)
        self.assertEqual(self.MAX_HOSTS, len(flows))
        self.assertEqual(
            self.MAX_HOSTS,
            len(self.scrape_prometheus_var(
                'learned_macs',
                {'port': self.port_map['port_2'], 'vlan': '100'},
                multiple=True)))
        self.assertGreater(
            self.scrape_prometheus_var(
                'port_learn_bans', {'port': self.port_map['port_2']}), 0)


class FaucetHostsTimeoutPrometheusTest(FaucetUntaggedTest):
    """Test for hosts that have been learnt are exported via prometheus.
       Hosts should timeout, and the exported prometheus values should
       be overwritten.
       If the maximum number of MACs at any one time is 5, then only 5 values
       should be exported, even if over 2 hours, there are 100 MACs learnt
    """
    TIMEOUT = 10
    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
"""

    CONFIG = """
        timeout: 10
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def mac_as_int(self, mac):
        return long(mac.replace(':', ''), 16)

    def macs_learned_on_port(self, port):
        port_learned_macs_prom = self.scrape_prometheus_var(
            'learned_macs', {'port': str(port), 'vlan': '100'},
            default=[], multiple=True)
        macs_learned = []
        for _, mac_int in port_learned_macs_prom:
            if mac_int:
                macs_learned.append(mac_int)
        return macs_learned

    def hosts_learned(self, hosts):
        """Check that hosts are learned by FAUCET on the expected ports."""
        mac_ints_on_port_learned = {}
        for mac, port in hosts.items():
            self.mac_learned(mac)
            if port not in mac_ints_on_port_learned:
                mac_ints_on_port_learned[port] = set()
            macs_learned = self.macs_learned_on_port(port)
            mac_ints_on_port_learned[port].update(macs_learned)
        for mac, port in hosts.items():
            mac_int = self.mac_as_int(mac)
            if not mac_int in mac_ints_on_port_learned[port]:
                return False
        return True

    def verify_hosts_learned(self, first_host, mac_ips, hosts):
        fping_out = None
        for _ in range(3):
            fping_out = first_host.cmd(faucet_mininet_test_util.timeout_cmd(
                'fping -i1 -p1 -c3 %s' % ' '.join(mac_ips), 5))
            if self.hosts_learned(hosts):
                return
            time.sleep(1)
        self.fail('%s cannot be learned (%s)' % (mac_ips, fping_out))

    def test_untagged(self):
        first_host, second_host = self.net.hosts[:2]
        learned_mac_ports = {}
        learned_mac_ports[first_host.MAC()] = self.port_map['port_1']
        mac_intfs = []
        mac_ips = []

        for i in range(10, 16):
            if i == 14:
                self.verify_hosts_learned(first_host, mac_ips, learned_mac_ports)
                learned_mac_ports = {}
                mac_intfs = []
                mac_ips = []
                # wait for first lot to time out.
                time.sleep(self.TIMEOUT * 2)
            mac_intf = 'mac%u' % i
            mac_intfs.append(mac_intf)
            mac_ipv4 = '10.0.0.%u' % i
            mac_ips.append(mac_ipv4)
            self.add_macvlan(second_host, mac_intf)
            second_host.cmd('ip address add %s/24 dev brd + %s' % (
                mac_ipv4, mac_intf))
            address = second_host.cmd(
                '|'.join((
                    'ip link show %s' % mac_intf,
                    'grep -o "..:..:..:..:..:.."',
                    'head -1',
                    'xargs echo -n')))
            learned_mac_ports[address] = self.port_map['port_2']

        learned_mac_ports[first_host.MAC()] = self.port_map['port_1']
        self.verify_hosts_learned(first_host, mac_ips, learned_mac_ports)

        # Verify same or less number of hosts on a port reported by Prometheus
        self.assertTrue((
            len(self.macs_learned_on_port(self.port_map['port_1'])) <=
            len(learned_mac_ports)))


class FaucetLearn50MACsOnPortTest(FaucetUntaggedTest):

    MAX_HOSTS = 50
    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
"""

    CONFIG = """
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def test_untagged(self):
        first_host, second_host = self.net.hosts[:2]
        self.ping_all_when_learned()
        mac_intf_ipv4s = []
        for i in range(10, 10+self.MAX_HOSTS):
            mac_intf_ipv4s.append(('mac%u' % i, '10.0.0.%u' % i))
        # configure macvlan interfaces and stimulate learning
        for mac_intf, mac_ipv4 in mac_intf_ipv4s:
            self.add_macvlan(second_host, mac_intf)
            second_host.cmd('ip address add %s/24 brd + dev %s' % (
                mac_ipv4, mac_intf))
            second_host.cmd('ping -c1 -I%s %s &' % (mac_intf, first_host.IP()))
        # verify connectivity
        for mac_intf, _ in mac_intf_ipv4s:
            self.one_ipv4_ping(
                second_host, first_host.IP(),
                require_host_learned=False, intf=mac_intf)
        # verify FAUCET thinks it learned this many hosts
        self.assertGreater(
            self.scrape_prometheus_var('vlan_hosts_learned', {'vlan': '100'}),
            self.MAX_HOSTS)


class FaucetUntaggedHUPTest(FaucetUntaggedTest):
    """Test handling HUP signal without config change."""

    def _configure_count_with_retry(self, expected_count):
        for _ in range(3):
            configure_count = self.get_configure_count()
            if configure_count == expected_count:
                return
            time.sleep(1)
        self.fail('configure count %u != expected %u' % (
            configure_count, expected_count))

    def test_untagged(self):
        """Test that FAUCET receives HUP signal and keeps switching."""
        init_config_count = self.get_configure_count()
        for i in range(init_config_count, init_config_count+3):
            self._configure_count_with_retry(i)
            self.verify_hup_faucet()
            self._configure_count_with_retry(i+1)
            self.assertEqual(
                self.scrape_prometheus_var('of_dp_disconnections', default=0),
                0)
            self.assertEqual(
                self.scrape_prometheus_var('of_dp_connections', default=0),
                1)
            self.wait_until_controller_flow()
            self.ping_all_when_learned()


class FaucetConfigReloadTest(FaucetTest):
    """Test handling HUP signal with config change."""

    N_UNTAGGED = 4
    N_TAGGED = 0
    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
    200:
        description: "untagged"
"""
    CONFIG = """
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""
    ACL = """
acls:
    1:
        - rule:
            dl_type: 0x800
            nw_proto: 6
            tp_dst: 5001
            actions:
                allow: 0
        - rule:
            dl_type: 0x800
            nw_proto: 6
            tp_dst: 5002
            actions:
                allow: 1
        - rule:
            actions:
                allow: 1
    2:
        - rule:
            dl_type: 0x800
            nw_proto: 6
            tp_dst: 5001
            actions:
                allow: 1
        - rule:
            dl_type: 0x800
            nw_proto: 6
            tp_dst: 5002
            actions:
                allow: 0
        - rule:
            actions:
                allow: 1
"""

    def setUp(self):
        super(FaucetConfigReloadTest, self).setUp()
        self.acl_config_file = '%s/acl.yaml' % self.tmpdir
        with open(self.acl_config_file, 'w') as config_file:
            config_file.write(self.ACL)
        self.CONFIG = '\n'.join(
            (self.CONFIG, 'include:\n     - %s' % self.acl_config_file))
        self.topo = self.topo_class(
            self.ports_sock, self._test_name(), [self.dpid],
            n_tagged=self.N_TAGGED, n_untagged=self.N_UNTAGGED)
        self.start_net()

    def _get_conf(self):
        with open(self.faucet_config_path) as config_file:
            config = yaml.load(config_file.read())
        return config

    def _reload_conf(self, conf, restart, cold_start,
                     change_expected=True, host_cache=None):
        with open(self.faucet_config_path, 'w') as config_file:
            config_file.write(yaml.dump(conf))
        if restart:
            var = 'faucet_config_reload_warm'
            if cold_start:
                var = 'faucet_config_reload_cold'
            old_count = int(
                self.scrape_prometheus_var(var, dpid=True, default=0))
            old_mac_table = self.scrape_prometheus_var(
                'learned_macs', labels={'vlan': host_cache}, multiple=True)
            self.verify_hup_faucet()
            new_count = int(
                self.scrape_prometheus_var(var, dpid=True, default=0))
            new_mac_table = self.scrape_prometheus_var(
                'learned_macs', labels={'vlan': host_cache}, multiple=True)
            if host_cache:
                self.assertFalse(
                    cold_start, msg='host cache is not maintained with cold start')
                self.assertTrue(
                    new_mac_table, msg='no host cache for vlan %u' % host_cache)
                self.assertEqual(
                    old_mac_table, new_mac_table,
                    msg='host cache for vlan %u not same over reload' % host_cache)
            if change_expected:
                self.assertEqual(
                    old_count + 1, new_count,
                    msg='%s did not increment: %u' % (var, new_count))
            else:
                self.assertEqual(
                    old_count, new_count,
                    msg='%s incremented: %u' % (var, new_count))

    def get_port_match_flow(self, port_no, table_id=None):
        if table_id is None:
            table_id = self.ETH_SRC_TABLE
        flow = self.get_matching_flow_on_dpid(
            self.dpid, {u'in_port': int(port_no)}, table_id)
        return flow

    def test_add_unknown_dp(self):
        conf = self._get_conf()
        conf['dps']['unknown'] = {
            'dp_id': int(self.rand_dpid()),
            'hardware': 'Open vSwitch',
        }
        self._reload_conf(
            conf, restart=True, cold_start=False, change_expected=False)

    def change_port_config(self, port, config_name, config_value,
                           restart=True, conf=None, cold_start=False):
        if conf is None:
            conf = self._get_conf()
        conf['dps']['faucet-1']['interfaces'][port][config_name] = config_value
        self._reload_conf(conf, restart, cold_start)

    def change_vlan_config(self, vlan, config_name, config_value,
                           restart=True, conf=None, cold_start=False):
        if conf is None:
            conf = self._get_conf()
        conf['vlans'][vlan][config_name] = config_value
        self._reload_conf(conf, restart, cold_start)

    def test_tabs_are_bad(self):
        self.ping_all_when_learned()
        orig_conf = self._get_conf()
        self.force_faucet_reload('\t'.join(('tabs', 'are', 'bad')))
        self.ping_all_when_learned()
        self._reload_conf(
            orig_conf, restart=True, cold_start=False, change_expected=False)

    def test_port_change_vlan(self):
        first_host, second_host = self.net.hosts[:2]
        third_host, fourth_host = self.net.hosts[2:]
        self.ping_all_when_learned()
        self.change_port_config(
            self.port_map['port_1'], 'native_vlan', 200, restart=False)
        self.change_port_config(
            self.port_map['port_2'], 'native_vlan', 200, restart=True, cold_start=True)
        for port_name in ('port_1', 'port_2'):
            self.wait_until_matching_flow(
                {u'in_port': int(self.port_map[port_name])},
                table_id=self.VLAN_TABLE,
                actions=[u'SET_FIELD: {vlan_vid:4296}'])
        self.one_ipv4_ping(first_host, second_host.IP(), require_host_learned=False)
        # hosts 1 and 2 now in VLAN 200, so they shouldn't see floods for 3 and 4.
        self.verify_vlan_flood_limited(
            third_host, fourth_host, first_host)

    def test_port_change_acl(self):
        self.ping_all_when_learned()
        first_host, second_host = self.net.hosts[0:2]
        orig_conf = self._get_conf()
        self.change_port_config(
            self.port_map['port_1'], 'acl_in', 1, cold_start=False)
        self.wait_until_matching_flow(
            {u'in_port': int(self.port_map['port_1']), u'tp_dst': 5001},
            table_id=self.PORT_ACL_TABLE)
        self.verify_tp_dst_blocked(5001, first_host, second_host)
        self.verify_tp_dst_notblocked(5002, first_host, second_host)
        self._reload_conf(orig_conf, True, cold_start=False, host_cache=100)
        self.verify_tp_dst_notblocked(
            5001, first_host, second_host, table_id=None)
        self.verify_tp_dst_notblocked(
            5002, first_host, second_host, table_id=None)

    def test_port_change_permanent_learn(self):
        first_host, second_host, third_host = self.net.hosts[0:3]
        self.change_port_config(
            self.port_map['port_1'], 'permanent_learn', True, cold_start=False)
        self.ping_all_when_learned()
        original_third_host_mac = third_host.MAC()
        third_host.setMAC(first_host.MAC())
        self.assertEqual(100.0, self.net.ping((second_host, third_host)))
        self.retry_net_ping(hosts=(first_host, second_host))
        third_host.setMAC(original_third_host_mac)
        self.ping_all_when_learned()
        self.change_port_config(
            self.port_map['port_1'], 'acl_in', 1, cold_start=False)
        self.wait_until_matching_flow(
            {u'in_port': int(self.port_map['port_1']), u'tp_dst': 5001},
            table_id=self.PORT_ACL_TABLE)
        self.verify_tp_dst_blocked(5001, first_host, second_host)
        self.verify_tp_dst_notblocked(5002, first_host, second_host)


class FaucetUntaggedBGPIPv4DefaultRouteTest(FaucetUntaggedTest):
    """Test IPv4 routing and import default route from BGP."""

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
        faucet_vips: ["10.0.0.254/24"]
        bgp_port: %(bgp_port)d
        bgp_as: 1
        bgp_routerid: "1.1.1.1"
        bgp_neighbor_addresses: ["127.0.0.1"]
        bgp_neighbor_as: 2
"""

    CONFIG = """
        arp_neighbor_timeout: 2
        max_resolve_backoff_time: 1
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    exabgp_peer_conf = """
    static {
      route 0.0.0.0/0 next-hop 10.0.0.1 local-preference 100;
    }
"""
    exabgp_log = None
    exabgp_err = None
    config_ports = {'bgp_port': None}


    def pre_start_net(self):
        exabgp_conf = self.get_exabgp_conf(
            faucet_mininet_test_util.LOCALHOST, self.exabgp_peer_conf)
        self.exabgp_log, self.exabgp_err = self.start_exabgp(exabgp_conf)

    def test_untagged(self):
        """Test IPv4 routing, and BGP routes received."""
        first_host, second_host = self.net.hosts[:2]
        first_host_alias_ip = ipaddress.ip_interface(u'10.99.99.99/24')
        first_host_alias_host_ip = ipaddress.ip_interface(
            ipaddress.ip_network(first_host_alias_ip.ip))
        self.host_ipv4_alias(first_host, first_host_alias_ip)
        self.wait_bgp_up(
            faucet_mininet_test_util.LOCALHOST, 100, self.exabgp_log, self.exabgp_err)
        self.assertGreater(
            self.scrape_prometheus_var(
                'bgp_neighbor_routes', {'ipv': '4', 'vlan': '100'}),
            0)
        self.wait_exabgp_sent_updates(self.exabgp_log)
        self.add_host_route(
            second_host, first_host_alias_host_ip, self.FAUCET_VIPV4.ip)
        self.one_ipv4_ping(second_host, first_host_alias_ip.ip)
        self.one_ipv4_controller_ping(first_host)


class FaucetUntaggedBGPIPv4RouteTest(FaucetUntaggedTest):
    """Test IPv4 routing and import from BGP."""

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
        faucet_vips: ["10.0.0.254/24"]
        bgp_port: %(bgp_port)d
        bgp_as: 1
        bgp_routerid: "1.1.1.1"
        bgp_neighbor_addresses: ["127.0.0.1"]
        bgp_neighbor_as: 2
        routes:
            - route:
                ip_dst: 10.99.99.0/24
                ip_gw: 10.0.0.1
"""

    CONFIG = """
        arp_neighbor_timeout: 2
        max_resolve_backoff_time: 1
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    exabgp_peer_conf = """
    static {
      route 10.0.1.0/24 next-hop 10.0.0.1 local-preference 100;
      route 10.0.2.0/24 next-hop 10.0.0.2 local-preference 100;
      route 10.0.3.0/24 next-hop 10.0.0.2 local-preference 100;
      route 10.0.4.0/24 next-hop 10.0.0.254;
      route 10.0.5.0/24 next-hop 10.10.0.1;
   }
"""
    exabgp_log = None
    exabgp_err = None
    config_ports = {'bgp_port': None}


    def pre_start_net(self):
        exabgp_conf = self.get_exabgp_conf(
            faucet_mininet_test_util.LOCALHOST, self.exabgp_peer_conf)
        self.exabgp_log, self.exabgp_err = self.start_exabgp(exabgp_conf)

    def test_untagged(self):
        """Test IPv4 routing, and BGP routes received."""
        iperf_port = faucet_mininet_test_util.find_free_port(
            self.ports_sock, self._test_name())
        first_host, second_host = self.net.hosts[:2]
        # wait until 10.0.0.1 has been resolved
        self.wait_for_route_as_flow(
            first_host.MAC(), ipaddress.IPv4Network(u'10.99.99.0/24'))
        self.wait_bgp_up(
            faucet_mininet_test_util.LOCALHOST, 100, self.exabgp_log, self.exabgp_err)
        self.assertGreater(
            self.scrape_prometheus_var(
                'bgp_neighbor_routes', {'ipv': '4', 'vlan': '100'}),
            0)
        self.wait_exabgp_sent_updates(self.exabgp_log)
        self.verify_invalid_bgp_route('10.0.0.4/24 cannot be us')
        self.verify_invalid_bgp_route('10.0.0.5/24 is not a connected network')
        self.wait_for_route_as_flow(
            second_host.MAC(), ipaddress.IPv4Network(u'10.0.3.0/24'))
        self.verify_ipv4_routing_mesh(iperf_port)
        self.flap_all_switch_ports()
        self.verify_ipv4_routing_mesh(iperf_port)
        for host in first_host, second_host:
            self.one_ipv4_controller_ping(host)


class FaucetUntaggedIPv4RouteTest(FaucetUntaggedTest):
    """Test IPv4 routing and export to BGP."""

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
        faucet_vips: ["10.0.0.254/24"]
        bgp_port: %(bgp_port)d
        bgp_as: 1
        bgp_routerid: "1.1.1.1"
        bgp_neighbor_addresses: ["127.0.0.1"]
        bgp_neighbor_as: 2
        routes:
            - route:
                ip_dst: "10.0.1.0/24"
                ip_gw: "10.0.0.1"
            - route:
                ip_dst: "10.0.2.0/24"
                ip_gw: "10.0.0.2"
            - route:
                ip_dst: "10.0.3.0/24"
                ip_gw: "10.0.0.2"
"""

    CONFIG = """
        arp_neighbor_timeout: 2
        max_resolve_backoff_time: 1
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    exabgp_log = None
    exabgp_err = None
    config_ports = {'bgp_port': None}


    def pre_start_net(self):
        exabgp_conf = self.get_exabgp_conf(faucet_mininet_test_util.LOCALHOST)
        self.exabgp_log, self.exabgp_err = self.start_exabgp(exabgp_conf)

    def test_untagged(self):
        """Test IPv4 routing, and BGP routes sent."""
        iperf_port = faucet_mininet_test_util.find_free_port(
            self.ports_sock, self._test_name())
        self.verify_ipv4_routing_mesh(iperf_port)
        self.flap_all_switch_ports()
        self.verify_ipv4_routing_mesh(iperf_port)
        self.wait_bgp_up(
            faucet_mininet_test_util.LOCALHOST, 100, self.exabgp_log, self.exabgp_err)
        self.assertGreater(
            self.scrape_prometheus_var(
                'bgp_neighbor_routes', {'ipv': '4', 'vlan': '100'}),
            0)
        # exabgp should have received our BGP updates
        updates = self.exabgp_updates(self.exabgp_log)
        assert re.search('10.0.0.0/24 next-hop 10.0.0.254', updates)
        assert re.search('10.0.1.0/24 next-hop 10.0.0.1', updates)
        assert re.search('10.0.2.0/24 next-hop 10.0.0.2', updates)
        assert re.search('10.0.2.0/24 next-hop 10.0.0.2', updates)


class FaucetZodiacUntaggedIPv4RouteTest(FaucetUntaggedIPv4RouteTest):

    RUN_GAUGE = False
    N_UNTAGGED = 3


class FaucetUntaggedVLanUnicastFloodTest(FaucetUntaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
        unicast_flood: True
"""

    CONFIG = """
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def test_untagged(self):
        self.ping_all_when_learned()
        self.verify_port1_unicast(True)
        self.assertTrue(self.bogus_mac_flooded_to_port1())


class FaucetUntaggedNoVLanUnicastFloodTest(FaucetUntaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
        unicast_flood: False
"""

    CONFIG = """
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def test_untagged(self):
        self.verify_port1_unicast(False)
        self.assertFalse(self.bogus_mac_flooded_to_port1())


class FaucetUntaggedPortUnicastFloodTest(FaucetUntaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
        unicast_flood: False
"""

    CONFIG = """
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
                unicast_flood: True
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def test_untagged(self):
        self.verify_port1_unicast(False)
        # VLAN level config to disable flooding takes precedence,
        # cannot enable port-only flooding.
        self.assertFalse(self.bogus_mac_flooded_to_port1())


class FaucetUntaggedNoPortUnicastFloodTest(FaucetUntaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
        unicast_flood: True
"""

    CONFIG = """
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
                unicast_flood: False
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def test_untagged(self):
        self.verify_port1_unicast(False)
        self.assertFalse(self.bogus_mac_flooded_to_port1())


class FaucetUntaggedHostMoveTest(FaucetUntaggedTest):

    def test_untagged(self):
        first_host, second_host = self.net.hosts[0:2]
        self.retry_net_ping(hosts=(first_host, second_host))
        self.swap_host_macs(first_host, second_host)
        self.net.ping((first_host, second_host))
        for host, in_port in (
                (first_host, self.port_map['port_1']),
                (second_host, self.port_map['port_2'])):
            self.require_host_learned(host, in_port=in_port)
        self.retry_net_ping(hosts=(first_host, second_host))


class FaucetUntaggedHostPermanentLearnTest(FaucetUntaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
"""

    CONFIG = """
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
                permanent_learn: True
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def test_untagged(self):
        self.ping_all_when_learned()
        first_host, second_host, third_host = self.net.hosts[0:3]
        # 3rd host impersonates 1st, 3rd host breaks but 1st host still OK
        original_third_host_mac = third_host.MAC()
        third_host.setMAC(first_host.MAC())
        self.assertEqual(100.0, self.net.ping((second_host, third_host)))
        self.retry_net_ping(hosts=(first_host, second_host))
        # 3rd host stops impersonating, now everything fine again.
        third_host.setMAC(original_third_host_mac)
        self.ping_all_when_learned()


class FaucetSingleUntaggedIPv4LACPTest(FaucetUntaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
        faucet_vips: ["10.0.0.254/24"]
"""

    CONFIG = """
        max_resolve_backoff_time: 1
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
                lacp: True
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""


    def test_untagged(self):
        host = self.net.hosts[0]
        bond = 'bond0'
        # Linux driver should have this state (0x3f/63)
        #
        #    Actor State: 0x3f, LACP Activity, LACP Timeout, Aggregation, Synchronization, Collecting, Distributing
        #        .... ...1 = LACP Activity: Active
        #        .... ..1. = LACP Timeout: Short Timeout
        #        .... .1.. = Aggregation: Aggregatable
        #        .... 1... = Synchronization: In Sync
        #        ...1 .... = Collecting: Enabled
        #        ..1. .... = Distributing: Enabled
        #        .0.. .... = Defaulted: No
        #        0... .... = Expired: No
        #    [Actor State Flags: **DCSGSA]

        # FAUCET should have this state (0x3a/58)
        #
        #    Partner State: 0x3a, LACP Timeout, Synchronization, Collecting, Distributing
        #        .... ...0 = LACP Activity: Passive
        #        .... ..1. = LACP Timeout: Short Timeout
        #        .... .0.. = Aggregation: Individual
        #        .... 1... = Synchronization: In Sync
        #        ...1 .... = Collecting: Enabled
        #        ..1. .... = Distributing: Enabled
        #        .0.. .... = Defaulted: No
        #        0... .... = Expired: No
        #    [Partner State Flags: **DCS*S*]


        synced_state_txt = r"""
details actor lacp pdu:
    system priority: 65535
    system mac address: 0e:00:00:00:00:99
    port key: \d+
    port priority: 255
    port number: 1
    port state: 63
details partner lacp pdu:
    system priority: 65535
    system mac address: 0e:00:00:00:00:01
    oper key: 1
    port priority: 255
    port number: 1
    port state: 58
""".strip()
        for setup_cmd in (
                'ip link set %s down' % host.defaultIntf(),
                'ip address flush dev %s' % host.defaultIntf(),
                'ip link add %s address 0e:00:00:00:00:99 type bond mode 802.3ad lacp_rate fast' % bond,
                'ip link set dev %s master %s' % (host.defaultIntf(), bond),
                'ip add add 10.0.0.1/24 dev %s' % bond,
                'ip link set %s up' % bond):
            result = host.cmd(setup_cmd)
            self.assertEquals('', result)
        for _ in range(10):
            result = host.cmd('cat /proc/net/bonding/%s|sed "s/[ \t]*$//g"' % bond)
            result = '\n'.join([line.rstrip() for line in result.splitlines()])
            if re.search(synced_state_txt, result):
                return
            time.sleep(1)
        self.fail('LACP did not synchronize: %s\n\nexpected:\n\n%s' % (
            result, synced_state_txt))


class FaucetSingleUntaggedIPv4ControlPlaneTest(FaucetUntaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
        faucet_vips: ["10.0.0.254/24"]
"""

    CONFIG = """
        max_resolve_backoff_time: 1
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def test_ping_controller(self):
        first_host, second_host = self.net.hosts[0:2]
        for _ in range(5):
            self.one_ipv4_ping(first_host, second_host.IP())
            for host in first_host, second_host:
                self.one_ipv4_controller_ping(host)
            self.flap_all_switch_ports()

    def test_fping_controller(self):
        first_host = self.net.hosts[0]
        self.one_ipv4_controller_ping(first_host)
        self.verify_controller_fping(first_host, self.FAUCET_VIPV4)

    def test_fuzz_controller(self):
        first_host = self.net.hosts[0]
        self.one_ipv4_controller_ping(first_host)
        packets = 1000
        for fuzz_cmd in (
                ('python -c \"from scapy.all import * ;'
                 'scapy.all.send(IP(dst=\'%s\')/'
                 'fuzz(%s(type=0)),count=%u)\"' % ('10.0.0.254', 'ICMP', packets)),
                ('python -c \"from scapy.all import * ;'
                 'scapy.all.send(IP(dst=\'%s\')/'
                 'fuzz(%s(type=8)),count=%u)\"' % ('10.0.0.254', 'ICMP', packets)),
                ('python -c \"from scapy.all import * ;'
                 'scapy.all.send(fuzz(%s(pdst=\'%s\')),'
                 'count=%u)\"' % ('ARP', '10.0.0.254', packets))):
            self.assertTrue(
                re.search('Sent %u packets' % packets, first_host.cmd(fuzz_cmd)))
        self.one_ipv4_controller_ping(first_host)


class FaucetUntaggedIPv6RATest(FaucetUntaggedTest):

    FAUCET_MAC = "0e:00:00:00:00:99"

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
        faucet_vips: ["fe80::1:254/64", "fc00::1:254/112", "fc00::2:254/112", "10.0.0.254/24"]
        faucet_mac: "%s"
""" % FAUCET_MAC

    CONFIG = """
        advertise_interval: 5
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def test_ndisc6(self):
        first_host = self.net.hosts[0]
        for vip in ('fe80::1:254', 'fc00::1:254', 'fc00::2:254'):
            self.assertEqual(
                self.FAUCET_MAC.upper(),
                first_host.cmd('ndisc6 -q %s %s' % (vip, first_host.defaultIntf())).strip())

    def test_rdisc6(self):
        first_host = self.net.hosts[0]
        rdisc6_results = sorted(list(set(first_host.cmd(
            'rdisc6 -q %s' % first_host.defaultIntf()).splitlines())))
        self.assertEqual(
            ['fc00::1:0/112', 'fc00::2:0/112'],
            rdisc6_results)

    def test_ra_advertise(self):
        first_host = self.net.hosts[0]
        tcpdump_filter = ' and '.join((
            'ether dst 33:33:00:00:00:01',
            'ether src %s' % self.FAUCET_MAC,
            'icmp6',
            'ip6[40] == 134',
            'ip6 host fe80::1:254'))
        tcpdump_txt = self.tcpdump_helper(
            first_host, tcpdump_filter, [], timeout=30, vflags='-vv', packets=1)
        for ra_required in (
                r'fe80::1:254 > ff02::1:.+ICMP6, router advertisement',
                r'fc00::1:0/112, Flags \[onlink, auto\]',
                r'fc00::2:0/112, Flags \[onlink, auto\]',
                r'source link-address option \(1\), length 8 \(1\): %s' % self.FAUCET_MAC):
            self.assertTrue(
                re.search(ra_required, tcpdump_txt),
                msg='%s: %s' % (ra_required, tcpdump_txt))

    def test_rs_reply(self):
        first_host = self.net.hosts[0]
        tcpdump_filter = ' and '.join((
            'ether src %s' % self.FAUCET_MAC,
            'ether dst %s' % first_host.MAC(),
            'icmp6',
            'ip6[40] == 134',
            'ip6 host fe80::1:254'))
        tcpdump_txt = self.tcpdump_helper(
            first_host, tcpdump_filter, [
                lambda: first_host.cmd(
                    'rdisc6 -1 %s' % first_host.defaultIntf())],
            timeout=30, vflags='-vv', packets=1)
        for ra_required in (
                r'fe80::1:254 > fe80::.+ICMP6, router advertisement',
                r'fc00::1:0/112, Flags \[onlink, auto\]',
                r'fc00::2:0/112, Flags \[onlink, auto\]',
                r'source link-address option \(1\), length 8 \(1\): %s' % self.FAUCET_MAC):
            self.assertTrue(
                re.search(ra_required, tcpdump_txt),
                msg='%s: %s (%s)' % (ra_required, tcpdump_txt, tcpdump_filter))


class FaucetSingleUntaggedIPv6ControlPlaneTest(FaucetUntaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
        faucet_vips: ["fc00::1:254/112"]
"""

    CONFIG = """
        max_resolve_backoff_time: 1
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def test_ping_controller(self):
        first_host, second_host = self.net.hosts[0:2]
        self.add_host_ipv6_address(first_host, 'fc00::1:1/112')
        self.add_host_ipv6_address(second_host, 'fc00::1:2/112')
        for _ in range(5):
            self.one_ipv6_ping(first_host, 'fc00::1:2')
            for host in first_host, second_host:
                self.one_ipv6_controller_ping(host)
            self.flap_all_switch_ports()

    def test_fping_controller(self):
        first_host = self.net.hosts[0]
        self.add_host_ipv6_address(first_host, 'fc00::1:1/112')
        self.one_ipv6_controller_ping(first_host)
        self.verify_controller_fping(first_host, self.FAUCET_VIPV6)

    def test_fuzz_controller(self):
        first_host = self.net.hosts[0]
        self.add_host_ipv6_address(first_host, 'fc00::1:1/112')
        self.one_ipv6_controller_ping(first_host)
        fuzz_success = False
        packets = 1000
        for fuzz_class in dir(scapy.all):
            if fuzz_class.startswith('ICMPv6'):
                fuzz_cmd = (
                    'python -c \"from scapy.all import * ;'
                    'scapy.all.send(IPv6(dst=\'%s\')/'
                    'fuzz(%s()),count=%u)\"' % ('fc00::1:254', fuzz_class, packets))
                if re.search('Sent %u packets' % packets, first_host.cmd(fuzz_cmd)):
                    output(fuzz_class)
                    fuzz_success = True
        self.assertTrue(fuzz_success)
        self.one_ipv6_controller_ping(first_host)


class FaucetTaggedAndUntaggedTest(FaucetTest):

    N_TAGGED = 2
    N_UNTAGGED = 4

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "tagged"
    101:
        description: "untagged"
"""

    CONFIG = """
        interfaces:
            %(port_1)d:
                tagged_vlans: [100]
                description: "b1"
            %(port_2)d:
                tagged_vlans: [100]
                description: "b2"
            %(port_3)d:
                native_vlan: 101
                description: "b3"
            %(port_4)d:
                native_vlan: 101
                description: "b4"
"""

    def setUp(self):
        super(FaucetTaggedAndUntaggedTest, self).setUp()
        self.topo = self.topo_class(
            self.ports_sock, self._test_name(), [self.dpid],
            n_tagged=2, n_untagged=2)
        self.start_net()

    def test_seperate_untagged_tagged(self):
        tagged_host_pair = self.net.hosts[:2]
        untagged_host_pair = self.net.hosts[2:]
        self.verify_vlan_flood_limited(
            tagged_host_pair[0], tagged_host_pair[1], untagged_host_pair[0])
        self.verify_vlan_flood_limited(
            untagged_host_pair[0], untagged_host_pair[1], tagged_host_pair[0])
        # hosts within VLANs can ping each other
        self.retry_net_ping(hosts=tagged_host_pair)
        self.retry_net_ping(hosts=untagged_host_pair)
        # hosts cannot ping hosts in other VLANs
        self.assertEqual(
            100, self.net.ping([tagged_host_pair[0], untagged_host_pair[0]]))


class FaucetUntaggedACLTest(FaucetUntaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
acls:
    1:
        - rule:
            dl_type: 0x800
            nw_proto: 6
            tp_dst: 5002
            actions:
                allow: 1
        - rule:
            dl_type: 0x800
            nw_proto: 6
            tp_dst: 5001
            actions:
                allow: 0
        - rule:
            actions:
                allow: 1
"""
    CONFIG = """
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
                acl_in: 1
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def test_port5001_blocked(self):
        self.ping_all_when_learned()
        first_host, second_host = self.net.hosts[0:2]
        self.verify_tp_dst_blocked(5001, first_host, second_host)

    def test_port5002_notblocked(self):
        self.ping_all_when_learned()
        first_host, second_host = self.net.hosts[0:2]
        self.verify_tp_dst_notblocked(5002, first_host, second_host)


class FaucetUntaggedACLTcpMaskTest(FaucetUntaggedACLTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
acls:
    1:
        - rule:
            dl_type: 0x800
            nw_proto: 6
            tp_dst: 5002
            actions:
                allow: 1
        - rule:
            dl_type: 0x800
            nw_proto: 6
            tp_dst: 5001
            actions:
                allow: 0
        - rule:
            dl_type: 0x800
            nw_proto: 6
            # Match packets > 1023
            tp_dst: 1024/1024
            actions:
                allow: 0
        - rule:
            actions:
                allow: 1
"""

    def test_port_gt1023_blocked(self):
        self.ping_all_when_learned()
        first_host, second_host = self.net.hosts[0:2]
        self.verify_tp_dst_blocked(1024, first_host, second_host, mask=1024)
        self.verify_tp_dst_notblocked(1023, first_host, second_host, table_id=None)


class FaucetUntaggedVLANACLTest(FaucetUntaggedTest):

    CONFIG_GLOBAL = """
acls:
    1:
        - rule:
            dl_type: 0x800
            nw_proto: 6
            tp_dst: 5001
            actions:
                allow: 0
        - rule:
            dl_type: 0x800
            nw_proto: 6
            tp_dst: 5002
            actions:
                allow: 1
        - rule:
            actions:
                allow: 1
vlans:
    100:
        description: "untagged"
        acl_in: 1
"""
    CONFIG = """
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def test_port5001_blocked(self):
        self.ping_all_when_learned()
        first_host, second_host = self.net.hosts[0:2]
        self.verify_tp_dst_blocked(
            5001, first_host, second_host, table_id=self.VLAN_ACL_TABLE)

    def test_port5002_notblocked(self):
        self.ping_all_when_learned()
        first_host, second_host = self.net.hosts[0:2]
        self.verify_tp_dst_notblocked(
            5002, first_host, second_host, table_id=self.VLAN_ACL_TABLE)


class FaucetZodiacUntaggedACLTest(FaucetUntaggedACLTest):

    RUN_GAUGE = False
    N_UNTAGGED = 3

    def test_untagged(self):
        """All hosts on the same untagged VLAN should have connectivity."""
        self.ping_all_when_learned()
        self.flap_all_switch_ports()
        self.ping_all_when_learned()


class FaucetUntaggedACLMirrorTest(FaucetUntaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
        unicast_flood: False
acls:
    1:
        - rule:
            actions:
                allow: 1
                mirror: mirrorport
"""

    CONFIG = """
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
                acl_in: 1
            %(port_2)d:
                native_vlan: 100
                description: "b2"
                acl_in: 1
            mirrorport:
                number: %(port_3)d
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def test_untagged(self):
        first_host, second_host, mirror_host = self.net.hosts[0:3]
        self.verify_ping_mirrored(first_host, second_host, mirror_host)

    def test_eapol_mirrored(self):
        first_host, second_host, mirror_host = self.net.hosts[0:3]
        self.verify_eapol_mirrored(first_host, second_host, mirror_host)


class FaucetZodiacUntaggedACLMirrorTest(FaucetUntaggedACLMirrorTest):

    RUN_GAUGE = False
    N_UNTAGGED = 3


class FaucetUntaggedACLMirrorDefaultAllowTest(FaucetUntaggedACLMirrorTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
        unicast_flood: False
acls:
    1:
        - rule:
            actions:
                mirror: mirrorport
"""

    CONFIG = """
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
                acl_in: 1
            %(port_2)d:
                native_vlan: 100
                description: "b2"
                acl_in: 1
            mirrorport:
                number: %(port_3)d
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""


class FaucetUntaggedOutputTest(FaucetUntaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
        unicast_flood: False
acls:
    1:
        - rule:
            dl_dst: "01:02:03:04:05:06"
            actions:
                output:
                    dl_dst: "06:06:06:06:06:06"
                    vlan_vid: 123
                    port: acloutport
"""

    CONFIG = """
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
                acl_in: 1
            acloutport:
                number: %(port_2)d
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def test_untagged(self):
        first_host, second_host = self.net.hosts[0:2]
        # we expected to see the rewritten address and VLAN
        tcpdump_filter = ('icmp and ether dst 06:06:06:06:06:06')
        tcpdump_txt = self.tcpdump_helper(
            second_host, tcpdump_filter, [
                lambda: first_host.cmd(
                    'arp -s %s %s' % (second_host.IP(), '01:02:03:04:05:06')),
                lambda: first_host.cmd('ping -c1 %s' % second_host.IP())])
        self.assertTrue(re.search(
            '%s: ICMP echo request' % second_host.IP(), tcpdump_txt))
        self.assertTrue(re.search(
            'vlan 123', tcpdump_txt))


class FaucetUntaggedMultiVlansOutputTest(FaucetUntaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
        unicast_flood: False
acls:
    1:
        - rule:
            dl_dst: "01:02:03:04:05:06"
            actions:
                output:
                    dl_dst: "06:06:06:06:06:06"
                    vlan_vids: [123, 456]
                    port: acloutport
"""

    CONFIG = """
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
                acl_in: 1
            acloutport:
                number: %(port_2)d
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    @unittest.skip('needs OVS dev >= v2.8')
    def test_untagged(self):
        first_host, second_host = self.net.hosts[0:2]
        # we expected to see the rewritten address and VLAN
        tcpdump_filter = 'vlan'
        tcpdump_txt = self.tcpdump_helper(
            second_host, tcpdump_filter, [
                lambda: first_host.cmd(
                    'arp -s %s %s' % (second_host.IP(), '01:02:03:04:05:06')),
                lambda: first_host.cmd('ping -c1 %s' % second_host.IP())])
        self.assertTrue(re.search(
            '%s: ICMP echo request' % second_host.IP(), tcpdump_txt))
        self.assertTrue(re.search(
            'vlan 456.+vlan 123', tcpdump_txt))


class FaucetUntaggedMultiConfVlansOutputTest(FaucetUntaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
        unicast_flood: False
acls:
    1:
        - rule:
            dl_dst: "01:02:03:04:05:06"
            actions:
                output:
                    dl_dst: "06:06:06:06:06:06"
                    vlan_vids: [{vid: 123, eth_type: 0x88a8}, 456]
                    port: acloutport
"""

    CONFIG = """
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
                acl_in: 1
            acloutport:
                number: %(port_2)d
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    @unittest.skip('needs OVS dev >= v2.8')
    def test_untagged(self):
        first_host, second_host = self.net.hosts[0:2]
        # we expected to see the rewritten address and VLAN
        tcpdump_filter = 'ether proto 0x88a8'
        tcpdump_txt = self.tcpdump_helper(
            second_host, tcpdump_filter, [
                lambda: first_host.cmd(
                    'arp -s %s %s' % (second_host.IP(), '01:02:03:04:05:06')),
                lambda: first_host.cmd('ping -c1 %s' % second_host.IP())])
        self.assertTrue(re.search(
            '%s: ICMP echo request' % second_host.IP(), tcpdump_txt))
        self.assertTrue(re.search(
            'vlan 456.+ethertype 802.1Q-QinQ, vlan 123', tcpdump_txt))


class FaucetUntaggedMirrorTest(FaucetUntaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
        unicast_flood: False
"""

    CONFIG = """
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
                mirror: %(port_1)d
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def test_untagged(self):
        first_host, second_host, mirror_host = self.net.hosts[0:3]
        self.flap_all_switch_ports()
        self.verify_ping_mirrored(first_host, second_host, mirror_host)


class FaucetTaggedTest(FaucetTest):

    N_UNTAGGED = 0
    N_TAGGED = 4

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "tagged"
"""

    CONFIG = """
        interfaces:
            %(port_1)d:
                tagged_vlans: [100]
                description: "b1"
            %(port_2)d:
                tagged_vlans: [100]
                description: "b2"
            %(port_3)d:
                tagged_vlans: [100]
                description: "b3"
            %(port_4)d:
                tagged_vlans: [100]
                description: "b4"
"""

    def setUp(self):
        super(FaucetTaggedTest, self).setUp()
        self.topo = self.topo_class(
            self.ports_sock, self._test_name(), [self.dpid],
            n_tagged=4)
        self.start_net()

    def test_tagged(self):
        self.ping_all_when_learned()


class FaucetTaggedSwapVidOutputTest(FaucetTaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "tagged"
        unicast_flood: False
    101:
        description: "tagged"
        unicast_flood: False
acls:
    1:
        - rule:
            vlan_vid: 100
            actions:
                output:
                    swap_vid: 101
                    port: acloutport
"""

    CONFIG = """
        interfaces:
            %(port_1)d:
                tagged_vlans: [100]
                description: "b1"
                acl_in: 1
            acloutport:
                number: %(port_2)d
                tagged_vlans: [101]
                description: "b2"
            %(port_3)d:
                tagged_vlans: [100]
                description: "b3"
            %(port_4)d:
                tagged_vlans: [100]
                description: "b4"
"""

    def test_tagged(self):
        first_host, second_host = self.net.hosts[0:2]
        # we expected to see the swapped VLAN VID
        tcpdump_filter = 'vlan 101'
        tcpdump_txt = self.tcpdump_helper(
            second_host, tcpdump_filter, [
                lambda: first_host.cmd(
                    'arp -s %s %s' % (second_host.IP(), '01:02:03:04:05:06')),
                lambda: first_host.cmd('ping -c1 %s' % second_host.IP())], root_intf=True)
        self.assertTrue(re.search(
            '%s: ICMP echo request' % second_host.IP(), tcpdump_txt))
        self.assertTrue(re.search(
            'vlan 101', tcpdump_txt))


class FaucetTaggedPopVlansOutputTest(FaucetTaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "tagged"
        unicast_flood: False
acls:
    1:
        - rule:
            vlan_vid: 100
            dl_dst: "01:02:03:04:05:06"
            actions:
                output:
                    dl_dst: "06:06:06:06:06:06"
                    pop_vlans: 1
                    port: acloutport
"""

    CONFIG = """
        interfaces:
            %(port_1)d:
                tagged_vlans: [100]
                description: "b1"
                acl_in: 1
            acloutport:
                tagged_vlans: [100]
                number: %(port_2)d
                description: "b2"
            %(port_3)d:
                tagged_vlans: [100]
                description: "b3"
            %(port_4)d:
                tagged_vlans: [100]
                description: "b4"
"""

    def test_tagged(self):
        first_host, second_host = self.net.hosts[0:2]
        tcpdump_filter = 'not vlan and icmp and ether dst 06:06:06:06:06:06'
        tcpdump_txt = self.tcpdump_helper(
            second_host, tcpdump_filter, [
                lambda: first_host.cmd(
                    'arp -s %s %s' % (second_host.IP(), '01:02:03:04:05:06')),
                lambda: first_host.cmd(
                    'ping -c1 %s' % second_host.IP())], packets=10, root_intf=True)
        self.assertTrue(re.search(
            '%s: ICMP echo request' % second_host.IP(), tcpdump_txt))


class FaucetTaggedIPv4ControlPlaneTest(FaucetTaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "tagged"
        faucet_vips: ["10.0.0.254/24"]
"""

    CONFIG = """
        max_resolve_backoff_time: 1
        interfaces:
            %(port_1)d:
                tagged_vlans: [100]
                description: "b1"
            %(port_2)d:
                tagged_vlans: [100]
                description: "b2"
            %(port_3)d:
                tagged_vlans: [100]
                description: "b3"
            %(port_4)d:
                tagged_vlans: [100]
                description: "b4"
"""

    def test_ping_controller(self):
        first_host, second_host = self.net.hosts[0:2]
        self.one_ipv4_ping(first_host, second_host.IP())
        for host in first_host, second_host:
            self.one_ipv4_controller_ping(host)


class FaucetTaggedIPv6ControlPlaneTest(FaucetTaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "tagged"
        faucet_vips: ["fc00::1:254/112"]
"""

    CONFIG = """
        max_resolve_backoff_time: 1
        interfaces:
            %(port_1)d:
                tagged_vlans: [100]
                description: "b1"
            %(port_2)d:
                tagged_vlans: [100]
                description: "b2"
            %(port_3)d:
                tagged_vlans: [100]
                description: "b3"
            %(port_4)d:
                tagged_vlans: [100]
                description: "b4"
"""

    def test_ping_controller(self):
        first_host, second_host = self.net.hosts[0:2]
        self.add_host_ipv6_address(first_host, 'fc00::1:1/112')
        self.add_host_ipv6_address(second_host, 'fc00::1:2/112')
        self.one_ipv6_ping(first_host, 'fc00::1:2')
        for host in first_host, second_host:
            self.one_ipv6_controller_ping(host)


class FaucetTaggedICMPv6ACLTest(FaucetTaggedTest):

    CONFIG_GLOBAL = """
acls:
    1:
        - rule:
            dl_type: 0x86dd
            vlan_vid: 100
            ip_proto: 58
            icmpv6_type: 135
            ipv6_nd_target: "fc00::1:2"
            actions:
                output:
                    port: b2
        - rule:
            actions:
                allow: 1
vlans:
    100:
        description: "tagged"
        faucet_vips: ["fc00::1:254/112"]
"""

    CONFIG = """
        max_resolve_backoff_time: 1
        interfaces:
            %(port_1)d:
                tagged_vlans: [100]
                description: "b1"
                acl_in: 1
            b2:
                number: %(port_2)d
                tagged_vlans: [100]
                description: "b2"
            %(port_3)d:
                tagged_vlans: [100]
                description: "b3"
            %(port_4)d:
                tagged_vlans: [100]
                description: "b4"
"""

    def test_icmpv6_acl_match(self):
        first_host, second_host = self.net.hosts[0:2]
        self.add_host_ipv6_address(first_host, 'fc00::1:1/112')
        self.add_host_ipv6_address(second_host, 'fc00::1:2/112')
        self.one_ipv6_ping(first_host, 'fc00::1:2')
        self.wait_nonzero_packet_count_flow(
            {u'ipv6_nd_target': u'fc00::1:2'}, table_id=self.PORT_ACL_TABLE)


class FaucetTaggedIPv4RouteTest(FaucetTaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "tagged"
        faucet_vips: ["10.0.0.254/24"]
        routes:
            - route:
                ip_dst: "10.0.1.0/24"
                ip_gw: "10.0.0.1"
            - route:
                ip_dst: "10.0.2.0/24"
                ip_gw: "10.0.0.2"
            - route:
                ip_dst: "10.0.3.0/24"
                ip_gw: "10.0.0.2"
"""

    CONFIG = """
        arp_neighbor_timeout: 2
        max_resolve_backoff_time: 1
        interfaces:
            %(port_1)d:
                tagged_vlans: [100]
                description: "b1"
            %(port_2)d:
                tagged_vlans: [100]
                description: "b2"
            %(port_3)d:
                tagged_vlans: [100]
                description: "b3"
            %(port_4)d:
                tagged_vlans: [100]
                description: "b4"
"""

    def test_tagged(self):
        iperf_port = faucet_mininet_test_util.find_free_port(
            self.ports_sock, self._test_name())
        host_pair = self.net.hosts[:2]
        first_host, second_host = host_pair
        first_host_routed_ip = ipaddress.ip_interface(u'10.0.1.1/24')
        second_host_routed_ip = ipaddress.ip_interface(u'10.0.2.1/24')
        for _ in range(3):
            self.verify_ipv4_routing(
                first_host, first_host_routed_ip,
                second_host, second_host_routed_ip, iperf_port)
            self.swap_host_macs(first_host, second_host)


class FaucetTaggedProactiveNeighborIPv4RouteTest(FaucetTaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "tagged"
        faucet_vips: ["10.0.0.254/24"]
"""

    CONFIG = """
        arp_neighbor_timeout: 2
        max_resolve_backoff_time: 1
        proactive_learn: true
        interfaces:
            %(port_1)d:
                tagged_vlans: [100]
                description: "b1"
            %(port_2)d:
                tagged_vlans: [100]
                description: "b2"
            %(port_3)d:
                tagged_vlans: [100]
                description: "b3"
            %(port_4)d:
                tagged_vlans: [100]
                description: "b4"
"""

    def test_tagged(self):
        host_pair = self.net.hosts[:2]
        first_host, second_host = host_pair
        first_host_alias_ip = ipaddress.ip_interface(u'10.0.0.99/24')
        first_host_alias_host_ip = ipaddress.ip_interface(
            ipaddress.ip_network(first_host_alias_ip.ip))
        self.host_ipv4_alias(first_host, first_host_alias_ip)
        self.add_host_route(second_host, first_host_alias_host_ip, self.FAUCET_VIPV4.ip)
        self.one_ipv4_ping(second_host, first_host_alias_ip.ip)
        self.assertGreater(
            self.scrape_prometheus_var(
                'vlan_neighbors', {'ipv': '4', 'vlan': '100'}),
            1)


class FaucetTaggedProactiveNeighborIPv6RouteTest(FaucetTaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "tagged"
        faucet_vips: ["fc00::1:3/64"]
"""

    CONFIG = """
        arp_neighbor_timeout: 2
        max_resolve_backoff_time: 1
        proactive_learn: true
        interfaces:
            %(port_1)d:
                tagged_vlans: [100]
                description: "b1"
            %(port_2)d:
                tagged_vlans: [100]
                description: "b2"
            %(port_3)d:
                tagged_vlans: [100]
                description: "b3"
            %(port_4)d:
                tagged_vlans: [100]
                description: "b4"
"""

    def test_tagged(self):
        host_pair = self.net.hosts[:2]
        first_host, second_host = host_pair
        first_host_alias_ip = ipaddress.ip_interface(u'fc00::1:99/64')
        faucet_vip_ip = ipaddress.ip_interface(u'fc00::1:3/126')
        first_host_alias_host_ip = ipaddress.ip_interface(
            ipaddress.ip_network(first_host_alias_ip.ip))
        self.add_host_ipv6_address(first_host, ipaddress.ip_interface(u'fc00::1:1/64'))
        # We use a narrower mask to force second_host to use the /128 route,
        # since otherwise it would realize :99 is directly connected via ND and send direct.
        self.add_host_ipv6_address(second_host, ipaddress.ip_interface(u'fc00::1:2/126'))
        self.add_host_ipv6_address(first_host, first_host_alias_ip)
        self.add_host_route(second_host, first_host_alias_host_ip, faucet_vip_ip.ip)
        self.one_ipv6_ping(second_host, first_host_alias_ip.ip)
        self.assertGreater(
            self.scrape_prometheus_var(
                'vlan_neighbors', {'ipv': '6', 'vlan': '100'}),
            1)


class FaucetUntaggedIPv4InterVLANRouteTest(FaucetUntaggedTest):

    FAUCET_MAC2 = '0e:00:00:00:00:02'

    CONFIG_GLOBAL = """
vlans:
    100:
        faucet_vips: ["10.100.0.254/24"]
    vlanb:
        vid: 200
        faucet_vips: ["10.200.0.254/24"]
        faucet_mac: "%s"
    vlanc:
        vid: 100
        description: "not used"
routers:
    router-1:
        vlans: [100, vlanb]
""" % FAUCET_MAC2

    CONFIG = """
        arp_neighbor_timeout: 2
        max_resolve_backoff_time: 1
        proactive_learn: True
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: vlanb
                description: "b2"
            %(port_3)d:
                native_vlan: vlanb
                description: "b3"
            %(port_4)d:
                native_vlan: vlanb
                description: "b4"
"""

    def test_untagged(self):
        first_host_ip = ipaddress.ip_interface(u'10.100.0.1/24')
        first_faucet_vip = ipaddress.ip_interface(u'10.100.0.254/24')
        second_host_ip = ipaddress.ip_interface(u'10.200.0.1/24')
        second_faucet_vip = ipaddress.ip_interface(u'10.200.0.254/24')
        first_host, second_host = self.net.hosts[:2]
        first_host.setIP(str(first_host_ip.ip), prefixLen=24)
        second_host.setIP(str(second_host_ip.ip), prefixLen=24)
        self.add_host_route(first_host, second_host_ip, first_faucet_vip.ip)
        self.add_host_route(second_host, first_host_ip, second_faucet_vip.ip)
        self.one_ipv4_ping(first_host, second_host_ip.ip)
        self.one_ipv4_ping(second_host, first_host_ip.ip)
        self.assertEqual(
            self._ip_neigh(first_host, first_faucet_vip.ip, 4), self.FAUCET_MAC)
        self.assertEqual(
            self._ip_neigh(second_host, second_faucet_vip.ip, 4), self.FAUCET_MAC2)


class FaucetUntaggedIPv6InterVLANRouteTest(FaucetUntaggedTest):

    FAUCET_MAC2 = '0e:00:00:00:00:02'

    CONFIG_GLOBAL = """
vlans:
    100:
        faucet_vips: ["fc00::1:254/64"]
    vlanb:
        vid: 200
        faucet_vips: ["fc01::1:254/64"]
        faucet_mac: "%s"
    vlanc:
        vid: 100
        description: "not used"
routers:
    router-1:
        vlans: [100, vlanb]
""" % FAUCET_MAC2

    CONFIG = """
        arp_neighbor_timeout: 2
        max_resolve_backoff_time: 1
        proactive_learn: True
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: vlanb
                description: "b2"
            %(port_3)d:
                native_vlan: vlanb
                description: "b3"
            %(port_4)d:
                native_vlan: vlanb
                description: "b4"
"""

    def test_untagged(self):
        host_pair = self.net.hosts[:2]
        first_host, second_host = host_pair
        first_host_net = ipaddress.ip_interface(u'fc00::1:1/64')
        second_host_net = ipaddress.ip_interface(u'fc01::1:1/64')
        self.add_host_ipv6_address(first_host, first_host_net)
        self.add_host_ipv6_address(second_host, second_host_net)
        self.add_host_route(
            first_host, second_host_net, self.FAUCET_VIPV6.ip)
        self.add_host_route(
            second_host, first_host_net, self.FAUCET_VIPV6_2.ip)
        self.one_ipv6_ping(first_host, second_host_net.ip)
        self.one_ipv6_ping(second_host, first_host_net.ip)


class FaucetUntaggedIPv4PolicyRouteTest(FaucetUntaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "100"
        faucet_vips: ["10.0.0.254/24"]
        acl_in: pbr
    200:
        description: "200"
        faucet_vips: ["10.20.0.254/24"]
        routes:
            - route:
                ip_dst: "10.99.0.0/24"
                ip_gw: "10.20.0.2"
    300:
        description: "300"
        faucet_vips: ["10.30.0.254/24"]
        routes:
            - route:
                ip_dst: "10.99.0.0/24"
                ip_gw: "10.30.0.3"
acls:
    pbr:
        - rule:
            vlan_vid: 100
            dl_type: 0x800
            nw_dst: "10.99.0.2"
            actions:
                allow: 1
                output:
                    swap_vid: 300
        - rule:
            vlan_vid: 100
            dl_type: 0x800
            nw_dst: "10.99.0.0/24"
            actions:
                allow: 1
                output:
                    swap_vid: 200
        - rule:
            actions:
                allow: 1
routers:
    router-100-200:
        vlans: [100, 200]
    router-100-300:
        vlans: [100, 300]
"""
    CONFIG = """
        arp_neighbor_timeout: 2
        max_resolve_backoff_time: 1
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 200
                description: "b2"
            %(port_3)d:
                native_vlan: 300
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def test_untagged(self):
        # 10.99.0.1 is on b2, and 10.99.0.2 is on b3
        # we want to route 10.99.0.0/24 to b2, but we want
        # want to PBR 10.99.0.2/32 to b3.
        first_host_ip = ipaddress.ip_interface(u'10.0.0.1/24')
        first_faucet_vip = ipaddress.ip_interface(u'10.0.0.254/24')
        second_host_ip = ipaddress.ip_interface(u'10.20.0.2/24')
        second_faucet_vip = ipaddress.ip_interface(u'10.20.0.254/24')
        third_host_ip = ipaddress.ip_interface(u'10.30.0.3/24')
        third_faucet_vip = ipaddress.ip_interface(u'10.30.0.254/24')
        first_host, second_host, third_host = self.net.hosts[:3]
        remote_ip = ipaddress.ip_interface(u'10.99.0.1/24')
        remote_ip2 = ipaddress.ip_interface(u'10.99.0.2/24')
        second_host.setIP(str(second_host_ip.ip), prefixLen=24)
        third_host.setIP(str(third_host_ip.ip), prefixLen=24)
        self.host_ipv4_alias(second_host, remote_ip)
        self.host_ipv4_alias(third_host, remote_ip2)
        self.add_host_route(first_host, remote_ip, first_faucet_vip.ip)
        self.add_host_route(second_host, first_host_ip, second_faucet_vip.ip)
        self.add_host_route(third_host, first_host_ip, third_faucet_vip.ip)
        # ensure all nexthops resolved.
        self.one_ipv4_ping(first_host, first_faucet_vip.ip)
        self.one_ipv4_ping(second_host, second_faucet_vip.ip)
        self.one_ipv4_ping(third_host, third_faucet_vip.ip)
        self.wait_for_route_as_flow(
            second_host.MAC(), ipaddress.IPv4Network(u'10.99.0.0/24'), vlan_vid=200)
        self.wait_for_route_as_flow(
            third_host.MAC(), ipaddress.IPv4Network(u'10.99.0.0/24'), vlan_vid=300)
        # verify b1 can reach 10.99.0.1 and .2 on b2 and b3 respectively.
        self.one_ipv4_ping(first_host, remote_ip.ip)
        self.one_ipv4_ping(first_host, remote_ip2.ip)


class FaucetUntaggedMixedIPv4RouteTest(FaucetUntaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
        faucet_vips: ["172.16.0.254/24", "10.0.0.254/24"]
"""

    CONFIG = """
        arp_neighbor_timeout: 2
        max_resolve_backoff_time: 1
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def test_untagged(self):
        host_pair = self.net.hosts[:2]
        first_host, second_host = host_pair
        first_host_net = ipaddress.ip_interface(u'10.0.0.1/24')
        second_host_net = ipaddress.ip_interface(u'172.16.0.1/24')
        second_host.setIP(str(second_host_net.ip), prefixLen=24)
        self.one_ipv4_ping(first_host, self.FAUCET_VIPV4.ip)
        self.one_ipv4_ping(second_host, self.FAUCET_VIPV4_2.ip)
        self.add_host_route(
            first_host, second_host_net, self.FAUCET_VIPV4.ip)
        self.add_host_route(
            second_host, first_host_net, self.FAUCET_VIPV4_2.ip)
        self.one_ipv4_ping(first_host, second_host_net.ip)
        self.one_ipv4_ping(second_host, first_host_net.ip)


class FaucetUntaggedMixedIPv6RouteTest(FaucetUntaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
        faucet_vips: ["fc00::1:254/64", "fc01::1:254/64"]
"""

    CONFIG = """
        arp_neighbor_timeout: 2
        max_resolve_backoff_time: 1
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def test_untagged(self):
        host_pair = self.net.hosts[:2]
        first_host, second_host = host_pair
        first_host_net = ipaddress.ip_interface(u'fc00::1:1/64')
        second_host_net = ipaddress.ip_interface(u'fc01::1:1/64')
        self.add_host_ipv6_address(first_host, first_host_net)
        self.one_ipv6_ping(first_host, self.FAUCET_VIPV6.ip)
        self.add_host_ipv6_address(second_host, second_host_net)
        self.one_ipv6_ping(second_host, self.FAUCET_VIPV6_2.ip)
        self.add_host_route(
            first_host, second_host_net, self.FAUCET_VIPV6.ip)
        self.add_host_route(
            second_host, first_host_net, self.FAUCET_VIPV6_2.ip)
        self.one_ipv6_ping(first_host, second_host_net.ip)
        self.one_ipv6_ping(second_host, first_host_net.ip)


class FaucetUntaggedBGPIPv6DefaultRouteTest(FaucetUntaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
        faucet_vips: ["fc00::1:254/112"]
        bgp_port: %(bgp_port)d
        bgp_as: 1
        bgp_routerid: "1.1.1.1"
        bgp_neighbor_addresses: ["::1"]
        bgp_neighbor_as: 2
"""

    CONFIG = """
        arp_neighbor_timeout: 2
        max_resolve_backoff_time: 1
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    exabgp_peer_conf = """
    static {
      route ::/0 next-hop fc00::1:1 local-preference 100;
    }
"""

    exabgp_log = None
    exabgp_err = None
    config_ports = {'bgp_port': None}


    def pre_start_net(self):
        exabgp_conf = self.get_exabgp_conf('::1', self.exabgp_peer_conf)
        self.exabgp_log, self.exabgp_err = self.start_exabgp(exabgp_conf)

    def test_untagged(self):
        first_host, second_host = self.net.hosts[:2]
        self.add_host_ipv6_address(first_host, 'fc00::1:1/112')
        self.add_host_ipv6_address(second_host, 'fc00::1:2/112')
        first_host_alias_ip = ipaddress.ip_interface(u'fc00::50:1/112')
        first_host_alias_host_ip = ipaddress.ip_interface(
            ipaddress.ip_network(first_host_alias_ip.ip))
        self.add_host_ipv6_address(first_host, first_host_alias_ip)
        self.wait_bgp_up('::1', 100, self.exabgp_log, self.exabgp_err)
        self.assertGreater(
            self.scrape_prometheus_var(
                'bgp_neighbor_routes', {'ipv': '6', 'vlan': '100'}),
            0)
        self.wait_exabgp_sent_updates(self.exabgp_log)
        self.add_host_route(
            second_host, first_host_alias_host_ip, self.FAUCET_VIPV6.ip)
        self.one_ipv6_ping(second_host, first_host_alias_ip.ip)
        self.one_ipv6_controller_ping(first_host)


class FaucetUntaggedBGPIPv6RouteTest(FaucetUntaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
        faucet_vips: ["fc00::1:254/112"]
        bgp_port: %(bgp_port)d
        bgp_as: 1
        bgp_routerid: "1.1.1.1"
        bgp_neighbor_addresses: ["::1"]
        bgp_neighbor_as: 2
"""

    CONFIG = """
        arp_neighbor_timeout: 2
        max_resolve_backoff_time: 1
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    exabgp_peer_conf = """
    static {
      route fc00::10:1/112 next-hop fc00::1:1 local-preference 100;
      route fc00::20:1/112 next-hop fc00::1:2 local-preference 100;
      route fc00::30:1/112 next-hop fc00::1:2 local-preference 100;
      route fc00::40:1/112 next-hop fc00::1:254;
      route fc00::50:1/112 next-hop fc00::2:2;
    }
"""
    exabgp_log = None
    exabgp_err = None
    config_ports = {'bgp_port': None}


    def pre_start_net(self):
        exabgp_conf = self.get_exabgp_conf('::1', self.exabgp_peer_conf)
        self.exabgp_log, self.exabgp_err = self.start_exabgp(exabgp_conf)

    def test_untagged(self):
        iperf_port = faucet_mininet_test_util.find_free_port(
            self.ports_sock, self._test_name())
        first_host, second_host = self.net.hosts[:2]
        self.wait_bgp_up('::1', 100, self.exabgp_log, self.exabgp_err)
        self.assertGreater(
            self.scrape_prometheus_var(
                'bgp_neighbor_routes', {'ipv': '6', 'vlan': '100'}),
            0)
        self.wait_exabgp_sent_updates(self.exabgp_log)
        self.verify_invalid_bgp_route('fc00::40:1/112 cannot be us')
        self.verify_invalid_bgp_route('fc00::50:1/112 is not a connected network')
        self.verify_ipv6_routing_mesh(iperf_port)
        self.flap_all_switch_ports()
        self.verify_ipv6_routing_mesh(iperf_port)
        for host in first_host, second_host:
            self.one_ipv6_controller_ping(host)


class FaucetUntaggedSameVlanIPv6RouteTest(FaucetUntaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
        faucet_vips: ["fc00::10:1/112", "fc00::20:1/112"]
        routes:
            - route:
                ip_dst: "fc00::10:0/112"
                ip_gw: "fc00::10:2"
            - route:
                ip_dst: "fc00::20:0/112"
                ip_gw: "fc00::20:2"
"""

    CONFIG = """
        arp_neighbor_timeout: 2
        max_resolve_backoff_time: 1
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def test_untagged(self):
        first_host, second_host = self.net.hosts[:2]
        first_host_ip = ipaddress.ip_interface(u'fc00::10:2/112')
        first_host_ctrl_ip = ipaddress.ip_address(u'fc00::10:1')
        second_host_ip = ipaddress.ip_interface(u'fc00::20:2/112')
        second_host_ctrl_ip = ipaddress.ip_address(u'fc00::20:1')
        self.add_host_ipv6_address(first_host, first_host_ip)
        self.add_host_ipv6_address(second_host, second_host_ip)
        self.add_host_route(
            first_host, second_host_ip, first_host_ctrl_ip)
        self.add_host_route(
            second_host, first_host_ip, second_host_ctrl_ip)
        self.wait_for_route_as_flow(
            first_host.MAC(), first_host_ip.network)
        self.wait_for_route_as_flow(
            second_host.MAC(), second_host_ip.network)
        self.one_ipv6_ping(first_host, second_host_ip.ip)
        self.one_ipv6_ping(first_host, second_host_ctrl_ip)
        self.one_ipv6_ping(second_host, first_host_ip.ip)
        self.one_ipv6_ping(second_host, first_host_ctrl_ip)


class FaucetUntaggedIPv6RouteTest(FaucetUntaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
        faucet_vips: ["fc00::1:254/112"]
        bgp_port: %(bgp_port)d
        bgp_as: 1
        bgp_routerid: "1.1.1.1"
        bgp_neighbor_addresses: ["::1"]
        bgp_neighbor_as: 2
        routes:
            - route:
                ip_dst: "fc00::10:0/112"
                ip_gw: "fc00::1:1"
            - route:
                ip_dst: "fc00::20:0/112"
                ip_gw: "fc00::1:2"
            - route:
                ip_dst: "fc00::30:0/112"
                ip_gw: "fc00::1:2"
"""

    CONFIG = """
        arp_neighbor_timeout: 2
        max_resolve_backoff_time: 1
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    exabgp_log = None
    exabgp_err = None
    config_ports = {'bgp_port': None}


    def pre_start_net(self):
        exabgp_conf = self.get_exabgp_conf('::1')
        self.exabgp_log, self.exabgp_err = self.start_exabgp(exabgp_conf)

    def test_untagged(self):
        iperf_port = faucet_mininet_test_util.find_free_port(
            self.ports_sock, self._test_name())
        self.verify_ipv6_routing_mesh(iperf_port)
        second_host = self.net.hosts[1]
        self.flap_all_switch_ports()
        self.wait_for_route_as_flow(
            second_host.MAC(), ipaddress.IPv6Network(u'fc00::30:0/112'))
        self.verify_ipv6_routing_mesh(iperf_port)
        self.wait_bgp_up('::1', 100, self.exabgp_log, self.exabgp_err)
        self.assertGreater(
            self.scrape_prometheus_var(
                'bgp_neighbor_routes', {'ipv': '6', 'vlan': '100'}),
            0)
        updates = self.exabgp_updates(self.exabgp_log)
        assert re.search('fc00::1:0/112 next-hop fc00::1:254', updates)
        assert re.search('fc00::10:0/112 next-hop fc00::1:1', updates)
        assert re.search('fc00::20:0/112 next-hop fc00::1:2', updates)
        assert re.search('fc00::30:0/112 next-hop fc00::1:2', updates)


class FaucetTaggedIPv6RouteTest(FaucetTaggedTest):
    """Test basic IPv6 routing without BGP."""

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "tagged"
        faucet_vips: ["fc00::1:254/112"]
        routes:
            - route:
                ip_dst: "fc00::10:0/112"
                ip_gw: "fc00::1:1"
            - route:
                ip_dst: "fc00::20:0/112"
                ip_gw: "fc00::1:2"
"""

    CONFIG = """
        arp_neighbor_timeout: 2
        max_resolve_backoff_time: 1
        interfaces:
            %(port_1)d:
                tagged_vlans: [100]
                description: "b1"
            %(port_2)d:
                tagged_vlans: [100]
                description: "b2"
            %(port_3)d:
                tagged_vlans: [100]
                description: "b3"
            %(port_4)d:
                tagged_vlans: [100]
                description: "b4"
"""

    def test_tagged(self):
        """Test IPv6 routing works."""
        iperf_port = faucet_mininet_test_util.find_free_port(
            self.ports_sock, self._test_name())
        host_pair = self.net.hosts[:2]
        first_host, second_host = host_pair
        first_host_ip = ipaddress.ip_interface(u'fc00::1:1/112')
        second_host_ip = ipaddress.ip_interface(u'fc00::1:2/112')
        first_host_routed_ip = ipaddress.ip_interface(u'fc00::10:1/112')
        second_host_routed_ip = ipaddress.ip_interface(u'fc00::20:1/112')
        for _ in range(5):
            self.verify_ipv6_routing_pair(
                first_host, first_host_ip, first_host_routed_ip,
                second_host, second_host_ip, second_host_routed_ip,
                iperf_port)
            self.swap_host_macs(first_host, second_host)


class FaucetStringOfDPTest(FaucetTest):

    NUM_HOSTS = 4
    VID = 100
    dpids = None

    def build_net(self, stack=False, n_dps=1,
                  n_tagged=0, tagged_vid=100,
                  n_untagged=0, untagged_vid=100,
                  include=None, include_optional=None,
                  acls=None, acl_in_dp=None):
        """Set up Mininet and Faucet for the given topology."""
        if include is None:
            include = []
        if include_optional is None:
            include_optional = []
        if acls is None:
            acls = {}
        if acl_in_dp is None:
            acl_in_dp = {}
        self.dpids = [str(self.rand_dpid()) for _ in range(n_dps)]
        self.dpid = self.dpids[0]
        self.CONFIG = self.get_config(
            self.dpids,
            stack,
            self.hardware,
            self.debug_log_path,
            n_tagged,
            tagged_vid,
            n_untagged,
            untagged_vid,
            include,
            include_optional,
            acls,
            acl_in_dp,
        )
        with open(self.faucet_config_path, 'w') as config_file:
            config_file.write(self.CONFIG)
        self.topo = faucet_mininet_test_topo.FaucetStringOfDPSwitchTopo(
            self.ports_sock,
            dpids=self.dpids,
            n_tagged=n_tagged,
            tagged_vid=tagged_vid,
            n_untagged=n_untagged,
            test_name=self._test_name(),
        )

    def get_config(self, dpids=[], stack=False, hardware=None, ofchannel_log=None,
                   n_tagged=0, tagged_vid=0, n_untagged=0, untagged_vid=0,
                   include=[], include_optional=[], acls={}, acl_in_dp={}):
        """Build a complete Faucet configuration for each datapath, using the given topology."""

        def dp_name(i):
            return 'faucet-%i' % (i + 1)

        def add_vlans(n_tagged, tagged_vid, n_untagged, untagged_vid):
            vlans_config = {}
            if n_untagged:
                vlans_config[untagged_vid] = {
                    'description': 'untagged',
                }

            if ((n_tagged and not n_untagged) or
                    (n_tagged and n_untagged and tagged_vid != untagged_vid)):
                vlans_config[tagged_vid] = {
                    'description': 'tagged',
                }
            return vlans_config

        def add_acl_to_port(name, port, interfaces_config):
            if name in acl_in_dp and port in acl_in_dp[name]:
                interfaces_config[port]['acl_in'] = acl_in_dp[name][port]

        def add_dp_to_dp_ports(dp_config, port, interfaces_config, i,
                               dpid_count, stack, n_tagged, tagged_vid,
                               n_untagged, untagged_vid):
            # Add configuration for the switch-to-switch links
            # (0 for a single switch, 1 for an end switch, 2 for middle switches).
            first_dp = i == 0
            second_dp = i == 1
            last_dp = i == dpid_count - 1
            end_dp = first_dp or last_dp
            num_switch_links = 0
            if dpid_count > 1:
                if end_dp:
                    num_switch_links = 1
                else:
                    num_switch_links = 2

            if stack and first_dp:
                dp_config['stack'] = {
                    'priority': 1
                }

            first_stack_port = port

            for stack_dp_port in range(num_switch_links):
                tagged_vlans = None

                peer_dp = None
                if stack_dp_port == 0:
                    if first_dp:
                        peer_dp = i + 1
                    else:
                        peer_dp = i - 1
                    if first_dp or second_dp:
                        peer_port = first_stack_port
                    else:
                        peer_port = first_stack_port + 1
                else:
                    peer_dp = i + 1
                    peer_port = first_stack_port

                description = 'to %s' % dp_name(peer_dp)

                interfaces_config[port] = {
                    'description': description,
                }

                if stack:
                    interfaces_config[port]['stack'] = {
                        'dp': dp_name(peer_dp),
                        'port': peer_port,
                    }
                else:
                    if n_tagged and n_untagged and n_tagged != n_untagged:
                        tagged_vlans = [tagged_vid, untagged_vid]
                    elif ((n_tagged and not n_untagged) or
                          (n_tagged and n_untagged and tagged_vid == untagged_vid)):
                        tagged_vlans = [tagged_vid]
                    elif n_untagged and not n_tagged:
                        tagged_vlans = [untagged_vid]

                    if tagged_vlans:
                        interfaces_config[port]['tagged_vlans'] = tagged_vlans

                add_acl_to_port(name, port, interfaces_config)
                port += 1

        def add_dp(name, dpid, i, dpid_count, stack,
                   n_tagged, tagged_vid, n_untagged, untagged_vid):
            dpid_ofchannel_log = ofchannel_log + str(i)
            dp_config = {
                'dp_id': int(dpid),
                'hardware': hardware,
                'ofchannel_log': dpid_ofchannel_log,
                'interfaces': {},
            }
            interfaces_config = dp_config['interfaces']

            port = 1
            for _ in range(n_tagged):
                interfaces_config[port] = {
                    'tagged_vlans': [tagged_vid],
                    'description': 'b%i' % port,
                }
                add_acl_to_port(name, port, interfaces_config)
                port += 1

            for _ in range(n_untagged):
                interfaces_config[port] = {
                    'native_vlan': untagged_vid,
                    'description': 'b%i' % port,
                }
                add_acl_to_port(name, port, interfaces_config)
                port += 1

            add_dp_to_dp_ports(
                dp_config, port, interfaces_config, i, dpid_count, stack,
                n_tagged, tagged_vid, n_untagged, untagged_vid)

            return dp_config

        config = {'version': 2}

        if include:
            config['include'] = list(include)

        if include_optional:
            config['include-optional'] = list(include_optional)

        config['vlans'] = add_vlans(
            n_tagged, tagged_vid, n_untagged, untagged_vid)

        config['acls'] = acls.copy()

        dpid_count = len(dpids)
        config['dps'] = {}

        for i, dpid in enumerate(dpids):
            name = dp_name(i)
            config['dps'][name] = add_dp(
                name, dpid, i, dpid_count, stack,
                n_tagged, tagged_vid, n_untagged, untagged_vid)

        return yaml.dump(config, default_flow_style=False)

    def matching_flow_present(self, match, timeout=10, table_id=None,
                              actions=None, match_exact=None):
        """Find the first DP that has a flow that matches match."""
        for dpid in self.dpids:
            if self.matching_flow_present_on_dpid(
                    dpid, match, timeout=timeout,
                    table_id=table_id, actions=actions,
                    match_exact=match_exact):
                return True
        return False


class FaucetStringOfDPUntaggedTest(FaucetStringOfDPTest):

    NUM_DPS = 3

    def setUp(self):
        super(FaucetStringOfDPUntaggedTest, self).setUp()
        self.build_net(
            n_dps=self.NUM_DPS, n_untagged=self.NUM_HOSTS, untagged_vid=self.VID)
        self.start_net()

    def test_untagged(self):
        """All untagged hosts in multi switch topology can reach one another."""
        self.retry_net_ping()


class FaucetStringOfDPTaggedTest(FaucetStringOfDPTest):

    NUM_DPS = 3

    def setUp(self):
        super(FaucetStringOfDPTaggedTest, self).setUp()
        self.build_net(
            n_dps=self.NUM_DPS, n_tagged=self.NUM_HOSTS, tagged_vid=self.VID)
        self.start_net()

    def test_tagged(self):
        """All tagged hosts in multi switch topology can reach one another."""
        self.retry_net_ping()


class FaucetStackStringOfDPTaggedTest(FaucetStringOfDPTest):
    """Test topology of stacked datapaths with tagged hosts."""

    NUM_DPS = 3

    def setUp(self):
        super(FaucetStackStringOfDPTaggedTest, self).setUp()
        self.build_net(
            stack=True,
            n_dps=self.NUM_DPS,
            n_tagged=self.NUM_HOSTS,
            tagged_vid=self.VID)
        self.start_net()

    def test_tagged(self):
        """All tagged hosts in stack topology can reach each other."""
        self.retry_net_ping()


class FaucetStackStringOfDPUntaggedTest(FaucetStringOfDPTest):
    """Test topology of stacked datapaths with tagged hosts."""

    NUM_DPS = 2
    NUM_HOSTS = 2

    def setUp(self):
        super(FaucetStackStringOfDPUntaggedTest, self).setUp()
        self.build_net(
            stack=True,
            n_dps=self.NUM_DPS,
            n_untagged=self.NUM_HOSTS,
            untagged_vid=self.VID)
        self.start_net()

    def test_untagged(self):
        """All untagged hosts in stack topology can reach each other."""
        self.retry_net_ping()


class FaucetStringOfDPACLOverrideTest(FaucetStringOfDPTest):

    NUM_DPS = 1
    NUM_HOSTS = 2

    # ACL rules which will get overridden.
    ACLS = {
        1: [
            {'rule': {
                'dl_type': int('0x800', 16),
                'nw_proto': 6,
                'tp_dst': 5001,
                'actions': {
                    'allow': 1,
                },
            }},
            {'rule': {
                'dl_type': int('0x800', 16),
                'nw_proto': 6,
                'tp_dst': 5002,
                'actions': {
                    'allow': 0,
                },
            }},
            {'rule': {
                'actions': {
                    'allow': 1,
                },
            }},
        ],
    }

    # ACL rules which get put into an include-optional
    # file, then reloaded into FAUCET.
    ACLS_OVERRIDE = {
        1: [
            {'rule': {
                'dl_type': int('0x800', 16),
                'nw_proto': 6,
                'tp_dst': 5001,
                'actions': {
                    'allow': 0,
                },
            }},
            {'rule': {
                'dl_type': int('0x800', 16),
                'nw_proto': 6,
                'tp_dst': 5002,
                'actions': {
                    'allow': 1,
                },
            }},
            {'rule': {
                'actions': {
                    'allow': 1,
                },
            }},
        ],
    }

    # DP-to-acl_in port mapping.
    ACL_IN_DP = {
        'faucet-1': {
            # Port 1, acl_in = 1
            1: 1,
        },
    }

    def setUp(self):
        super(FaucetStringOfDPACLOverrideTest, self).setUp()
        self.acls_config = os.path.join(self.tmpdir, 'acls.yaml')
        self.build_net(
            n_dps=self.NUM_DPS,
            n_untagged=self.NUM_HOSTS,
            untagged_vid=self.VID,
            include_optional=[self.acls_config],
            acls=self.ACLS,
            acl_in_dp=self.ACL_IN_DP,
        )
        self.start_net()

    def test_port5001_blocked(self):
        """Test that TCP port 5001 is blocked."""
        self.ping_all_when_learned()
        first_host, second_host = self.net.hosts[0:2]
        self.verify_tp_dst_notblocked(5001, first_host, second_host)
        with open(self.acls_config, 'w') as config_file:
            config_file.write(self.get_config(acls=self.ACLS_OVERRIDE))
        self.verify_hup_faucet()
        self.verify_tp_dst_blocked(5001, first_host, second_host)

    def test_port5002_notblocked(self):
        """Test that TCP port 5002 is not blocked."""
        self.ping_all_when_learned()
        first_host, second_host = self.net.hosts[0:2]
        self.verify_tp_dst_blocked(5002, first_host, second_host)
        with open(self.acls_config, 'w') as config_file:
            config_file.write(self.get_config(acls=self.ACLS_OVERRIDE))
        self.verify_hup_faucet()
        self.verify_tp_dst_notblocked(5002, first_host, second_host)


class FaucetGroupTableTest(FaucetUntaggedTest):

    CONFIG = """
        group_table: True
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def test_group_exist(self):
        self.assertEqual(
            100,
            self.get_group_id_for_matching_flow(
                {u'dl_vlan': u'100', u'dl_dst': u'ff:ff:ff:ff:ff:ff'},
                table_id=self.FLOOD_TABLE))


class FaucetTaggedGroupTableTest(FaucetTaggedTest):

    CONFIG = """
        group_table: True
        interfaces:
            %(port_1)d:
                tagged_vlans: [100]
                description: "b1"
            %(port_2)d:
                tagged_vlans: [100]
                description: "b2"
            %(port_3)d:
                tagged_vlans: [100]
                description: "b3"
            %(port_4)d:
                tagged_vlans: [100]
                description: "b4"
"""

    def test_group_exist(self):
        self.assertEqual(
            100,
            self.get_group_id_for_matching_flow(
                {u'dl_vlan': u'100', u'dl_dst': u'ff:ff:ff:ff:ff:ff'},
                table_id=self.FLOOD_TABLE))


class FaucetGroupTableUntaggedIPv4RouteTest(FaucetUntaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
        faucet_vips: ["10.0.0.254/24"]
        routes:
            - route:
                ip_dst: "10.0.1.0/24"
                ip_gw: "10.0.0.1"
            - route:
                ip_dst: "10.0.2.0/24"
                ip_gw: "10.0.0.2"
            - route:
                ip_dst: "10.0.3.0/24"
                ip_gw: "10.0.0.2"
"""
    CONFIG = """
        arp_neighbor_timeout: 2
        max_resolve_backoff_time: 1
        group_table_routing: True
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def test_untagged(self):
        iperf_port = faucet_mininet_test_util.find_free_port(
            self.ports_sock, self._test_name())
        host_pair = self.net.hosts[:2]
        first_host, second_host = host_pair
        first_host_routed_ip = ipaddress.ip_interface(u'10.0.1.1/24')
        second_host_routed_ip = ipaddress.ip_interface(u'10.0.2.1/24')
        self.verify_ipv4_routing(
            first_host, first_host_routed_ip,
            second_host, second_host_routed_ip,
            iperf_port, with_group_table=True)
        self.swap_host_macs(first_host, second_host)
        self.verify_ipv4_routing(
            first_host, first_host_routed_ip,
            second_host, second_host_routed_ip,
            iperf_port, with_group_table=True)


class FaucetGroupUntaggedIPv6RouteTest(FaucetUntaggedTest):

    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
        faucet_vips: ["fc00::1:254/112"]
        routes:
            - route:
                ip_dst: "fc00::10:0/112"
                ip_gw: "fc00::1:1"
            - route:
                ip_dst: "fc00::20:0/112"
                ip_gw: "fc00::1:2"
            - route:
                ip_dst: "fc00::30:0/112"
                ip_gw: "fc00::1:2"
"""

    CONFIG = """
        arp_neighbor_timeout: 2
        max_resolve_backoff_time: 1
        group_table_routing: True
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def test_untagged(self):
        iperf_port = faucet_mininet_test_util.find_free_port(
            self.ports_sock, self._test_name())
        host_pair = self.net.hosts[:2]
        first_host, second_host = host_pair
        first_host_ip = ipaddress.ip_interface(u'fc00::1:1/112')
        second_host_ip = ipaddress.ip_interface(u'fc00::1:2/112')
        first_host_routed_ip = ipaddress.ip_interface(u'fc00::10:1/112')
        second_host_routed_ip = ipaddress.ip_interface(u'fc00::20:1/112')
        self.verify_ipv6_routing_pair(
            first_host, first_host_ip, first_host_routed_ip,
            second_host, second_host_ip, second_host_routed_ip,
            iperf_port, with_group_table=True)
        self.swap_host_macs(first_host, second_host)
        self.verify_ipv6_routing_pair(
            first_host, first_host_ip, first_host_routed_ip,
            second_host, second_host_ip, second_host_routed_ip,
            iperf_port, with_group_table=True)


class FaucetEthSrcMaskTest(FaucetUntaggedTest):
    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"

acls:
    1:
        - rule:
            eth_src: 0e:0d:00:00:00:00/ff:ff:00:00:00:00
            actions:
                allow: 1
        - rule:
            actions:
                allow: 0
"""
    CONFIG = """
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
                acl_in: 1
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def test_untagged(self):
        first_host, second_host = self.net.hosts[0:2]
        first_host.setMAC('0e:0d:00:00:00:99')
        self.retry_net_ping(hosts=(first_host, second_host))
        self.wait_nonzero_packet_count_flow(
            {u'dl_src': u'0e:0d:00:00:00:00/ff:ff:00:00:00:00'},
            table_id=self.PORT_ACL_TABLE)


class FaucetDestRewriteTest(FaucetUntaggedTest):
    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"

acls:
    1:
        - rule:
            dl_dst: "00:00:00:00:00:02"
            actions:
                allow: 1
                output:
                    dl_dst: "00:00:00:00:00:03"
        - rule:
            actions:
                allow: 1
"""
    CONFIG = """
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
                acl_in: 1
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def test_untagged(self):
        first_host, second_host = self.net.hosts[0:2]
        # we expect to see the rewritten mac address.
        tcpdump_filter = ('icmp and ether dst 00:00:00:00:00:03')
        tcpdump_txt = self.tcpdump_helper(
            second_host, tcpdump_filter, [
                lambda: first_host.cmd(
                    'arp -s %s %s' % (second_host.IP(), '00:00:00:00:00:02')),
                lambda: first_host.cmd('ping -c1 %s' % second_host.IP())])
        self.assertTrue(re.search(
            '%s: ICMP echo request' % second_host.IP(), tcpdump_txt))

    def verify_dest_rewrite(self, source_host, overridden_host, rewrite_host, tcpdump_host):
        overridden_host.setMAC('00:00:00:00:00:02')
        rewrite_host.setMAC('00:00:00:00:00:03')
        rewrite_host.cmd('arp -s %s %s' % (overridden_host.IP(), overridden_host.MAC()))
        rewrite_host.cmd('ping -c1 %s' % overridden_host.IP())
        self.wait_until_matching_flow(
            {u'dl_dst': u'00:00:00:00:00:03'},
            table_id=self.ETH_DST_TABLE,
            actions=[u'OUTPUT:%u' % self.port_map['port_3']])
        tcpdump_filter = ('icmp and ether src %s and ether dst %s' % (
            source_host.MAC(), rewrite_host.MAC()))
        tcpdump_txt = self.tcpdump_helper(
            tcpdump_host, tcpdump_filter, [
                lambda: source_host.cmd(
                    'arp -s %s %s' % (rewrite_host.IP(), overridden_host.MAC())),
                # this will fail if no reply
                lambda: self.one_ipv4_ping(
                    source_host, rewrite_host.IP(), require_host_learned=False)])
        # ping from h1 to h2.mac should appear in third host, and not second host, as
        # the acl should rewrite the dst mac.
        self.assertFalse(re.search(
            '%s: ICMP echo request' % rewrite_host.IP(), tcpdump_txt))

    def test_switching(self):
        """Tests that a acl can rewrite the destination mac address,
           and the packet will only go out the port of the new mac.
           (Continues through faucet pipeline)
        """
        source_host, overridden_host, rewrite_host = self.net.hosts[0:3]
        self.verify_dest_rewrite(
            source_host, overridden_host, rewrite_host, overridden_host)


@unittest.skip('use_idle_timeout unreliable')
class FaucetWithUseIdleTimeoutTest(FaucetUntaggedTest):
    CONFIG_GLOBAL = """
vlans:
    100:
        description: "untagged"
"""
    CONFIG = """
        timeout: 1
        use_idle_timeout: true
        interfaces:
            %(port_1)d:
                native_vlan: 100
                description: "b1"
            %(port_2)d:
                native_vlan: 100
                description: "b2"
            %(port_3)d:
                native_vlan: 100
                description: "b3"
            %(port_4)d:
                native_vlan: 100
                description: "b4"
"""

    def wait_for_host_removed(self, host, in_port, timeout=5):
        for _ in range(timeout):
            if not self.host_learned(host, in_port=in_port, timeout=1):
                return
        self.fail('host %s still learned' % host)

    def wait_for_flowremoved_msg(self, src_mac=None, dst_mac=None, timeout=30):
        pattern = "OFPFlowRemoved"
        mac = None
        if src_mac:
            pattern = "OFPFlowRemoved(.*)'eth_src': '%s'" % src_mac
            mac = src_mac
        if dst_mac:
            pattern = "OFPFlowRemoved(.*)'eth_dst': '%s'" % dst_mac
            mac = dst_mac
        for _ in range(timeout):
            for _, debug_log_name in self._get_ofchannel_logs():
                with open(debug_log_name) as debug_log:
                    debug = debug_log.read()
                if re.search(pattern, debug):
                    return
            time.sleep(1)
        self.fail('Not received OFPFlowRemoved for host %s' % mac)

    def wait_for_host_log_msg(self, host_mac, msg, timeout=15):
        controller = self._get_controller()
        count = 0
        for _ in range(timeout):
            count = controller.cmd('grep -c "%s %s" %s' % (
                msg, host_mac, self.env['faucet']['FAUCET_LOG']))
            if int(count) != 0:
                break
            time.sleep(1)
        self.assertGreaterEqual(
            int(count), 1, 'log msg "%s" for host %s not found' % (msg, host_mac))

    def test_untagged(self):
        self.ping_all_when_learned()
        first_host, second_host = self.net.hosts[:2]
        self.swap_host_macs(first_host, second_host)
        for host, port in (
                (first_host, self.port_map['port_1']),
                (second_host, self.port_map['port_2'])):
            self.wait_for_flowremoved_msg(src_mac=host.MAC())
            self.require_host_learned(host, in_port=int(port))


@unittest.skip('use_idle_timeout unreliable')
class FaucetWithUseIdleTimeoutRuleExpiredTest(FaucetWithUseIdleTimeoutTest):

    def test_untagged(self):
        """Host that is actively sending should have its dst rule renewed as the
        rule expires. Host that is not sending expires as usual.
        """
        self.ping_all_when_learned()
        first_host, second_host, third_host, fourth_host = self.net.hosts
        self.host_ipv4_alias(first_host, ipaddress.ip_interface(u'10.99.99.1/24'))
        first_host.cmd('arp -s %s %s' % (second_host.IP(), second_host.MAC()))
        first_host.cmd('timeout 120s ping -I 10.99.99.1 %s &' % second_host.IP())
        for host in (second_host, third_host, fourth_host):
            self.host_drop_all_ips(host)
        self.wait_for_host_log_msg(first_host.MAC(), 'refreshing host')
        self.assertTrue(self.host_learned(
            first_host, in_port=int(self.port_map['port_1'])))
        for host, port in (
                (second_host, self.port_map['port_2']),
                (third_host, self.port_map['port_3']),
                (fourth_host, self.port_map['port_4'])):
            self.wait_for_flowremoved_msg(src_mac=host.MAC())
            self.wait_for_host_log_msg(host.MAC(), 'expiring host')
            self.wait_for_host_removed(host, in_port=int(port))


class FaucetAuthenticationTest(FaucetTest):
    """Base class for the authentication tests """

    RUN_GAUGE = False
    pids = {}

    max_hosts = 3

    def tearDown(self):
        if self.net is not None:
            host = self.net.hosts[0]
            print "about to kill everything"
            for name, pid in self.pids.iteritems():
                host.cmd('kill ' + str(pid))

            self.net.stop()
        super(FaucetAuthenticationTest, self).tearDown()

    def setup_hosts(self, hosts):
        """Create wpa_supplicant config file for each authenticating host.
        Args:
            hosts (list<mininet.host>): host to create config for.
        """
        i = 0
        for host in hosts:
            username = 'hostuser{}'.format(i)
            password = 'hostpass{}'.format(i)
            i += 1

            wpa_conf = '''ctrl_interface=/var/run/wpa_supplicant
ctrl_interface_group=0
eapol_version=2
ap_scan=0
network={
key_mgmt=IEEE8021X
eap=TTLS MD5
identity="%s"
anonymous_identity="%s"
password="%s"
phase1="auth=MD5"
phase2="auth=PAP password=password"
eapol_flags=0
}''' % (username, username, password)
            host.cmd('''echo '{0}' > {1}/{2}.conf'''.format(wpa_conf, self.tmpdir, host.defaultIntf()))
 
    def get_users(self):
        """Get the hosts that are users (ie not the portal or controller hosts)
        Returns:
            list<mininet.host>
        """
        users = []
        for host in self.net.hosts:
            if host.name.startswith("h"):
                users.append(host)
        return users

    def find_host(self, hostname):
        """Find a host when given the name
        Args:
            hostname (str): name of host to find.
        """
        for host in self.net.hosts:
            if host.name == hostname:
                return host
        return None

    def logoff_dot1x(self, host, intf=None, wait=True):
        if intf is None:
            intf = host.defaultIntf()

        start_reload_count = self.get_configure_count()

        host.cmd('wpa_cli -i %s logoff' % intf)
        if wait:
            time.sleep(5)
            end_reload_count = self.get_configure_count()

            self.assertGreater(end_reload_count, start_reload_count)

    def logon_dot1x(self, host, intf=None, netns=None, wait=True):
        """Log on a host using dot1x
        Args:
            host (mininet.host): host to logon.
            intf (str): interface to logon with. if None uses host.defaultIntf()
        """

        if intf is None:
            intf = host.defaultIntf()

        for direction in ['in', 'out']:
            tcpdump_args = ' '.join((
                '-Q', direction,
                '-s 0',
                '-e',
                '-n',
                '-U',
                '-q',
                '-i %s' % intf,
                '-w %s/%s-%s.cap' % (self.tmpdir, intf, direction),
                '>/dev/null',
                '2>/dev/null',
            ))
            cmd = 'tcpdump %s &' % tcpdump_args
            if netns is None:
                host.cmd(cmd)
            else:
                host.cmdPrint('ip netns exec %s %s' % (netns, cmd))
            self.pids['%s-%s-%s-tcpdump' % (host.name, intf, direction)] = host.lastPid

        start_reload_count = self.get_configure_count()

        cmd = "wpa_supplicant -i{1} -Dwired -c{0}/{1}.conf -t -f {0}/wpa-{1}.log &".format(self.tmpdir, intf)
        if netns is None:
            host.cmd(cmd)
        else:
            host.cmdPrint('ip netns exec %s %s' %(netns , cmd))
        self.pids['wpa_supplicant-%s-%s' % (host.name, intf)] = host.lastPid

        # TODO make this loop a function so can be used by relogin.
        # TODO also probably add a more specific regex, and to be able to handle different conditions. e.g. authenticating.

        new_status = self.wpa_cli_status(host, intf)
        for i in range(20):
            if new_status == 'CONNECTING':
                if not wait:
                    print('not waiting')
                    break
            elif new_status == 'HELD':
                print('logging attemot failed. trying again')
                host.cmdPrint('wpa_cli -i %s logon' % intf)
            elif 'AUTHENTICATED' != new_status:
                break
            time.sleep(1)
            print('login attempt failed. trying again.')
            new_status = host.cmd('wpa_cli -i %s status' % intf)
            print(new_status)
        background_dhcpcd = ''
        if wait:
            background_dhcpcd = '&'
        cmds = ["ip addr flush %s" % intf, "dhcpcd --timeout 60 %s" % intf]
        for cmd in cmds:
            if netns is None:
                host.cmd(cmd)
            else:
                host.cmdPrint('ip netns exec %s %s' % (netns, cmd))

        host.defaultIntf().updateIP()
        if wait:
            end_reload_count = 0
            for i in range(20):
                end_reload_count = self.get_configure_count()
                if end_reload_count > start_reload_count:
                    break
                time.sleep(0.5)
            self.assertGreater(end_reload_count, start_reload_count, 'Host: %s. Intf: %s MAC: %s didn\'t cause config reload. wpa_cli status: %s.' % (host, intf, host.MAC(), new_status))
            self.assertLess(i, 3, 'logon has taken %d to reload. max allowable time 1.5seconds' % i)

    def wpa_cli_status(self, host, intf=None):
        if intf is None:
            intf = host.defautlIntf()
        status = host.cmd('wpa_cli -i %s status' % intf)
        
        pattern = 'Supplicant PAE state=\S*'
        for l in status.split('\n'):
            match = re.search(pattern, l)
            if match:
                return match.group(0).split('=')[1]


    def relogon_dot1x(self, host, intf=None, wait=True):
        """Log on a host using dot1x that has already logged on once.
        (tcpdump/wpa_supplicant already started, and has an ip address)
        """
        if intf is None:
            intf = host.defaultIntf()
        start_reload_count = self.get_configure_count()
        old_status = host.cmd('wpa_cli -i %s status' % intf)
        host.cmdPrint('wpa_cli -i %s logon > %s/wpa_cli-%s.log 2>&1' % (intf, self.tmpdir, host.name))

        new_status = self.wpa_cli_status(host, intf)
        for i in range(40):
            if new_status == 'CONNECTING':
                if not wait:
                    break
                time.sleep(1)
            elif new_status == 'AUTHENTICATED':
                time.sleep(10)
                break
            elif new_status == 'AUTHENTICATING':
                time.sleep(1)
            elif new_status == 'HELD':
                # authentication failed for some reason.
                # maybe restart wpa_supplicant?

                host.cmdPrint('wpa_cli note aboutToKillWpaSupp')
                host.cmdPrint('kill %s' % self.pids['wpa_supplicant-%s-%s' % (host.name, host.defaultIntf())])
#                host.cmdPrint('wpa_cli terminate')
#                host.cmdPrint('rm /var/run/wpa_supplicant/%s-%s' % (host.name, host.defaultIntf()))
                time.sleep(1)
                cmd = "wpa_supplicant -i{1} -Dwired -c{0}/{1}.conf -t -f {0}/wpa-{1}.log &".format(self.tmpdir, intf)
                host.cmdPrint(cmd)
                self.pids['wpa_supplicant-%s-%s' % (host.name, host.defaultIntf())] = host.lastPid
                time.sleep(2)
            else:
                time.sleep(1)
                print('unknown wpa status %s' % new_status)
#                host.cmdPrint('wpa_cli -i %s logon' % intf)

            new_status = self.wpa_cli_status(host, intf)
            print(new_status)

        print('relogon took %d loops' % i)
        if wait:
            end_reload_count = 0
            for i in range(20):
                end_reload_count = self.get_configure_count()
                if end_reload_count > start_reload_count:
                    break
                time.sleep(0.5)
            self.assertGreater(end_reload_count, start_reload_count, 'Host: %s. Intf: %s MAC: %s didn\'t cause config reload. wpa_cli status: %s.\nOld Status: %s' % (host, intf, host.MAC(), new_status, old_status))
            self.assertLess(i, 3, 'relogon has taken %d to reload. max allowable time 1.5seconds' % i)

    def fail_ping_ipv4(self, host, dst, retries=1, intf=None, netns=None):
        """Try to ping to a destination from a host.
        Args:
            host (mininet.host): source host.
            dst (str): destination ip address.
            retries (int): number of attempts.
            intf (str): interface to ping with, if none uses host.defaultIntf()
        """
        for i in range(retries):
            try:
                self.one_ipv4_ping(host, dst, retries=1, require_host_learned=False, intf=intf, netns=netns)
            except AssertionError:
                return
            time.sleep(1)
        self.fail('host %s + interface %s should not be able to ping %s' % (host.name, intf, dst))

    def check_http_connection(self, host, retries=3):
        """Test the http connectivity by wget-ing a webpage on 10.0.0.2
        Args:
            host (mininet.host): source.
            retries (int): number of attempts.
        Returns:
            True if download successful. False otherwise."""
        for _ in range(retries):
            # pylint: disable=no-member
            result = host.cmd("wget --output-document=- --quiet 10.0.0.2:{}/index.txt".format(self.ws_port))
            if re.search("This is a text file on a webserver", result) is not None:
                return True
        return False

    def run_controller(self, host):
        """Starts the authentication controller app.
        Args:
            host (mininet.host): host to start app on (generally the controller)
        """
        print 'Starting Controller ....'
        with open('/faucet-src/tests/config/auth.yaml', 'r') as f:
            httpconfig = f.read()

        config_values = {}
        config_values['tmpdir'] = self.tmpdir
        config_values['promport'] = self.prom_port
        config_values['logger_location'] = self.tmpdir + '/auth_app.log'
        config_values['portal'] = self.net.hosts[0].name
        config_values['intf'] = self.net.hosts[0].defaultIntf().name
        host.cmd('echo "%s" > %s/auth.yaml' % (httpconfig % config_values, self.tmpdir))
        host.cmd('cp -r /faucet-src %s/' % self.tmpdir)

        host.cmd('echo "%s" > %s/base-acls.yaml' % (self.CONFIG_BASE_ACL, self.tmpdir))

        faucet_acl = self.tmpdir + '/faucet-acl.yaml'
        base = self.tmpdir + '/base-acls.yaml'

        host.cmd('python3.5 {0}/faucet-src/faucet/rule_manager.py {1} {2} > {0}/rule_man.log 2> {0}/rule_man.err'.format(self.tmpdir, base, faucet_acl))

        pid = int(open(host.pid_file, 'r').read())
        open('%s/contr_pid' % self.tmpdir, 'w').write(str(pid))
        os.kill(pid, signal.SIGHUP)
        # send signal to faucet here. as we have just generated new acls. and it is already running.

        host.cmd('python3.5 {0}/faucet-src/faucet/auth_app.py --config  {0}/auth.yaml  > {0}/auth_app.txt 2> {0}/auth_app.err &'.format(self.tmpdir))
        print 'authentication controller app started'
        self.pids['auth_server'] = host.lastPid

        tcpdump_args = ' '.join((
            '-s 0',
            '-e',
            '-n',
            '-U',
            '-q',
            '-i %s-eth0' % host.name,
            '-w %s/%s-eth0.cap' % (self.tmpdir, host.name),
            '>/dev/null',
            '2>/dev/null',
        ))
        host.cmd('tcpdump %s &' % tcpdump_args)

        self.pids['tcpdump'] = host.lastPid

        print 'Controller started.'

    def create_hostapd_users_file(self, num_hosts):
        conf = ''
        for i in range(num_hosts):
            conf = '''%s\n"hostuser%d"   MD5     "hostpass%d"''' % (conf, i, i)

        with open('%s/hostapd.eap_user' % self.tmpdir, 'w+') as f:
            f.write(conf)

    def run_hostapd(self, host):
        """Compiles and starts the hostapd process.
        Args:
            host (mininet.host): host to run hostapd on.
        """
        # create the hostapd config files
        hostapd_config_cmd = ''
#        for vlan_id in range(3, 3 + self.max_hosts):
        ctrl_iface_dir = '%s/hostapd' % self.tmpdir
        intf = '%s-eth0' % host.name
        host.cmd('''echo "interface={3}\n
ctrl_interface={2}
driver=wired\n
logger_stdout=-1\n
logger_stdout_level=0\n
ieee8021x=1\n
eap_reauth_period=3600\n
use_pae_group_addr=0\n
eap_server=1\n
eap_user_file={1}/hostapd.eap_user\n" > {1}/{0}-wired.conf'''.format(host.name, self.tmpdir, ctrl_iface_dir, intf))
        hostapd_config_cmd = hostapd_config_cmd + ' {0}/{1}-wired.conf'.format(self.tmpdir, host.name)
#            host.cmdPrint('ip link add link {0}-eth0 name {0}-eth0.{1} type vlan id {1}'.format(host.name, vlan_id))
#            host.cmd('ip link set {0}-eth0.{1} up'.format(host.name, vlan_id))

        ctrl_iface_path = '%s/%s' % (ctrl_iface_dir, intf)
        self.assertLess(len( ctrl_iface_path), 108, 'hostapd ctrl socket cannot be larger than 108 bytes (including null terminator)\nWas: %d\n%s' % (len(ctrl_iface_path), ctrl_iface_path))

        print 'Starting hostapd ....'
        host.cmd('mkdir %s/hostapd' % self.tmpdir)
        self.create_hostapd_users_file(self.max_hosts)

        # start hostapd
        host.cmd('hostapd -dd {1} > {0}/hostapd.out 2>&1 &'.format(self.tmpdir, hostapd_config_cmd))
        self.pids['hostapd'] = host.lastPid
        
        tcpdump_args = ' '.join((
            '-s 0',
            '-e',
            '-n',
            '-U',
            '-q',
            '-i %s-eth1' % host.name,
            '-w %s/%s-eth1.cap' % (self.tmpdir, host.name),
            '>/dev/null',
            '2>/dev/null',
        ))
        host.cmd('tcpdump %s &' % tcpdump_args)
        self.pids['p1-tcpdump'] = host.lastPid

        tcpdump_args = ' '.join((
            '-s 0',
            '-e',
            '-n',
            '-U',
            '-q',
            '-i %s-eth0' % host.name,
            '-w %s/%s-eth0.cap' % (self.tmpdir, host.name),
            '>/dev/null',
            '2>/dev/null',
        ))
        host.cmd('tcpdump %s &' % tcpdump_args)
        self.pids['p0-tcpdump'] = host.lastPid

        # TODO is this still required?
        host.cmd('ping -i 0.1 10.0.0.2 &')
        self.pids['p0-ping'] = host.lastPid


    def make_dhcp_config(self, filename, intf, gw, dns):
        """Create configuration file for udhcpd.
        Args:
            filename (str): name of config file.
            intf: interface of server to listen on.
            gw (str): ip address of gateway
            dns (str): ip address of dns server
        """
        dns_template = """
start       10.0.0.20
end     10.0.0.250
option  subnet  255.255.255.0
option  domain  local
option  lease   300  # seconds
"""

        # Create a DHCP configuration file
        config = (
            'interface %s' % intf,
            dns_template,
            'option router %s' % gw,
            'option dns %s' % dns,
            '')
        with open(filename, 'w') as f:
            f.write('\n'.join(config))

    def start_dhcp_server(self, host, gw, dns):
        """Start DHCP server (udhcp) on host with specified DNS server
        Args:
            host (mininet.host): host to run udhcp server on.
            intf: interface of server to listen on.
            gw (str): ip address of gateway
            dns (str): ip address of dns server
        """
        print('* Starting DHCP server on', host, 'at', host.IP(), '\n')
        dhcp_config = '/tmp/%s-udhcpd.conf' % host
        self.make_dhcp_config(dhcp_config, host.defaultIntf(), gw, dns)
        host.cmd('udhcpd -f', dhcp_config,
                 '> %s/%s-dhcp.log 2>&1  &' % (self.tmpdir, host))

        tcpdump_args = ' '.join((
            '-s 0',
            '-e',
            '-n',
            '-U',
            '-q',
            '-i %s-eth0' % host.name,
            '-w %s/%s-eth0.cap' % (self.tmpdir, host.name),
            '>/dev/null',
            '2>/dev/null',
        ))
        host.cmd('tcpdump %s &' % tcpdump_args)
        self.pids['i-tcpdump'] = host.lastPid


    def setup(self):
        super(FaucetAuthenticationTest, self).setUp()


class FaucetAuthenticationSingleSwitchTest(FaucetAuthenticationTest):
    """Base Test class for single switch topology
    """
    ws_port = 0
    clients = []

    N_UNTAGGED = 5
    N_TAGGED = 0
    max_hosts = 3
    CONFIG_GLOBAL = faucet_mininet_test_util.gen_config_global(max_hosts)
    CONFIG_BASE_ACL = faucet_mininet_test_util.gen_base_config(max_hosts)
    CONFIG = faucet_mininet_test_util.gen_config(max_hosts)
    port_map = faucet_mininet_test_util.gen_port_map(N_UNTAGGED + N_TAGGED)

    def setUp(self):
        super(FaucetAuthenticationSingleSwitchTest, self).setUp()
       
        self.topo = self.topo_class(
            self.ports_sock, self._test_name(), dpids=[self.dpid], n_tagged=self.N_TAGGED, n_untagged=self.N_UNTAGGED)
       
        # do the base config thing here.
        open(self.tmpdir + '/faucet-acl.yaml', 'w').write(faucet_mininet_test_util.gen_faucet_acl(self.max_hosts) % self.port_map)

        self.start_net()
        self.start_programs()

    def start_programs(self):
        """Start the authentication controller app, hostapd, dhcp server, 'internet' webserver
        """
        # pylint: disable=unbalanced-tuple-unpacking
        portal, interweb = self.net.hosts[:2]
        # pylint: disable=no-member
        pid = int(open(self.net.controller.pid_file, 'r').read())
        self.net.controller.cmd('echo {} > {}/contr_pid'.format(pid, self.tmpdir))

        # pylint: disable=no-member
        contr_num = int(self.net.controller.name.split('-')[1]) % 255
        self.assertLess(int(contr_num), 255)
        self.net.addLink(
            portal,
            self.net.controller,
            params1={'ip': '192.168.%s.2/24' % contr_num},
            params2={'ip': '192.168.%s.3/24' % contr_num})
        self.one_ipv4_ping(portal, '192.168.%s.3' % contr_num, intf=('%s-eth1' % portal.name))
#        portal.setMAC('70:6f:72:74:61:6c', portal.defaultIntf())
        self.run_hostapd(portal)
        self.run_controller(self.net.controller)

        interweb.cmd('echo "This is a text file on a webserver" > index.txt')
        self.ws_port = faucet_mininet_test_util.find_free_port(
            self.ports_sock, self._test_name())

        interweb.cmd('python -m SimpleHTTPServer {0} &'.format(self.ws_port))

        self.clients = self.net.hosts[2:]
        self.setup_hosts(self.clients)

        self.start_dhcp_server(interweb, gw='10.0.0.2', dns='8.8.8.8')




class FaucetAuthMultiHostDiffPortTest(FaucetAuthenticationSingleSwitchTest):
    """Check if authenticated and unauthenticated users can communicate and of different authentication methods (1x & cp)"""

    def ping_between_hosts(self, users):
        """Ping between the specified host
        Args:
            users (list<mininet.host>): users to ping between.
                0 & 1 should be authenitcated.
                2 should be unauthenticated,
        """
        for user in users:
            user.defaultIntf().updateIP()

        h0 = users[0]
        h1 = users[1]
        h2 = users[2]
        h1_ip = ipaddress.ip_address(unicode(h1.IP()))
        # h2 will not have an ip via dhcp as they are unauthenticated, so give them one.
        h2.setIP('10.0.12.253')
        h2_ip = ipaddress.ip_address(unicode(h2.IP()))
        # ping between the authenticated hosts
        self.one_ipv4_ping(h0, h1_ip)
        self.one_ipv4_ping(h1, '10.0.0.2')

        #ping between an authenticated host and an unauthenticated host
        self.fail_ping_ipv4(h0, h2_ip)
        self.fail_ping_ipv4(h1, h2_ip)

        ploss = self.net.ping(hosts=[users[0], users[2]], timeout='5')
        self.assertAlmostEqual(ploss, 100)


    def test_onlydot1x(self):
        """Only authenticate through dot1x.
        At first h0 will logon (only h0 can ping), then h1 will logon (both can ping), h1 will then logoff (h0 should still be logged on, h1 logged off)"""
        h0 = self.clients[0]
        h1 = self.clients[1]

        self.logon_dot1x(h0)
        self.one_ipv4_ping(h0, '10.0.0.2')

        h1.setIP('10.0.0.10')

        self.fail_ping_ipv4(h1, '10.0.0.2')

        self.logon_dot1x(h1)
        time.sleep(5)
        self.ping_between_hosts(self.clients)

        self.logoff_dot1x(h1)

        self.fail_ping_ipv4(h1, h0.IP())
        self.fail_ping_ipv4(h1, '10.0.0.2')
        self.one_ipv4_ping(h0, '10.0.0.2')


class FaucetAuthMultiHostPerPortTest(FaucetAuthenticationSingleSwitchTest):
    """Config has multiple authenticating hosts on the same port.
    """
    mac_interfaces = {} # {'1': intefcae}
    max_vlan_hosts = 2
    def setUp(self):
        super(FaucetAuthMultiHostPerPortTest, self).setUp()
        h0 = self.clients[0]

        for i in range(self.max_vlan_hosts):
            mac_intf = '%s-mac%u' % (h0.name, i)

            self.mac_interfaces[str(i)] = mac_intf

            self.add_macvlan(h0, mac_intf)
            netns =  mac_intf + 'ns'
            h0.cmd('ip netns add %s' % netns)
            h0.cmd('ip link set %s netns %s' % (mac_intf, netns))

            h0.cmd('ip netns exec %s ip link set %s up' % (netns, mac_intf))

            username = 'hostuser{}'.format(i)
            password = 'hostpass{}'.format(i)

            wpa_conf = '''ctrl_interface=/var/run/wpa_supplicant
    ctrl_interface_group=0
    eapol_version=2
    ap_scan=0
    network={
    key_mgmt=IEEE8021X
    eap=TTLS MD5
    identity="%s"
    anonymous_identity="%s"
    password="%s"
    phase1="auth=MD5"
    phase2="auth=PAP password=password"
    eapol_flags=0
    }''' % (username, username, password)
            h0.cmd('''echo '{0}' > {1}/{2}.conf'''.format(wpa_conf, self.tmpdir, mac_intf))

    def tearDown(self):
        h0 = self.clients[0]

        for mac_intf in list(self.mac_interfaces.values()):
            netns = mac_intf + 'ns'
            h0.cmd('ip netns del %s' % netns)
        super(FaucetAuthMultiHostPerPortTest, self).tearDown()

    def get_macvlan_ip(self, h, intf):
        '''Get the IP address of a macvlan that is in an netns
        '''
        netns = intf + 'ns'
        cmd = "ip addr show dev %s" % intf
        ip_result = h.cmd('ip netns exec %s %s' % (netns, cmd))
        return re.findall('[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+', ip_result)[0]


#@unittest.skip('broken.')
class FaucetAuthTwoHostsPerPortTest(FaucetAuthMultiHostPerPortTest):

    max_vlan_hosts = 2

    def test_two_hosts_one_port(self):
        h0 = self.clients[0]
        interweb = self.net.hosts[1]

        self.logon_dot1x(h0)
        self.one_ipv4_ping(h0, interweb.IP())
        result = self.check_http_connection(h0)
        self.assertTrue(result)

        mac_intf = self.mac_interfaces['1']

        self.fail_ping_ipv4(h0, '10.0.0.2', intf=mac_intf)

        self.logon_dot1x(h0, intf=mac_intf)

        self.one_ipv4_ping(h0, interweb.IP(), intf=mac_intf)

        self.logoff_dot1x(h0)
        self.fail_ping_ipv4(h0, '10.0.0.2')

        self.relogon_dot1x(h0)
        self.one_ipv4_ping(h0, interweb.IP())

        self.logoff_dot1x(h0)
        self.fail_ping_ipv4(h0, '10.0.0.2')


class FaucetAuthMultiHostsTest(FaucetAuthenticationSingleSwitchTest):

    def test_multi_hosts_sequential(self):
        """Log X different users on on the different ports sequentially (each should complete before the next starts).
        Then Log them all off. Then back on again.
        """
        interweb = self.net.hosts[1]

        # get each intf going.
        for host in self.clients:
            self.logon_dot1x(host)
            self.one_ipv4_ping(host, interweb.IP(), retries=10)
        print('first logons complete')

        for host in self.clients:
            self.logoff_dot1x(host)
            self.fail_ping_ipv4(host, interweb.IP())
        print('logoffs complete')

        for host in self.clients:
            self.relogon_dot1x(host)
        print('relogons complete')


        passed = False
        for i in range(9):
            try:
                for host in self.clients:
                    print('ping after relogin')
                    self.one_ipv4_ping(host, interweb.IP(), retries=1)
                # if it makes it to here all pings have succeeded.
                passed = True
                break
            except AssertionError as e:
                print(e)
                print('try ping again')
        self.assertTrue(passed)

    @unittest.skip('currently broken')
    def test_multi_hosts_parallel(self):
        """Log X different users on on different ports in parallel.
        Then log them all off, and back on again. Each stage completes before the next.
        """
        interweb = self.net.hosts[1]

        # setup.
        # start tcpdump. (move this from logon to setup host.)
        # start wpa_supplicant

        # log all on.
        for h in self.clients:
            self.logon_dot1x(h, wait=False)
        for h in self.clients:
            h.defaultIntf().updateIP()
            self.one_ipv4_ping(h, interweb.IP(), retries=5)
        # log all off.       
        for h in self.clients:
            self.logoff_dot1x(h, wait=False)
        for h in self.clients:
            self.fail_ping_ipv4(h, interweb.IP(), retries=5)
        # log all back on again
        for h in self.clients:
            self.relogon_dot1x(h, wait=False)
        for h in self.clients:
            h.defaultIntf().updateIP()
            self.one_ipv4_ping(h, interweb.IP(), retries=10)

    @unittest.skip('currently broken')
    def test_multi_hosts_random_parallel(self):
        """Log X different users on and off randomly on different ports in parallel.
        """
        # How do we check if the host has successfully logged on or not?
        host_status = {}
        for i in range(5):
            for h in self.clients:
                status = self.wpa_cli_status(h)
                r = random.random() 
                if status == 'AUTHENTICATED':
                    # should we logoff?
                    if r <= 0.5:
                        self.logoff_dot1x(h, wait=False)
                        host_status[h.name] = 'logoff'
                elif status == 'LOGOFF':
                    # should we logon?
                    if r <= 0.5:
                        self.relogon_dot1x(h, wait=False)
                        host_status[h.name] = 'logon'
                elif status == 'CONNECTING':
                    pass
                elif status == None:
                    # first time?
                    if r <= 0.5:
                        self.logon_dot1x(h, wait=False)
                        host_status[h.name] = 'logon'
                else:
                    # do not know how to handle the status.
                    self.assertIsNotNone(status)
                    self.assertIsNone(status)
            if i == 1 or i == 3 or i == 4:
                for h in self.clients:
                    # dhcp completed?
                    h.defualtIntf().updateIP()
                    if host_status[h.name] == 'logon':
                        # this in effect gives >5 seconds for the logon to occur
                        self.one_ipv4_ping(h, interweb.IP(), retries=5)
                    elif host_status[h.name] == 'logoff':
                        # this has the effect of giving >5 seconds for logoff to occur.
                        self.fail_ping_ipv4(h, interweb.IP(), retries=5)


class FaucetAuthTenHostsTest(FaucetAuthMultiHostsTest):
    N_UNTAGGED = 12
    max_hosts = N_UNTAGGED - 2

    CONFIG = faucet_mininet_test_util.gen_config(max_hosts)
    CONFIG_GLOBAL = faucet_mininet_test_util.gen_config_global(max_hosts)
    CONFIG_BASE_ACL = faucet_mininet_test_util.gen_base_config(max_hosts)

    port_map = faucet_mininet_test_util.gen_port_map(N_UNTAGGED)


class FaucetAuthTwentyHostsTest(FaucetAuthMultiHostsTest):
    N_UNTAGGED = 22
    max_hosts = N_UNTAGGED - 2

    CONFIG = faucet_mininet_test_util.gen_config(max_hosts)
    CONFIG_GLOBAL = faucet_mininet_test_util.gen_config_global(max_hosts)
    CONFIG_BASE_ACL = faucet_mininet_test_util.gen_base_config(max_hosts)

    port_map = faucet_mininet_test_util.gen_port_map(N_UNTAGGED)


class FaucetAuth14HostsTest(FaucetAuthMultiHostsTest):
    N_UNTAGGED = 16
    max_hosts = N_UNTAGGED - 2

    CONFIG = faucet_mininet_test_util.gen_config(max_hosts)
    CONFIG_GLOBAL = faucet_mininet_test_util.gen_config_global(max_hosts)
    CONFIG_BASE_ACL = faucet_mininet_test_util.gen_base_config(max_hosts)

    port_map = faucet_mininet_test_util.gen_port_map(N_UNTAGGED)


class FaucetAuthTenHostsPerPortTest(FaucetAuthMultiHostPerPortTest):

    max_vlan_hosts = 10

    N_UNTAGGED = 12
    max_hosts = N_UNTAGGED - 2

    CONFIG = faucet_mininet_test_util.gen_config(max_hosts)
    CONFIG_GLOBAL = faucet_mininet_test_util.gen_config_global(max_hosts)
    CONFIG_BASE_ACL = faucet_mininet_test_util.gen_base_config(max_hosts)

    port_map = faucet_mininet_test_util.gen_port_map(N_UNTAGGED)


    def test_ten_hosts_one_port_sequential(self):
        """Log 10 different users on on the same port (using macvlans) sequentially (each should complete before the next starts).
        Then Log them all off. Then back on again. This takes a VERY LONG time to complete >15mins. 
        """
        h0 = self.clients[0]
        h1 = self.clients[1]
        h2 = self.clients[2]
        interweb = self.net.hosts[1]
        self.logon_dot1x(h2)
        self.logon_dot1x(h1)
        self.logon_dot1x(h0)

        self.one_ipv4_ping(h0, h1.IP())
        mac_intfs = self.mac_interfaces.values()

        # get each intf going.
        for intf in mac_intfs:
            netns = intf + 'ns'
            self.logon_dot1x(h0, intf=intf, netns=netns)
            macvlan_ip = self.get_macvlan_ip(h0, intf)
            self.assertTrue(macvlan_ip != '')
            self.assertTrue(macvlan_ip is not None)
            self.one_ipv4_ping(h1, macvlan_ip, retries=10)
        print('first logons complete')

        for intf in mac_intfs:
            self.logoff_dot1x(h0, intf=intf)
            macvlan_ip = self.get_macvlan_ip(h0, intf)
            self.fail_ping_ipv4(h0, h2.IP(), intf=intf, netns=intf+'ns')#macvlan_ip)
        print('logoffs complete')
        self.one_ipv4_ping(h0, interweb.IP())

        for intf in mac_intfs[1:]:
            self.relogon_dot1x(h0, intf=intf)
        print('relogons complete')
        self.one_ipv4_ping(h0, interweb.IP())
        print(datetime.now())
        passed = False
        for i in range(9):
            try:
                for intf in mac_intfs[1:]:
                    print('ping after relogin')
                    print(intf)
                    macvlan_ip = self.get_macvlan_ip(h0, intf)
                    print(macvlan_ip)
                    self.one_ipv4_ping(h0, h2.IP(), intf=intf, retries=1, netns=intf+'ns')
                # if it makes it to here all pings have succeeded.
                passed = True
                break
            except AssertionError as e:
                print(e)
                print('try ping again')
        self.assertTrue(passed)


class FaucetAuthNoLogOnTest(FaucetAuthenticationSingleSwitchTest):
    """Check the connectivity when the hosts are not authenticated"""

    def test_nologon(self):
        """Get the users to ping each other before anyone has authenticated
        """
        users = self.clients
        i = 20
        for user in users:
            i = i + 1
            host = user
            tcpdump_args = ' '.join((
                '-s 0',
                '-e',
                '-n',
                '-U',
                '-q',
                '-i %s-eth0' % host.name,
                '-w %s/%s-eth0.cap' % (self.tmpdir, host.name),
                '>/dev/null',
                '2>/dev/null',
            ))
            host.cmd('tcpdump %s &' % tcpdump_args)
            self.pids['i-tcpdump-%s' % host.name] = host.lastPid

            cmd = "ip addr flush {0} && dhcpcd --timeout 5 {0}".format(
                user.defaultIntf())
            user.cmd(cmd)
            # TODO check dhcp did not work.

            # give ip address so ping 'could' work (it won't).
            user.cmd('ip addr add 10.0.0.%d/24 dev %s' % (i, user.defaultIntf()))

        ploss = self.net.ping(hosts=users, timeout='5')
        self.assertAlmostEqual(ploss, 100)


class FaucetAuthDot1XLogonAndLogoffTest(FaucetAuthenticationSingleSwitchTest):
    """Log on using dot1x and log off"""

    def test_logoff(self):
        """Check that the user cannot go on the internet after logoff"""
        h0 = self.clients[0]
        interweb = self.net.hosts[1]

        self.logon_dot1x(h0)
        self.one_ipv4_ping(h0, interweb.IP())
        result = self.check_http_connection(h0)
        self.assertTrue(result)

        self.logoff_dot1x(h0)
        # TODO possibly poll wpa_cli status to check that the status has changed?
        #  instead of a sleep??

        self.fail_ping_ipv4(h0, '10.0.0.2')
        result = self.check_http_connection(h0)
        self.assertFalse(result)

        self.relogon_dot1x(h0)
        self.one_ipv4_ping(h0, interweb.IP())


class FaucetAuthDupLogonTest(FaucetAuthenticationSingleSwitchTest):
    """Tests various username and MAC address combinations that may or may not result in
    the configuration changing.
    """
    # TODO need to define what the correct behaviour is for these tests.

    def count_username_and_mac(self, mac, username):
        base = yaml.load(open('%s/base-acls.yaml' % self.tmpdir, 'r'))

        count = 0
        for acl_name, acl in list(base['acls'].items()):
            for obj in acl:
                if isinstance(obj, dict) and 'rule' in obj:
                    # normal faucet rule.
                    for _, rule in list(obj.items()):
                        if '_mac_' in rule and '_name_' in rule:
                            if username == rule['_name_'] and mac == rule['_mac_']:
                                count = count + 1
                elif isinstance(obj, dict):
                    # alias
                    for name, l in list(obj.items()):
                        for r in l:
                            r = r['rule']
                            if '_mac_' in r and '_name_' in r:
                                if username == r['_name_'] and mac == r['_mac_']:
                                    count = count + 1
                elif isinstance(obj, list):
                    for y in obj:
                        if isinstance(y, dict):
                            for _, r in list(y.items()):
                                if '_mac_' in r and '_name_' in r:
                                    if username == r['_name_'] and mac == r['_mac_']:
                                        count = count + 1
                        else:
                            # if change the rule_manager to allow lists of other types change this test. 
                            self.assertFalse(True, 'test doesnt support list of type: %s. value: %s' % (type(y), y))
                elif isinstance(obj, str) and obj == 'authed-rules':
                    print('obj is string')
                    pass
                else:
                    # if change rule_manager to allow other types change this test.
                    self.assertFalse(True, 'test doesnt support rule type: %s. value: %s' % (type(obj),obj))
        return count

    def test_same_user_same_mac_logon_2_same_port(self):
        """Tests that the same username and the same MAC logging onto the same port
        does not add to the base-config file on the second time.
        """
        h0 = self.clients[0]
        interweb = self.net.hosts[1]

        self.logon_dot1x(h0)
        self.one_ipv4_ping(h0, interweb.IP())

        # kill wpa_supplicant so we can attempt to logon again.
        h0.cmd('kill %d' % self.pids['wpa_supplicant-%s-%s' % (h0.name, h0.defaultIntf())])
        time.sleep(3)

        with open('%s/base-acls.yaml' % self.tmpdir, 'rw') as f:
            start_base = f.read()
        try:
            self.logon_dot1x(h0)
        except AssertionError:
            print('logon didnt reload config')
            pass
        else:
            self.assertTrue(False, 'logon should have assertion failed due to config being reloaded, when should be same as before (therefore no reload).')

        with open('%s/auth_app.log' % self.tmpdir, 'r') as auth_log:
            matches = re.findall('authenticated', auth_log.read())

            if matches[0] == 'deauthenticated' and matches[1] == 'authenticated' and matches[2] == 'deauthenticated':
                self.assertFalse(True)
        count = self.count_username_and_mac(h0.MAC(), 'hostuser0')
        self.assertEqual(count, 2)

        with open('%s/base-acls.yaml' % self.tmpdir, 'r') as f:
            end_base = f.read()
        self.assertTrue(end_base != '')
        self.assertTrue(end_base != None)
        self.assertTrue(start_base == end_base)

    def test_same_user_same_mac_logon_2_diff_port(self):
        """Tests that the same username and the same MAC address can logon on the different ports.
        The system is amiguous in that the first port to authenticate may or may not be logged off,
        when the second start the authentication process. TODO need to clarify what correct behavoiur should be.
        """
        h0, h1 = self.clients[0:2]
        interweb = self.net.hosts[1]

        self.logon_dot1x(h0)
        self.one_ipv4_ping(h0, interweb.IP())

        h1.setMAC(h0.MAC())

        h1.cmd('sed -i -e s/hostuser1/hostuser0/g %s/%s.conf' % (self.tmpdir, h1.defaultIntf()))
        h1.cmd('sed -i -e s/hostpass1/hostpass0/g %s/%s.conf' % (self.tmpdir, h1.defaultIntf()))

        self.logon_dot1x(h1)
        self.one_ipv4_ping(h1, interweb.IP())

        # TODO 
        # self.one_ipv4_ping(h0, interweb.IP())
        count = self.count_username_and_mac(h0.MAC(), 'hostuser1')
        self.assertGreaterEqual(count, 2)

    def test_same_user_diff_mac_logon_2_diff_port(self):
        """Tests that the same username with a different MAC address can logon on different ports.
        """
        h0, h1 = self.clients[0:2]
        interweb = self.net.hosts[1]

        self.logon_dot1x(h0)
        self.one_ipv4_ping(h0, interweb.IP())

        h1.cmd('sed -i -e s/hostuser1/hostuser0/g %s/%s.conf' % (self.tmpdir, h1.defaultIntf()))
        h1.cmd('sed -i -e s/hostpass1/hostpass0/g %s/%s.conf' % (self.tmpdir, h1.defaultIntf()))

        self.logon_dot1x(h1)
        self.one_ipv4_ping(h1, interweb.IP())

        h0_count = self.count_username_and_mac(h0.MAC(), 'hostuser0')
        h1_count = self.count_username_and_mac(h1.MAC(), 'hostuser0')
        self.assertEqual(h0_count, 2)
        self.assertEqual(h1_count, 2)
