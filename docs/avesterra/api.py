#!/usr/bin/env python3

"""api.py:  the API layer of the Python binding for AvesTerra.
"""

__author__ = "Dave Bridgeland and J. C. Smart"
__copyright__ = "Copyright 2015-2020, Georgetown University"
__patents__ = "US Patent No. 9,996,567"
__credits__ = ["J. C. Smart", "Dave Bridgeland", "Norman Kraft"]

__version__ = "3.15.5"
__maintainer__ = "Dave Bridgeland"
__email__ = "dave@hangingsteel.com"
__status__ = "Prototype"

import logging 
import enum

import avesterra.hgtp as HGTP
import avesterra.base as at

logger = logging.getLogger(__name__)

# AvesTerra null constants:

NULL_ENTITY = at.Entity(0, 0, 0)
NULL_INSTANCE = 0   
NULL_NAME = b''
NULL_KEY = b''
NULL_VALUE = at.Value(0, b'')
NULL_OPTIONS = b''
NULL_PARAMETER = 0
NULL_PRECEDENCE = 0
NULL_INDEX = 0
NULL_COUNT = 0
NULL_MODE = 0
NULL_TIMEOUT = 0
NULL_AUTHORIZATION = at.Authorization(0)
NULL_RESULT = ''
NULL_DATA = b''

# Used only for defaults, because the real values are retrieved from ontology
NULL_CLASS = 0
NULL_SUBCLASS = 0
NULL_ATTRIBUTE = 0
NULL_METHOD = 0
NULL_EVENT = 0
NULL_STATE = 0


################################################################################
#
# Initialize, including socket_max
#

socket_max = None
def initialize(server=NULL_ENTITY, socket_count=16): 
    logger.info("Initializing server {} with {} sockets".format(
      server, socket_count))
    global socket_max
    socket_max = socket_count
    HGTP.initialize(server, socket_count)
    logger.info("Server initialized")

def finalize():
    logger.info('Ending AvesTerra session')
    HGTP.finalize()

def max_async_connections():
    """What is the maximum number of async connections supported?"""
    return socket_max 


################################################################################
#
# Entity operations
#

def create(server=NULL_ENTITY, name=NULL_NAME, klass=NULL_CLASS, 
           subklass=NULL_SUBCLASS, authorization=NULL_AUTHORIZATION):
    """Create entity.""" 
    logger.info(
        'Creating entity {} of class {}, subclass {}'.format(
            name, klass, subklass))
    at.Verify.bytes(name)
    at.Verify.code(klass, 'class')
    at.Verify.code(subklass, 'subclass')
    at.Verify.authorization(authorization)
    return HGTP.create(server, name, int(klass), int(subklass),
                       authorization)

def delete(entity, authorization=NULL_AUTHORIZATION):
    logger.info('Deleting entity {}'.format(entity))
    at.Verify.entity(entity)
    at.Verify.authorization(authorization)
    return HGTP.delete(entity, authorization)

def invoke(entity, auxiliary=NULL_ENTITY, method=NULL_METHOD, 
           attribute=NULL_ATTRIBUTE, instance=NULL_INSTANCE, name=NULL_NAME, 
           key=NULL_KEY, value=NULL_VALUE, options=NULL_OPTIONS, 
           parameter=NULL_PARAMETER, index=NULL_INDEX, count=NULL_COUNT, 
           mode=NULL_MODE, precedence=NULL_PRECEDENCE, timeout=NULL_TIMEOUT,
           authorization=NULL_AUTHORIZATION):
    logger.info(
        ('Invoking method {} on entity {}, with attribute {}, instance {}, ' +
        'name {}, key {}, value {}, options {}, parameter {}, index {}, ' +
        'count {}, mode {}, precedence {}, and timeout {}').format(
            method, entity, attribute, instance, name, key, value, options, 
            parameter, index, count, mode, precedence, timeout))
    at.Verify.entity(entity)
    at.Verify.entity(auxiliary)
    at.Verify.natural(method)
    at.Verify.natural(attribute)
    at.Verify.natural(instance)
    at.Verify.bytes(name)
    at.Verify.bytes(key)
    at.Verify.value(value)
    at.Verify.bytes(options)
    at.Verify.integer(parameter)
    at.Verify.natural(index)
    at.Verify.natural(count)
    at.Verify.natural(mode)
    at.Verify.natural(precedence)
    at.Verify.integer(timeout)
    at.Verify.authorization(authorization)
    return HGTP.invoke(
        entity, auxiliary, method, attribute, instance, name, key, value, 
        options, parameter, index, count, mode, precedence, timeout, 
        authorization)

def inquire(entity, auxiliary=NULL_ENTITY, attribute=NULL_ATTRIBUTE, 
            instance=NULL_INSTANCE, name=NULL_NAME, key=NULL_KEY, 
            value=NULL_VALUE, options=NULL_OPTIONS, parameter=NULL_PARAMETER, 
            index=NULL_INDEX, count=NULL_COUNT, mode=NULL_MODE, 
            precedence=NULL_PRECEDENCE, timeout=NULL_TIMEOUT,
            authorization=NULL_AUTHORIZATION):
    at.Verify.entity(entity)
    at.Verify.entity(auxiliary)
    at.Verify.natural(attribute)
    at.Verify.natural(instance)
    at.Verify.bytes(name)
    at.Verify.bytes(key)
    at.Verify.value(value)
    at.Verify.bytes(options)
    at.Verify.integer(parameter)
    at.Verify.natural(index)
    at.Verify.natural(count)
    at.Verify.natural(mode)
    at.Verify.natural(precedence)
    at.Verify.integer(timeout)
    at.Verify.authorization(authorization)
    return HGTP.inquire(
        entity, auxiliary, attribute, instance, name, key, value, options,
        parameter, index, count, mode, precedence, timeout, authorization)


def reference(entity, authorization=NULL_AUTHORIZATION):
    at.Verify.entity(entity)
    at.Verify.authorization(authorization)
    return HGTP.reference(entity, authorization)


def dereference(entity, authorization=NULL_AUTHORIZATION):
    at.Verify.entity(entity)
    at.Verify.authorization(authorization)
    return HGTP.dereference(entity, authorization)


# Connection operations:

def connect(entity, outlet, method=NULL_METHOD, precedence=NULL_PRECEDENCE,
            authorization=NULL_AUTHORIZATION):
    at.Verify.entity(entity)
    at.Verify.entity(outlet)
    at.Verify.natural(method),
    at.Verify.natural(precedence)
    at.Verify.authorization(authorization)
    return HGTP.connect(entity, outlet, method, precedence, authorization)

def disconnect(entity, outlet, method=NULL_METHOD, precedence=NULL_PRECEDENCE,
               authorization=NULL_AUTHORIZATION):
    at.Verify.entity(entity)
    at.Verify.authorization(authorization)
    return HGTP.disconnect(
        entity, outlet, int(method), precedence, authorization)

def connection(entity, index, authorization=NULL_AUTHORIZATION):
    at.Verify.entity(entity)
    at.Verify.authorization(authorization)
    return HGTP.connection(entity, index, authorization)

def connected(entity, method=NULL_METHOD, precedence=NULL_PRECEDENCE, 
              authorization=NULL_AUTHORIZATION):
    at.Verify.entity(entity)
    at.Verify.natural(method)
    at.Verify.natural(precedence)
    at.Verify.authorization(authorization)
    return HGTP.connected(entity, method, precedence, authorization)

# Attachment operations

def attach(entity, outlet, attribute=NULL_ATTRIBUTE, precedence=NULL_PRECEDENCE,
           authorization=NULL_AUTHORIZATION):
    at.Verify.entity(entity)
    at.Verify.entity(outlet)
    at.Verify.natural(attribute)
    at.Verify.natural(precedence)
    at.Verify.authorization(authorization)
    return HGTP.attach(entity, outlet, int(attribute), precedence,authorization)

def detach(entity, outlet=NULL_ENTITY, attribute=NULL_ATTRIBUTE, 
           precedence=NULL_PRECEDENCE, authorization=NULL_AUTHORIZATION):
    at.Verify.entity(entity)
    at.Verify.entity(outlet)
    at.Verify.natural(attribute)
    at.Verify.natural(precedence)
    at.Verify.authorization(authorization)
    return HGTP.detach(entity, outlet, int(attribute), precedence,authorization)

def attachment(entity, index, authorization=NULL_AUTHORIZATION):
    at.Verify.entity(entity)
    at.Verify.authorization(authorization)
    return HGTP.attachment(entity, index, authorization)

def attached(entity, attribute=NULL_ATTRIBUTE, precedence=NULL_PRECEDENCE, 
             authorization=NULL_AUTHORIZATION):
    at.Verify.entity(entity)
    at.Verify.natural(attribute)
    at.Verify.natural(precedence)
    at.Verify.authorization(authorization)
    return HGTP.attached(entity, attribute, precedence, authorization)

# Outlet operations

def activate(outlet, authorization=NULL_AUTHORIZATION):
    at.Verify.entity(outlet)
    at.Verify.authorization(authorization)
    return HGTP.activate(outlet, authorization)


def deactivate(outlet, authorization=NULL_AUTHORIZATION):
    at.Verify.entity(outlet)
    at.Verify.authorization(authorization)
    return HGTP.deactivate(outlet, authorization)


def reset(outlet, authorization=NULL_AUTHORIZATION):
    at.Verify.entity(outlet)
    at.Verify.authorization(authorization)
    return HGTP.reset(outlet, authorization)


def adapt(outlet, adapter=None, timeout=NULL_TIMEOUT, 
          authorization=NULL_AUTHORIZATION):
    at.Verify.entity(outlet)
    at.Verify.authorization(authorization)
    return HGTP.adapt(outlet, adapter, timeout, authorization)


# Event operations and utility functions

def publish(entity, authorization, event=NULL_EVENT, attribute=NULL_ATTRIBUTE, 
            instance=NULL_INSTANCE, name=NULL_NAME, key=NULL_KEY, 
            value=NULL_VALUE, options=NULL_OPTIONS, parameter=NULL_PARAMETER, 
            index=NULL_INDEX, count=NULL_COUNT, mode=NULL_MODE):
    at.Verify.entity(entity)
    at.Verify.natural(event)
    at.Verify.natural(attribute)
    at.Verify.natural(instance)
    at.Verify.bytes(name)
    at.Verify.bytes(key)
    at.Verify.value(value)
    at.Verify.bytes(options)
    at.Verify.integer(parameter)
    at.Verify.natural(index)
    at.Verify.natural(count)
    at.Verify.natural(mode)
    at.Verify.authorization(authorization)
    return HGTP.publish(
        entity, event, attribute, instance, name, key, value, options,
        parameter, index, count, mode, authorization)


def subscribe(publishee, outlet, event=NULL_EVENT, timeout=NULL_TIMEOUT,
              authorization=NULL_AUTHORIZATION):
    at.Verify.entity(publishee)
    at.Verify.entity(outlet)
    at.Verify.natural(event)
    at.Verify.natural(timeout)
    at.Verify.authorization(authorization)
    return HGTP.subscribe(publishee, outlet, event, timeout, authorization)


def cancel(entity, outlet, event=NULL_EVENT, authorization=NULL_AUTHORIZATION):
    at.Verify.entity(entity)
    at.Verify.entity(outlet)
    at.Verify.authorization(authorization)
    return HGTP.cancel(entity, outlet, int(event), authorization)

def subscription(outlet, index, authorization=NULL_AUTHORIZATION):
    at.Verify.entity(outlet) 
    at.Verify.natural(index)
    at.Verify.authorization(authorization)
    return HGTP.subscription(outlet, index, authorization)

def subscribed(entity, event=NULL_EVENT, authorization=NULL_AUTHORIZATION):
    at.Verify.entity(entity)
    at.Verify.natural(event)
    at.Verify.authorization(authorization)
    return HGTP.subscribed(entity, event, authorization)

def wait(outlet, callback=None, timeout=NULL_TIMEOUT, 
         authorization=NULL_AUTHORIZATION):
    at.Verify.entity(outlet)
    at.Verify.natural(timeout)
    at.Verify.callback(callback)
    at.Verify.authorization(authorization)
    return HGTP.wait(outlet, callback, timeout, authorization)


def flush(outlet, authorization=NULL_AUTHORIZATION):
    at.Verify.entity(outlet)
    at.Verify.authorization(authorization)
    HGTP.flush(outlet, authorization)

def subscriptions(entity):
    at.Verify.entity(entity)
    return HGTP.subscriptions(entity)

def pending(entity):
    """Are there pending events in the queue?"""
    at.Verify.entity(entity)
    return HGTP.pending(entity)


# Authorization operations

def authorize(entity, authority, authorization):
    at.Verify.entity(entity)
    at.Verify.authorization(authorization)
    return HGTP.authorize(entity, authority, authorization)


def deauthorize(entity, authority, authorization):
    at.Verify.entity(entity)
    at.Verify.authorization(authorization)
    return HGTP.deauthorize(entity, authority, authorization)


def authorized(entity, authority, authorization):
    at.Verify.entity(entity)
    at.Verify.authorization(authorization)
    return HGTP.authorized(entity, authority, authorization)


def authority(entity, index, authorization):
    at.Verify.entity(entity)
    at.Verify.authorization(authorization)
    return at.Authorization(HGTP.authority(entity, index, authorization))

# Lock operations

def lock(entity, timeout=NULL_TIMEOUT, authorization=NULL_AUTHORIZATION):
    """Attempt to lock entity."""
    at.Verify.entity(entity)
    at.Verify.authorization(authorization)
    return HGTP.lock(entity, timeout, authorization)

def unlock(entity, authorization=NULL_AUTHORIZATION):
    """Attempt to unlock entity."""
    at.Verify.entity(entity)
    at.Verify.authorization(authorization)
    return HGTP.unlock(entity, authorization)

# Entity set operations

def set_name(entity, name, authorization):
    at.Verify.entity(entity)
    at.Verify.bytes(name)
    at.Verify.authorization(authorization)
    HGTP.set_name(entity, name, authorization)

def set_class(entity, klass, authorization):
    at.Verify.entity(entity)
    at.Verify.code(klass, 'class')
    at.Verify.authorization(authorization)
    HGTP.set_class(entity, klass, authorization)

def set_subclass(entity, subklass, authorization):
    at.Verify.entity(entity)
    at.Verify.code(subklass, 'subclass')
    at.Verify.authorization(authorization)
    HGTP.set_subclass(entity, subklass, authorization)

# Utility functions:

def name(entity):
    at.Verify.entity(entity)
    return HGTP.name(entity)

def klass(entity):
    at.Verify.entity(entity)
    return HGTP.klass(entity)

def subclass(entity):
    at.Verify.entity(entity)
    return HGTP.subclass(entity)

def server(entity):
    at.Verify.entity(entity)
    return HGTP.server(entity)

def redirection(entity):
    at.Verify.entity(entity)
    return HGTP.redirection(entity)

def timestamp(entity):
    at.Verify.entity(entity)
    return HGTP.timestamp(entity)

def available(entity):
    at.Verify.entity(entity)
    return HGTP.available(entity)

def extinct(entity):
    at.Verify.entity(entity)
    return HGTP.deleted(entity)

def activated(entity):
    at.Verify.entity(entity)
    return HGTP.activated(entity)

def connections(entity):
    at.Verify.entity(entity)
    return HGTP.connections(entity)

def attachments(entity):
    at.Verify.entity(entity)
    return HGTP.attachments(entity)

def references(entity):
    at.Verify.entity(entity)
    return HGTP.references(entity)

def authorities(entity):
    at.Verify.entity(entity)
    return HGTP.authorities(entity)

def locked(entity):
    at.Verify.entity(entity)
    return HGTP.locked(entity)

def authorization_of(token):
    return int(token)




# Server operations

def local():
    return HGTP.local()

def host():
    return HGTP.host()

def gateway():
    return HGTP.gateway()

def version():
    return HGTP.version()




