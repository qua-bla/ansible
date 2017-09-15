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
    description: Current number of CPUs
    type: int
  cpus_max:
    description: Maximum number of CPUs
    type: int
  hypervisor_uri:
    description: Hypervisor URI
  memory:
    description: Current amount of memory
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
    description: Virtualization type (KVM etc.)
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
- name: provision running vm
  libvirt_dom:
    name: vm2
    title: KVM Machine 2
    state: running
    status: defined
    affect: config
    cpus: 2
    memory: 100 MB
    type: kvm
'''

RETURN = '''

'''

from ansible.module_utils.basic import AnsibleModule, env_fallback
from ansible.module_utils import libvirt_common as virt
from ansible.module_utils.libvirt_common import x_set, x_default, x_get
from libvirt import libvirtError
from lxml import etree

def update_xml(domxml, params):

    if params['name']:
        x_set(domxml.xml, 'name', params['name'])

    if params['title']:
        x_set(domxml.xml, 'title', params['title'])

    if params['uuid']:
        x_set(domxml.xml, 'uuid', params['uuid'])

    if params['type']:
        domxml.xml.set('type', params['type'])

    if params['memory']:
        # libvirt errors if max. memory is missing
        domxml.set_memory_max(virt.Memory(params['memory']), default=True)
        domxml.set_memory(virt.Memory(params['memory']))

    if params['memory_max']:
        domxml.set_memory_max(virt.Memory(params['memory_max']))

    if params['cpus']:
        # libvirt errors if max. CPUs is missing
        domxml.set_cpus_max(params['cpus'], default=True)
        domxml.set_cpus(params['cpus'])

    if params['cpus_max']:
        domxml.set_cpus_max(params['cpus_max'])

    x_default(domxml.xml, ['os', 'type'], 'hvm')


def get_domain(xml, conn, inter):
    if x_get(xml, 'uuid'):
        try:
            return virt.Domain(conn.lookupByUUIDString(x_get(xml, 'uuid')), inter)
        except libvirtError:
            return None
    elif x_get(xml, 'name'):
        try:
            return virt.Domain(conn.lookupByName(x_get(xml, 'name')), inter)
        except libvirtError:
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

    if params['timeout']:
        virt.Connection.timeout = params['timeout']*1000

    xmlobj = virt.DomainXml(params['xml'])
    update_xml(xmlobj, params)
    xmlstr = etree.tostring(xmlobj.xml)
    inter.result['xml'] = xmlstr

    conn = virt.connect(params)

    domain = get_domain(xmlobj.xml, conn, inter)

    if not domain:
        if params['status'] == 'defined':
            # TODO: checkmode
            domain = virt.Domain(conn.defineXML(xmlstr), inter)
        elif params['status'] == 'transient':
            # TODO: checkmode
            domain = virt.Domain(conn.createXML(xmlstr), inter)
    else:
        if params['status'] == 'transient' and domain.handle.isPersistent():
            domain.handle.undefine()
        if params['status'] == 'defined' and not domain.handle.isPersistent():
            # TODO: checkmode
            conn.defineXML(xmlstr)
        elif params['status'] == 'undefined':
            domain.undefine_full()
            domain = None

    if params['state']:
        domain.ensure_state(params['state'])

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
            module.fail_json(msg=err.msg)

if __name__ == '__main__':
    main()
