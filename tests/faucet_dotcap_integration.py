#!/usr/bin/python
"""
Classes for testing the FAUCET and Authentication
methods (Dot1x and Capflow)
"""
import unittest
import time
import os
import sys
import re
import inspect
import shutil
import tempfile
import threading

from mininet.net import Mininet
from mininet.link import Intf
from mininet.node import OVSSwitch
from mininet.node import RemoteController
from mininet.cli import CLI

import faucet_mininet_test_base
from faucet_mininet_test import make_suite
from faucet_mininet_test import parse_args
import faucet_mininet_test_util



testdir = os.path.dirname(__file__)
srcdir = '../src/ryu_faucet/org/onfsdn/faucet'
sys.path.insert(0, os.path.abspath(os.path.join(testdir, srcdir)))

from config_parser import dp_parser

class InbandController(RemoteController):
    """The controller is one of the mininet hosts"""

    def checkListening(self):
        "Overridden to do nothing."
        return


class FaucetDot1xCapFlowController(RemoteController):
    """A controller that uses the integrated version """

    def __init__(self, name, **kwargs):
        self.ofctl_port = 8084
        RemoteController.__init__(self, name, **kwargs)
    
    def checkListening(self):
        "Overridden to do nothing."
        return


class MultiSwitch(OVSSwitch):
    "Custom Switch() subclass that connects to different controllers"

    def start(self, controllers):
        """get s1 to connect to c0 and s2 to c1"""
        i = int(self.name[1:]) - 1
        return OVSSwitch.start(self, [controllers[i]])


class FaucetIntegrationTest(faucet_mininet_test_base.FaucetTestBase):
    """Base class for the integration tests """

    RUN_GAUGE = False
#    script_path = os.path.join(
#        os.path.dirname(os.path.realpath(sys.argv[0])),
#        "dot1x_capflow_scripts")
    script_path = "/faucet-src/tests/dot1x_capflow_scripts" 

    def setUp(self):
        self.net = None
        self.dpid = "1"

#        self.v2_config_hashes, v2_dps = dp_parser('/faucet-src/tests/config/testconfigv2-1x.yaml', 'test_auth')
#        self.v2_dps_by_id = {}
#        for dp in v2_dps:
#            self.v2_dps_by_id[dp.dp_id] = dp
#        self.v2_dp = self.v2_dps_by_id[0x1]

        # copy config file from tests/config to /etc/ryu/faucet/facuet/yaml
        shutil.copyfile("/faucet-src/tests/config/testconfigv2-1x.yaml", "/etc/ryu/faucet/faucet.yaml")

        self.start_net()

    def tearDown(self):
        if self.net is not None:
            host = self.net.hosts[0]
            print "about to kill everything"
            print host.cmdPrint('/faucet-src/tests/scripts/kill.sh')
            print "should of killed everything"
            self.net.stop()

    def get_users(self):
        """
        Get the hosts that are users
        (ie not the portal or controller hosts)
        """
        users = []
        for host in self.net.hosts:
            if host.name.startswith("h"):
                users.append(host)
        return users

    def find_host(self, hostname):
        """Find a host when given the name"""
        for host in self.net.hosts:
            if host.name == hostname:
                return host
        return None

    def logon_capflow(self, host):
        """Log on a host using CapFlow"""
        cmd = "ip addr flush {0}-eth0 && dhclient {0}-eth0 -timeout 5".format(host.name)
        host.cmdPrint(cmd)
        host.cmdPrint("ip route add default via 172.17.0.1")
        host.cmdPrint('echo "nameserver 8.8.8.8" >> /etc/resolv.conf')
        cmd = 'lynx -cmd_script={0}_lynx'.format(
            os.path.join(self.script_path, host.name))
        host.cmdPrint(cmd)

    def logon_dot1x(self, host):
        """Log on a host using dot1x"""
        cmd = "{0}_wpa.sh".format(os.path.join(self.script_path, host.name))
        host.cmdPrint(cmd)
        time.sleep(2)
        cmd = "ip addr flush {0}-eth0 && dhcpcd {0}-eth0".format(host.name)
        host.cmdPrint(cmd)
        host.cmdPrint("ip route add default via 172.17.0.1")
        host.cmdPrint('echo "nameserver 8.8.8.8" >> /etc/resolv.conf')
        print host.cmdPrint("cat h0-wpa.txt")

    def fail_ping_ipv4(self, host, dst, retries=3):
        """Try to ping to a destination from a host. This should fail on all the retries"""
        self.require_host_learned(host)
        for _ in range(retries):
            ping_result = host.cmd('ping -c1 %s' % dst)
            print ping_result
            self.assertIsNone(re.search(self.ONE_GOOD_PING, ping_result))

    def check_http_connection(self, host, retries=3):
        """Test the http connectivity"""
        for _ in range(retries):
            result = host.cmdPrint("wget --output-document=- --quiet www.google.com/humans.txt")
            print result
            if re.search("Google is built by a large",result) is not None:
                return True
        return False

    def start_net(self):
        """Start Mininet."""
        os.system('pwd')
        os.system('ls scripts')
        #os.system('/faucet-src/tests/scripts/run_controller.sh')
        self.net = Mininet(build=False)
        c0 = self.net.addController(
            "c0",
            controller=FaucetDot1xCapFlowController,
            ip='127.0.0.1',
            port=6633,
            switch=OVSSwitch)
        c0.cmdPrint('/faucet-src/tests/scripts/run_controller.sh')

        switch1 = self.net.addSwitch(
            "s1", cls=OVSSwitch, inband=True, protocols=["OpenFlow13"])
#        switch1 = OVSSwitch('s1', inNamespace=False, protocols=["OpenFlow13"])
        switch1.start([c0])
#        print switch1.vsctl("set-controller tcp:127.0.0.1:6633")
        switch2 = self.net.addSwitch(
            "s2", cls=OVSSwitch, inband=False, protocols=["OpenFlow13"])
        self.net.addLink(switch1, switch2)
        print switch1.connected()
        portal = self.net.addHost(
            "portal", ip='10.0.12.3/24', mac="70:6f:72:74:61:6c")
        self.net.addLink(portal, switch1)
        self.net.addLink(
            portal,
            c0,
            params1={'ip': '10.0.13.2/24'},
            params2={'ip': '10.0.13.3/24'})
        #controllerHost = self.net.addHost(
        #    "contr", ip='10.0.10.2/24', mac='63:6f:6e:74:72:6f')
        #self.net.addLink(
        #    controllerHost, switch2, params2={'ip': '10.0.10.1/24'})

        for i in range(0, 3):
            host = self.net.addHost(
                "h{0}".format(i),
                mac="00:00:00:00:00:1{0}".format(i),
                privateDirs=['/etc/wpa_supplicant'])
            self.net.addLink(host, switch2)
            print host.cmdPrint('/faucet-src/tests/scripts/copyconfigs.sh', "host11{0}user".format(i),
                          "host11{0}pass".format(i))
            print host.cmdPrint("ls /etc/wpa_supplicant")
                        

        self.net.build()
        for iface in ['eth0', ]:
            # Connect the switch to the eth1 interface of this host machine
            Intf(iface, node=switch1)

        self.net.start()
        print "start portal"
        portal.cmdPrint('/faucet-src/tests/scripts/portal.sh')
        print "portal route"
        portal.cmdPrint('ip route add 10.0.0.0/8 dev portal-eth0')
        #print "controller route"
        #controllerHost.cmdPrint('ip route add 10.0.0.0/8 dev contr-eth0')
        #print "contorller rm"
        #controllerHost.cmdPrint('rm -r /var/run/wpa_supplicant') 
        os.system("ps aux")

class FaucetIntegrationCapFlowLogonTest(FaucetIntegrationTest):
    """Check if a user can logon successfully using CapFlow"""

    def test_capflowlogon(self):
        """Log on using CapFlow"""
        h0 = self.find_host("h0")
        self.logon_capflow(h0)
        self.one_ipv4_ping(h0, "www.google.co.nz")
        result = self.check_http_connection(h0)
        self.assertTrue(result)


class FaucetIntegrationSomeLoggedOnTest(FaucetIntegrationTest):
    """Check if authenticated and unauthenticated users can communicate"""

    def ping_between_hosts(self, users):
        """Ping between the specified hosts"""
        for user in users:
            user.defaultIntf().updateIP()

        #ping between the authenticated hosts
        ploss = self.net.ping(hosts=users[:2], timeout='5')
        self.assertAlmostEqual(ploss, 0)

        #ping between an authenticated host and an unauthenticated host
        ploss = self.net.ping(hosts=users[1:], timeout='5')
        self.assertAlmostEqual(ploss, 100)
        ploss = self.net.ping(hosts=[users[0], users[2]], timeout='5')
        self.assertAlmostEqual(ploss, 100)

    def test_onlycapflow(self):
        """Only authenticate through CapFlow """
        users = self.get_users()
        self.logon_capflow(users[0])
        self.logon_capflow(users[1])
        cmd = "ip addr flush {0}-eth0 && dhclient {0}-eth0".format(
            users[2].name)
        users[2].cmdPrint(cmd)
        self.ping_between_hosts(users)

    def test_onlydot1x(self):
        """Only authenticate through dot1x"""
        users = self.get_users()
        self.logon_dot1x(users[0])
        self.logon_dot1x(users[1])
        cmd = "ip addr flush {0}-eth0 && dhclient {0}-eth0".format(
            users[2].name)
        users[2].cmdPrint(cmd)
        self.ping_between_hosts(users)

    def test_bothauthentication(self):
        """Authenicate one user with dot1x and the other with CapFlow"""
        users = self.get_users()
        self.logon_dot1x(users[0])
        self.logon_capflow(users[1])
        cmd = "ip addr flush {0}-eth0 && dhclient {0}-eth0".format(
            users[2].name)
        users[2].cmdPrint(cmd)
        self.ping_between_hosts(users)


class FaucetIntegrationNoLogOnTest(FaucetIntegrationTest):
    """Check the connectivity when the hosts are not authenticated"""

    def test_nologon(self):
        """
        Get the users to ping each other 
        before anyone has authenticated
        """
        users = self.get_users()
        for user in users:
            cmd = "ip addr flush {0}-eth0 && dhclient {0}-eth0".format(
                user.name)
            user.cmdPrint(cmd)
            user.defaultIntf().updateIP()

        ploss = self.net.ping(hosts=users, timeout='5')
        self.assertAlmostEqual(ploss, 100)


class FaucetIntegrationDot1XLogonTest(FaucetIntegrationTest):
    """Check if a user can logon successfully using dot1x"""

    def test_dot1xlogon(self):
        """Log on using dot1x"""
        os.system("ps aux")
        h0 = self.find_host("h0")
        self.logon_dot1x(h0) 
        #CLI(self.net)
        self.one_ipv4_ping(h0, "172.17.0.1")
        result = self.check_http_connection(h0)
        self.assertTrue(result)


class FaucetIntegrationDot1XLogoffTest(FaucetIntegrationTest):
    """Log on using dot1x and log off"""

    def test_logoff(self):
        """Check that the user cannot go on the internet after logoff"""
        h0 = self.find_host("h0")
        self.logon_dot1x(h0)
        self.one_ipv4_ping(h0, "172.17.0.1")
        time.sleep(5)
        result = self.check_http_connection(h0)

        self.assertTrue(result)
        print h0.cmdPrint("wpa_cli logoff")
        #CLI(self.net) 
        time.sleep(1)
        self.fail_ping_ipv4(h0, "172.17.0.1")
        result = self.check_http_connection(h0)
        self.assertFalse(result)


class FaucetIntegrationCapFlowLogoffTest(FaucetIntegrationTest):
    """Log on using CapFlow and log off"""

    def test_logoff(self):
        """Check that the user cannot go on the internet after logoff"""
        h0 = self.find_host("h0")
        self.logon_capflow(h0)
        self.one_ipv4_ping(h0, "www.google.co.nz")
        result = self.check_http_connection(h0)
        self.assertTrue(result)
        h0.cmdPrint("timeout 10s curl http://10.0.12.3/loggedout")
        self.fail_ping_ipv4(h0, "www.google.co.nz")
        result = self.check_http_connection(h0)
        self.assertFalse(result)

def start_all_tests():
    """Start all the tests in this file"""

    requested_test_classes, clean, serial = parse_args()
    tests = unittest.TestSuite()
    root_tmpdir = tempfile.mkdtemp(prefix='faucet-tests-')
    ports_sock = os.path.join(root_tmpdir, 'ports-server')
    ports_server = threading.Thread(
        target=faucet_mininet_test_util.serve_ports, args=(ports_sock,))
    ports_server.setDaemon(True)
    ports_server.start()
    config = None
    for name, obj in inspect.getmembers(sys.modules[__name__]):
        if requested_test_classes and name not in requested_test_classes:
            continue

        if inspect.isclass(obj) and name.startswith("FaucetIntegration"):
            tests.addTest(make_suite(obj, config, root_tmpdir, ports_sock))
    unittest.TextTestRunner(verbosity=2).run(tests)


if __name__ == '__main__':
    start_all_tests()
