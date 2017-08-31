#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import absolute_import, division, print_function
__metaclass__ = type


ANSIBLE_METADATA = {'metadata_version': '1.0',
                    'status': ['preview'],
                    'supported_by': 'community'}


DOCUMENTATION = '''
---
module: libvirt_dom
short_description: Manages virtual machines supported by libvirt
description:
     - Manages virtual machines supported by I(libvirt).
version_added: "0.2"
options:
  name:
    description:
      - name of the guest VM being managed. Note that VM must be previously
        defined with xml.
    required: true
    default: null
    aliases: []
  state:
    description:
      - Note that there may be some lag for state requests like C(shutdown)
        since these refer only to VM states. After starting a guest, it may not
        be immediately accessible.
    required: false
    choices: [ "running", "shutdown", "destroyed", "paused" ]
    default: "no"
  command:
    description:
      - in addition to state management, various non-idempotent commands are available. See examples
    required: false
    choices: ["create","status", "start", "stop", "pause", "unpause",
              "shutdown", "undefine", "destroy", "get_xml",
              "freemem", "list_vms", "info", "nodeinfo", "virttype", "define"]
  autostart:
    description:
      - start VM at host startup
    choices: [True, False]
    version_added: "2.3"
    default: null
  uri:
    description:
      - libvirt connection uri
    required: false
    default: qemu:///system
  xml:
    description:
      - XML document used with the define command
    required: false
    default: null
requirements:
    - "python >= 2.6"
    - "libvirt-python"
author:
    - "Ansible Core Team"
    - "Michael DeHaan"
    - "Seth Vidal"
'''

EXAMPLES = '''

'''

RETURN = '''

'''

from ansible.module_utils import virt
from ansible.module_utils.basic import AnsibleModule
import libvirt
from lxml import etree

from ansible.module_utils.virt import x_set, x_elem, x_default, x_get

def update_xml(xml, params):

    if params['name']:
        x_set(xml, 'name', params['name'])

    if params['title']:
        x_set(xml, 'title', params['title'])

    if not params['uuid']:
        # default is to remove uuid
        for e in xml.xpath('uuid'):
            xml.remove(e)
    elif params['uuid'] != 'FROM_XML':
        x_set(xml, 'uuid', params['uuid'])

    if params['type']:
        xml.set('type', params['type'])

    if params['memory']:
        x_set(xml, 'currentMemory', virt.Memory(params['memory']))

    if params['max_memory']:
        x_set(xml, 'memory', virt.Memory(params['max_memory']))

    if params['cpus']:
        # libvirt errors if vcpu.text (i.e. max. cpus) is missing
        x_default(xml, 'vcpu', params['cpus'])
        x_elem(xml, 'vcpu').set('current', str(params['cpus']))

    if params['max_cpus']:
        x_set(xml, 'vcpu', params['max_cpus'])

    x_default(xml, ['os', 'type'], 'hvm')

def core(module):

    params = module.params

    xml = etree.fromstring(params['xml'])
    update_xml(xml, params)
    xmlstr = etree.tostring(xml)
    conn = libvirt.open(params['hypervisor_uri'])

    vm = None
    if x_get(xml, 'uuid'):
        try:
            vm = conn.lookupByUUIDString(x_get(xml, 'uuid'))
        except libvirt.libvirtError:
            pass
    elif x_get(xml, 'name'):
        try:
            vm = conn.lookupByName(x_get(xml, 'name'))
        except libvirt.libvirtError:
            pass
    
    if not vm:
        if params['status'] == 'defined':
            conn.defineXML(xmlstr)
        elif params['status'] == 'transient':
            conn.createXML(xmlstr)
    
    if vm and params['status'] == 'undefined':
        if vm.isPersistent():
            vm.undefine()
            try:
                vm.destroy()
            except libvirt.libvirtError:
                # occurs if vm was not running on undefine
                pass
        else:
            vm.destroy()
      

    print(xmlstr)
    
    return {'changed': True, 'xml': xmlstr, 'ud':str(1)}

def main():

    module = AnsibleModule(
        argument_spec=dict(
            state=dict(choices=['running', 'paused', 'shut-off', 'info']),
            status=dict(choices=['defined', 'transient', 'undefined']),
            name=dict(),        
            title=dict(),
            uuid=dict(),
            type=dict(),
            memory=dict(),
            max_memory=dict(),
            cpus=dict(type='int'),
            max_cpus=dict(type='int'),
            xml=dict(default='<domain></domain>'),
            hypervisor_uri=dict(),
            autostart=dict(type='bool'),
        ),
        
    )

    result = core(module)

    module.exit_json(**result)

if __name__ == '__main__':
    main()

