# Copyright (C) 2013 Nippon Telegraph and Telephone Corporation.
# Copyright (C) 2015 Brad Cowie, Christopher Lorier and Joe Stringer.
# Copyright (C) 2015 Research and Education Advanced Network New Zealand Ltd.
# Copyright (C) 2015--2017 The Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASISo
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import valve_of

# TODO: change this, maybe this can be rewritten easily
# possibly replace with a class for ACLs
def build_acl_entry(rule_conf, acl_allow_inst, port_num=None, vlan_vid=None):
    acl_inst = []
    match_dict = OrderedDict()
    if vlan_vid is not None:
        match_dict['vlan_vid'] = valve_of.vid_present(vlan_vid)
        print valve_of.match_from_dict(match_dict)

    for attrib, attrib_value in rule_conf.iteritems():
        if attrib == 'name':
            continue
        if attrib == 'in_port':
            continue
        if attrib == 'actions':
            allow = False
            allow_specified = False
            if 'allow' in attrib_value:
                allow_specified = True
                if attrib_value['allow'] == 1:
                    allow = True
            if 'mirror' in attrib_value:
                port_no = attrib_value['mirror']
                acl_inst.append(
                    valve_of.apply_actions([valve_of.output_port(port_no)]))
                if not allow_specified:
                    allow = True
            # if output selected, output packet now and exit pipeline.
            if 'output' in attrib_value:
                output_dict = attrib_value['output']
                output_actions = []
                # if destination rewriting selected, rewrite it.
                if 'dl_dst' in output_dict:
                    output_actions.append(
                        valve_of.set_eth_dst(output_dict['dl_dst']))
                # if vlan tag is specified, push it.
                if 'vlan_vid' in output_dict:
                    output_actions.extend(
                        valve_of.push_vlan_act(output_dict['vlan_vid']))
                # output to port
                port_no = output_dict['port']
                output_actions.append(valve_of.output_port(port_no))
                acl_inst.append(valve_of.apply_actions(output_actions))
                continue
            actions = []
            if 'dl_dst' in attrib_value:
         	    actions.append(valve_of.set_eth_dst(attrib_value["dl_dst"]))
            if "vlan_vid" in attrib_value:
                # TODO If the vlan is not already loaded, load it.
                print "vlan_vid " + str(attrib_value["vlan_vid"])
                actions.extend(valve_of.push_vlan_act(attrib_value["vlan_vid"]))
            if "pop_vlan" in attrib_value:
                actions.append(valve_of.pop_vlan())
#            if "ipv4_dst" in attrib_value:
#                print "found ipv4_dst"
#                actions.append(valve_of.set_ipv4_dst(attrib_value["ipv4_dst"]))


            acl_inst.append(valve_of.apply_actions(actions))


            if allow:
                acl_inst.append(acl_allow_inst)
        else:
            match_dict[attrib] = attrib_value
    if port_num is not None:
        match_dict['in_port'] = port_num
    acl_match = valve_of.match_from_dict(match_dict)
    return acl_match, acl_inst
