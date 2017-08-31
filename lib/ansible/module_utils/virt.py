# -*- coding: utf-8 -*-
#

import re
import libvirt
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

