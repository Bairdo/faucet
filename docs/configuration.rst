Configuration
=============


Faucet is configured with a YAML-based configuration file, ``faucet.yaml``.
The following is example demonstrating a few common features:

.. literalinclude:: ../etc/ryu/faucet/faucet.yaml
  :language: yaml
  :caption: faucet.yaml
  :name: faucet.yaml

The datapath ID may be specified as an integer or hex string (beginning with 0x).

A port not explicitly defined in the YAML configuration file will be left down and will drop all packets.

Gauge is configured similarly with, ``gauge.yaml``.
The following is example demonstrating a few common features:

.. literalinclude:: ../etc/ryu/faucet/gauge.yaml
  :language: yaml
  :caption: gauge.yaml
  :name: gauge.yaml

Verifying configuration
-----------------------

You can verify that your configuration is correct with the ``check_faucet_config`` script:

.. code:: console

  check_faucet_config /etc/ryu/faucet/faucet.yaml

Configuration examples
----------------------

For complete working examples of configuration features, see the unit tests, ``tests/faucet_mininet_test.py``.
For example, ``FaucetUntaggedACLTest`` shows how to configure an ACL to block a TCP port,
``FaucetTaggedIPv4RouteTest`` shows how to configure static IPv4 routing.

Applying configuration updates
------------------------------

You can update FAUCET's configuration by sending it a HUP signal.
This will cause it to apply the minimum number of flow changes to the switch(es), to implement the change.

.. code:: console

  pkill -HUP -f faucet.faucet

Configuration in separate files
-------------------------------

Extra DP, VLAN or ACL data can also be separated into different files and included into the main configuration file, as shown below. The ``include`` field is used for configuration files which are required to be loaded, and Faucet will log an error if there was a problem while loading a file. Files listed on ``include-optional`` will simply be skipped and a warning will be logged instead.

Files are parsed in order, and both absolute and relative (to the configuration file) paths are allowed. DPs, VLANs or ACLs defined in subsequent files overwrite previously defined ones with the same name.

``faucet.yaml``

.. code:: yaml

  include:
      - /etc/ryu/faucet/dps.yaml
      - /etc/ryu/faucet/vlans.yaml

  include-optional:
      - acls.yaml

``dps.yaml``

.. code:: yaml

  # Recursive include is allowed, if needed.
  # Again, relative paths are relative to this configuration file.
  include-optional:
      - override.yaml

  dps:
      test-switch-1:
          ...
      test-switch-2:
          ...

Configuration options
---------------------

Top Level
~~~~~~~~~
.. list-table:: Faucet.yaml
    :widths: 31 15 15 60
    :header-rows: 1


    * - Attribute
      - Type
      - Default
      - Description
    * - acls
      - dictionary
      - {}
      - Configuration specific to acls. The keys are names of each acl, and the
        values are config dictionaries holding the acl's configuration (see
        below).
    * - dps
      - dictionary
      - {}
      - Configuration specific to datapaths. The keys are names or dp_ids
        of each datapath, and the values are config dictionaries holding the
        datapath's configuration (see below).
    * - routers
      - dictionary
      - {}
      - Configuration specific to routers. The keys are names of each router,
        and the values are config dictionaries holding the router's
        configuration (see below).
    * - version
      - integer
      - 2
      - The config version. 2 is the only supported version.
    * - vlans
      - dictionary
      - {}
      - Configuration specific to vlans. The keys are names or vids of each
        vlan, and the values are config dictionaries holding the
        vlan's configuration (see below).

DP
~~
DP configuration is entered in the 'dps' configuration block. The 'dps'
configuration contains a dictionary of configuration blocks each
containing the configuration for one datapath. The keys can either be
string names given to the datapath, or the OFP datapath id.

.. csv-table:: dps/<dp name or id>/
    :file: dp.py.csv
    :widths: 31, 15, 15, 61
    :header-rows: 1
    :delim: #

Stacking (DP)
~~~~~~~~~~~~~
Stacking is configured in the dp configuration block and in the interface
configuration block. At the dp level the following attributes can be configured
withing the configuration block 'stack':

.. list-table:: dps/<dp name or id>/stack/
    :widths: 31 15 15 60
    :header-rows: 1

    * - Attribute
      - Type
      - Default
      - Description
    * - priority
      - integer
      - 0
      - setting any value for stack priority indicates that this datapath
        should be the root for the stacking topology.


Interfaces
~~~~~~~~~~
Configuration for each interface is entered in the 'interfaces' configuration
block withing the config for the datapath. Each interface configuration block
is a dictionary keyed by the interface name.

Defaults for groups of interfaces can also be configured under the
'interface-ranges' attribute within the datapath configuration block. These
provide default values for a number of interfaces which can be overwritten with
the config block for an individual interface. These are keyed with a string
containing a comma separated list of OFP port numbers, interface names or with
OFP port number ranges (eg. 1-6).

.. csv-table:: dps/<dp name or id>/interfaces/<interface name or OFP port number>/
    :file: port.py.csv
    :widths: 31, 15, 15, 61
    :header-rows: 1
    :delim: #

Stacking (Interfaces)
~~~~~~~~~~~~~~~~~~~~~
Stacking port configuration indicates how datapaths are connected when using
stacking. The configuration is found under the 'stack' attribute of an
interface configuration block. The following attributes can be configured:

.. list-table:: dps/<dp name or id>/interfaces/<interface name or port number/stack/
    :widths: 31 15 15 60
    :header-rows: 1

    * - Attribute
      - Type
      - Default
      - Description
    * - dp
      - integer or string
      - None
      - the name of dp_id of the dp connected to this port
    * - port
      - integer or string
      - None
      - the name or OFP port number of the interface on the remote dp connected
        to this interface.

Router
~~~~~~
Routers config is used to allow routing between vlans. Routers configuration
is entered in the 'routers' configuration block at the top level of the faucet
configuration file. Configuration for each router is an entry in the routers
dictionary and is keyed by a name for the router. The following attributes can
be configured:

.. list-table:: routers/<router name>/:
    :widths: 31 15 15 60
    :header-rows: 1

    * - Attribute
      - Type
      - Default
      - Description
    * - vlans
      - list of integers or strings
      - None
      - Enables inter-vlan routing on the given vlans


VLAN
~~~~

VLANs are configured in the 'vlans' configuration block at the top level of
the faucet config file. The config for each vlan is an entry keyed by its vid
or a name. The following attributes can be configured:

.. csv-table:: vlans/<vlan name or vid>/:
    :file: vlan.py.csv
    :widths: 31, 15, 15, 61
    :header-rows: 1
    :delim: #

Static Routes
~~~~~~~~~~~~~

Static routes are given as a list. Each entry in the list contains a dictionary
keyed with the keyword 'route' and contains a dictionary configuration block as
follows:

.. list-table:: vlans/<vlan name or vid>/routes/[list]/route/:
    :widths: 31 15 15 60
    :header-rows: 1

    * - Attribute
      - Type
      - Default
      - Description
    * - ip_dst
      - string (IP subnet)
      - None
      - The destination subnet.
    * - ip_gw
      - string (IP address)
      - None
      - The next hop for this route

ACLs
~~~~

ACLs are configured under the 'acls' configuration block. The acls block
contains a dictionary of individual acls each keyed by its name.

Each acl contains a list of rules, a packet will have the first matching rule
applied to it.

Each rule is a dictionary containing the single key 'rule' with the value the
matches and actions for the rule.

The matches are key/values based on the ryu RESTFul API.

.. list-table:: /acls/<acl name>/[list]/rule/actions
    :widths: 31 15 15 60
    :header-rows: 1

    * - Attribute
      - Type
      - Default
      - Description
    * - allow
      - boolean
      - False
      - If True allow the packet to continue through the Faucet pipeline, if
        False drop the packet.
    * - cookie
      - int, 0-2**16
      - defaults to datapath cookie value
      - If set, cookie on this flow will be set to this value.
    * - meter
      - string
      - None
      - meter to apply to the packet
    * - output
      - dict
      - None
      - used to output a packet directly. Details below.

The output action contains a dictionary with the following elements:

.. list-table:: /acls/<acl name>/[list]/rule/actions/output/
    :widths: 31 15 15 60
    :header-rows: 1

    * - set_fields
      - list of dicts
      - None
      - A list of fields to set with values, eg. eth_dst: "1:2:3:4:5:6"
    * - port
      - integer or string
      - None
      - The port to output the packet to.
    * - swap_vid
      - integer
      - None
      - Rewrite the vlan vid of the packet when outputting
    * - failover
      - dict
      - None
      - Output with a failover port (see below).

Failover is an experimental option, but can be configured as follows:

.. list-table:: /acls/<acl name>/[list]/rule/actions/output/failover/
    :widths: 31 15 15 60
    :header-rows: 1

    * - Attribute
      - Type
      - Default
      - Description
    * - group_id
      - integer
      - None
      - The OFP group id to use for the failover group
    * - ports
      - list
      - None
      - The list of ports the packet can be output through.

