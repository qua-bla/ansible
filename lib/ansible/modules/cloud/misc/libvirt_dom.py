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

def x_list(element):
    if type(element) is str:
        return [element]
    else:
        return element

def x_elem(parent, element):
    element = x_list(element)

    for tag in element:
        elem = parent.find(tag)
        if elem is None:
            elem = etree.SubElement(parent, tag)
        parent = elem
        
    return parent

def x_get(parent, element, unit=False):
    element = x_list(element)

    e = xml.xpath('/'.join(element))
    
    if e is None:
        return None
    
    if unit:
        return virt.Memory(e.text, e.get('unit', 'B'))
        
    return e

def x_set(parent, element, value):
    e = x_elem(parent, element)
    
    if isinstance(value, virt.Memory):
        e.text = str(value.size)
        e.set('unit', value.unit)
    else:
        e.text = str(value)
    
    return e

def x_default(parent, element, value):
    element = x_list(element)

    if not parent.xpath('/'.join(element)):
        x_set(parent, element, value)

def update_xml(xml, params):
    
    xml.set('type', params['type'])

    if params['cpus']:
        x_default(xml, 'vcpu', params['cpus'])
        x_elem(xml, 'vcpu').set('current', str(params['cpus']))

    if params['max_cpus']:
        x_set(xml, 'vcpu', params['max_cpus'])

    if params['memory']:
        x_set(xml, 'currentMemory', virt.Memory(params['memory']))
    
    if params['max_memory']:
        x_set(xml, 'memory', virt.Memory(params['max_memory']))
    
    x_default(xml, ['os', 'type'], 'hvm')

def core(module):

    xml = etree.fromstring(module.params['xml'])
    
    update_xml(xml, module.params)
       
    xmlstr = etree.tostring(xml)
    
    #conn = libvirt.open()
    #conn.createXML(xmlstr)
    
    return {'changed': True, 'xml': xmlstr}

def main():

    module = AnsibleModule(argument_spec=dict(
        state=dict(choices=['running', 'paused', 'shut-off', 'info'], required=True),
        status=dict(choices=['defined', 'transient', 'undefined']),
        persistent=dict(default=True, type='bool'),
        name=dict(),        
        uuid=dict(),
        type=dict(),
        autostart=dict(type='bool'),
        title=dict(),
        memory=dict(),
        max_memory=dict(),
        cpus=dict(type='int'),
        max_cpus=dict(type='int'),
        uri=dict(),
        xml=dict(default='<domain></domain>'),
    ))

    result = core(module)

    module.exit_json(**result)

if __name__ == '__main__':
    main()

