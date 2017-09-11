#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import absolute_import, division, print_function
__metaclass__ = type


ANSIBLE_METADATA = {'metadata_version': '1.1'}


DOCUMENTATION = '''
---
module: libvirt_dom
short_description: Manages virtual machines supported by libvirt
description:
  - Manages domains (virtual machines or containers) through I(libvirt).
  - All available domain properties can be defined via libvirt's XML format.
  - Some options like the number of CPUs can be specified as module options. If settings are specified via module options, they take precedence over the XML options.
  - Options that are available als domain options are also adjsuted on running domains.
  - If the I(xml) argument is given and the I(status) option is set to I(defined), atomic updates are not supported. An existing domain definition will be completely overwritten.
version_added: 2.4
options:
  autostart:
    description: Autostart
    type: bool
  cpus:
    description: CPUs
    type: int
  cpus_max:
    description: Max. CPUs
    type: int
  hypervisor_uri:
    description: Hypervisor URI
  memory:
    description: Memory
  memory_max:
    description: Max. Memory
  name:
    description: Name
  state:
    description: State
    choices: ['running', 'paused', 'shut-off', 'info']
  status:
    description: Status
    choices: ['defined', 'transient', 'undefined']
  timeout:
    description: |
      Time in seconds until operations like starting a domain are considered
      failed.
    default: 120
    type: int
  title:
    description: Title
  type:
    description: Type
  uuid:
    description: UUID
  xml:
    description: XML
    default: '<domain></domain>'
requirements:
    - python >= 2.6
    - python-libvirt
    - python-lxml
notes:
  - '**OPEN QUESTIONS**'
  - Should domains be renamed if uuid and name is given and the name differs?
  - '**NOTES**'
  - A task might include more then one operation that can timeout. Therefore, the total runtime of task can be a multiple of the timeout.
author:
  - Sophie Herold (@sophie-h)
'''

EXAMPLES = '''
- name: ensure that vm1 is started
  libvirt_dom:
    name: vm1
    state: running


'''

RETURN = '''

'''

from ansible.module_utils import virt
from ansible.module_utils.basic import AnsibleModule, env_fallback
import libvirt
from lxml import etree
import time

from ansible.module_utils.virt import x_set, x_elem, x_default, x_get

def update_xml(xml, params):

    if params['name']:
        x_set(xml, 'name', params['name'])

    if params['title']:
        x_set(xml, 'title', params['title'])

    if params['uuid']:
        x_set(xml, 'uuid', params['uuid'])

    if params['type']:
        xml.set('type', params['type'])

    if params['memory']:
        x_set(xml, 'currentMemory', virt.Memory(params['memory']))

    if params['memory_max']:
        x_set(xml, 'memory', virt.Memory(params['memory_max']))

    if params['cpus']:
        # libvirt errors if vcpu.text (i.e. max. cpus) is missing
        x_default(xml, 'vcpu', params['cpus'])
        x_elem(xml, 'vcpu').set('current', str(params['cpus']))

    if params['cpus_max']:
        x_set(xml, 'vcpu', params['cpus_max'])

    x_default(xml, ['os', 'type'], 'hvm')


def get_domain(xml, conn, inter):
    if x_get(xml, 'uuid'):
        try:
            return virt.Domain(conn.lookupByUUIDString(x_get(xml, 'uuid')), inter)
        except libvirt.libvirtError:
            return None
    elif x_get(xml, 'name'):
        try:
            return virt.Domain(conn.lookupByName(x_get(xml, 'name')), inter)
        except libvirt.libvirtError:
            return None
    else:
        raise virt.Error('Either `name` or `uuid` must be specified.')

def core(module):

    inter = virt.ModuleInteraction(module)
    params = module.params

    if params['state'] == 'info' and params['status']:
        raise virt.Error("`state: info` does not allow definition of `status`")

    if params['status'] == 'undefined' and params['state']:
        raise virt.Error(
            "`status: undefined` does not allow definition of `state`")

    xml = etree.fromstring(params['xml'])
    update_xml(xml, params)
    xmlstr = etree.tostring(xml)
    xmlobj = virt.DomainXml(xmlstr)
    inter.result['xml'] = xmlstr

    conn = virt.connect(params)

    domain = get_domain(xml, conn, inter)

    if not domain:
        if params['status'] == 'defined':
            domain = virt.Domain(conn.defineXML(xmlstr), inter)
        elif params['status'] == 'transient':
            domain = virt.Domain(conn.createXML(xmlstr), inter)
    else:
        if params['status'] == 'transient' and domain.handle.isPersistent():
            domain.handle.undefine()
        if params['status'] == 'defined' and not domain.handle.isPersistent():
            conn.defineXML(xmlstr)
        elif params['status'] == 'undefined':
            domain.undefine()
            domain = None

    if params['state']:
        domain.ensure_state(params['state'])
        inter.result['off']= 'off'

    if domain and params['status']:
        if params['affect'] == 'live':
            if not domain.state().running():
                raise virt.Error("Domain must be running to apply live changes")
            else:
                domain.adjust_atomic(xmlobj, 'live')
        
        if params['affect'] == 'config':
            domain.adjust_atomic(xmlobj, 'config')
            
        if params['affect'] == 'applicable':
            if domain.handle.isPersistent():
                domain.adjust_atomic(xmlobj, 'config')
            if domain.state().running():
                domain.adjust_atomic(xmlobj, 'live')

    return inter

def main():
    module = AnsibleModule(
        argument_spec=dict(
            affect=dict(
                default='applicable',
                choices=['applicable', 'config', 'live']),
            autostart=dict(type='bool'),
            cpus=dict(type='int'),
            cpus_max=dict(type='int'),
            hypervisor_uri=dict(),
            memory=dict(),
            memory_max=dict(),
            name=dict(),
            state=dict(choices=['running', 'paused', 'shut-off', 'info']),
            status=dict(choices=['defined', 'transient', 'undefined']),
            timeout=dict(
                default=120,
                type='int',
                fallback=(env_fallback, ['ANSIBLE_LIBVIRT_TIMEOUT'])),
            title=dict(),
            type=dict(),
            uuid=dict(),
            xml=dict(default='<domain></domain>'),
        ),
        required_one_of=[['name', 'uuid', 'xml']],
        supports_check_mode=True,
    )

    try:
        core(module).exit()
    except virt.Error as err:
        if err.inter:
            err.inter.error = err
            err.inter.exit()
        else:
            module.fail_json(msg=str(err))

if __name__ == '__main__':
    main()
