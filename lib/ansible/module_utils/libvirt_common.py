# -*- coding: utf-8 -*-
#

import re
import signal

import libvirt
from lxml import etree
import syslog

__metaclass__ = type

class Connection:
    init = False
    timeoutInterval = 200
    runtime = 0
    timeout = 3000
    exception = None
    stopPolling = False
    action = ''
    on_deregister = None

    def __init__(self):
        libvirt.virEventRegisterDefaultImpl()
        libvirt.virEventAddTimeout(
            Connection.timeoutInterval,
            Connection.timeout_callback,
            None)
        signal.signal(signal.SIGINT, Connection.signal_handler)
        Connection.init = True

    @staticmethod
    def event_poll():
        exception = Connection.exception
        Connection.exception = None

        if exception:
            raise exception

        libvirt.virEventRunDefaultImpl()

    @staticmethod
    def listen_events():
        while not Connection.stopPolling:
            Connection.event_poll()
        Connection.deregister()
        Connection.stopPolling = False

    @staticmethod
    def deregister():
        Connection.runtime = 0
        Connection.on_deregister(None)
        Connection.on_deregister = None

    @staticmethod
    def timeout_callback(timer, opaque):
        # pylint: disable=unused-argument
        syslog.syslog('timeout_callback {} {}'.format(Connection.runtime, Connection.timeout))
        Connection.runtime += Connection.timeoutInterval
        if Connection.runtime >= Connection.timeout:
            Connection.deregister()
            Connection.exception = Timeout('Timeout: `{}`'.format(Connection.action))

    @staticmethod
    def signal_handler(sig_code, frame):
        # pylint: disable=unused-argument
        Connection.exception = KeyboardInterrupt()
        raise KeyboardInterrupt()


def connect(params):
    if not Connection.init:
        Connection()

    conn = libvirt.open(params['hypervisor_uri'])

    return conn


class Error(Exception):
    def __init__(self, msg, **arg):
        self.inter = arg.get('inter', None)
        self.msg = msg
        super(Error, self).__init__(self, msg, **arg)


class Timeout(Error):
    pass

class ModuleInteraction:
    def __init__(self, module):
        self.module = module
        self.run = not module.check_mode
        self.result = {'changed': False, 'changes': ''}
        self.error = None

    def changed(self, what=None):
        self.result['changed'] = True
        if what:
            if self.result['changes']:
                self.result['changes'] += ', '
            self.result['changes'] += what

    def exit(self):
        if self.error:
            self.result['msg'] = str(self.error)
            self.module.fail_json(**self.result)
        else:
            self.module.exit_json(**self.result)


class DomainXml:

    def __init__(self, xml_string):
        self.xml = etree.fromstring(xml_string)

    def get_cpus(self):
        cpus = x_elem(self.xml, 'vcpu').get('current')
        if cpus is None:
            return None
        else:
            return int(cpus)

    def set_cpus(self, cpus):
        x_elem(self.xml, 'vcpu').set('current', str(cpus))

    def get_cpus_max(self):
        return x_get(self.xml, 'vcpu', int)

    def set_cpus_max(self, cpus, default=False):
        if default:
            x_default(self.xml, 'vcpu', cpus)
        else:
            x_set(self.xml, 'vcpu', cpus)

    def get_memory(self):
        return x_get(self.xml, 'currentMemory', Memory)

    def set_memory(self, memory):
        x_set(self.xml, 'currentMemory', memory)

    def get_memory_max(self):
        return x_get(self.xml, 'memory', Memory)

    def set_memory_max(self, memory, default=False):
        if default:
            x_default(self.xml, 'memory', memory)
        else:
            x_set(self.xml, 'memory', memory)

    def get_name(self):
        return x_get(self.xml, 'name')

    def get_uuid(self):
        return x_get(self.xml, 'uuid')

    def tostring(self):
        return etree.tostring(self.xml)


class Domain:

    def __init__(self, domain, inter):
        self.domain = domain
        self.handle = domain
        self.conn = domain.connect()
        self.inter = inter

    def adjust_atomic(self, target, what):
        if what == 'config':
            fetch_flags = libvirt.VIR_DOMAIN_XML_INACTIVE
            set_flags = libvirt.VIR_DOMAIN_AFFECT_CONFIG
        elif what == 'live':
            fetch_flags = 0
            set_flags = libvirt.VIR_DOMAIN_AFFECT_LIVE

        current = DomainXml(self.handle.XMLDesc(fetch_flags))

        def changed(fun):
            return fun(target) and fun(target) != fun(current)

        if changed(DomainXml.get_cpus):
            self.inter.changed('cpus')
            if self.inter.run:
                self.handle.setVcpusFlags(target.get_cpus(), set_flags)

        if changed(DomainXml.get_cpus_max):
            self.inter.changed('cpus_max')
            if self.inter.run:
                self.handle.setVcpusFlags(
                    target.get_cpus_max(),
                    set_flags | libvirt.VIR_DOMAIN_VCPU_MAXIMUM)

        if changed(DomainXml.get_memory):
            self.inter.changed('memory')
            if self.inter.run:
                self.handle.setMemoryFlags(
                    target.get_memory().kbytes(),
                    set_flags)

        if changed(DomainXml.get_memory_max):
            self.inter.changed('memory_max')
            if self.inter.run:
                self.handle.setMemoryFlags(
                    target.get_memory_max().kbytes(),
                    set_flags | libvirt.VIR_DOMAIN_MEM_MAXIMUM)


    def state(self):
        return Domain.State(self.domain)

    def ensure_state(self, target_state):
        state = self.state()

        if target_state == 'running' and not state.running():
            if state.stopping():
                self.listen_state_change('shut-off').await()
                self.start()
            elif state.paused():
                self.resume()
            else:
                self.start()

        if target_state == 'paused' and not state.paused():
            if state.stopped():
                self.pause(start=True)
            elif state.running():
                self.pause()

        if target_state == 'shut-off' and not state.stopped():
            if state.paused():
                self.resume()
            try:
                self.shutdown()
            except Timeout:
                # TODO: Only destroy if wanted
                self.destroy()

    def undefine_full(self):
        if self.handle.isPersistent():
            self.undefine()
            try:
                self.destroy()
            except libvirt.libvirtError:
                # occurs if vm was not running on undefine
                pass
        else:
            self.destroy()

    def undefine(self):
        self.inter.changed('undefine')
        if self.inter.run:
            state_undefined = self.listen_state_change('undefined')
            self.handle.undefine()
            state_undefined.await()

    def shutdown(self):
        self.inter.changed('state->shutdown')
        if self.inter.run:
            state_shut_off = self.listen_state_change('shut-off')
            self.handle.shutdown()
            state_shut_off.await()

    def destroy(self):
        self.inter.changed('state->destroyed')
        if self.inter.run:
            state_shut_off = self.listen_state_change('shut-off')
            self.handle.destroy()
            state_shut_off.await()

    def resume(self):
        self.inter.changed('state->running')
        if self.inter.run:
            state_shut_off = self.listen_state_change('running')
            self.handle.resume()
            state_shut_off.await()

    def pause(self, start=False):
        self.inter.changed('state->paused')
        if self.inter.run:
            state_paused = self.listen_state_change('paused')
            if start:
                self.handle.createWithFlags(libvirt.VIR_DOMAIN_START_PAUSED)
            else:
                self.handle.suspend()
            state_paused.await()

    def start(self):
        self.inter.changed('state->running')
        if self.inter.run:
            state_running = self.listen_state_change('running')
            self.handle.create()
            state_running.await()

    def listen_state_change(self, wait_for):
        return Domain.ListenStateChange(self, wait_for)

    class ListenStateChange:
        TARGET_STATE = {
            'shut-off': [
                libvirt.VIR_DOMAIN_EVENT_STOPPED,
                libvirt.VIR_DOMAIN_EVENT_CRASHED],
            'running': [
                libvirt.VIR_DOMAIN_EVENT_STARTED,
                libvirt.VIR_DOMAIN_EVENT_RESUMED],
            'paused': [libvirt.VIR_DOMAIN_EVENT_SUSPENDED],
            'undefined': [libvirt.VIR_DOMAIN_EVENT_UNDEFINED],
        }

        def __init__(self, domain, wait_for):
            if type(wait_for) is str:
                self.wait_for = Domain.ListenStateChange.TARGET_STATE[wait_for]
            else:
                self.wait_for = wait_for

            self.action = "Waiting for Domain state '{}'".format(str(wait_for))
            self.domain = domain

            if self.domain.inter.run:
                self.handle = domain.conn.domainEventRegisterAny(
                    domain.domain,
                    libvirt.VIR_DOMAIN_EVENT_ID_LIFECYCLE,
                    self.callback,
                    None)

                Connection.on_deregister = staticmethod(
                    lambda _:
                    self.domain.conn.domainEventDeregisterAny(self.handle)
                    )


        def callback(self, conn, dom, event, detail, opaque):
            # pylint: disable=unused-argument, too-many-arguments
            if event in self.wait_for:
                Connection.stopPolling = True

        def await(self):
            Connection.action = self.action
            if self.domain.inter.run:
                Connection.listen_events()


    class State:

        RUNNING = [
            libvirt.VIR_DOMAIN_RUNNING,
            libvirt.VIR_DOMAIN_BLOCKED,
            libvirt.VIR_DOMAIN_PMSUSPENDED]
        PAUSED = [libvirt.VIR_DOMAIN_PAUSED]
        STOPPING = [libvirt.VIR_DOMAIN_SHUTDOWN]

        def __init__(self, domain):
            self.state, self.reason = domain.state()

        def running(self):
            return self.state in self.RUNNING

        def paused(self):
            return self.state in self.PAUSED

        def stopped(self):
            return self.state not in self.RUNNING + self.PAUSED + self.STOPPING

        def stopping(self):
            return self.state in self.STOPPING


class Memory:

    REGEX = re.compile(r"^\s*(\d+)\s*([a-zA-Z]*)\s*$")

    UNITS_MAP = {
        'B': 1,
        'BYTES': 1,
        'KB': 10**3,
        'K': 2**10,
        'KIB': 2**10,
        'MB': 10**6,
        'M': 2**20,
        'MIB': 2**20,
        'GB': 10**9,
        'G': 2**30,
        'GIB': 2**30,
        'TB': 10**12,
        'T': 2**40,
        'TIB': 2**40,
        'PB': 10**15,
        'P': 2**50,
        'PIB': 2**50,
        'EB': 10**18,
        'E': 2**60,
        'EIB': 2**60
    }

    def __init__(self, value, unit=None):

        if unit is None:
            match = self.REGEX.match(str(value))
            if match is None:
                raise Error("invalid size format '{}'".format(value))
            self.size, self.unit = match.group(1, 2)

        else:
            self.size = value
            self.unit = unit

        self.size = int(self.size)

        # trigger error if unit unknown
        self.factor()

    def __cmp__(self, other):
        diff = self.bytes() - other.bytes()

        if diff < 1024 and diff > -1024:
            return 0
        elif diff < 0:
            return -1
        else:
            return 1

    def bytes(self):
        return self.size * self.factor()

    def kbytes(self):
        return self.size * self.factor() / self.UNITS_MAP['KIB']

    def factor(self):
        try:
            return self.UNITS_MAP[self.unit.upper()]
        except KeyError:
            raise Error("invalid unit '{}'".format(self.unit))

    def tostring(self):
        return "{} {}".format(self.size, self.unit)


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

def x_get(parent, element, typ=str):
    element = x_list(element)

    elem = parent.xpath('/'.join(element))

    if elem:
        elem = elem[0]
    else:
        return None

    if typ == Memory:
        return Memory(elem.text, elem.get('unit', 'B'))
    if typ == int:
        if elem.text is None:
            return None
        else:
            return int(elem.text)
    elif typ == object:
        return elem
    else:
        return elem.text

def x_set(parent, element, value):
    elem = x_elem(parent, element)

    if isinstance(value, Memory):
        elem.text = str(value.size)
        elem.set('unit', value.unit)
    else:
        elem.text = str(value)

    return elem

def x_default(parent, element, value):
    element = x_list(element)

    if not parent.xpath('/'.join(element)):
        x_set(parent, element, value)


def attach_dict_to_xml(xml_node, value):
    if type(value) is dict:
        for elem_name in value:
            if elem_name == '--':
                xml_node.text = str(value[elem_name])
            elif elem_name[:1] == '-':
                xml_node.set(elem_name[1:], str(value[elem_name]))
            else:
                new_elem = etree.SubElement(xml_node, elem_name)
                attach_dict_to_xml(new_elem, value[elem_name])
    elif type(value) is list:
        for elem in value:
            attach_dict_to_xml(xml_node, elem)
    elif value is None:
        pass
    else:
        xml_node.text = str(value)


def xml_to_dict(xml):
    if not len(xml) and not xml.items():
        return xml.text
    else:
        tags = {}
        tag_doubled = False
        for elem in xml:
            if tags.get(elem.tag, False):
                tag_doubled = True
                break
            else:
                tags[elem.tag] = True

        if tag_doubled:
            result = []
            def _attach(result, key, value):
                result.append({key: value})
        else:
            result = {}
            def _attach(result, key, value):
                result[key] = value

        if xml.text is not None:
            _attach(result, '--', xml.text)

        for name, value in sorted(xml.items()):
            _attach(result, '-' + name, value)

        for elem in xml:
            _attach(result, elem.tag, xml_to_dict(elem))

        return result

