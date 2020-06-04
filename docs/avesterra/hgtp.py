#!/usr/bin/env python3

"""hgtp.py: the client side of the HGTP protocol for AvesTerra
This is a fork of the original AvesTerra_HGTP, upgraded to Python 3.6,
and with many changes and improvements.
"""

__author__ = "Dave Bridgeland and J. C. Smart"
__copyright__ = "Copyright 2015-2020, Georgetown University"
__patents__ = "US Patent No. 9,996,567"
__credits__ = ["J. C. Smart", "Dave Bridgeland", "Norman Kraft"]

__version__ = "3.15.5"
__maintainer__ = "Dave Bridgeland"
__email__ = "dave@hangingsteel.com"
__status__ = "Prototype"
 
import socket
import struct
import logging
import queue
import collections
import threading
import time

from enum import Enum
import avesterra.base as at

logger = logging.getLogger(__name__)


################################################################################
#
# Constants and enums
#

# HGTP message codes:
class Message(Enum):
    BYE = 0
    CREATE = 1
    DELETE = 2
    CONNECT = 3
    DISCONNECT = 4
    ATTACH = 5
    DETACH = 6
    INVOKE = 7
    INQUIRE = 8
    CALL = 9
    ADAPT = 10
    RESET = 11
    CONNECTION = 12
    ATTACHMENT = 13
    REFERENCE = 14
    DEREFERENCE = 15
    ACTIVATE = 16
    DEACTIVATE = 17
    PUBLISH = 18
    SUBSCRIBE = 19
    NOTIFY = 20
    CANCEL = 21
    SUBSCRIPTION = 22
    WAIT = 23
    FLUSH = 24
    ATTACHED = 25
    CONNECTED = 26
    SUBSCRIBED = 27
    AUTHORIZE = 28
    DEAUTHORIZE = 29
    AUTHORIZED = 30
    AUTHORITY = 31
    REPORT = 32
    LOCK = 33
    UNLOCK = 34
    SET = 35

class ReportCode(Enum):
    NULL = 0
    AVAILABLE = 1
    NAME = 2
    CLASS = 3
    SUBCLASS = 4
    ACTIVATED = 5
    CONNECTIONS = 6
    ATTACHMENTS = 7
    SUBSCRIPTIONS = 8
    AUTHORITIES = 9
    REDIRECTION = 10
    PERSISTENCE = 11
    REFERENCES = 12
    TIMESTAMP = 13
    SERVER = 14
    LOCAL = 15
    GATEWAY = 16
    HOSTNAME = 17
    VERSION = 18
    DELETED = 19
    PENDING = 20
    LOCKED = 21
    RENDEZVOUS = 22
    RETRIEVE = 23

class SetCode(Enum):
    """Used to change the name, class, or subclass of existing entity."""
    NULL = 0
    NAME = 1
    CLASS = 2
    SUBCLASS = 3

# same as exception_code in hgtp-io in reference implementation
class HGTPexception(Enum):
    NULL = 0 
    ENTITY = 1
    OUTLET = 2
    COMMUNICATION = 3
    NETWORK = 4
    TIMEOUT = 5
    AUTHORIZATION = 6
    ADAPTER = 7
    SUBSCRIBER = 8
    APPLICATION = 9
    BYPASS = 10
    FORWARD = 11
    VALUE = 12

PORT = 20057
HOST = 0

BUFFER_TERMINATOR = b'\x00'
BUFFER_TERMINATOR_BYTE = BUFFER_TERMINATOR[0]
BUFFER_SIZE = 1024
ACK = b'\x06'
ACK_BYTE = ACK[0]
NAK = b'\x15'
NAK_BYTE = NAK[0]
MESSAGE_SIZE_LIMIT_IN_BYTES = 1_048_575

################################################################################
#
# HGTP interface
#

def initialize(entity, socket_count = 16):
    """Allocate resources to communicate with AvesTerra server"""
    logger.debug("Initializing entity {} with {} sockets".format(
        entity, socket_count))
    global _socket_pool
    # To do: check whether existing _socket_pool points to same server
    # if not: raise error
    if _socket_pool is None or not _socket_pool.alive():
        _socket_pool = _create_new_socket_pool(entity, socket_count)
        _test_socket_pool(_socket_pool, entity)

def _create_new_socket_pool(entity, socket_count):
    """Create a new socket pool and return it."""
    logger.debug("Creating minimal socket pool")
    host_id = entity.hid
    if host_id == 0:
        # convert the IP address of the local host into an int
        # should replace with convert_IP_address_to_int()
        host_id = _ip2addr(socket.gethostbyname(socket.gethostname()))
    ip = _addr2ip(host_id)
    return SocketPool(ip, PORT, socket_count)

def _test_socket_pool(spool, entity):
    """Test the socket pool by borrowing a socket and then returning it."""
    try: 
        sock = spool.borrow_socket()
    except Exception:
        spool.end_pool()
        raise at.AvesTerraError('Failed to initialize conection to {}'.format(
            entity))
    else:
        spool.return_socket(sock)

def finalize():
    """Release all AvesTerra resources"""
    global _socket_pool
    if _socket_pool:
        logger.debug("Finalizing sockets")
        _socket_pool.end_pool()
        _socket_pool = None 

def create(server, name, avesterra_class, subclass, authorization):
    logger.debug(
        "Creating entity {} of class {}, subclass {} on server {}".format(
            name, avesterra_class, subclass, server))
    resp = _send_and_wait_for_response(_format_create(
            server, name, avesterra_class, subclass, authorization))
    new_entity = resp.pop_entity()
    logger.debug("Created entity {}".format(new_entity))
    return new_entity

def _format_create(server, name, klass, subklass, authorization):
    """Format the CREATE message in HGTP"""
    return _serialize_all(
        _serialize_message(Message.CREATE),
        _serialize_entity(server), 
        _serialize_name(name),
        _serialize_class(klass),
        _serialize_subclass(subklass),
        _serialize_authorization(authorization))

def delete(entity, authorization):
    logger.debug("Deleting entity {}".format(entity))
    _send_and_wait_for_response(_format_delete(entity, authorization))
    logger.debug("Deleted")

def _format_delete(entity, authorization):
    """Format the DELETE invocation in HGTP."""
    return _serialize_all(
        _serialize_message(Message.DELETE), 
        _serialize_entity(entity), 
        _serialize_authorization(authorization))

def invoke(entity, auxiliary, method, attribute, instance, name, key, value,
           options, parameter, index, count, mode, precedence, timeout, 
           authorization):
    logger.debug(
        ('Invoking entity {} with auxilliary {}, method {}, attribute {}, ' +
         'instance {}, name {}, key {}, value {}, options {}, parameter {}, ' +
         'index {}, count {}, mode {}, precedence {}, and timeout {}').format(
            entity, auxiliary, method, attribute, instance, name, key, value,
            options, parameter, index, count, mode, precedence, timeout))
    resp = _send_and_wait_for_response(_format_invoke(
        entity, auxiliary, method, attribute, instance, name, key, value, 
        options, parameter, index, count, mode, precedence, timeout, 
        authorization))
        
    result = resp.pop_value()
    logger.debug("Invocation returned {}".format(result))
    return result

def _format_invoke(entity, auxiliary, method, attribute, instance, name, key, 
                   value, options, parameter, index, count, mode, precedence,
                   timeout, authorization):
    """Format the INVOKE message in HGTP"""
    return _serialize_all(
        _serialize_message(Message.INVOKE), 
        _serialize_entity(entity), 
        _serialize_entity(auxiliary), 
        _serialize_method(method), 
        _serialize_attribute(attribute), 
        _serialize_instance(instance), 
        _serialize_name(name), 
        _serialize_key(key),
        _serialize_value(value),
        _serialize_options(options), 
        _serialize_parameter(parameter),       
        _serialize_index(index), 
        _serialize_count(count), 
        _serialize_mode(mode),
        _serialize_precedence(precedence),  
        _serialize_timeout(timeout), 
        _serialize_authorization(authorization))

def inquire(entity, auxiliary, attribute, instance, name, key, value, options,
            parameter, index, count, mode, precedence, timeout, authorization):
    logger.debug(
        "Inquiring about attribute {} of entity {}".format(attribute, entity))
    resp = _send_and_wait_for_response(_format_inquire(
            entity, auxiliary, attribute, instance, name, key, value, options, 
            parameter, index, count, mode, precedence, timeout, authorization))
    result = resp.pop_value()
    logger.debug("Inquiry returned {}".format(result))
    return result

def _format_inquire(entity, auxiliary, attribute, instance, name, key, value, 
                    options, parameter, index, count, mode, precedence, timeout,
                    authorization):
    """Format the INQUIRE message in HGTP."""
    return _serialize_all(
        _serialize_message(Message.INQUIRE),
        _serialize_entity(entity),
        _serialize_entity(auxiliary),
        _serialize_attribute(attribute),
        _serialize_instance(instance),
        _serialize_name(name),
        _serialize_key(key),
        _serialize_value(value),
        _serialize_options(options),
        _serialize_parameter(parameter),      
        _serialize_index(index), 
        _serialize_count(count), 
        _serialize_mode(mode),
        _serialize_precedence(precedence),
        _serialize_timeout(timeout),
        _serialize_authorization(authorization))

def reference(entity, authorization):
    _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.REFERENCE),
        _serialize_entity(entity),
        _serialize_authorization(authorization)))

def dereference(entity, authorization):
    _send_and_wait_for_response(_serialize_all(
       _serialize_message(Message.DEREFERENCE),
       _serialize_entity(entity),
       _serialize_authorization(authorization)))

def set_name(entity, name, authorization):
    _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.SET),
        _serialize_code(SetCode.NAME), 
        _serialize_entity(entity),
        _serialize_name(name),
        _serialize_authorization(authorization)))

def set_class(entity, klass, authorization):
    _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.SET),
        _serialize_code(SetCode.CLASS),
        _serialize_entity(entity),
        _serialize_class(klass),
        _serialize_authorization(authorization)))

def set_subclass(entity, subklass, authorization):
    _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.SET),
        _serialize_code(SetCode.SUBCLASS),
        _serialize_entity(entity),
        _serialize_subclass(subklass),
        _serialize_authorization(authorization)))



# Connection operations

def connect(entity, outlet, method, precedence, authorization):
    logger.debug(
        "Connecting entity {} to outlet {} for method {} and precedence {}".format(
        entity, outlet, method, precedence))
    _send_and_wait_for_response(_format_connect(
        entity, outlet, method, precedence, authorization))
    logger.debug("Connected")

def _format_connect(entity, outlet, method, precedence, authorization):
    """Format the CONNECT message in HGTP."""
    return(_serialize_all(
        _serialize_message(Message.CONNECT),
        _serialize_entity(entity),
        _serialize_entity(outlet),
        _serialize_method(method),
        _serialize_precedence(precedence), 
        _serialize_authorization(authorization)))

def disconnect(entity, outlet, method, precedence, authorization):
    _send_and_wait_for_response(_format_disconnect(
        entity, outlet, method, precedence, authorization))

def _format_disconnect(entity, outlet, method, precedence, authorization):
    """Format the DISCONNECT message in HGTP."""
    return _serialize_all(
        _serialize_message(Message.DISCONNECT),
        _serialize_entity(entity),
        _serialize_entity(outlet),
        _serialize_method(method),
        _serialize_precedence(precedence), 
        _serialize_authorization(authorization))

def connection(entity, index, authorization):
    resp = _send_and_wait_for_response(_format_connection(
        entity, index, authorization))
    return resp.pop_entity(), resp.pop_integer(), resp.pop_integer()

def _format_connection(entity, index, authorization):
    """Format the CONNECTION message in HGTP."""
    return(_serialize_all(
        _serialize_message(Message.CONNECTION),
        _serialize_entity(entity),
        _serialize_index(index),
        _serialize_authorization(authorization)))

# Attachment operations

def attach(entity, outlet, attribute, precedence, authorization):
    logger.debug(
        'Attaching entity {} to outlet {}, with attr {}, precedence {}'.format(
            entity, outlet, attribute, precedence))
    _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.ATTACH),
        _serialize_entity(entity),
        _serialize_entity(outlet),
        _serialize_attribute(attribute),
        _serialize_precedence(precedence), 
        _serialize_authorization(authorization)))
    logger.debug('Attached')

def detach(entity, outlet, attribute, precedence, authorization):
    _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.DETACH),
        _serialize_entity(entity),
        _serialize_entity(outlet),
        _serialize_attribute(attribute),
        _serialize_precedence(precedence), 
        _serialize_authorization(authorization)))

def attachment(entity, index, authorization):
    resp = _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.ATTACHMENT),
        _serialize_entity(entity),
        _serialize_index(index),
        _serialize_authorization(authorization)))
    return resp.pop_entity(), resp.pop_integer(), resp.pop_integer()

def attached(entity, attribute, precedence, authorization):
    resp = _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.ATTACHED),
        _serialize_entity(entity),
        _serialize_attribute(attribute),
        _serialize_precedence(precedence),
        _serialize_authorization(authorization)))
    isattached = resp.pop_boolean()
    return isattached

def connected(entity, method, precedence, authorization):
    """Is the entity connected to some adapter at some precedence?"""
    logger.debug(
        f'Connected called on {entity}, method {method}, and precedence ' +
        f'{precedence}')
    resp = _send_and_wait_for_response(_format_connected(
        entity, method, precedence, authorization))
    isconnected = resp.pop_boolean()
    logger.debug(f'Connected returned {isconnected}')
    return isconnected

def _format_connected(entity, method, precedence, authorization):
    """Format the CONNECTED message."""
    return _serialize_all(
        _serialize_message(Message.CONNECTED), 
        _serialize_entity(entity), 
        _serialize_method(method), 
        _serialize_precedence(precedence), 
        _serialize_authorization(authorization))

# Outlet operations:

def activate(outlet, authorization):
    _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.ACTIVATE),
        _serialize_entity(outlet),
        _serialize_authorization(authorization)))

def deactivate(outlet, authorization):
    _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.DEACTIVATE),
        _serialize_entity(outlet),
        _serialize_authorization(authorization)))

def reset(outlet, authorization):
    _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.RESET),
        _serialize_entity(outlet),
        _serialize_authorization(authorization)))

def adapt(outlet, adapter, timeout, authorization): 
    logger.debug("Adapt on outlet {}, adapter {}, timeout {}".format(
        outlet, adapter, timeout))
    resp, sock  = _send_and_wait_for_response(
        _format_adapt(outlet, timeout, authorization), 
        keep_socket=True) 
    try:
        adapter_args = _parse_adapt_resp(resp)
        if adapter is not None:
            try:
                response = adapter(*adapter_args)
            except Exception as e:
                _notify_about_adapt_error(e, sock)
            else:
                _send_and_no_wait(
                    ACK + _serialize_all(_serialize_response(response)),
                    sock)
        else:
            _send_and_no_wait(ACK + b'0 ' + BUFFER_TERMINATOR, sock)
    except Exception as e:
        logger.debug("Error encountered during adapt callback: %s", e)
        raise
    finally:
        logger.debug("Returning socket %s", sock)
        _socket_pool.return_socket(sock)

def _format_adapt(outlet, timeout, authorization):    
    """Format the ADAPT message in HGTP."""
    return _serialize_all(
        _serialize_message(Message.ADAPT),
        _serialize_entity(outlet),
        _serialize_timeout(timeout),
        _serialize_authorization(authorization))

def _parse_adapt_resp(resp):
    """Parse the invocation response and return 15 things."""
    outlet = resp.pop_entity()
    entity = resp.pop_entity()
    auxiliary = resp.pop_entity()
    method = resp.pop_integer()
    attribute = resp.pop_integer()
    instance = resp.pop_integer()
    name = resp.pop_bytes()
    key = resp.pop_bytes()
    value = resp.pop_value()
    options = resp.pop_bytes()
    parameter = resp.pop_integer()
    index = resp.pop_integer()
    count = resp.pop_integer()
    mode = resp.pop_integer() 
    authorization = resp.pop_integer()
    return (
        outlet, entity, auxiliary, method, attribute, instance, name, key, 
        value, options, parameter, index, count, mode, authorization )

def _notify_about_adapt_error(error, sock):
    """An error has been raised in adapter. Notify the authorities."""
    logger.debug('Error {} encountered on adapt'.format(error))
    _send_and_no_wait(
        NAK + 
            _serialize_all(
                _serialize_code(HGTPexception.ADAPTER),
                _serialize_string(str(error))),
        sock)


# Event operations and utility functions

def publish(entity, event, attribute, instance, name, key, value, options,
            parameter, index, count, mode, authorization):
    _send_and_wait_for_response(_format_publish(
        entity, event, attribute, instance, name, key, value, options, 
        parameter, index, count, mode, authorization))

def _format_publish(entity, event, attribute, instance, name, key, value, 
                    options, parameter, index, count, mode, authorization):
    """Format the PUBLISH message in HGTP"""    
    return _serialize_all(
        _serialize_message(Message.PUBLISH), 
        _serialize_entity(entity), 
        _serialize_event(event),
        _serialize_attribute(attribute), 
        _serialize_instance(instance), 
        _serialize_name(name),
        _serialize_key(key),
        _serialize_value(value),
        _serialize_options(options), 
        _serialize_parameter(parameter),
        _serialize_index(index),
        _serialize_count(count), 
        _serialize_mode(mode),
        _serialize_authorization(authorization))

def subscribe(publishee, outlet, event, timeout, authorization):
    _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.SUBSCRIBE),
        _serialize_entity(publishee),
        _serialize_entity(outlet),
        _serialize_event(event),
        _serialize_timeout(timeout),
        _serialize_authorization(authorization)))

def cancel(entity, outlet, event, authorization):
    logger.debug("Cancel on outlet {}, entity {}, event {}".format(
        outlet, entity, event))
    _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.CANCEL),
        _serialize_entity(entity),
        _serialize_entity(outlet),
        _serialize_event(event),
        _serialize_authorization(authorization)))

def subscription(entity, index, authorization):
    resp = _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.SUBSCRIPTION),
        _serialize_entity(entity),
        _serialize_index(index),
        _serialize_authorization(authorization)))
    return resp.pop_entity(), resp.pop_integer()

def subscribed(entity, event, authorization):
    resp = _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.SUBSCRIBED),
        _serialize_entity(entity),
        _serialize_event(event),
        _serialize_authorization(authorization)))
    return resp.pop_boolean()

def wait(outlet, callback, timeout, authorization):
    logger.debug("Wait on outlet {}, callback {}, timeout {}".format(
        outlet, callback, timeout))
    resp = _send_and_wait_for_response(
        _format_wait(outlet, timeout, authorization))
    outlet = resp.pop_entity()
    publishee = resp.pop_entity()
    event = resp.pop_integer()
    attribute = resp.pop_integer()
    instance = resp.pop_integer()
    name = resp.pop_bytes()
    key = resp.pop_bytes()
    value = resp.pop_value()
    options = resp.pop_bytes()
    parameter = resp.pop_integer()
    index = resp.pop_integer()
    count = resp.pop_integer()
    mode = resp.pop_integer()

    if callback is not None: 
        try:
            callback(
                outlet, publishee, event, attribute, instance, name, key, value,
                options, parameter, index, count, mode, authorization)
        except Exception as e:
            logger.debug('Error {} encountered on wait'.format(e)) 
            raise 

def _format_wait(outlet, timeout, authorization):
    """Format a WAIT message in HGTP."""
    return _serialize_all(
        _serialize_message(Message.WAIT),
        _serialize_entity(outlet),
        _serialize_timeout(timeout),
        _serialize_authorization(authorization))

def flush(outlet, authorization):
    logger.debug(f"Flushing outlet {outlet}")
    _send_and_wait_for_response(_format_flush(outlet, authorization))

def _format_flush(outlet, authorization):
    return _serialize_all(
        _serialize_message(Message.FLUSH),
        _serialize_entity(outlet),
        _serialize_authorization(authorization))

def subscriptions(entity):
    resp = _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.REPORT), 
        _serialize_code(ReportCode.SUBSCRIPTIONS),
        _serialize_entity(entity)))
    return resp.pop_integer()

def pending(entity):
    """Are there pending events?"""
    resp = _send_and_wait_for_response(_format_pending(entity))
    return resp.pop_integer()

def _format_pending(entity):
    """Format the PENDING report in HGTP."""
    return _serialize_all(
        _serialize_message(Message.REPORT),
        _serialize_code(ReportCode.PENDING),
        _serialize_entity(entity))
    
# Authorization operations

def authorize(entity, authority, authorization):
    _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.AUTHORIZE),
        _serialize_entity(entity),
        _serialize_authority(authority), 
        _serialize_authorization(authorization)))

def deauthorize(entity, authority, authorization):
    _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.DEAUTHORIZE),
        _serialize_entity(entity),
        _serialize_authority(authority), 
        _serialize_authorization(authorization)))

def authorized(entity, authority, authorization):
    resp = _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.AUTHORIZED),
        _serialize_entity(entity),
        _serialize_authority(authority), 
        _serialize_authorization(authorization)))
    return resp.pop_boolean()

def authority(entity, index, authorization):
    resp = _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.AUTHORITY),
        _serialize_entity(entity),
        _serialize_index(index),
        _serialize_authorization(authorization)))
    return resp.pop_integer()

def authorities(entity):
    resp = _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.REPORT), 
        _serialize_code(ReportCode.AUTHORITIES),
        _serialize_entity(entity)))
    return resp.pop_integer()

# Lock operations

def lock(entity, timeout, authorization):
    """Attempt to lock entity."""
    _send_and_wait_for_response(_format_lock(entity, timeout, authorization))

def _format_lock(entity, timeout, authorization):
    """Format a LOCK message in HGTP."""
    return _serialize_all(
        _serialize_message(Message.LOCK), 
        _serialize_entity(entity), 
        _serialize_timeout(timeout), 
        _serialize_authorization(authorization))

def unlock(entity, authorization):
    """Attempt to unlock entity."""
    _send_and_wait_for_response(_format_unlock(entity, authorization))

def _format_unlock(entity, authorization):
    """Format an UNLOCK message in HGTP."""
    return _serialize_all(
        _serialize_message(Message.UNLOCK), 
        _serialize_entity(entity), 
        _serialize_authorization(authorization))

def locked(entity):
    """Return whether the entity is locked."""
    resp = _send_and_wait_for_response(_format_locked(entity))
    return resp.pop_boolean()

def _format_locked(entity):
    """Format a REPORT message with LOCKED code."""
    return _serialize_all(
        _serialize_message(Message.REPORT),
        _serialize_code(ReportCode.LOCKED),
        _serialize_entity(entity))

# Utility functions:

def name(entity):
    resp = _send_and_wait_for_response(_serialize_all(
            _serialize_message(Message.REPORT),
            _serialize_code(ReportCode.NAME),
            _serialize_entity(entity)))
    return resp.pop_string()

def klass(entity):
    resp = _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.REPORT), 
        _serialize_code(ReportCode.CLASS),
        _serialize_entity(entity)))
    return resp.pop_integer()

def subclass(entity):
    resp = _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.REPORT), 
        _serialize_code(ReportCode.SUBCLASS),
        _serialize_entity(entity)))
    return resp.pop_integer()

def server(entity):
    resp = _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.REPORT),
        _serialize_code(ReportCode.SERVER),
        _serialize_entity(entity)))
    return resp.pop_entity()

def redirection(entity):
    resp = _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.REPORT),
        _serialize_code(ReportCode.REDIRECTION),
        _serialize_entity(entity)))
    return resp.pop_entity()

def timestamp(entity):
    resp = _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.REPORT),
        _serialize_code(ReportCode.TIMESTAMP),
        _serialize_entity(entity)))
    return resp.pop_integer()

def available(entity):
    resp = _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.REPORT),
        _serialize_code(ReportCode.AVAILABLE),
        _serialize_entity(entity)))
    return resp.pop_boolean()

def deleted(entity):
    resp = _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.REPORT),
        _serialize_code(ReportCode.DELETED),
        _serialize_entity(entity)))
    return resp.pop_boolean()

def activated(entity):
    resp = _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.REPORT),
        _serialize_code(ReportCode.ACTIVATED),
        _serialize_entity(entity)))
    return resp.pop_boolean()

def connections(entity):
    resp = _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.REPORT),
        _serialize_code(ReportCode.CONNECTIONS),
        _serialize_entity(entity)))
    return resp.pop_integer()

def attachments(entity):
    resp = _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.REPORT),
        _serialize_code(ReportCode.ATTACHMENTS),
        _serialize_entity(entity)))
    return resp.pop_integer()

def references(entity):
    resp = _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.REPORT),
        _serialize_code(ReportCode.REFERENCES),
        _serialize_entity(entity)))
    return resp.pop_integer()

def host():
    resp = _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.REPORT), 
        _serialize_code(ReportCode.HOSTNAME),
        b"0 0 0"))
    return resp.pop_string() 

def version():
    resp = _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.REPORT),
        _serialize_code(ReportCode.VERSION),
        b" 0 0 0"))
    return resp.pop_string()

def local():
    resp = _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.REPORT),
        _serialize_code(ReportCode.LOCAL),
        b" 0 0 0"))
    return resp.pop_entity()

def gateway():
    resp = _send_and_wait_for_response(_serialize_all(
        _serialize_message(Message.REPORT),
        _serialize_code(ReportCode.GATEWAY),
        b" 0 0 0"))
    return resp.pop_entity()


################################################################################
#
# Helper functions
#
# (arguably these should be static functions in one class)


def _serialize_all(*bytezes):
    """Return a bytes of all args separated by spaces, ending with delimiter"""
    return b' '.join(bytezes) + BUFFER_TERMINATOR

def _serialize_string(message_string):
    """Serialize the string in the standard format"""
    assert isinstance(message_string, str), \
        'Trying to serialize purported string {} which is not a string'.format(
            message_string)
    message_bytes = message_string.encode(at.ENCODING)
    return b'%d %b' % (len(message_bytes), message_bytes)

def _serialize_entity(entity):
    """Serialize the entity in the standard format"""
    return b'%d %d %d' % (entity.pid, entity.hid, entity.uid)

def _serialize_message(message):
    """Serialize the message in the standard format."""
    return b'%d' % message.value

def _serialize_method(method):
    """Serialize the method in the standard format."""
    return b'%d' % method 

def _serialize_attribute(attribute):
    """Serialize the attribute in the standard format."""
    return b'%d' % attribute

def _serialize_instance(instance):
    """Serialize the instance in the standard format."""
    return b'%d' % instance

def _serialize_name(name):
    """Serialize a name in the standard format."""
    return b'%d %b' % (len(name), name)

def _serialize_key(key):
    """Serialize a key in the standard format."""
    return b'%d %b' % (len(key), key)

def _serialize_value(value):
    """Serialize a value in the standard format."""
    return value.serialize()

def _serialize_options(options):
    """Serialize the options in the standard format."""
    return b'%d %b' % (len(options), options)

def _serialize_parameter(parameter):
    """Serialize the parameter in the standard format."""
    return b'%d' % parameter

def _serialize_index(index):
    """Serialize the index in the standard format."""
    return b'%d' % index

def _serialize_count(count):
    """Serialize the count in the standard format."""
    return b'%d' % count    

def _serialize_mode(mode):
    """Serialize the mode in the standard format."""
    return b'%d' % mode 

def _serialize_precedence(precedence):
    """Serialize the precedence in the standard format."""
    return b'%d' % precedence 

def _serialize_timeout(timeout):
    """Serialize the timeout in the standard format."""
    return b'%d' % timeout 

def _serialize_authorization(auth):
    """Serialize the authorization code."""
    return auth.bytes()

def _serialize_response(response):
    """Serialize a response in the standard format."""
    return at.Value.from_object(response).serialize()

def _serialize_event(event):
    """Serialize an event in the standard format."""
    return b'%d' % event

def _serialize_class(klass):
    """Serialize a class in the standard format."""
    return b'%d' % klass

def _serialize_subclass(subklass):
    """Serialize a subclass in the standard format."""
    return b'%d' % subklass 

def _serialize_code(code):
    """Serialize a code (e.g. report code, error code) instandard format."""
    return b'%d' % code.value 

def _serialize_authority(authority):
    """Serialize an authority."""
    return authority.bytes()

def _serialize_integer(integer):
    """Serialize the integer in the standard format."""
    return b'%d' % integer

_socket_pool = None

def _ip2addr(ip):
    return struct.unpack("!L", socket.inet_aton(ip))[0]

def _addr2ip(addr):
    return socket.inet_ntoa(struct.pack("!L", addr))

def _confirm(message):
    logger.debug("Checking response '{}' for error reported".format(message))
    if len(message) == 0:
        logger.error("Empty response strinserver reg received", stack_info=True)
        raise at.CommunicationError('Empty response string received')
    elif message[0] == ACK_BYTE:
        logger.debug("No error reported")
    else:
        err_code, error_message_reported = parse_error(message)
        error = {
            HGTPexception.NULL: at.AvesTerraError,
            HGTPexception.ENTITY: at.EntityError,
            HGTPexception.OUTLET: at.OutletError,
            HGTPexception.COMMUNICATION: at.CommunicationError,
            HGTPexception.NETWORK: at.NetworkError,
            HGTPexception.TIMEOUT: at.TimeoutError,
            HGTPexception.AUTHORIZATION: at.AuthorizationError,
            HGTPexception.ADAPTER: at.AdapterError,
            HGTPexception.SUBSCRIBER: at.SubscriberError,
            HGTPexception.APPLICATION: at.ApplicationError,
            HGTPexception.BYPASS: at.BypassError,
            HGTPexception.FORWARD: at.ForwardError,
            HGTPexception.VALUE: at.ValueError
        }[err_code]

        error_message = 'Server reported {} error: {}'.format(
            err_code.name, error_message_reported)
        logger.error(error_message)
        raise error(error_message)

def parse_error(response):
    """Parse the error response and return the error and message (if any)"""
    if response[0] != NAK_BYTE:
        raise at.CommunicationError(
            'Response is neither ACK nor NAK: {}'.format(response))
    elif len(response) == 1:
        raise at.CommunicationError(
            'AvesTerra flagged an error, but provided no error code')
    else:
        _message_response = _MessageResponse(response)
        try:
            error_code = _message_response.pop_integer()
            if _message_response.is_empty():
                return HGTPexception(error_code), ''
            else: 
                return HGTPexception(error_code), _message_response.pop_string()
        except Exception:
            msg = 'Invalid error format: {}'.format(response)
            logger.error(msg)
            raise at.CommunicationError(msg)

def _send_and_wait_for_response(message, keep_socket=False):
    """Send the message and wait on response, blocking until received."""
    logger.debug("Sending message '{}' to AvesTerra server".format(message))
    if keep_socket:
        return _send_and_wait_for_response_keep_socket(message)
    else:
        return _send_and_wait_for_response_return_socket(message)

def _send_and_wait_for_response_return_socket(message):
    """Send message and wait on response."""
    sock = _socket_pool.borrow_socket()
    try:
        response = _send_and_wait_on_socket(message, sock)
    except (at.NetworkError, at.CommunicationError) as err:
        logger.debug('Error %s encountered while sending on socket %s',
            err, sock)
        _socket_pool.discard_socket(sock)
        raise
    except Exception as err:
        logger.debug('Error %s encountered while sending on socket %s',
            err, sock)
        _return_or_discard_socket(sock, err)
        raise
    _socket_pool.return_socket(sock)
    message_resp = _MessageResponse(response)
    return message_resp

def _send_and_wait_for_response_keep_socket(message):
    """Send message and wait on response."""
    sock = _socket_pool.borrow_socket()
    try:
        response = _send_and_wait_on_socket(message, sock)
    # Discard or return the socket if this does not work
    except (at.NetworkError, at.CommunicationError) as err:
        logger.debug('Error %s encountered while sending on socket %s',
            err, sock)
        _socket_pool.discard_socket(sock)
        raise
    except Exception as err:        
        logger.debug('Error %s encountered while sending on socket %s',
            err, sock)
        # the safe way: always discard
        _socket_pool.discard_socket(sock)
        # _return_or_discard_socket(sock, err)
        raise
    message_resp = _MessageResponse(response)
    return message_resp, sock 

def _return_or_discard_socket(sock, err):
    """Return or discard socket, depending on the error encountered."""
    # seems really ad hoc, but it works
    if 'Broken pipe' in str(err):
        _socket_pool.discard_socket(sock)
    else:
        _socket_pool.return_socket(sock)

def _send_and_wait_on_socket(message, sock):
    """Just send and wait.""" 
    _raise_error_if_overly_large(message)
    logger.debug("Sending bytes '{}' on socket {}".format(message, sock))
    sock.sendall(message)
    response = _recvall(sock)
    logger.debug("Received resp '{}' on socket {}".format(response, sock))
    _confirm(response)
    return response

def _raise_error_if_overly_large(bytes):
    """If the bytes are too big to send, raise an error."""
    if len(bytes) > MESSAGE_SIZE_LIMIT_IN_BYTES:
        msg = 'Attempting to send overly large message starting with {}'.format(
            bytes[:100])
        logger.warn(msg)
        raise at.MessageTooLargeError(msg)

def _send_and_no_wait(message, sock):
    """Send the message and do not wait for a response."""
    logger.debug("Sending message {} to AvesTerra server".format(message)) 
    _raise_error_if_overly_large(message)
    logger.debug("Sending bytes '{}' on socket {}".format(message, sock))
    sock.sendall(message)


def _recvall(sock):
    """Receive all the bytes, perhaps involving multiple recv() calls"""
    # Note: this expects a BUFFER_TERMINATOR at the end
    # If there are many calls to recv, this is pretty inefficient. To refactor
    def recv_and_check():
        try:
            m = sock.recv(BUFFER_SIZE)
        except ConnectionResetError as err:
            msg = 'Connection reset error on sock {}'.format(sock)
            logger.error(msg) 
            raise at.CommunicationError(msg)
        if m == b'':
            msg = 'The socket {} was unexpectedly closed'.format(sock)
            logger.error(msg)
            raise at.CommunicationError(msg)
        return m 

    msg = recv_and_check()
    i = 1
    while msg[-1] != BUFFER_TERMINATOR_BYTE:
        msg = msg + recv_and_check()
        i = i + 1
    return msg


class _MessageResponse:
    """For parsing the message responses from the AvesTerra server."""
    def __init__(self, msg):
        self._remaining = msg[1:]

    def pop_entity(self):
        """Pull the three components of an entity, and return the entity."""
        return at.Entity(
            self.pop_integer(), self.pop_integer(), self.pop_integer())

    def pop_integer(self):
        """Pull an integer, delimited by a space, and return it."""
        try:
            maybe_integer, self._remaining = tuple(self._remaining.split(
                b' ', 1))
        except ValueError:
            try:
                maybe_integer, self._remaining = tuple(self._remaining.split(
                    b'\x00', 1))
            except ValueError:
                maybe_integer = self._remaining
                self._remaining = b''

        return int(maybe_integer)

    def pop_bytes(self):
        """Pull bytes, whose length is given as an integer."""
        length = self.pop_integer()
        bytez = self._remaining[:length]
        if len(bytez) < length:
            raise at.CommunicationError('String too short')
        self._remaining = self._remaining[length + 1:]
        return bytez

    def pop_string(self):
        """Pop bytes and convert to string."""
        return self.pop_bytes().decode(at.ENCODING)

    def pop_boolean(self):
        """Pull a boolean and return  it."""
        return bool(self.pop_integer())

    def pop_delimited_bytes(self):
        """Pull bytes, delimited by a space."""
        try:
            bytez, self._remaining = tuple(self._remaining.split(' ', 1))
        except ValueError:
            bytez, self._remaining = tuple(self._remaining.split('\x00', 1))
        return bytez

    def pop_value(self):
        """Pull an instance of type value."""
        return at.Value(self.pop_integer(), self.pop_bytes())

    def is_empty(self):
        """Is nothing left in the mssage response?"""
        return self._remaining == ''


################################################################################
#
# SocketPool
#

class SocketPool:
    """A threadsafe pool of socket connetions to this host and port"""

    def __init__(self, host_ip, port, quantity, timeout=30):
        logger.debug("Creating a new socket pool")
        # could check whether host_ip is an string for an IP address, 
        # and whether port is a valid port
        self._host_ip = host_ip
        self._port = port
        self._pool = TimeoutPool(
            lambda: self._create_socket(),
            lambda s: self._close_socket(s),
            quantity,
            timeout)

    def borrow_socket(self):
        """Get a socket from the pool of sockets. Block until available"""
        sock = self._pool.borrow_resource()
        logger.debug('Borrowing socket %s', sock)
        return sock

    def return_socket(self, sock):
        """Return socket to the pool"""
        logger.debug('Returning socket %s', sock)
        self._pool.return_resource(sock)

    def discard_socket(self, sock):
        """Discard socket, so it is not used again."""
        self._pool.discard_resource(sock)

    def end_pool(self):
        """Close all sockets in the pool"""
        self._pool.spin_down_pool()

    def alive(self):
        """Is the socket pool still alive or has it already ended?"""
        return self._pool.alive()

    def _create_socket(self):
        """Create a new socket to host and port"""
        logger.debug("Creating socket")
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM) 
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        try:
            s.connect((self._host_ip, self._port))
        except OSError as err:
            logger.error('Error {} on connect to host {}, port {}'.format(
                err, self._host_ip, self._port))
            s.close()
            raise
        logger.debug("Socket created: {}".format(s))
        return s 

    def _close_socket(self, sock):
        """Close this socket"""
        def close_socket(): 
            logger.debug("Closing socket {}".format(sock))
            try:
                sock.sendall(_serialize_message(Message.BYE) +BUFFER_TERMINATOR)
            except BrokenPipeError as err:
                message = 'Broken pipe {} while closing socket {}: {}'.format(
                    err.errno, sock, err.strerror)
                logger.error(message)
                return
            try:
                sock.close()
                logger.debug("Socket closed")
            except OSError as err:
                message = 'OS error {} while closing socket {}: {}'.format(
                    err.errno, sock, err.strerror)
                if err.errno == 57:
                    logger.debug(message)
                else:
                    logger.error(message)
                    logger.debug('Socket not closed, maybe')

        logger.debug("Creating thread to close socket {}".format(sock))
        # IN a separate thread in case it takes awhile
        threading.Thread(target=close_socket).start()

# 
#  TimeoutPool --- a generic class for managing a pool of resources
#                  that timeout after no usage for awhile
#
#  This wants to be moved to its own module
#
class TimeoutPool:
    """A pool of resources that will spin down automatically with no usage"""
    # resources must be hashable
    def __init__(self, spin_up, spin_down, max_quantity, no_usage_duration=60):
        """
        spin_up --- callable to create a resource, returns resource
        spin_down --- callable to destory a resource 
        max_quantity --- maximum number of resources that are allowed
        no_usage_duration --- how long (in seconds) of no use before 
                              automatic spin_down
        """
        logger.debug(
            "Creating a new timeout pool {} of {} timing out at {}".format(
            self, max_quantity, no_usage_duration))
        if max_quantity < 1:
            raise TimeoutPoolError('max_quantity must be at least 1')
        elif no_usage_duration < 1:
            raise TimeoutPoolError('No usage duration must be at least 1 sec')
        else:
            # only need this for debugging data structures
            self._lifeguard = _TimeoutPoolLifeguard(
                spin_up, spin_down, max_quantity, no_usage_duration)
            self._lifeguard_requests = self._lifeguard.request_queue()

    def borrow_resource(self):
        """Borrow a resource from the pool, creating or blocking as nec"""
        logger.debug('Trying to borrow a resource from {}'.format(self))
        assert self.alive(), 'Attempting to borrow from spun down pool'
        # Are queues lightweight enough for use once and dispose?
        resource_destination = queue.Queue()
        self._lifeguard_requests.put(('borrow', resource_destination))
        results =  resource_destination.get()
        if results == 'error':
            raise TimeoutPoolError(resource_destination.get())
        else:
            return results

    def return_resource(self, res):
        """Return the resource to the pool"""
        logger.debug('Returning resource {} to {}'.format(res, self))
        assert self.alive(), 'Attempting to return to spun down pool'
        self._lifeguard_requests.put(('return', res))

    def discard_resource(self, res):
        """Throw away the resource."""
        logger.debug('Discarding resource {}'.format(res))
        assert self.alive(), 'Attempt to discard resource in spun down pool'
        self._lifeguard_requests.put(('discard', res))

    def spin_down_pool(self):
        """Spin down all resources in the pool"""
        logger.debug('Spinning down pool {}'.format(self))
        if self.alive():
            self._lifeguard_requests.put(('stop',))
            del self._lifeguard_requests

    def alive(self):
        """Is the timeout pool still alive?"""
        return hasattr(self, '_lifeguard_requests')

class _TimeoutPoolLifeguard:
    """Manages a TimeoutPool; exactly one lifeguard for each pool"""
    def __init__(self, spin_up, spin_down, max_quantity, no_usage_duration=60):
        """
        spin_up --- callable to create a resource, returns resource
        spin_down --- callable to destory a resource, given resource
        quantity --- how many resources to create as max
        no_usage_duration --- how long (in seconds) of no use before 
                              automatic spin_down
        """
        logger.debug('Creating a new timeout pool lifeguard %s', self)
        self._spin_up = spin_up 
        self._spin_down = spin_down
        self._max_quantity = max_quantity 
        self._current_quantity = 0
        self._no_usage_duration = no_usage_duration
        self._free_resources = {}   # dict of resource and time last returned
        self._waiting_to_borrow = collections.deque() 
        self._requestq = queue.Queue()
        threading.Thread(target=self._perform_requests_forever, args=()).start()

    def request_queue(self):
        return self._requestq 

    def _perform_requests_forever(self):
        """perform requests one at a time, checking occasionally for staleness"""
        while True:
            try:
                request = self._requestq.get(timeout=5)
                self._perform_request(*request)
            except queue.Empty:
                self._spin_down_stale_resources()
            except FinishLifeguarding:
                break

    def _perform_request(self, request_action, *args):
        """Do whatever is requested"""
        if request_action == 'borrow':
            borrower_queue, = args
            self._provide_resource_to_borrower(borrower_queue)
        elif request_action == 'return':
            resource_returned, = args
            self._collect_resource_from_borrower(resource_returned)
        elif request_action == 'discard':
            trash, = args
            self._discard_resource(trash)
        elif request_action == 'stop':
            self._spin_down_all_resources()
            raise FinishLifeguarding
        else:
            raise TimeoutPoolError('Unknown request {}'.format(request_action))

    def _provide_resource_to_borrower(self, borrower_queue):
        logger.debug('Attempting to provide resource on %s', borrower_queue)
        if self._free_resources:
            resource, ignore = self._free_resources.popitem()
            logger.debug('Resource %s put on queue %s', resource,borrower_queue)
            borrower_queue.put(resource)
        elif self._current_quantity < self._max_quantity:
            logger.debug('Resource must be created for queue %s',borrower_queue)
            self._create_resource(borrower_queue)
        else:
            logger.debug('Waiting for resource to be freed')
            self._waiting_to_borrow.append(borrower_queue)

    def _collect_resource_from_borrower(self, resource_returned):
        """Someone has returned a resource. Put it back in the free list"""
        logger.debug('Resource %s is returned.', resource_returned)
        if self._waiting_to_borrow:
            q = self._waiting_to_borrow.popleft()
            logger.debug('Returned resource %s sent on %s', resource_returned,q)
            q.put(resource_returned)
        else:
            tm = time.time()
            logger.debug(
                'Returned resource %s put on freelist at %s', 
                resource_returned, 
                tm)
            self._free_resources[resource_returned] = tm

    def _spin_down_stale_resources(self):
        """If any of the resources are stale, spin them down"""
        now = time.time()
        # logger.debug('Checking for stale resources at %s', now)
        # copy is critical because we may remove resources from list
        for resource, last_used in self._free_resources.copy().items():
            if last_used + self._no_usage_duration < now:
                logger.debug('Resource %s unused since %s', resource, last_used)
                self._spin_down_and_remove(resource) 

    def _spin_down_all_resources(self):
        """Spin down all of them, whether they are stale or not"""
        logger.debug('Spinning down all resources, on request')
        for resource, last_used in self._free_resources.copy().items():
            self._spin_down_and_remove(resource)

    def _spin_down_and_remove(self, resource):
        """Spin down a single resource and remove it from the freelist"""
        logger.debug('Spinning down and removing resource %s', resource)
        self._free_resources.pop(resource)
        self._discard_resource(resource)

    def _create_resource(self, q):
        """Create a new resource, put on q, and record how many are out."""
        try:
            res = self._spin_up()
            q.put(res)
            self._current_quantity += 1
            logger.debug(
                'Created timeout pool resource %s, %d out', 
                res, self._current_quantity)
        except Exception as err:
            q.put('error')
            q.put('{}: {}'.format(type(err).__name__, str(err)))

    def _discard_resource(self, resource_to_discard):
        """Discard this resource."""
        logger.debug(
            'Discarding timeout pool resource %s, %d out', 
            resource_to_discard, self._current_quantity - 1)
        self._spin_down(resource_to_discard)
        self._current_quantity -= 1


class FinishLifeguarding(Exception):
    """When the socket pool is finishing up"""
    pass

class TimeoutPoolError(Exception):
    """Error with the timeout pool"""
    def __init__(self, message):
        self.message = message