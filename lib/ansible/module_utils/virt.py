# -*- coding: utf-8 -*-
#

import re
import signal

import libvirt
from lxml import etree

__metaclass__ = type

class Connection:
    init = False
    timeoutInterval = 200
    runtime = 0
    timeout = 3000
    exception = None
    stopPolling = False
    action = ''

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
        Connection.stopPolling = False

    @staticmethod
    def timeout_callback(timer, opaque):
        # pylint: disable=unused-argument
        Connection.runtime += Connection.timeoutInterval
        if Connection.runtime >= Connection.timeout:
            Connection.runtime = 0
            Connection.exception = Exception('Timeout: `{}`'.format(Connection.action))

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
        super(Error, self).__init__(self, msg, **arg)


class ModuleInteraction:
    def __init__(self, module):
        self.module = module
        self.run = not module.check_mode
        self.result = {'changed': False}
        self.error = None

    def changed(self, changed=True):
        self.result['changed'] = changed

    def exit(self):
        if self.error:
            self.result['msg'] = str(self.error)
            self.module.fail_json(**self.result)
        else:
            self.module.exit_json(**self.result)


class Domain:

    def __init__(self, domain, inter):
        self.domain = domain
        self.handle = domain
        self.conn = domain.connect()
        self.inter = inter

    def ensure_state(self, target_state):

        domain = self.domain
        inter = self.inter
        state = Domain.State(domain)

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

    def destroy(self):
        self.inter.changed()
        if self.inter.run:
            state_shut_off = self.listen_state_change('shut-off')
            self.handle.destroy()
            state_shut_off.await()

    def resume(self):
        self.inter.changed()
        if self.inter.run:
            state_shut_off = self.listen_state_change('running')
            self.handle.resume()
            state_shut_off.await()

    def pause(self, start=False):
        self.inter.changed()
        if self.inter.run:
            state_paused = self.listen_state_change('paused')
            if start:
                self.handle.createWithFlags(libvirt.VIR_DOMAIN_START_PAUSED)
            else:
                self.handle.suspend()
            state_paused.await()

    def start(self):
        self.inter.changed()
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

        }

        def __init__(self, domain, wait_for):
            if type(wait_for) is str:
                self.wait_for = Domain.ListenStateChange.TARGET_STATE[wait_for]
            else:
                self.wait_for = wait_for

            self.action = "Wait for Domain state '{}'".format(str(wait_for))
            self.domain = domain

            if self.domain.inter.run:
                self.handle = domain.conn.domainEventRegisterAny(
                    domain.domain,
                    libvirt.VIR_DOMAIN_EVENT_ID_LIFECYCLE,
                    self.callback,
                    None)

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
                raise Exception("invalid size format '{}'".format(value))
            self.size, self.unit = match.group(1, 2)

        else:
            self.size = value
            self.unit = unit

        self.size = int(self.size)

        # trigger error if unit unknown
        self.factor()

    def bytes(self):
        return self.size * self.factor()

    def factor(self):
        try:
            return self.UNITS_MAP[self.unit.upper()]
        except KeyError:
            raise Exception("invalid unit '{}'".format(self.unit))

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


class Xml:
    unit_fields = ["capacity", "allocation"]

    def __init__(self, root_name, data):
        self.root = etree.Element(root_name)
        self.append_data(self.root, data)

    def append_data(self, node, data):
        for field, value in data.items():
            child = etree.SubElement(node, field)
            if isinstance(value, dict):
                self.append_data(child, value)
            elif field in self.unit_fields:
                mem = Memory(value)
                child.text = str(mem.size)
                child.set('unit', mem.unit)
            else:
                child.text = str(value)

    def to_string(self):
        return etree.tostring(self.root, pretty_print=True)
