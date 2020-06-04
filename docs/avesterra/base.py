#!/usr/bin/env python3

"""AvesTerra.py: AvesTerra base layer defining classes and errors
"""

__author__ = "Dave Bridgeland and J. C. Smart"
__copyright__ = "Copyright 2015-2020, Georgetown University"
__patents__ = "US Patent No. 9,996,567"
__credits__ = ["J. C. Smart", "Dave Bridgeland", "Norman Kraft"]

__version__ = "3.15.5"
__maintainer__ = "Dave Bridgeland"
__email__ = "dave@hangingsteel.com"
__status__ = "Prototype"

import functools
import re
import json
import enum
import time
import calendar
import urllib

# AvesTerra classes:

LARGEST_32_BIT_INT = 4_294_967_295
LARGEST_64_BIT_INT = 18_446_744_073_709_551_615

ENCODING = 'utf-8'

class Entity:
    def __init__(self, pid, hid, uid):
      if 0 <= pid <= LARGEST_32_BIT_INT:
        self.pid = pid
      else:
        raise EntityError(
          'Public host ID {} either too small or too big'.format(pid))

      if 0 <= hid <= LARGEST_32_BIT_INT:
        self.hid = hid
      else:
        raise EntityError(
          'Local host ID {} either too small or too big'.format(hid))

      if 0 <= uid <= LARGEST_64_BIT_INT:
        self.uid = uid
      else:
        raise EntityError(
          'Unique entity ID {} either too small or too big'.format(uid))

    def __repr__(self):
      return "Entity({}, {}, {})".format(self.pid, self.hid, self.uid)

    def __str__(self):
      return "<{}|{}|{}>".format(self.pid, self.hid, self.uid)

    def __eq__(self, other):
      if type(self) is type(other):
        return self.__dict__ == other.__dict__
      return NotImplemented

    def __ne__(self, other):
      if type(self) is type(other):
        return not self == other
      return NotImplemented

    def __hash__(self):
      return hash(tuple(sorted(self.__dict__.items())))

    def is_entity(self):
        return True
        

# Probably this should just be an init method of Entity
def entity_of(s):
    match = re.fullmatch(_entity_regex_pattern(), s)
    if match:
       gps = match.groups()
       return Entity(int(gps[0]), int(gps[1]), int(gps[2]))
    else:
        raise EntityError('Bad entity ID: {}'.format(s))

@functools.lru_cache(maxsize=1)
def _entity_regex_pattern():
    """Return the regex pattern for entities."""
    return re.compile('<([0-9]+)\|([0-9]+)\|([0-9]+)>')

def is_entity(thing):
    """Returns whether thing is an entity or can be interpreted as one."""
    try:
        return thing.is_entity()
    except Exception:
        try:
            return re.fullmatch(_entity_regex_pattern(), thing) is not None
        except Exception:
            return False


class Authorization:
    def __init__(self, code):
        self._code = code 

    def bytes(self):
        """Serialize as byte array."""
        return b'%d' % self._code


################################################################################
#
# Errors
#

# AvesTerra errors.  

class AvesTerraError(Exception):
    """Some sort of error with the AvesTerra"""
    def __init__(self, message):
        self.message = message

class TaxonomyError(AvesTerraError):
    pass

class EntityError(AvesTerraError):
    pass

class OutletError(AvesTerraError):
    pass

class CommunicationError(AvesTerraError):
    """A communications error with the AvesTerra server""" 
    pass

class NetworkError(AvesTerraError):
    pass

class TimeoutError(AvesTerraError):
    pass

class AuthorizationError(AvesTerraError):
    pass

class AdapterError(AvesTerraError):
    pass

class SubscriberError(AvesTerraError):
    pass

class ApplicationError(AvesTerraError):
    pass

class BypassError(AvesTerraError):
    pass

class ForwardError(AvesTerraError):
    pass

class ValueError(AvesTerraError):
    pass

class MessageTooLargeError(AvesTerraError):
    pass

################################################################################
#
# Value class, for typing AvesTerra stuff
#

# Cannot be generated automatically as it is needed for initialization
class Tag(enum.IntEnum):
    NULL = 0
    BOOLEAN = 1 
    CHARACTER = 2
    STRING = 3 
    TEXT = 4
    INTEGER = 5
    FLOAT = 6
    ENTITY = 7
    TIME = 8
    UNIFORM = 9
    INTERCHANGE = 10
    DATA = 11
    ERROR = 12
    OPERATOR = 13
    FUNCTION = 14


class Value:
    def __init__(self, type_tag, bytes):
        self._type_tag = type_tag
        self._bytes = bytes

    def __repr__(self):
        return f'Value({self._type_tag}, "{self._bytes}")'

    @classmethod
    def from_object(klass, object):
        """Create a Value instance from the type of the object.""" 
        if isinstance(object, Value):
          return klass(object._type_tag, object._bytes)
        elif isinstance(object, bool):
            return klass(Tag.BOOLEAN.value, b'TRUE' if object else b'FALSE')
        elif isinstance(object, str):
            return klass (Tag.TEXT.value, object.encode(ENCODING))
        elif isinstance(object, int):
            # the seemingly unnecessary int() is to deal with enums
            return klass(Tag.INTEGER.value, str(int(object)).encode(ENCODING))
        elif isinstance(object, float):
            return klass(Tag.FLOAT.value, str(object).encode(ENCODING))
        elif isinstance(object, Entity):
            return klass(Tag.ENTITY.value, str(object).encode(ENCODING))
        elif isinstance(object, time.struct_time):
            return klass(
                Tag.TIME.value, str(calendar.timegm(object)).encode(ENCODING))
        elif isinstance(object, bytes):
            return klass(Tag.DATA.value, object)
        else:
            return klass.create_interchange_value(object) 

    @classmethod
    def character_from_string(klass, string):
        """Create Value instance of a string that is encoded as a single byte"""
        encoded = string.encode(ENCODING)
        if len(encoded) == 1:
            return klass(Tag.CHARACTER.value, encoded)
        else:
            raise AvesTerraError(f'Unable to interpret {string} as a character')

    @classmethod
    def resource_from_string(klass, string):
        """Create Value instance with a string as a URI."""
        try:
            urllib.parse.urlparse(string)
        except ValueError:
            raise AvesTerraError(f'Unable to interpret {string} as URI')
        else:
            return klass(Tag.UNIFORM.value, string.encode(ENCODING))

    @classmethod
    def ascii_from_string(klass, string):
        """Create Value instance with a string, interpreted as ascii."""
        try:
            encoded = string.encode('ASCII')
        except UnicodeEncodeError:
            raise AvesTerraError(f'Unable to interpret {string} as ASCII')
        else:
            return klass(Tag.STRING.value, encoded)


    @classmethod
    def create_interchange_value(klass, object):
        """Try to create an value object as an interchange."""
        try:
            interchange = transform_to_interchange(object)
            jsonified_interchange = json.dumps(
                interchange, ensure_ascii=False).encode(ENCODING)
        except TypeError:
            raise AvesTerraError(
                f'Unable to provide {object} as AvesTerra value')
        new_obj = klass(Tag.INTERCHANGE.value, jsonified_interchange)
        # Interchange objects need an additional field
        new_obj._interchange = interchange
        return new_obj

    def serialize(self):
        """Return a string that is the serialization of the value."""
        return b'%d %d %b' % (self._type_tag, len(self._bytes), self._bytes)

    def __eq__(self, other):
        """Are they equal?"""
        try:
            return (
              self._type_tag == other._type_tag and 
              self._bytes == other._bytes
            ) 
        except AttributeError:
          return False

def transform_to_interchange(object):
    """Attempt to transform the object into (pre-json) interchange."""
    # Find all the entities and change them to strings.
    if isinstance(object, Entity):
        return str(object)
    elif isinstance(object, dict):
        return {k:transform_to_interchange(v) for k, v in object.items()}
    elif isinstance(object, list):
        return [transform_to_interchange(elt) for elt in object]
    else:
        return object

################################################################################
#
# Verify class, for type checking of stuff
#   (not pythonic, but necessary to work with AvesTerra)

class Verify:
    @staticmethod
    def entity(obj):
        """Raise error if obj is not an entity."""
        if not isinstance(obj, Entity):
            raise AvesTerraError('{} is not an entity'.format(obj))

    @staticmethod
    def integer(obj):
        """Raise error if obj is not an integer."""
        if not isinstance(obj, int) or isinstance(obj, enum.IntEnum):
            raise AvesTerraError('{} is not an integer'.format(obj))

    @staticmethod
    def natural(obj):
        """Raise error if obj is not a non-negative integer."""
        if not isinstance(obj, int) or isinstance(obj, enum.IntEnum):
            raise AvesTerraError('{} is not an integer'.format(obj))
        if obj < 0:
            raise AvesTerraError('{} is less than zero'.format(obj))

    @staticmethod
    def string(obj):
        """Raise error if obj is not a string."""
        if not isinstance(obj, str):
            raise AvesTerraError('{} is not a string'.format(obj))

    @staticmethod
    def bytes(obj):
        """Raise error if obj is not bytes."""
        if not isinstance(obj, bytes):
            raise AvesTerraError('{} is not a bytes object'.format(obj))

    @staticmethod
    def options(obj):
        """Raise error if obj is not valid options."""
        if not isinstance(obj, str):
            raise AvesTerraError('{} is not valid options'.format(obj))

    @staticmethod
    def code(obj, code_type):
        """Raise error if obj cannot be interpreted as a code."""
        # This is generous as it allows an integer to be interpreted as a subclass
        # or a method to be interpreted as a class
        try:
            int(obj)
        except Exception:
            raise AvesTerraError('{} is not a {}'.format(obj, code_type))

    @staticmethod
    def value(obj):
        if not isinstance(obj, Value):
            raise AvesTerraError('{} is not a value'.format(obj))

    @staticmethod
    def callback(obj):
        if obj is not None and not callable(obj):
            raise AvesTerraError(f'{obj} is not a callable callback.')

    @staticmethod
    def authorization(obj):
        """Raise error if obj is not an authorization."""
        if not isinstance(obj, Authorization):
            raise AuthorizationError('{} is not an authorization'.format(obj))





