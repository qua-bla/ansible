# -*- coding: utf-8 -*-
#

import re
import libvirt
import signal
from lxml import etree

UNITS_REGEX = re.compile(r"^\s*(\d+)\s*([a-zA-Z]*)\s*$")

def parse_number(value):

    match = UNITS_REGEX.match(str(value))

    if match is None:
        raise Exception("invalid size format '{}'".format(value))

    size, unit = match.group(1, 2)

    if unit:
        try:
            return int(size) * UNITS_MAP[unit.upper()]
        except KeyError:
            raise Exception("invalid unit '{}'".format(unit))
    else:
        return int(size)


class Connection:
    init = False
    timeoutInterval = 200
    runtime = 0
    timeout = 1500
    exception = None
    stopPolling = False

    @staticmethod
    def eventPoll():
        exception = Connection.exception
        Connection.exception = None

        if exception:
            raise exception

        libvirt.virEventRunDefaultImpl()
    
    @staticmethod
    def listenEvents():
        while not Connection.stopPolling:
            Connection.eventPoll()
        Connection.stopPolling = False

    @staticmethod
    def timeoutCallback(timer, opaque):
        Connection.runtime += Connection.timeoutInterval
        print(Connection.runtime, Connection.timeout)
        if Connection.runtime >= Connection.timeout:
            Connection.runtime = 0
            Connection.exception = Exception('TIMEOUT')

    @staticmethod
    def signalHandler(sig_code, frame):
        Connection.exception = KeyboardInterrupt()
        raise KeyboardInterrupt()


class ListenDomainStateChange:
    def __init__(self, conn, dom, waitFor):
        self.waitFor = waitFor
        self.handle = conn.domainEventRegisterAny(
                dom,
                libvirt.VIR_DOMAIN_EVENT_ID_LIFECYCLE,
                self.callback,
                None)

    def callback(self, conn, dom, event, detail, opaque):
        print(event)
        if event in self.waitFor:
            Connection.stopPolling = True

    def await(self):
        Connection.listenEvents()


def connect(params):
    if Connection.init == False:
        libvirt.virEventRegisterDefaultImpl()
        libvirt.virEventAddTimeout(
            Connection.timeoutInterval,
            Connection.timeoutCallback,
            None)
        signal.signal(signal.SIGINT, Connection.signalHandler)
        Connection.init = True

    conn = libvirt.open(params['hypervisor_uri'])

    return conn
    

class DomainState:

    RUNNING = [
        libvirt.VIR_DOMAIN_RUNNING,
        libvirt.VIR_DOMAIN_BLOCKED,
        libvirt.VIR_DOMAIN_PMSUSPENDED]    
    PAUSED = [libvirt.VIR_DOMAIN_PAUSED]
    STOPPING = [libvirt.VIR_DOMAIN_SHUTDOWN]
    
    def __init__(self, domain):
        self.domain = domain
    
    def state(self):
        state, reason = self.domain.state()
        return state
    
    def running(self):
        return self.state() in self.RUNNING

    def paused(self):
        return self.state() in self.PAUSED
    
    def stopped(self):
        return self.state() not in self.RUNNING + self.PAUSED + self.STOPPING

    def stopping(self):
        return self.state() in self.STOPPING

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

def x_get(parent, element, type=str):
    element = x_list(element)

    e = parent.xpath('/'.join(element))
    
    if e:
        e = e[0]
    else:
        return None
    
    if type == Memory:
        return Memory(e.text, e.get('unit', 'B'))
    elif type == object:
        return e
    else:
        return e.text

def x_set(parent, element, value):
    e = x_elem(parent, element)
    
    if isinstance(value, Memory):
        e.text = str(value.size)
        e.set('unit', value.unit)
    else:
        e.text = str(value)
    
    return e

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
                child.text = str(parse_number(value))
            else:
                child.text = str(value)

    def to_string(self):
        return etree.tostring(self.root, pretty_print=True)

