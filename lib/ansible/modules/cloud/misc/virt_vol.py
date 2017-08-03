#!/usr/bin/python
# -*- coding: utf-8 -*-

# (c) 2017, Sophie Herold <sophie@hemio.de>
#
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

ANSIBLE_METADATA = {'metadata_version': '1.0',
                    'status': ['preview'],
                    'supported_by': 'community'}


DOCUMENTATION = '''
---
module: virt_vol
author: "Sophie Herold (@sophie-h)"
version_added: "2.4"
short_description: Manage libvirt storage volumes
description:
    - Manage I(libvirt) storage volumes.
'''

EXAMPLES = '''
- virt_vol:
   pool: default
   name: mailserver-var
   capacity: 1 TB
   options:
    allocation: 0
'''

import re

fail = None

try:
    import libvirt
except ImportError:
    fail = 'The `libvirt` module is not importable. Check the requirements.'

try:
    from lxml import etree
except ImportError:
     fail = 'The `lxml` module is not importable. Check the requirements.'

from ansible.module_utils.basic import *

class LibvirtConnection(object):

    def __init__(self, uri, module, pool_name):

        self.module = module

        self.conn = libvirt.open(uri)

        if not self.conn:
            raise Exception("hypervisor connection failure")

        self.pool = self.conn.storagePoolLookupByName(pool_name)

    def define(self, xml):
        if not self.module.check_mode:
            return self.pool.createXML(xml)

class VirtStoragePool(object):

    def __init__(self, uri, module, pool_name):
        self.module = module
        self.uri = uri
        self.conn = LibvirtConnection(self.uri, self.module, pool_name)

    def getVolume(self, vol_name):
        try:
            return self.conn.pool.storageVolLookupByName(vol_name)
        except libvirt.libvirtError:
            return None
        
    def define(self, xml):
        return self.conn.define(xml)

class DictToXml:
    unit_fields = ["capacity", "allocation"]
    re_unit = re.compile(r"^\s*(\d+)\s*([a-zA-Z]*)\s*$")

    def __init__(self, root_name, data):
        self.root = etree.Element(root_name)
        self.append_data(self.root, data)

    def append_data(self, node, data):
        for field, value in data.items():
            child = etree.SubElement(node, field)
            if isinstance(value, dict):
                self.append_data(child, value)
            else:
                if field in self.unit_fields:
                    match = self.re_unit.match(str(value))
                    if match is None:
                        raise Exception("In '{}: {}': invalid unit".format(field,value))
                    child.text = match.group(1)
                    if match.group(2):
                        child.set("unit", match.group(2))
                else:
                    child.text = str(value)

    def to_string(self):
        return etree.tostring(self.root, pretty_print=True)

def core(module):

    pool      = module.params['pool']
    name      = module.params['name']
    capacity  = module.params['capacity']
    options   = module.params['options']
    uri       = module.params['uri']

    v = VirtStoragePool(uri, module, pool)

    options['name'] = name
    options['capacity'] = capacity
    
    if v.getVolume(name) is None:
        v.define(DictToXml('volume', options).to_string())
        module.exit_json(changed = True)
    else:
        module.exit_json(changed = False)  

def main():

    if fail:
        module.fail_json(msg = fail)

    module = AnsibleModule (
        argument_spec = dict(
            pool = dict(required=True),
            name = dict(required=True, aliases=['volume']),
            capacity = dict(required=True),
            #resize = dict(default='disabled', choices=['disabled'])
            options = dict(default=dict(), type='dict'),
            uri = dict(default='qemu:///system'),
        ),
        supports_check_mode = True
    )

    try:
        result = core(module)
    except Exception as e:
        module.fail_json(msg=repr(e))

    module.exit_json(**result)

if __name__ == '__main__':
    main()
