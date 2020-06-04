#!/usr/bin/env python3

"""avial.py: AvesTerra layer implementing types and other stuff.
"""

__author__ = "Dave Bridgeland and J. C. Smart"
__copyright__ = "Copyright 2015-2020, Georgetown University"
__patents__ = "US Patent No. 9,996,567"
__credits__ = ["J. C. Smart", "Dave Bridgeland", "Norman Kraft"]

__version__ = "2.5.3"
__maintainer__ = "Dave Bridgeland"
__email__ = "dave@hangingsteel.com"
__status__ = "Prototype"

import functools 
import json
import logging
import os
import sys
import contextlib 
import enum
import urllib
import time

import jsonschema

import avesterra.api as atapi
import avesterra.base as at

logger = logging.getLogger(__name__)

################################################################################
#
# Value class, with added functionality
#

class Value(at.Value):
    _size_limit = 1_048_575

    class _ConversionError(Exception):
        """Transient error if object cannot be instantiated."""
        pass

    def size(self):
        """Length of string"""
        return len(self._bytes)

    def instantiate(self):
        """Convert bytes into some Python value."""
        try:
            return self._converter()()
        except KeyError:
            raise AvialError('Type tag {} not known'.format(self._type_tag))
        except Value._ConversionError:
            raise AvialError(
                'Value represented as "{}" cannot be converted to {}'.format(
                    self._bytes, at.Tag(self._type_tag).name))

    def _converter(self):
        "What function converts the bytes representation?"
        return {
            at.Tag.NULL.value: self._as_is,
            at.Tag.BOOLEAN.value: self._boolean,
            at.Tag.CHARACTER.value: self._character,
            at.Tag.STRING.value: self.string,
            at.Tag.TEXT.value: self.utf_8,
            at.Tag.INTEGER.value: self._integer,
            at.Tag.FLOAT.value: self._float,
            at.Tag.ENTITY.value: self._entity,
            at.Tag.TIME.value: self._time,
            at.Tag.UNIFORM.value: self._resource,
            at.Tag.INTERCHANGE.value: self._json,
            at.Tag.DATA.value: self._as_is
        }[self._type_tag]

    def _as_is(self):
        """No conversion."""
        return self._bytes

    def _boolean(self):
        """Convert to boolean, strictly."""
        try:
            return {b'TRUE': True, b'FALSE': False}[self._bytes]
        except KeyError:
            raise Value._ConversionError()

    def _character(self):
        """Convert to character (string of length 1), strictly."""
        maybe_char = self._bytes.decode(at.ENCODING)
        if len(maybe_char) == 1:
            return maybe_char
        else:
            raise Value._ConversionError()

    def string(self):
        """Convert ascii bytes to string."""
        try:
            return self._bytes.decode('ascii')
        except UnicodeDecodeError:
            logger.error(
                f'Non-ascii bytes found in supposed ascii {self._bytes}')
            return self._bytes.decode('ascii', errors='ignore')

    def utf_8(self):
        """Convert UTF-8 bytes to string."""
        try:
            return self._bytes.decode('utf_8')
        except UnicodeDecodeError:
            logger.error(
                f'Non-UTF-8 bytes found in supposed UTF-8 {self._bytes}')
            return self._bytes.decode('utf-8', errors='ignore')

    def _integer(self):
        """Convert to integer, stricly."""
        try:
            return int(self._bytes)
        except ValueError:
            raise Value._ConversionError()

    def _float(self):
        """Convert to float, stricly."""
        try:
            return float(self._bytes)
        except ValueError:
            raise Value._ConversionError()

    def _entity(self):
        """Convert to entity, strictly."""
        try:
            return entity_of(self._bytes.decode(at.ENCODING))
        except at.EntityError:
            raise Value._ConversionError

    def _time(self):
        """Convert to time object."""
        try:
            return time.gmtime(int(self._bytes))
        except ValueError:
            raise Value._ConversionError()

    def _resource(self):
        """Attempt to interpret as URI."""
        maybe_resource = self._bytes.decode(at.ENCODING)
        try:
            # despite name, parses URIs
            urllib.parse.urlparse(maybe_resource)
        except Exception:
            raise Value._ConversionError()
        return maybe_resource
        
    def _json(self):
        """Convert to jsonified python, string."""
        try:
            return json.loads(self._bytes)
        except json.decoder.JSONDecodeError:
            raise Value._ConversionError

################################################################################
#
# Session operations
#

def initialize(server='<0|0|0>', auth_code=0):
    """
    Start an AvesTerra session.

    Start an AvesTerra session, initializing communication with the 
    AvesTerra server, downloading and initializing the taxonomy, and loading the 
    store format schema.

    Parameters
    ----------
    server : str or Entity, optional
        the server or the UUID of the server to which the session is made. If
        not provided, the session is connected to a server running on the local
        host.

    auth_code : int, optional
        numeric code to authorize the server. If not provided, zero is assumed,
        and will work if the server requires no authorization code.

    Returns
    -------
    Authorization 
        Authorization object, to be supplied to other operations in the 
        session

    Raises
    ------
    AvialError
        If ``server`` is neither a UUID nor an AvesTerra server entity

    See also
    --------
    :func:`finalize` : end the AvesTerra session

    :func:`create_entity` : create an entity

    Examples
    --------
    >>> import avesterra.avial as av  

    Start an AvesTerra session, returning an authorization token for 
    subsequent use.

    >>> auth = initialize()

    Create a new entity. (See :func:`create_entity` for details.)

    >>> ths = av.create_entity(
    ...     "The Hold Steady", av.Class.ORGANIZATION, av.Subclass.GROUP, auth, 
    ...     outlet=av.object_outlet(), autosave=True)

    >>> str(ths)
    '<2906857743|167772516|804228>'

    End the session.

    >>> av.finalize()
    """
    with handle_API_exceptions(
            f'while initializing AvesTerra on server entity {server}'):
        return _initialize(server, auth_code)

def _initialize(server='<0|0|0>', auth_code=0):
    """Initialize AvesTerra session."""
    # Initialization of logging, store schema, and on-the-fly taxonomy
    # differs from reference implementation 
    _initialize_basic_logging()
    atapi.initialize(entity_of(server))
    _initialize_store_schema()
    _initialize_taxonomy()
    return at.Authorization(auth_code)

def finalize():
    """
    End the AvesTerra session.

    End the AvesTerra session. If no session has been started or the session is
    already ended, does nothing.

    Returns
    -------
    None

    See also
    --------
    :func:`initialize` : start an AvesTerra session
    """
    with handle_API_exceptions('while attempting to finalize AvesTerra'):
        atapi.finalize()

def local_server():
    """
    local_server()
    Return the local server.

    Return the entity representing the local server, the server on which new
    entities are to be created.

    Returns
    -------
    Entity
        the entity of the local server

    See also
    --------
    :func:`initialize` : start an AvesTerra session

    :func:`entity_server` : return the server that manages an entity

    Examples
    -------
    >>> import avesterra.avial as av
    >>> auth = av.initialize() 

    Find the local server.

    >>> av.local_server()
    Entity(2906857743, 167772516, 0)

    Find the UUID of the local server

    >>> str(av.local_server())
    '<2906857743|167772516|0>'

    >>> av.finalize()
    """
    with handle_API_exceptions('while finding local server'):
        return atapi.local()

################################################################################
#
# Operator decoration
#

def manage_exceptions(description, check_for_naked_instance=False):
    """Decorator maker to wrap Avial operations, for handling exceptions."""
    # 1. By default handles all exceptions, explaining context
    # 2. Adds an optional paramter handle_exceptions, which can be set to False
    # 3. Optionally checks for instance specified without attribute
    # _raise_error_on_naked_instance only works when attribute and instnace
    # are both keywords, and keyword-only is enforced. 
    def decorator(fn):
        """Decorator for optionally handling exceptions."""
        def wrapped(*args, handle_exceptions=True, **kwargs):
            """Wrapping decorated function."""
            if check_for_naked_instance:
                while_msg = create_while_msg(description, args, kwargs)
                _raise_error_on_naked_instance(kwargs, while_msg)
                if handle_exceptions:
                    with handle_API_exceptions(while_msg):
                        return fn(*args, **kwargs)
                else:
                    return fn(*args, **kwargs)
            else:
                if handle_exceptions:
                    while_msg = create_while_msg(description, args, kwargs)
                    with handle_API_exceptions(while_msg):
                        return fn(*args, **kwargs)
                else:
                    return fn(*args, **kwargs)
        wrapped.__doc__ = fn.__doc__
        return wrapped
    return decorator

def create_while_msg(description, args, kwargs):
    """Return message describing while doing."""
    return description.format(*args) + _descr_non_nones(kwargs)

def _descr_non_nones(kwargs):
    """Generate description of all non-None parameters in kwargs."""
    descr =' with ' + ', '.join(f'{k}={v!r}' for k, v in kwargs.items() if v)
    if descr == ' with ':
        return ''
    else:
        return descr

@contextlib.contextmanager
def handle_API_exceptions(while_msg):
    """Context manager to raise appropriate error on exceptions."""
    try:
        yield 
    except AvialNotFound:
        raise
    except at.TimeoutError as err:
        raise AvialTimeout(f'Timeout: {err.message} {_truncate(while_msg)}')
    except at.AvesTerraError as err:
        raise AvialError(f'Error: {err.message} {_truncate(while_msg)}')
    except Exception as err:
        raise AvialError(f'Error: {err} {_truncate(while_msg)}')

def _truncate(string):
    """Truncate long string at 200 characters."""
    return (string[:197] + '...') if len(string) > 200 else string

def _raise_error_on_naked_instance(kwargs, while_msg):
    """Raise error on attempt to find invalid instance of entity properties."""
    def truthy_kwarg(key):
        """Is key in kwargs and has a truthy value?"""
        return key in kwargs and kwargs[key]

    if truthy_kwarg('instance') and not truthy_kwarg('attribute'):
        raise AvialError(
            f'Must specify attribute when instance is provided, {while_msg}')


################################################################################
#
# Entity operations
#

@manage_exceptions('while creating entity {0} of class {1}, subclass {2}')
def create_entity(name, klass, subklass, auth, *, outlet=None, autosave=True):
    """
    create_entity(name, klass, subklass, auth, *, outlet=None, autosave=True)
    Create and return a new entity.

    Create an entity and connect it to an outlet. Indicate whether changes
    to the entity should be saved automatically.

    Parameters
    ----------
    name : str 
        the name of the entity to be created, as a string. Subsequent calls to 
        :func:`entity_name` will return this string.

    klass : Class
        the AvesTerra class (not Python class) of the entity to be created.
        Subsequent calls to :func:`entity_class` will return this class.

    subklass : Subclass
        the AvesTerra subclass of the entity to be created. Subsequent calls
        to :func:`entity_subclass` will return this subclass.

    auth : Authorization
        an object that authorizes the creation of the entity.

    outlet : Entity, optional
        the outlet that is responsible for maintaining this entity. The outlet 
        is often the object outlet, provided by a call to 
        :func:`object_outlet`. If not provided, no outlet is connected to
        the entity. See :func:`connect_method` for more on connections.

    autosave : bool, optional
        should every change to the class be automatically saved by the outlet?
        Or should changes only be saved on an explicit call to 
        :func:`save_entity`?

    Returns
    -------
    at.Entity
        The newly created AvesTerra entity.

    Raises
    ------
    AvialError
        If ``name`` is not a string, ``klass`` is not an AvesTerra class, 
        ``subklass`` is not an AvesTerra class, ``outlet`` is not an outlet,
        ``auth`` does not authorize the creation.

    See also
    --------
    :func:`delete_entity` : delete an entity

    :func:`entity_name` : return the name of an entity

    :func:`entity_class` : return the AvesTerra class of an entity

    :func:`entity_subclass` : return the AvesTerra subclass of an entity

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = initialize()

    Create a new entity, with class ORGANIZATION and subclass GROUP. Connect
    it to the object outlet. Set autosave, so all changes to the entity are
    automatically persisted. 

    >>> ths = av.create_entity(
    ...     "The Hold Steady", av.Class.ORGANIZATION, av.Subclass.GROUP, auth, 
    ...     outlet=av.object_outlet(), autosave=True)

    What is the name of the newly created entity?

    >>> av.entity_name(ths)
    'The Hold Steady'

    What is the class?

    >>> av.entity_class(ths)
    <Class.ORGANIZATION: 5>

    What is the subclass?

    >>> av.entity_subclass(ths)
    <Subclass.GROUP: 76>

    Clean up the example.

    >>> av.delete_entity(ths, auth)
    >>> av.finalize()
    """ 
    ent = atapi.create(
        name=TranslateFromAvialToAPI.name(name), 
        authorization=auth, 
        klass=klass, 
        subklass=subklass)

    if outlet is not None:
        connect_method(ent, outlet, auth, handle_exceptions=False)
        invoke(
            ent, Method.CREATE, authorization=auth, name=name,
            parameter=1 if autosave else 0)
    return ent 

@manage_exceptions('while deleting entity {0}')
def delete_entity(entity, auth, *, ignore_references=False): 
    """
    delete_entity(entity, auth, *, ignore_references=False)
    Delete the entity. If there are references to the entity (if the reference
    count is greater than zero), the entity can only be deleted by specifying 
    a ``True`` value for ``ignore_references``.

    Parameters
    ----------
    entity : Entity
        the entity to be deleted.

    auth : Authorization
        an object that authorizes the deletion of the entity.

    ignore_references : bool, optional
        if the entity has a reference count greater than zero, should it be
        deleted anyway? The default is ``False``: raise an exception 
        on an attempt to delete an entity with a reference
        count greater than zero.

    Returns
    -------
    None

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or ``entity`` has a non-zero 
        reference count and ``ignore_references`` is ``False``, or ``auth`` does
        not authorize the deletion.

    See also
    --------
    :func:`create_entity` : create an entity

    :func:`entity_extinct` : has entity been deleted already?

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize() 

    Create an entity.

    >>> ths = av.create_entity(
    ...     "The Hold Steady", av.Class.ORGANIZATION, av.Subclass.GROUP, auth)

    Note that this entity has not yet been deleted.

    >>> av.entity_extinct(ths)
    False

    Delete the newly created entity. 

    >>> av.delete_entity(ths, auth)

    Verify that the entity is deleted.

    >>> av.entity_extinct(ths)
    True

    Create another entity.

    >>> gb = av.create_entity(
    ...     "Gogol Bordello", av.Class.ORGANIZATION, av.Subclass.GROUP, auth)

    Increment the reference count of the entity.

    >>> av.reference_entity(gb, auth)
    >>> av.entity_references(gb)
    1

    Attempt to delete the entity.

    >>> av.delete_entity(gb, auth) 
    AvialError: Attempt to delete entity with non-zero reference count 

    Delete the entity, ignoring the reference count.

    >>> av.delete_entity(gb, auth, ignore_references=True)

    Verify that the entity is deleted.

    >>> av.entity_extinct(gb)
    True

    Clean up.

    >>> av.finalize()
    """ 
    # differs from reference implementation in trying to invoke delete
    # method instead of testing for connection
    if (ignore_references or 
        entity_references(entity, handle_exceptions=False) == 0):
        with suppress_console_error_logging('Server reported ENTITY error'):
            with suppress_console_error_logging('Server reported OUTLET error'):
                try:
                    invoke(entity, Method.DELETE, authorization=auth)
                except (at.EntityError, at.TimeoutError, at.OutletError,
                        at.ApplicationError):
                    pass

                atapi.delete(entity, authorization=auth)
    else:
        raise AvialError(
            'Attempt to delete entity with non-zero reference count')

@manage_exceptions('while saving entity {0}')
def save_entity(entity, auth):
    """
    save_entity(entity, auth)
    Persist any non-persisted changes.

    Persist any non-persisted changes.
    Has no effect if the entity is connected to an adapter with autosave.  

    Parameters
    ----------
    entity : Entity
        the entity to be saved.

    auth : Authorization
        an object that authorizes the saving of the entity.

    Returns
    -------
    None

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or if ``auth`` does not authorize the saving.

    See also
    --------
    :func:`restore_entity` : restore entity to its persisted state

    :func:`create_entity` : create an entity

    :func:`get_value` : return the value of an attribute of an entity

    :func:`set_value` : change the value of an attribute of an entity

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize() 

    Create an entity with autosave False.

    >>> ths = av.create_entity(
    ...     "The Hold Steady", av.Class.ORGANIZATION, av.Subclass.GROUP, auth, 
    ...     outlet=av.object_outlet(), autosave=False)

    Set the age 16.

    >>> av.set_value(ths, 16, auth, attribute=av.Attribute.AGE)

    Check that age is in fact set.

    >>> av.get_value(ths, attribute=av.Attribute.AGE)
    16

    Persist the change.

    >>> av.save_entity(ths, auth)

    Change the age to 17.

    >>> av.set_value(ths, 17, auth, attribute=av.Attribute.AGE)

    The age is in fact 17.

    >>> av.get_value(ths, attribute=av.Attribute.AGE)
    17

    Restore the persisted state.

    >>> av.restore_entity(ths, auth)

    The age is 16, the last persisted age.

    >>> av.get_value(ths, attribute=av.Attribute.AGE)
    16

    Clean up.

    >>> av.delete_entity(ths, auth)
    >>> av.finalize()
    """ 
    invoke(entity, Method.SAVE, authorization=auth)

@manage_exceptions('while restoring entity {0}')
def restore_entity(entity, auth):
    """
    restore_entity(entity, auth)
    Revert the entity to the persisted state.

    Revert the entity to the persisted state, discarding any changes that have
    not been saved. Has no effect if the entity is connected to an adapter with
    autosave. 

    Parameters
    ----------
    entity : Entity
        the entity to be restored.

    auth : Authorization
        an object that authorizes the restoration of the entity.

    Returns
    -------
    None

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or if ``auth`` does not authorize the restore.

    See also
    ---------
    :func:`save_entity` : save any non-persisted changes of the entity

    :func:`create_entity` : create an entity

    :func:`get_value` : return the value of an attribute of an entity

    :func:`set_value` : change the value of an attribute of an entity

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize() 

    Create an entity with autosave False.

    >>> ths = av.create_entity(
    ...     "The Hold Steady", av.Class.ORGANIZATION, av.Subclass.GROUP, auth, 
    ...     outlet=av.object_outlet(), autosave=False)

    Set the age 16.

    >>> av.set_value(ths, 16, auth, attribute=av.Attribute.AGE)

    Check that age is in fact set.

    >>> av.get_value(ths, attribute=av.Attribute.AGE)
    16

    Persist the change.

    >>> av.save_entity(ths, auth)

    Change the age to 17.

    >>> av.set_value(ths, 17, auth, attribute=av.Attribute.AGE)

    The age is in fact 17.

    >>> av.get_value(ths, attribute=av.Attribute.AGE)
    17

    Restore the persisted state.

    >>> av.restore_entity(ths, auth)

    The age is 16, the last persisted age.

    >>> av.get_value(ths, attribute=av.Attribute.AGE)
    16

    Clean up.

    >>> av.delete_entity(ths, auth)
    >>> av.finalize()
    """ 
    invoke(entity, Method.LOAD, authorization=auth)

@manage_exceptions('while erasing entity {0}', check_for_naked_instance=True)
def erase_entity(entity, auth, *, attribute=None, instance=None):
    """
    erase_entity(entity, auth, *, attribute=None, instance=None)
    Erase the entity.

    Erase the entity, removing all attributes, properties, and values. After
    an erase, it is as if the entity had just been created.

    If ``attribute`` is specified, only a single attribute is erased, instead of 
    the whole entity. If both ``attribute`` and ``instance`` are specified, only
    a single attribute instance is erased. See examples below.

    If the entity is connected to an adapter with autosave, erasing the entity
    affects its persisted state. If connected to an adapter without autosave,
    only the transient state is affected, at least until :func:`save_entity`
    is called.

    Parameters
    ----------
    entity : Entity
        the entity to be erased.

    auth : Authorization
        an object that authorizes the erasure of the entity.

    attribute : Attribute or None, optional
        if provided, erase only the one attribute on the entity, leaving the 
        other attributes, the properties, and the entity values unchanged. The 
        default is None: erase everything.

    instance : int, optional
        if provided and ``attribute`` is also provided, erase only a single
        instance attribute. For example, if ``attribute`` is ``Attribute.CHILD``
        and ``instance`` is 3, the third child instance is erased. The default
        is None: erase all the instances.

    Returns
    -------
    None

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or ``auth`` is not a valid 
        authorization, or ``attribute`` is not an attribute, or an instance 
        is specified but no attribute    

    See also
    --------
    :func:`create_entity` : create an entity

    :func:`get_value` : return the value of an attribute of an entity

    :func:`set_value` : change the value of an attribute of an entity

    :func:`insert_property` : put a new name/key/value property on an entity

    :func:`retrieve_entity` : return all attributes, properties, and values of an entity, in :ref:`comprehensive format <comprehensive_format>`

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize(auth_code=20165) 
    >>> import pprint
    >>> pp = pprint.PrettyPrinter(indent=4, compact=True)

    Create an entity for the band The Hold Steady.

    >>> ths = av.create_entity(
    ...     "The Hold Steady", av.Class.ORGANIZATION, av.Subclass.GROUP, auth, 
    ...     outlet=av.object_outlet(), autosave=True)

    Set the age of the band.

    >>> av.set_value(ths, 16, auth, attribute=av.Attribute.AGE)

    Set one of the members of the band: Craig Finn. Craig sings and plays
    rhythm guitar. (In practice all the people should be entities 
    themselves. This is just an example illustrating :func:`erase_entity`, so
    we can keep it simple.)

    >>> av.set_value(ths, 'Craig Finn', auth, attribute=av.Attribute.MEMBER)
    >>> av.insert_property(
    ...     ths, auth, attribute=av.Attribute.MEMBER, instance=1, 
    ...     name='plays', value='lead vocals')
    >>> av.insert_property(
    ...     ths, auth, attribute=av.Attribute.MEMBER, instance=1, 
    ...     name='plays', value='rhythm guitar')

    So where are we?

    >>> pp.pprint(av.retrieve_entity(ths))
    {'Attributes': {
        'AGE_ATTRIBUTE': [{'Values': [{'INTEGER': '16'}]}],
        'MEMBER_ATTRIBUTE': [
            {
                'Properties': [
                    ['plays', '', {'UTF-8': 'lead vocals'}], 
                    ['plays', '', {'UTF-8': 'rhythm guitar'}]
                    ],
                'Values': [{'UTF-8': 'Craig Finn'}]
            } ]
        },
    'Label': 'The Hold Steady'}

    What happens if we erase the entity?

    >>> av.erase_entity(ths, auth)
    >>> av.retrieve_entity(ths)
    {'Label': 'The Hold Steady'}

    Let's return to where we were. 

    >>> av.set_value(ths, 16, auth, attribute=av.Attribute.AGE)
    >>> av.set_value(ths, 'Craig Finn', auth, attribute=av.Attribute.MEMBER)
    >>> av.insert_property(
    ...     ths, auth, attribute=av.Attribute.MEMBER, instance=1, 
    ...     name='plays', value='lead vocals')
    >>> av.insert_property(
    ...     ths, auth, attribute=av.Attribute.MEMBER, instance=1, 
    ...     name='plays', value='rhythm guitar')

    Add another member of the band: Tad Kubler. Tad plays lead guitar and 
    sings backing vocals.

    >>> av.set_value(
    ...     ths, 'Tad Kubler', auth, attribute=av.Attribute.MEMBER, instance=2)
    >>> av.insert_property(
    ...     ths, auth, attribute=av.Attribute.MEMBER, instance=2, 
    ...     name='plays', value='lead guitar')
    >>> av.insert_property(
    ...     ths, auth, attribute=av.Attribute.MEMBER, instance=1, 
    ...     name='plays', value='backing vocals')
    >>> pp.pprint(av.retrieve_entity(ths))
    {'Attributes': {
        'AGE_ATTRIBUTE': [{'Values': [{'INTEGER': '16'}]}],
        'MEMBER_ATTRIBUTE': [
            {
                'Properties': [
                    ['plays', '', {'UTF-8': 'lead vocals'}],
                    ['plays', '', {'UTF-8': 'rhythm guitar'}],
                    ['plays', '', {'UTF-8': 'backing vocals'}]
                    ],
                'Values': [{'UTF-8': 'Craig Finn'}]
            }, 
            {
                'Properties': [['plays', '', {'UTF-8': 'lead guitar'}]], 
                'Values': [{'UTF-8': 'Tad Kubler'}]
            }]},
        'Label': 'The Hold Steady'}

    That's not right. Tad sings backing vocals, not Craig. Let's erase the
    MEMBER attribute.

    >>> av.erase_entity(ths, auth, attribute=av.Attribute.MEMBER)
    >>> pp.pprint(av.retrieve_entity(ths))
    {'Attributes': {
        'AGE_ATTRIBUTE': [{'Values': [{'INTEGER': '16'}]}]},
        'Label': 'The Hold Steady'}

    Adding property values one at a time is prone to errors. Let's write a 
    little function that does this, that sets the value 
    of the MEMBER attribute to the name of the band member, and then sets
    what he plays from a list, one property value at a time

    >>> def add_member(name, plays_list, instance):
    ...     av.set_value(
    ...         ths, name, auth, attribute=av.Attribute.MEMBER, 
    ...         instance=instance)
    ...     for plays in plays_list:
    ...         av.insert_property(
    ...             ths, auth, attribute=av.Attribute.MEMBER, instance=instance, 
    ...             name='plays', value=plays)
    ... 

    Now we can add all five band members.

    >>> add_member('Craig Finn', ['lead vocals', 'rhythm guitar'], 1)
    >>> add_member('Tad Kubler', ['lead guitar', 'backing vocals'], 2)
    >>> add_member('Galen Polivka', ['bass guitar'], 3)
    >>> add_member(
    ...     'Franz Nicolay', 
    ...     ['piano', 'keyboards', 'accordion', 'harmonica', 'backing vocals'], 
    ...     4)
    >>> add_member('Bobby Drake', ['drums'], 5)
    >>> pp.pprint(av.retrieve_entity(ths))
    {'Attributes': {
        'AGE_ATTRIBUTE': [{'Values': [{'INTEGER': '16'}]}],
        'MEMBER_ATTRIBUTE': [
            {
                'Properties': [
                    ['plays', '', {'UTF-8': 'lead vocals'}], ['plays', '', {'UTF-8': 'rhythm guitar'}]
                    ],
                'Values': [{'UTF-8': 'Craig Finn'}]
            },
            {
                'Properties': [
                    ['plays', '', {'UTF-8': 'lead guitar'}], 
                    ['plays', '', {'UTF-8': 'backing vocals'}]
                    ], 
                'Values': [{'UTF-8': 'Tad Kubler'}]
            },
            {
                'Properties': [['plays', '', {'UTF-8': 'bass guitar'}]], 
                'Values': [{'UTF-8': 'Galen Polivka'}]
            },
            {
                'Properties': [
                    ['plays', '', {'UTF-8': 'piano'}], 
                    ['plays', '', {'UTF-8': 'keyboards'}], 
                    ['plays', '', {'UTF-8': 'accordion'}], 
                    ['plays', '', {'UTF-8': 'harmonica'}], 
                    ['plays', '', {'UTF-8': 'backing vocals'}]
                    ], 
                'Values': [{'UTF-8': 'Franz Nicolay'}]
            },
            {
                'Properties': [['plays', '', {'UTF-8': 'drums'}]], 
                'Values': [{'UTF-8': 'Bobby Drake'}]
            }]},
    'Label': 'The Hold Steady'}


    Hmm. Franz left the band in 2010.  We erase just him.

    >>> av.erase_entity(ths, auth, attribute=av.Attribute.MEMBER, instance=4)
    >>> pp.pprint(av.retrieve_entity(ths))
    {'Attributes': {
        'AGE_ATTRIBUTE': [{'Values': [{'INTEGER': '16'}]}],
        'MEMBER_ATTRIBUTE': [
            {
                'Properties': [
                    ['plays', '', {'UTF-8': 'lead vocals'}], ['plays', '', {'UTF-8': 'rhythm guitar'}]
                    ],
                'Values': [{'UTF-8': 'Craig Finn'}]
            },
            {
                'Properties': [
                    ['plays', '', {'UTF-8': 'lead guitar'}], 
                    ['plays', '', {'UTF-8': 'backing vocals'}]
                    ], 
                'Values': [{'UTF-8': 'Tad Kubler'}]
            },
            {
                'Properties': [['plays', '', {'UTF-8': 'bass guitar'}]], 
                'Values': [{'UTF-8': 'Galen Polivka'}]
            },
            {
                'Properties': [['plays', '', {'UTF-8': 'drums'}]], 
                'Values': [{'UTF-8': 'Bobby Drake'}]
            }]},
    'Label': 'The Hold Steady'}

    Later in 2010, Steve Selvidge was added, another guitar player.

    >>> add_member('Steve Selvidge', ['guitar', 'backing vocals'], 5)
    >>> pp.pprint(av.retrieve_entity(ths))
    {'Attributes': {
        'AGE_ATTRIBUTE': [{'Values': [{'INTEGER': '16'}]}],
        'MEMBER_ATTRIBUTE': [
            {
                'Properties': [
                    ['plays', '', {'UTF-8': 'lead vocals'}], ['plays', '', {'UTF-8': 'rhythm guitar'}]
                    ],
                'Values': [{'UTF-8': 'Craig Finn'}]
            },
            {
                'Properties': [
                    ['plays', '', {'UTF-8': 'lead guitar'}], 
                    ['plays', '', {'UTF-8': 'backing vocals'}]
                    ], 
                'Values': [{'UTF-8': 'Tad Kubler'}]
            },
            {
                'Properties': [['plays', '', {'UTF-8': 'bass guitar'}]], 
                'Values': [{'UTF-8': 'Galen Polivka'}]
            },
            {
                'Properties': [['plays', '', {'UTF-8': 'drums'}]], 
                'Values': [{'UTF-8': 'Bobby Drake'}]
            },
            {
                'Properties': [
                    ['plays', '', {'UTF-8': 'guitar'}], 
                    ['plays', '', {'UTF-8': 'backing vocals'}]
                    ], 
                'Values': [{'UTF-8': 'Steve Selvidge'}]
            }]}, 
    'Label': 'The Hold Steady'} 

    Then in 2016, Franz returns. The Hold Steady is now a six piece band.

    >>> add_member(
    ...     'Franz Nicolay', 
    ...     ['piano', 'keyboards', 'accordion', 'harmonica', 'backing vocals'], 
    ...     6)
    >>> pp.pprint(av.retrieve_entity(ths))
    {'Attributes': {
        'AGE_ATTRIBUTE': [{'Values': [{'INTEGER': '16'}]}],
        'MEMBER_ATTRIBUTE': [
            {
                'Properties': [
                    ['plays', '', {'UTF-8': 'lead vocals'}], ['plays', '', {'UTF-8': 'rhythm guitar'}]
                    ],
                'Values': [{'UTF-8': 'Craig Finn'}]
            },
            {
                'Properties': [
                    ['plays', '', {'UTF-8': 'lead guitar'}], 
                    ['plays', '', {'UTF-8': 'backing vocals'}]
                    ], 
                'Values': [{'UTF-8': 'Tad Kubler'}]
            },
            {
                'Properties': [['plays', '', {'UTF-8': 'bass guitar'}]], 
                'Values': [{'UTF-8': 'Galen Polivka'}]
            },
            {
                'Properties': [['plays', '', {'UTF-8': 'drums'}]], 
                'Values': [{'UTF-8': 'Bobby Drake'}]
            },
            {
                'Properties': [
                    ['plays', '', {'UTF-8': 'guitar'}], 
                    ['plays', '', {'UTF-8': 'backing vocals'}]
                    ], 
                'Values': [{'UTF-8': 'Steve Selvidge'}]
            },    
            {
                'Properties': [
                    ['plays', '', {'UTF-8': 'piano'}], 
                    ['plays', '', {'UTF-8': 'keyboards'}], 
                    ['plays', '', {'UTF-8': 'accordion'}], 
                    ['plays', '', {'UTF-8': 'harmonica'}], 
                    ['plays', '', {'UTF-8': 'backing vocals'}]
                    ], 
                'Values': [{'UTF-8': 'Franz Nicolay'}]
            }]}, 
    'Label': 'The Hold Steady'} 

    Clean up.

    >>> av.delete_entity(ths, auth)
    >>> av.finalize()
    """ 
    invoke(
        entity, Method.ERASE, attribute=attribute, instance=instance,
        authorization=auth )

@manage_exceptions('while redirecting {0} to {1}')
def redirect_entity(simple_UUID, complex_UUID, auth):  
    """
    redirect_entity(simple_UUID, complex_UUID, auth)
    Make one UUID an abbreviation for another.

    When an entity is created by a server, it is assigned a UUID. This 
    newly-assigned UUID is not easy to remember, e.g. 
    <2906857743|167772516|108621>. Sometimes it is useful to have a UUID that 
    is easy to remember, e.g. <0|0|9999>. The operation :func:`redirect_entity`
    makes a simple UUID (e.g. <0|0|9999>) a nickname for the difficult one
    (e.g. <2906857743|167772516|108621>). This redirection allows other 
    operations to reference the entity with the simple UUID instead of the 
    complex UUID.

    Parameters
    ----------
    simple_UUID : str
        the UUID that is intended as a nickname. Must have the UUID format:
        <public_host|local_host|unique_ID>, where public_host, local_host,
        and unique_ID are all non-negative integers. public_host and 
        local_host must be less than 4,294,967,296 and unique_ID must be
        less than 18,446,744,073,709,551,616

    complex_UUID : str
        the UUID that the nickname refers to. Must be the UUID of an existing
        entity. Must have the UUID format:
        <public_host|local_host|unique_ID>, where public_host, local_host,
        and unique_ID are all non-negative integers. public_host and 
        local_host must be less than 4,294,967,296 and unique_ID must be
        less than 18,446,744,073,709,551,616. 

    auth : Authorization
        an object that authorizes the redirection

    Returns
    -------
    None

    Raises
    ------
    AvialError
        if ``simple_UUID`` is not a valid UUID, or ``complex_UUID`` is not
        a valid UUID, or ``complex_UUID`` is not the UUID of an existing entity,
        or ``simple_UUID`` and ``complex_UUID`` are the same,  or ``auth`` does
        not authorize the redirection.

    See also
    --------
    :func:`create_entity` : create an entity

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize() 

    Create a new person entity.

    >>> av.create_entity(
    ...     'Jack Nicholson', av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    Entity(2906857743, 167772516, 108627)

    Jack has the UUID <2906857743|167772516|108627>. Set his age.

    >>> av.set_value(
    ...     av.entity_of('<2906857743|167772516|108627>'), 82, auth, 
    ...     attribute=av.Attribute.AGE)

    Check that his age has been set correctly.

    >>> av.get_value(
    ...     av.entity_of('<2906857743|167772516|108627>'), 
    ...     attribute=av.Attribute.AGE)
    82

    <2906857743|167772516|108627> is awkward. Let's use <0|0|555> instead.

    >>> av.redirect_entity('<0|0|555>', '<2906857743|167772516|108627>', auth)

    Check Jack's age using the UUID nickname.

    >>> av.get_value(av.entity_of('<0|0|555>'), attribute=av.Attribute.AGE)
    82

    Clean up. 

    >>> av.delete_entity(av.entity_of('<0|0|555>'), auth)
    >>> av.finalize()  
    """
    invoke(
        None, Method.AVESTERRA, name='REDIRECT', key=simple_UUID, 
        value=complex_UUID, authorization=auth)

@manage_exceptions('while referencing {0}')
def reference_entity(entity, auth):  
    """
    reference_entity(entity, auth)
    Increment the reference count of the entity.

    Every entity maintains a 
    `reference count <https://en.wikipedia.org/wiki/Reference_counting>`_, 
    a count of references to the entity from other entities. When the reference
    count reaches zero, the entity is subject to automatic deletion, e.g. if
    it is placed in the trash registry. As long as the reference count is 
    greater than zero, :func:`delete_entity` will raise an exception.

    This function increments the reference count, adding one to its prior value.

    Parameters
    ----------
    entity : Entity
        the entity whose reference count is to be incremented

    auth : Authorization
        an object that authorizes the increment

    Returns
    -------
    None

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or ``auth`` does not authorize the
        reference count increment.

    See also
    --------
    :func:`dereference_entity` : decrement the reference count of an entity

    :func:`entity_references` : return the current reference count of the entity

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize() 

    Create an entity.

    >>> jack = av.create_entity(
    ...     'Jack Nicholson', av.Class.PERSON, av.Subclass.PERSON, auth)

    There are no references to the newly created entity, from other entities.

    >>> av.entity_references(jack)
    0

    Increment the reference count.

    >>> av.reference_entity(jack, auth)

    The reference count is now 1.

    >>> av.entity_references(jack)
    1

    Attempt to delete the entity.

    >>> av.delete_entity(jack, auth)
    AvialError: Attempt to delete entity with non-zero reference count 

    Increment the reference count again.

    >>> av.reference_entity(jack, auth)
    >>> av.entity_references(jack)
    2

    Decrement the reference count.

    >>> av.dereference_entity(jack, auth)
    >>> av.entity_references(jack)
    1

    Decrement the reference count again.

    >>> av.dereference_entity(jack, auth)
    >>> av.entity_references(jack)
    0

    Now the entity can be deleted.

    >>> av.delete_entity(jack, auth)

    Clean up.

    >>> av.finalize()
    """
    atapi.reference(entity, auth)

@manage_exceptions('while dereferencing {0}')
def dereference_entity(entity, auth): 
    """
    dereference_entity(entity, auth)
    Decrement the reference count of the entity.

    Every entity maintains a 
    `reference count <https://en.wikipedia.org/wiki/Reference_counting>`_, 
    a count of references to the entity from other entities. When the reference
    count reaches zero, the entity is subject to automatic deletion, e.g. if
    it is placed in the trash registry. As long as the reference count is 
    greater than zero, :func:`delete_entity` will raise an exception.

    This function decrements the reference count, subtracting one from its prior
    value. If the prior value was zero, dereferencing has no effect: the 
    reference count stays zero.

    Parameters
    ----------
    entity : Entity
        the entity whose reference count is to be decremented

    auth : Authorization
        an object that authorizes the decrement

    Returns
    -------
    None

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or ``auth`` does not authorize the
        reference count decrement.

    See also
    --------
    :func:`reference_entity` : increment the reference count of an entity

    :func:`entity_references` : return the current reference count of the entity

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize() 

    Create an entity. The newly created entity has a reference count of zero.

    >>> jack = av.create_entity(
    ...     'Jack Nicholson', av.Class.PERSON, av.Subclass.PERSON, auth)
    >>> av.entity_references(jack)
    0

    Increment the entity's reference count.

    >>> av.reference_entity(jack, auth)
    >>> av.entity_references(jack)
    1

    Decrement the entity's reference count.

    >>> av.dereference_entity(jack, auth)
    >>> av.entity_references(jack)
    0

    Decrement the reference count again. Note that the reference count remains
    zero.

    >>> av.dereference_entity(jack, auth)
    >>> av.entity_references(jack)
    0

    Clean up.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """
    atapi.dereference(entity, auth)

@manage_exceptions('while invoking method {1} on entity {0}')
def invoke_entity(entity, method, *, attribute=None, instance=None, name=None, 
                  key=None, value=None, options=None, parameter=None, 
                  index=None, count=None, mode=None, precedence=None, 
                  timeout=None, auxiliary=None, authorization=None):
    """
    invoke_entity(entity, method, *, attribute=None, instance=None, name=None, key=None, value=None, options=None, parameter=None, index=None, count=None, mode=None, precedence=None, timeout=None, auxiliary=None, authorization=None)
    Invoke a method on the entity.

    Invoke a method on the entity, and 
    return the result, if any. The semantics of the arguments depend on the
    method invoked. See examples below.

    Parameters
    ----------
    entity : Entity
        the entity on which ``method`` is invoked.

    method : Method
        the method to be invoked on ``entity``. The method is an instance
        of the enum :class:`Method`, e.g. ``Method.CREATE`` or ``Method.SAVE``. 

    attribute : Attribute or None, optional
        Which attribute is to be affected by the invocation? 
        Some invoked methods make use of an attribute. For example, an attribute
        can be provided with an invocation of ``Method.SET``, allowing a value 
        to be set for some
        attribute of an entity. When an attribute is supplied, it must be an 
        instance of the enum :class:`Attribute`.

    instance : int or None, optional
        Which instance of the attribute is to be affected by the invocation? 
        Some invoked methods make use of an instance. For example, an instance 
        can be provided with an invocation of ``Method.SET``, allowing a value
        to be set on some
        particular instance of an attribute, indexed by the instance number.

    name : str or None, optional
        Some invoked methods make use of a name. For example, a name can be 
        provided with an invocation of ``Method.INSERT``, allowing the newly
        inserted property to be  named.

    key : str or None, optional
        Some invoked methods make use of a key. For example, a key can be 
        provided with an invocation of ``Method.INSERT``, allowing the newly
        inserted property to indexed by a unique key.

    value: int or float or bool or str or Entity or list or dict or Value or None, optional
        Some invoked methods make use of a value. For example, a value
        can be provided with an invocation of ``Method.INSERT``, allowing the 
        newly inserted property to include a value. If a list or dict is 
        supplied as a value, it must be a valid interchange object. For example,
        if the value is a list, the list cannot contain Python tuples or Python
        callables or other Python objects that are unknown to Avesterra.

    options : str or None, optional
        An invoked method could make use of an options string. The optinos 
        string is envisioned as a way to pass arbitrary options to an outlet,
        much like how options codes are passed with a Unix command. 

    parameter : int or None, optional
        Some invoked methods make use of a parameter. For example, after an
        entity is connected to an adapter, ``Method.CREATE`` is called to 
        create the entity within the adapter. That invocation can include a
        ``parameter`` of 1 if the adapter is to automatically save any changes
        to the entity.

    index : int or None, optional
        Some invoked methods make use of an index. For example, an index 
        can be provided with an invocation of ``Method.SET``, allowing a value
        to be set on some particular index of an attribute instance, indexed by 
        the index number.

    count : int or None, optional
        Some invoked methods make use of an index. For example, a count
        can be provided with an invocation of ``Method.RETRIEVE``, to
        specify the maximum number of properties that are to be retrieved, e.g.
        no more than 100 for this invocation.

    mode : Mode or None, optional
        A few invoked methods make use of a mode. For example, a mode can be 
        provided with an invocation of ``Method.STORE``, to specify how the
        new content is to be combined with any existing content. See 
        :func:`store_entity`---which uses the same ``mode`` parameter---for 
        more details.

    timeout : int or None, optional
        How long (in seconds) should the invocation of the method be allowed
        to run, before it is interrupted?  A few invoked methods make use of a 
        timeout duration. For example, a timeout can be provided with an 
        invocation of ``Method.SORT`` so sorts that take too long are 
        interrupted. 

    auxiliary : Entity or None, optional
        An invoked method can make use an auxiliary parameter. The auxiliary
        is an entity passed to the invoked method. An auxiliary is useful for
        an invoked method that may require many minutes to execute, or even 
        longer. Rather than waiting for the results, the invoker can provide an
        auxiliary entity as a destination of the results, and then proceed 
        asynchronously with other work, and pick up the results from the
        entity at some later date.

    authorization: Authorization or None, optional
        The invocation of some methods requires an authorization token. For 
        example, valid authorization must be provided with an invocation of
        ``Method.STORE``.

    Returns
    -------
    int or float or bool or str or Entity or list or dict
        The returned object entirely depends on the method. For 
        example, an invocation of ``Method.RETRIEVE`` will return a dict of
        the entity's attributes, properties, and values, in 
        :ref:`comprehensive format <comprehensive_format>`. An invocation of 
        ``Method.SET`` will return '', the empty string.

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or ``method`` is not a method.

    See also
    --------
    :func:`inquire_entity` : retrieve an attribute value from an entity

    :func:`create_entity` : create an entity

    :func:`store_entity` : set attributes, properties, and values of an entity

    :func:`retrieve_entity` : return all attributes, properties, and values of an entity, in :ref:`comprehensive format <comprehensive_format>`

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize() 
    >>> import pprint
    >>> pp = pprint.PrettyPrinter(indent=4, compact=True)

    Create an entity for the actor Jack Nicholson. (See :func:`create_entity`
    for details.)

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)

    Set the attributes and properties for Jack.

    >>> jacks_details = {
    ...     "Attributes":{
    ...         "SEX_ATTRIBUTE":[{"Values":["M"]}],
    ...         "AGE_ATTRIBUTE":[{"Values":[{'INTEGER': "80"}]}],
    ...         "HEIGHT_ATTRIBUTE":[{"Values":[{'INTEGER': "177"}]}],  
    ...         "CHILD_ATTRIBUTE":[
    ...             {
    ...                 "Values": [{'UTF-8': "Jennifer"}],
    ...                 "Properties": [ 
    ...                     ["Born","", {'INTEGER': '1963'}],
    ...                     ["Mother","", {'ASCII': 'Sandra Knight'}] 
    ...                 ]
    ...             },
    ...             {
    ...                 "Values": [{'UTF-8': "Caleb"}],
    ...                 "Properties": [ 
    ...                     ["Born","", {'INTEGER': "1970"}],
    ...                     [
    ...                         "Paternity", 
    ...                         "open question 2", 
    ...                         {'UTF-8': "not established"}],
    ...                     ["Mother","", {'UTF-8': "Susan Anspach"}],
    ...                 ]
    ...             },
    ...             {"Values": [{'UTF-8': "Honey"}]},
    ...             {"Values": [{'UTF-8': "Lorraine"}]},
    ...             {
    ...                 "Values": [{'UTF-8': "Raymond"}],
    ...                 "Properties": [ 
    ...                     ["Born","youngest", {'INTEGER': "1992"}],
    ...                     ["Mother","", {'UTF-8': "Rebecca Broussard"}] 
    ...                 ]
    ...             }]},
    ...     "Properties":[
    ...         ["known for","most popular role", {'UTF-8': "The Shining"}],
    ...         ["fan of","famous fan","Los Angeles Lakers"],
    ...         ["fan of", "", "Bob Dylan"],
    ...         ["also known for","best performance","Chinatown"]
    ...         ] 
    ... }
    >>> av.store_entity(jack, jacks_details, auth)

    Invoke the Jack entity with ``Method.SET`` to add another name to 
    the third child.

    >>> av.invoke_entity(
    ...     jack, av.Method.SET, attribute=av.Attribute.CHILD,
    ...     instance=3, index=2, value='Honey Hollman', authorization=auth)
    b''

    Look at the updated child attribute.

    >>> pp.pprint(av.retrieve_entity(jack)['Attributes']['CHILD_ATTRIBUTE'])
    [   {   'Properties': [   ['Born', '', {'INTEGER': '1963'}],
                              ['Mother', '', {'ASCII': 'Sandra Knight'}]],
            'Values': [{'UTF-8': 'Jennifer'}]},
        {   'Properties': [   ['Born', '', {'INTEGER': '1970'}],
                              [   'Paternity', 'open question 2',
                                  {'UTF-8': 'not established'}],
                              ['Mother', '', {'UTF-8': 'Susan Anspach'}]],
            'Values': [{'UTF-8': 'Caleb'}]},
        {'Values': [{'UTF-8': 'Honey'}, {'UTF-8': 'Honey Hollman'}]},
        {'Values': [{'UTF-8': 'Lorraine'}]},
        {   'Properties': [   ['Born', 'youngest', {'INTEGER': '1992'}],
                              ['Mother', '', {'UTF-8': 'Rebecca Broussard'}]],
            'Values': [{'UTF-8': 'Raymond'}]}]

    Invoke the Jack entity with ``Method.INSERT`` to add another property.

    >>> av.invoke_entity(
    ...     jack, av.Method.INSERT, name='fan of', 
    ...     key='boyhood team', value='New York Yankees', authorization=auth)
    b''

    Look at the updated properties.

    >>> pp.pprint(av.retrieve_entity(jack)['Properties'])
    [   ['known for', 'most popular role', {'UTF-8': 'The Shining'}],
        ['fan of', 'famous fan', 'Los Angeles Lakers'], ['fan of', '', 'Bob Dylan'],
        ['also known for', 'best performance', 'Chinatown'],
        ['fan of', 'boyhood team', {'UTF-8': 'New York Yankees'}]]

    Clean up. 

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """
    return invoke(
        entity, method, attribute=attribute, instance=instance, name=name, 
        key=key, value=value, options=options, parameter=parameter, index=index,
        count=count, mode=mode, precedence=precedence, timeout=timeout, 
        auxiliary=auxiliary, authorization=authorization, return_results=True)

def invoke(entity, method, attribute=None, instance=None, name=None, key=None, 
           value=None, options=None, parameter=None, index=None, count=None, 
           mode=None, precedence=None, timeout=None, auxiliary=None, 
           authorization=None, return_results=False, results_as_string=False):
    """Invoke a method on the entity, maybe interpreting the results."""

    results = atapi.invoke(
        entity=TranslateFromAvialToAPI.entity(entity),
        method=TranslateFromAvialToAPI.method(method),
        attribute=TranslateFromAvialToAPI.attribute(attribute),
        instance=TranslateFromAvialToAPI.instance(instance),
        name=TranslateFromAvialToAPI.name(name),
        key=TranslateFromAvialToAPI.key(key),
        value=TranslateFromAvialToAPI.value(value),
        options=TranslateFromAvialToAPI.options(options),
        parameter= TranslateFromAvialToAPI.parameter(parameter),
        index=TranslateFromAvialToAPI.index(index),
        count=TranslateFromAvialToAPI.count(count),
        mode=TranslateFromAvialToAPI.mode(mode), 
        precedence=TranslateFromAvialToAPI.precedence(precedence),
        timeout=TranslateFromAvialToAPI.timeout(timeout),
        auxiliary=TranslateFromAvialToAPI.entity(auxiliary),
        authorization=TranslateFromAvialToAPI.authorization(authorization)
     )
    if return_results:
        if results_as_string:
            return Value.from_object(results).string()
        else:
            return Value.from_object(results).instantiate()

@manage_exceptions('while inquring about entity {0}')
def inquire_entity(entity, *, attribute=None, instance=None, name=None, 
                   key=None, value=None, options=None, parameter=None, 
                   index=None, count=None, mode=None, timeout=None, 
                   auxiliary=None, authorization=None):
    """
    inquire_entity(entity, *, attribute=None, instance=None, name=None, key=None, value=None, options=None, parameter=None, index=None, count=None, mode=None, timeout=None, auxiliary=None, authorization=None)
    Inquire about an entity.

    Inquire about an entity, perhaps about one of its attributes, and
    return any result. The semantics of inquiry depend upon what outlet is 
    attached to the entity, and the adapter that is running on that outlet.
    :func:`inquire_entity` is much like :func:`invoke_entity`, except that no
    method is supplied to an inquiry, and except that an attached outlet 
    implements an inquiry while a connected outlet implements a invocation.

    Parameters
    ----------
    entity : Entity
        the entity that is the subject of the inquiry

    attribute : Attribute or None, optional
        Which attribute is the subject of the inquiry? 

    instance : int or None, optional
        Which instance is the subject of the inquiry? Typically the instance
        is interpreted as identifying the instance of the specified attribute. 

    name : str or None, optional
        What name is the subject of the inquiry? Typically ``name`` refers to
        the name of a property, perhaps a property of ``entity``.

    key : str or None, optional
        What key is the subject of the inquiry? Typically ``name`` identifies
        a property by its unique key, perhaps a property of ``entity``.

    value: int or float or bool or str or Entity or list or dict or Value or None, optional
        An inquiry may make use of a value.  If a list or dict is 
        supplied as a value, it must be a valid interchange object. For example,
        if the value is a list, the list cannot contain Python tuples or Python
        callables or other Python objects that are unknown to Avesterra.

    options : str or None, optional
        A string specifying some options defined by the outlet.

    parameter : int or None, optional
        An inquiry may make use of an integer parameter.

    index : int or None, optional
        An inquiry may make use of an integer index.

    count : int or None, optional
        An inquiry may make use of an integer count.

    mode : Mode or None, optional
        An inquiry may make use of a node. 

    timeout : int or None, optional
        How long (in seconds) should the inquiry be allowed
        to run, before it is interrupted?  

    auxiliary : Entity or None, optional
        An inquiry may make use of another entity, e.g. as a place to put the
        results if they are too big to return.

    authorization: Authorization or None, optional
        An inquiry may require an authorization token.  

    Returns
    -------
    int or float or bool or str or Entity or list or dict
        The returned object entirely depends on the implementation of the
        inquiry. 

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or ``method`` is not a method.

    See also
    --------
    :func:`invoke_entity` : invoke a method on an entity

    :func:`create_entity` : create an entity

    :func:`attach_attribute` : attach an outlet to an entity, to handle attribute inquiries

    Examples
    --------
    An example for :func:`inquire_entity` requires code in two different 
    processes, one process for the calls to :func:`inquire_entity`, and
    the other process for the code to handle the inquiries. *Start by setting
    up process 1.*

    >>> import avesterra.avial as av  
    >>> auth = av.initialize() 

    Create an outlet. Note the UUID of the outlet, for use in the other 
    process.

    >>> inquiry_outlet = av.create_outlet(
    ...     'Inquiry outlet', av.Class.AVESTERRA, av.Subclass.OUTLET, 
    ...     auth, self_connect=True)
    >>> str(inquiry_outlet)
    '<2906857743|167772516|112554>'

    Define an adapter function. In response to no method, the function returns 
    an age, a gender, or a height, depending on what attribute it hears. For
    other attributes, it returns ``None``. In response to a ``STOP`` method, the 
    function changes a global flag, signaling a finish.

    >>> still_active = True
    >>> def purple_inquiry_responder(
    ...         outlet, entity, auxiliary, method, attribute, instance, 
    ...         name, key, value, options, parameter, index, count, mode,
    ...         authorization): 
    ...     global still_active
    ...     if outlet == entity:
    ...         # so the outlet will not run forever
    ...         if method == av.Method.STOP:
    ...             still_active = False 
    ...     elif method is None:
    ...         try:
    ...             return {
    ...                 av.Attribute.AGE: 57,
    ...                 av.Attribute.GENDER: 'male', 
    ...                 av.Attribute.HEIGHT: 157
    ...             }[attribute]
    ...         except KeyError:
    ...             return 
    ... 

    Listen to the outlet forever, or at least until the global flag is changed
    to false. Call the function every time something is heard on the outlet.

    >>> while still_active:
    ...     av.adapt_outlet(inquiry_outlet, purple_inquiry_responder, auth)

    *Now switch to process 2.*

    >>> import avesterra.avial as av  
    >>> auth = av.initialize() 

    Create an entity for the late, great musician 
    `Prince <https://en.wikipedia.org/wiki/Prince_(musician)>`_.

    >>> prince = av.create_entity(
    ...     'Prince', av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet())

    Attach the Prince entity to the outlet defined in the other process.
    The attachment is done across all
    attributes. For more on attachment, see :func:`attach_attribute`.

    >>> inquiry_outlet = av.entity_of('<2906857743|167772516|112554>')
    >>> av.attach_attribute(prince, inquiry_outlet, auth)

    Inquire about Prince's age. The result is provided by the function
    ``purple_inquiry_responder``, defined in the other process.

    >>> av.inquire_entity(prince, attribute=av.Attribute.AGE)
    57

    Inquire about Prince's gender and his height. 

    >>> av.inquire_entity(prince, attribute=av.Attribute.GENDER)
    'male'
    >>> av.inquire_entity(prince, attribute=av.Attribute.HEIGHT)
    157

    Inquire about Prince's location. Note that location is not one of the
    attributes defined in ``purple_inquiry_responder``. Instead None is
    returned.

    >>> av.inquire_entity(prince, attribute=av.Attribute.LOCATION)

    Invoke the method ``STOP`` on the inquiry outlet. Note that this method is
    handled by the same ``purple_inquiry_responder``, as the inquiry outlet is 
    connected to itself.

    >>> av.invoke_entity(inquiry_outlet, av.Method.STOP)

    Detach the outlet from the Prince entity.

    >>> av.detach_attribute(prince, auth)

    Clean up process 2.

    >>> av.delete_entity(prince, auth)
    >>> av.finalize()

    *Switch to process 1.* Note that the while loop has finished. Clean up.

    >>> av.delete_outlet(inquiry_outlet, auth)
    >>> av.finalize() 
    """ 
    results = atapi.inquire(
        entity, 
        attribute=TranslateFromAvialToAPI.attribute(attribute),
        instance= TranslateFromAvialToAPI.instance(instance),
        name=TranslateFromAvialToAPI.name(name),
        key=TranslateFromAvialToAPI.key(key),
        value=TranslateFromAvialToAPI.value(value),
        options=TranslateFromAvialToAPI.options(options),
        parameter= TranslateFromAvialToAPI.parameter(parameter),
        index=TranslateFromAvialToAPI.index(index),
        count=TranslateFromAvialToAPI.count(count),
        mode=TranslateFromAvialToAPI.mode(mode), 
        timeout=TranslateFromAvialToAPI.timeout(timeout),
        auxiliary=TranslateFromAvialToAPI.entity(auxiliary),
        authorization=TranslateFromAvialToAPI.authorization(authorization)
     )
    return Value.from_object(results).instantiate()

@manage_exceptions('while changing the class or subclass of {0}')
def change_entity(entity, auth, *, klass=None, subklass=None, name=None):
    """
    change_entity(entity, auth, *, klass=None, subklass=None, name=None)
    Change the name, class, or subclass of an existing entity.

    The name, class, and subclass of an entity are established when the entity
    is created (via :func:`create_entity`). But they can be changed later, 
    using this function.

    Parameters
    ----------
    entity : Entity
        the entity whose name, class, or subclass is to be changed

    auth : Authorization
        an object that authorizes the change

    name : str or None, optional
        the new name for the entity. Subsequent calls to 
        :func:`entity_name` will return this string. The default is None: do
        not change the name of the entity.

    klass : Class or None, optional
        the AvesTerra class (not Python class) that the entity will assume.
        Subsequent calls to :func:`entity_class` will return this class. The
        default is None: do not change the class of the entity.

    subklass : Subclass or None, optional
        the AvesTerra subclass that the entity will assume. Subsequent calls
        to :func:`entity_subclass` will return this subclass. The
        default is None: do not change the subclass of the entity.

    Returns
    -------
    None

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or ``entity`` is extinct, or ``name``
        is not a string, or ``klass`` is not an AvesTerra class, or ``subklass``
        is not an AvesTerra subclass, or ``auth`` does not authorize the change.

    See also
    --------
    :func:`create_entity` : create an entity

    :func:`entity_name` : return the name of an entity

    :func:`entity_class` : return the AvesTerra class of an entity

    :func:`entity_subclass` : return the AvesTerra subclass of an entity

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize() 

    Create a new entity, Publius.

    >>> publius = av.create_entity(
    ...     'Publius', av.Class.PERSON, av.Subclass.PERSON, auth)

    Publius is a person

    >>> av.entity_class(publius)
    <Class.PERSON: 2>

    Change Publius to an organization.

    >>> av.change_entity(publius, auth, klass=av.Class.ORGANIZATION)
    >>> av.entity_class(publius)
    <Class.ORGANIZATION: 5>

    The subclass of Publius is still ``PERSON``.
    
    >>> av.entity_subclass(publius)
    <Subclass.PERSON: 78>

    Change the subclass of Publius to ``GROUP``.

    >>> av.change_entity(publius, auth, subklass=av.Subclass.GROUP)
    >>> av.entity_subclass(publius)
    <Subclass.GROUP: 76>

    Change the name of Publius to "Madison, Hamilton, and Jay".

    >>> av.entity_name(publius)
    'Publius'
    >>> av.change_entity(publius, auth, name='Madison, Hamilton, and Jay')
    >>> av.entity_name(publius)
    'Madison, Hamilton, and Jay'

    Clean up.

    >>> av.delete_entity(publius, auth)
    >>> av.finalize()
    """
    api_entity = TranslateFromAvialToAPI.entity(entity)
    if klass:
        atapi.set_class(api_entity, klass, auth)
    if subklass:
        atapi.set_subclass(api_entity, subklass, auth)
    if name:
        atapi.set_name(
            api_entity, TranslateFromAvialToAPI.name(name), auth)


@manage_exceptions('while checking whether entity {0} is extinct')
def entity_extinct(entity): 
    """
    entity_extinct(entity)
    Has the entity been deleted?

    Extinct entities are those that were once created and available, but were
    then later deleted. Once deleted, an entity is extinct forever.

    Parameters
    ----------
    entity : Entity
        the entity to be tested for extinction

    Returns
    -------
    bool
        whether ``entity`` is extinct

    Raises
    ------
    AvialError
        if ``entity`` is not an entity

    See also
    --------
    :func:`entity_available` : is the entity alive?

    :func:`entity_ready` : is the entity ready to be invoked?

    :func:`create_entity` : create an entity

    :func:`delete_entity` : delete an entity

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize() 

    Create an entity.

    >>> jack = av.create_entity(
    ...     'Jack Nicholson', av.Class.PERSON, av.Subclass.PERSON, auth)

    Jack is not extinct.

    >>> av.entity_extinct(jack)
    False

    Delete the entity.

    >>> av.delete_entity(jack, auth)

    Jack is extinct now.

    >>> av.entity_extinct(jack)
    True

    Clean up.

    >>> av.finalize()
    """
    return atapi.extinct(entity)

@manage_exceptions('while determining if entity {0} is available')
def entity_available(entity):
    """
    entity_available(entity)
    Is entity available?

    An available entity is one that has been created and not yet deleted, and 
    that is reachable over the network. 

    Parameters
    ----------
    entity : Entity
        The entity to be tested for availability

    Returns
    -------
    bool
        Whether ``entity`` is currently available.

    Raises
    ------
    AvialError
        if ``entity`` is not an entity.

    See also
    --------
    :func:`entity_extinct` : has the entity been deleted?

    :func:`entity_ready` : is the entity ready to be invoked?

    :func:`create_entity` : create an entity

    :func:`delete_entity` : delete an entity

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize()

    Create an Entity object that is not actually an entity on any AvesTerra
    server.

    >>> not_jack = av.entity_of('<2906857743|167772516|7700000>')
    >>> type(not_jack)
    avesterra.base.Entity

    That entity is not available.

    >>> av.entity_available(not_jack)
    False

    Create an entity with :func:`create_entity`.

    >>> jack = av.create_entity(
    ...     'Jack Nicholson', av.Class.PERSON, av.Subclass.PERSON, auth)
    >>> type(jack)
    avesterra.base.Entity

    That entity is available, even though it is not connected to any adapter.

    >>> av.entity_available(jack)
    True

    Delete that entity. 

    >>> av.delete_entity(jack, auth)

    That entity is no longer available.

    >>> av.entity_available(jack)
    False

    End the session.

    >>> av.finalize()
    """ 
    return atapi.available(entity)

@manage_exceptions('while determining whether entity {0} is ready')
def entity_ready(entity):
    """
    entity_ready(entity)
    Is the entity ready to be invoked?

    An entity can be available and yet not able to respond to any invocations.
    This function tests whether it is able to so respond.

    Parameters
    ----------
    entity : Entity
        the entity to be tested for readiness

    Returns
    -------
    bool
        whether ``entity`` is ready to be invoked  

    Raises
    ------
    AvialError
        if ``entity`` is not an entity

    See also
    --------
    :func:`entity_extinct` : has entity been deleted already?

    :func:`entity_available` : is the entity alive? 

    :func:`create_entity` : create an entity 

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize() 

    Create an entity, without connecting it to an outlet.

    >>> jack = av.create_entity(
    ...     'Jack Nicholson', av.Class.PERSON, av.Subclass.PERSON, auth)

    Jack is not ready.

    >>> av.entity_available(jack)
    True
    >>> av.entity_ready(jack)
    False

    Connect Jack to an outlet.

    >>> av.connect_method(jack, av.object_outlet(), auth)

    Jack is now ready.

    >>> av.entity_available(jack)
    True
    >>> av.entity_ready(jack)
    True

    Clean up.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """
    if entity_available(entity):
        try:
            with suppress_console_error_logging():
                resp = invoke(
                    entity, Method.ECHO, value='Hello, World!', 
                    return_results=True)
        except Exception:
            return False
        return resp == 'Hello, World!'
    else:
        return False 

@manage_exceptions('while determining name of entity {0}')
def entity_name(entity):
    """
    entity_name(entity)
    Return the name of the entity, as a string.

    Parameters
    ----------
    entity : Entity
        the entity whose name is to be found.

    Returns
    -------
    str
        the name of ``entity``.

    Raises
    ------
    AvialError
        if ``entity`` is not an entity.

    See also
    --------
    :func:`entity_class` : the AvesTerra class of ``entity``

    :func:`entity_subclass` : the AvesTerra subclass of ``entity``

    :func:`create_entity` : create an entity

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize()

    Create an entity 

    >>> jack = av.create_entity(
    ...     'Jack Nicholson', av.Class.PERSON, av.Subclass.PERSON, auth)

    Find the name of the entity.

    >>> av.entity_name(jack)
    'Jack Nicholson'

    Clean up the example.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """ 
    return atapi.name(entity)

@manage_exceptions('while determining class of entity {0}')
def entity_class(entity):
    """
    entity_class(entity)
    Return the (AvesTerra) class of the entity.

    Return the AvesTerra class of the entity. The AvesTerra class is not a
    Python class. Instead it is an instance of :class:`Class`. 

    Parameters
    ----------
    entity : Entity
        the entity whose class is to be determined.

    Returns
    -------
    Class
        the class of ``entity``

    Raises
    ------
    AvialError
        if ``entity`` is not an entity.

    See also
    --------
    :func:`entity_subclass` : return the AvesTerra subclass of an entity

    :func:`entity_name` : return the name of an entity

    :func:`create_entity` : create an entity

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize()

    Create an entity.

    >>> brooklyn = av.create_entity(
    ...     'Brooklyn', av.Class.PLACE, av.Subclass.CITY, auth)

    Find the class of the entity.

    >>> av.entity_class(brooklyn)
    <Class.PLACE: 3>

    Clean up the example and end the session.

    >>> av.delete_entity(brooklyn, auth)
    >>> av.finalize()

    """ 
    return Class(atapi.klass(entity))

@manage_exceptions('while determining subclass of entity {0}')
def entity_subclass(entity):
    """
    entity_subclass(entity)
    Return the (AvesTerra) subclass of the entity.

    Return the AvesTerra subclass of the entity. The AvesTerra class is not a
    Python class. Instead it's an instance of :class:`Subclass`.

    Parameters
    ----------
    entity : Entity
        the entity whose subclass is to be determined.

    Returns
    -------
    Subclass
        the subclass of ``entity``

    Raises
    ------
    AvialError
        if ``entity`` is not an entity.

    See also
    --------
    :func:`entity_class` : return the AvesTerra class of an entity

    :func:`entity_name` : return the name of an entity

    :func:`create_entity` : create an entity

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize()

    Create an entity.

    >>> brooklyn = av.create_entity('Brooklyn', av.Class.PLACE, av.Subclass.CITY, auth)

    Find the subclass of the entity.

    >>> av.entity_subclass(brooklyn)
    <Subclass.CITY: 30>

    Clean up the example and end the session.

    >>> av.delete_entity(brooklyn, auth)
    >>> av.finalize()

    """ 
    return Subclass(atapi.subclass(entity))

@manage_exceptions('while determing server of entity {0}')
def entity_server(entity): 
    """
    entity_server(entity)
    Determine the server that manages the entity.

    Every entity is managed by a server. Return the server that manages a
    particular entity. Note that the server returned is itself an entity.

    Parameters
    ----------
    entity : Entity
        the entity whose server is to be found

    Returns
    -------
    Entity
        the server that manages the entity, as an entity

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, of if ``entity`` is extinct.

    See also
    --------
    :func:`create_entity` : create an entity

    :func:`local_server` : return the local server

    Examples
    --------
    >>> import avesterra.avial as av
    >>> auth = av.initialize()

    Create an entity.

    >>> craig = av.create_entity(
    ...     "Craig Finn", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)

    Find the server for this newly created entity.

    >>> str(av.entity_server(craig))
    '<2906857743|167772516|0>'

    Clean up.

    >>> av.delete_entity(craig, auth)
    >>> av.finalize()
    """
    return atapi.server(entity)

@manage_exceptions('while counting references to entity {0}')
def entity_references(entity): 
    """
    entity_references(entity)
    What is the reference count of the entity?

    Every entity maintains a 
    `reference count <https://en.wikipedia.org/wiki/Reference_counting>`_, 
    a count of references to the entity from other entities. When the reference
    count reaches zero, the entity is subject to automatic deletion, e.g. if
    it is placed in the trash registry. As long as the reference count is 
    greater than zero, an attempt to delete the entity will raise an exception.

    This function returns the current reference count of the entity

    Parameters
    ----------
    entity : Entity
        the entity whose reference count we wish to learn

    Returns
    -------
    int
        the reference count of the entity, i.e. how many times does the entity
        appear in the values, attributes, and properties of other
        entities?

    Raises
    ------
    AvialError
        if ``entity`` is not an entity.

    See also
    --------
    :func:`reference_entity` : increment the reference count of an entity

    :func:`dereference_entity` : decrement the reference count of an entity

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize() 

    Create an entity.

    >>> jack = av.create_entity(
    ...     'Jack Nicholson', av.Class.PERSON, av.Subclass.PERSON, auth)

    A newly created entity has a reference count of zero.

    >>> av.entity_references(jack)
    0

    Increment the reference count.

    >>> av.reference_entity(jack, auth)
    >>> av.entity_references(jack)
    1

    Increment the reference count again.

    >>> av.reference_entity(jack, auth)
    >>> av.entity_references(jack)
    2

    Decrement the reference count.

    >>> av.dereference_entity(jack, auth)
    >>> av.entity_references(jack)
    1

    Decrement the reference count again.

    >>> av.dereference_entity(jack, auth)
    >>> av.entity_references(jack)
    0

    Decrement the reference count one more time. Note that the reference count
    stays at zero.

    >>> av.dereference_entity(jack, auth)
    >>> av.entity_references(jack)
    0

    Clean up.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """

    return atapi.references(entity)

@manage_exceptions('while finding the timestamp of entity {0}')
def entity_timestamp(entity):
    """
    entity_timestamp(entity)
    Return the time that the entity was created, as an epoch integer.

    Parameters
    ----------
    entity : Entity
        the entity whose timestamp is returned

    Returns
    -------
    int
        the time the entity was created, as an epoch integer: the number of 
        integer seconds since 00:00:00 UTC on 1 January 1970.

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or ``entity`` is extinct.

    See also
    --------
    :func:`create_entity` : create an entity

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize() 

    Create an entity.

    >>> jack = av.create_entity(
    ...     'Jack Nicholson', av.Class.PERSON, av.Subclass.PERSON, auth)

    Find the entity's timestamp

    >>> av.entity_timestamp(jack)
    1585345058

    Create another entity, 20 seconds after the first. Find its timestamp.

    >>> jack2 = av.create_entity(
    ...     'Jack Torrance', av.Class.PERSON, av.Subclass.PERSON, auth) 
    1585345058
    >>> av.entity_timestamp(jack2)
    1585345078

    Clean up.
    
    >>> av.delete_entity(jack, auth)
    >>> av.delete_entity(jack2, auth)
    >>> av.finalize()
    """
    return atapi.timestamp(entity)
    
################################################################################
#
# Comprehensive operations
#

class InterchangeValue(Value):
    """A Value object that is known to be json interchange format."""
    @classmethod
    def from_object(klass, object):
        return klass.create_interchange_value(object)

    def validate_against_schema(self, original_value):
        """Validate content if a store schema exists."""
        try:
            if store_schema:
                jsonschema.validate(self._interchange, store_schema)
        except Exception:
            raise AvialError(
                f'{original_value} does not comply with store format')

@manage_exceptions('while storing {1} on entity {0}')
def store_entity(entity, value, authorization, *, mode=None):
    """
    store_entity(entity, value, authorization, *, mode=None)
    Store new content on the entity.

    Store new content on the entity, after checking for errors. The new content
    is provided by the ``value`` parameter, in 
    :ref:`comprehensive format <comprehensive_format>`.

    There are four usage scenarios for :func:`store_entity`: create,
    replace, append, and update. The most common usage scenario is creation: 
    ``entity`` has just been created, and needs
    to be filled with attributes, properties, and values. ``value`` contains
    all the attributes, properties, and value for the new entity, in one
    big dict. See :ref:`create example <store_entity_create_example>`.

    Another common usage scenario is replacement: ``entity`` already exists 
    with some content---some attributes, properties, and values---but all
    of the existing content is to be replaced with new stuff in ``value``. 
    Performing replacement involves two steps. First the existing content
    of the entity is erased with a call to
    :func:`erase_entity`. Once erased, a call to :func:`store_entity` is
    made with the replacement ``value``. See 
    :ref:`replace example <store_entity_replace_example>`.

    Replacement is common because it is often easier to retrieve the contents
    of an entity, manipulate the contents in Python, and then store the
    results, rather than executing a series of Avial operations to manipulate
    an existing entity. But when the entity is large, with many attributes
    or many properties, replacement is impractical; you don't want to read
    10 megabytes of content just to make a small change. In these situations,
    append or update may be better. 

    :func:`store_entity` supports the append and update usage scenarios
    with the  
    ``mode`` parameter. If ``mode`` is ``Mode.APPEND``, :func:`store_entity`
    appends the new content to the entity's existing content. Any 
    :ref:`entity values <entity_values>`
    of the new content are appended to the entity values of the existing
    content, so if the existing content has one entity value and the new content
    has three, after :func:`store_entity`, the entity will have four values.

    If the same attribute exists in both the existing content and the new 
    content, the :ref:`attribute instances <attribute_instances>`
    of the new content are appended to the attribute
    instances of the existing content. For example, if the existing content
    has two CHILD attribute instances and the new content has three CHILD
    attribute instances, the resulting entity will have five children.
    See :ref:`replace example <store_entity_append_example>`.

    Append also appends any entity properties of ``value`` to the existing
    entity properties, for any properties that have non-conflicting keys. 
    A entity property in the new content is said to conflict with an 
    entity property in the existing content if their keys are identical and
    also non-empty. In other words, an entity property in the new content
    is appended to the existing entity properties as long as it either has
    an empty key or a key that does not already exist among the entity
    properties. Any property in the new content with a conflicting key is
    ignored. 

    The append usage scenario is useful when you want to add additional
    stuff to an existing entity: additional attributes, additional 
    attribute instances, or additional properties. When you want to change
    existing content, the update usage scenario may be useful. 

    If ``mode`` is ``Mode.UPDATE``, :func:`store_entity` updates the
    existing content of the entity, or at least attempts to. The rules for
    update are rather complex. Any entity values
    on the existing entity are replaced by the entity values of the new content,
    up to the limit of the number of values of the content entity. For 
    example, if the existing entity has three values, the integers 1, 2, and 3,
    and the new content provides two values 9 and 6, the updated entity
    will end up with three values: 9, 6, and 3.

    For each entity property in the new content:

    1. If the new property has a non-empty key that matches a key on a property
    in the existing entity, the existing property is replaced with the new 
    property.

    2. If the new property has a non-empty key that does not match any
    key of an existing property, the new property is added to the list of 
    entity properties.

    3. If the new property has an empty key and has a name that matches
    the name of an existing property, the first such matching property is 
    changed: its value is changed to the value of the new property.

    4. If the new property has an empty key and a name that matches the name
    of no existing properties, the new property is added to the list of 
    existing properties.

    For each attribute in the new content:

    1. If the attribute is not already present on the existing entity, all
    the attribute instances of the new attribute are added to the existing 
    attribute.

    2. If the attribute is already present on the existing entity, each new
    attribute instance is combined with each existing attribute instance.
    The properties of the attribute instances are combined according to the
    rules of updating entity properties, above. The values of the existing
    attribute instance are replaced by the values of the new attribute 
    instance, according ot the rules of combining entity values, also above.

    See :ref:`update example <store_entity_update_example>`.

    Parameters
    ----------
    entity : Entity
        the entity that is to be changed

    value : dict
        the new attributes, properties, and values, in 
        :ref:`comprehensive format <comprehensive_format>`

    authorization : Authorization
        an object authorizing changing the entity

    mode : Mode or None, optional
        the mode by which the new content in ``value`` is to be combined with
        any existing content. See explanation above.

    Returns
    -------
    None

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``value`` does not comply with comprehensive format, or
        ``authorization`` does not authorize storing new content on the entity,
        or ``mode`` is not a mode, or ``value`` is too large to store.

    See also
    --------
    :func:`retrieve_entity` : return all attributes, properties, and values of an entity, in :ref:`comprehensive format <comprehensive_format>`
    
    :func:`retrieve_value` : retrieve multiple values, in :ref:`comprehensive format <comprehensive_format>`

    :func:`retrieve_attribute` : return attribute values and properties, in :ref:`comprehensive format <comprehensive_format>`

    :func:`retrieve_property` : return entity properties, or attribute properties, in :ref:`comprehensive format <comprehensive_format>`

    Examples
    --------
    >>> import avesterra.avial as av
    >>> auth = av.initialize()

    .. _store_entity_create_example:

    Create an entity for Jack.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)

    Store the details on the newly created entity.

    >>> jacks_details_create = {
    ...     "Attributes":{
    ...         "SEX_ATTRIBUTE":[{"Values":["M"]}],
    ...         "AGE_ATTRIBUTE":[{"Values":[{"INTEGER": "80"}]}]
    ...     },
    ...     "Properties":[
    ...         ["known for","most popular role", {"UTF-8": "The Shining"}] 
    ...         ],
    ...     "Values": [{"UTF-8": "actor"}]
    ... }
    >>> av.store_entity(jack, jacks_details_create, auth)

    Check that everything is right.

    >>> av.retrieve_entity(jack)
    {
        'Values': [{'UTF-8': 'actor'}], 
        'Properties': [
            ['known for', 'most popular role', {'UTF-8': 'The Shining'}]
            ], 
        'Attributes': {
            'SEX_ATTRIBUTE': [{'Values': ['M']}], 
            'AGE_ATTRIBUTE': [{'Values': [{'INTEGER': '80'}]}]
            }, 
        'Label': 'Jack Nicholson'
    }

    .. _store_entity_replace_example:

    Replace the contents of Jack with new contents. Start by erasing 
    the existing attributes, properties, and values.

    >>> av.erase_entity(jack, auth)

    Store the new details.

    >>> jacks_details_replace = {
    ...     "Attributes":{ 
    ...         "LOCATION_ATTRIBUTE":[{"Values":[
    ...             {"UTF-8": "Los Angeles"} 
    ...         ]}],
    ...         "CHILD_ATTRIBUTE":[
    ...             {
    ...                 "Values": [{"UTF-8": "Jennifer"}],
    ...                 "Properties": [ 
    ...                     ["Born","", {"INTEGER": "1963"}],
    ...                     ["Mother","", {"ASCII": "Sandra Knight"}] 
    ...                 ]
    ...             },
    ...             {
    ...                 "Values": [{"UTF-8": "Caleb"}],
    ...                 "Properties": [ 
    ...                     ["Born","", {"INTEGER": "1970"}],
    ...                     [
    ...                         "Paternity", 
    ...                         "open question 2", 
    ...                         {"UTF-8": "not established"}],
    ...                     ["Mother","", {"UTF-8": "Susan Anspach"}]
    ...                 ]
    ...             } 
    ...         ]
    ...     },
    ...     "Properties":[
    ...         ["known for","most popular role", {"UTF-8": "The Shining"}],
    ...         ["fan of","famous fan","Los Angeles Lakers"],
    ...         ["fan of", "", "Bob Dylan"],
    ...         ["also known for","best performance","Chinatown"]
    ...     ],
    ...     "Values": [{"UTF-8": "actor"}, {"UTF-8": "player"}]
    ... }
    >>> av.store_entity(jack, jacks_details_replace, auth)

    Check the results.

    >>> av.retrieve_entity(jack)
    {
        'Values': [{'UTF-8': 'actor'}, {'UTF-8': 'player'}], 
        'Properties': [
            ['known for', 'most popular role', {'UTF-8': 'The Shining'}], 
            ['fan of', 'famous fan', 'Los Angeles Lakers'], 
            ['fan of', '', 'Bob Dylan'], 
            ['also known for', 'best performance', 'Chinatown']
            ], 
        'Attributes': {
            'LOCATION_ATTRIBUTE': [{'Values': [{'UTF-8': 'Los Angeles'}]}], 
            'CHILD_ATTRIBUTE': [
                {
                    'Values': [{'UTF-8': 'Jennifer'}], 
                    'Properties': [
                        ['Born', '', {'INTEGER': '1963'}], 
                        ['Mother', '', {'ASCII': 'Sandra Knight'}]
                        ]
                }, 
                {
                    'Values': [{'UTF-8': 'Caleb'}], 
                    'Properties': [
                        ['Born', '', {'INTEGER': '1970'}], 
                        ['Paternity', 'open question 2', {'UTF-8': 'not established'}], 
                        ['Mother', '', {'UTF-8': 'Susan Anspach'}]
                        ]
                }
            ]}, 
        'Label': 'Jack Nicholson'
    }

    .. _store_entity_append_example:

    Append some more content to the entity.

    >>> jacks_details_append = {
    ...     "Attributes":{ 
    ...         "LOCATION_ATTRIBUTE":[{"Values":[
    ...             {"UTF-8": "Malibu"} 
    ...         ]}],
    ...         "CHILD_ATTRIBUTE":[
    ...             {"Values": [{"UTF-8": "Honey"}]},
    ...             {"Values": [{"UTF-8": "Lorraine"}]},
    ...             {
    ...                 "Values": [{"UTF-8": "Raymond"}],
    ...                 "Properties": [ 
    ...                     ["Born","youngest", {"INTEGER": "1992"}],
    ...                     ["Mother","", {"UTF-8": "Rebecca Broussard"}] 
    ...                 ]
    ...             }] 
    ...     },
    ...     "Properties":[
    ...         ["also fan of", "best performance", {'UTF-8': "in Lakers games"}],
    ...         ["fan of","","New York Yankees"],
    ...         ["", "most popular role", {'UTF-8': "The Shining"}]
    ...     ],
    ...     "Values": [{"UTF-8": "filmmaker"}]
    ... }
    >>> av.store_entity(jack, jacks_details_append, auth, mode=av.Mode.APPEND)

    Check the result. Note that there are two new values, a second location, two
    new children, properties have changed.

    >>> av.retrieve_entity(jack)
    {
        'Values': [
            {'UTF-8': 'actor'}, 
            {'UTF-8': 'player'}, 
            {'UTF-8': 'filmmaker'}
            ], 
        'Properties': [
            ['known for', 'most popular role', {'UTF-8': 'The Shining'}], 
            ['fan of', 'famous fan', 'Los Angeles Lakers'], 
            ['fan of', '', 'Bob Dylan'], 
            ['also known for', 'best performance', 'Chinatown'], 
            ['fan of', '', 'New York Yankees']
            ], 
        'Attributes': {
            'LOCATION_ATTRIBUTE': [
                {'Values': [{'UTF-8': 'Los Angeles'}]}, 
                {'Values': [{'UTF-8': 'Malibu'}]}
                ], 
            'CHILD_ATTRIBUTE': [
                {
                    'Values': [{'UTF-8': 'Jennifer'}], 
                    'Properties': [
                        ['Born', '', {'INTEGER': '1963'}], 
                        ['Mother', '', {'ASCII': 'Sandra Knight'}]
                        ]
                }, 
                {
                    'Values': [{'UTF-8': 'Caleb'}], 
                    'Properties': [
                        ['Born', '', {'INTEGER': '1970'}], 
                        ['Paternity', 'open question 2', {'UTF-8': 'not established'}], 
                        ['Mother', '', {'UTF-8': 'Susan Anspach'}]
                        ]
                }, 
                {'Values': [{'UTF-8': 'Honey'}]}, 
                {'Values': [{'UTF-8': 'Lorraine'}]}, 
                {
                    'Values': [{'UTF-8': 'Raymond'}], 
                    'Properties': [
                        ['Born', 'youngest', {'INTEGER': '1992'}], 
                        ['Mother', '', {'UTF-8': 'Rebecca Broussard'}]
                        ]
                }]
            }, 
        'Label': 'Jack Nicholson'
    }

    .. _store_entity_update_example:

    Update the entity with some additional content.

    >>> jacks_details_update = {
    ...     "Attributes":{ 
    ...         "LOCATION_ATTRIBUTE":[{"Values":[
    ...             {"UTF-8": "Aspen"} 
    ...         ]}],
    ...         "CHILD_ATTRIBUTE":[ 
    ...             { 
    ...                 "Properties": [ 
    ...                     ["Mother","", {"ASCII": "Sandra"}],
    ...                     ["Born","", {"INTEGER": "1964"}]
    ...                 ]
    ...             },
    ...             {
    ...                 "Values": [{"UTF-8": "C"}]
    ...             },
    ...             {},
    ...             {
    ...                 "Values": [{"UTF-8": "Lorraine"}],
    ...                 "Properties": [ 
    ...                     ["Mother","", {"UTF-8": "Rebecca Broussard"}] 
    ...                 ]
    ...                 
    ...             },
    ...             {
    ...                 "Values": [{"UTF-8": "Raymond"}],
    ...                 "Properties": [ 
    ...                     ["Emerged","youngest", {"INTEGER": "1993"}]
    ...                 ]
    ...             }
    ...         ] 
    ...     },
    ...     "Properties":[
    ...         ["also fan of", "best performance", {'UTF-8': "in Lakers games"}],
    ...         ["fan of","", "The Hold Steady"],
    ...         ["not a fan of", "", {'UTF-8': "Los Angeles Clippers"}]
    ...     ],
    ...     "Values": [{"UTF-8": "bad boy"}]
    ... }
    >>> av.store_entity(jack, jacks_details_update, auth, mode=av.Mode.UPDATE)

    Check the result. Note that a value has been replaced, a location has been
    replaced, one child's name has been changed, several of the children 
    properties have been changed, and most surprisingly, Jack is now a fan 
    of the Brooklyn band the Hold Steady.

    >>> av.retrieve_entity(jack)
    {
        'Values': [
            {'UTF-8': 'bad boy'}, 
            {'UTF-8': 'player'}, 
            {'UTF-8': 'filmmaker'}
            ], 
        'Properties': [
            ['known for', 'most popular role', {'UTF-8': 'The Shining'}], 
            ['fan of', 'famous fan', 'The Hold Steady'], 
            ['fan of', '', 'Bob Dylan'], 
            ['also fan of', 'best performance', {'UTF-8': 'in Lakers games'}], ['fan of', '', 'New York Yankees'], 
            ['not a fan of', '', {'UTF-8': 'Los Angeles Clippers'}]
            ], 
        'Attributes': {
            'LOCATION_ATTRIBUTE': [
                {'Values': [{'UTF-8': 'Aspen'}]}, 
                {'Values': [{'UTF-8': 'Malibu'}]}
                ], 
            'CHILD_ATTRIBUTE': [
                {
                    'Values': [{'UTF-8': 'Jennifer'}], 
                    'Properties': [
                        ['Born', '', {'INTEGER': '1964'}], 
                        ['Mother', '', {'ASCII': 'Sandra'}]
                        ]
                }, 
                {
                    'Values': [{'UTF-8': 'C'}], 
                    'Properties': [
                        ['Born', '', {'INTEGER': '1970'}], 
                        ['Paternity', 'open question 2', {'UTF-8': 'not established'}], 
                        ['Mother', '', {'UTF-8': 'Susan Anspach'}]
                        ]
                }, 
                {'Values': [{'UTF-8': 'Honey'}]}, 
                {
                    'Values': [{'UTF-8': 'Lorraine'}], 
                    'Properties': [
                        ['Mother', '', {'UTF-8': 'Rebecca Broussard'}]
                        ]
                }, 
                {
                    'Values': [{'UTF-8': 'Raymond'}], 
                    'Properties': [
                        ['Emerged', 'youngest', {'INTEGER': '1993'}], 
                        ['Mother', '', {'UTF-8': 'Rebecca Broussard'}]
                        ]
                }]
            }, 
        'Label': 'Jack Nicholson'
    }

    Clean up.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """
    logger.debug(f'Storing content in entity {entity}: {value}') 
    value_obj = InterchangeValue.from_object(value) 
    value_obj.validate_against_schema(value)
    try: 
        invoke(
            entity, 
            Method.STORE, 
            value=value_obj, 
            mode=TranslateFromAvialToAPI.mode(mode),
            authorization=authorization)
    except at.MessageTooLargeError as err:
        raise AvialError(f'Content is too big to store: {err}')
    except at.AdapterError as err:
        raise AvialError(
            'Content ({} characters) failed to store because {}'.format(
                value_obj.size(), str(err)))

@manage_exceptions('while retrieving from entity {0}')
def retrieve_entity(entity):
    """
    retrieve_entity(entity)
    Retrieve the contents of entity, in comprehensive format.

    Retrieve and return the contents of entity, in comprehensive format. 
    Comprehensive format is a dict with the entity's label, attributes, 
    properties, and values. 
    See :ref:`comprehensive format <comprehensive_format>` for more detail on
    the format.    

    Parameters
    ----------
    entity : Entity
        the entity whose contents are retrieved

    Returns
    -------
    dict
        the contents of the entity in 
        :ref:`comprehensive format <comprehensive_format>`

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter

    See also
    --------
    :func:`store_entity` : set attributes, properties, and values of an entity
    
    :func:`retrieve_value` : retrieve multiple values, in :ref:`comprehensive format <comprehensive_format>`

    :func:`retrieve_attribute` : return attribute values and properties, in :ref:`comprehensive format <comprehensive_format>`

    :func:`retrieve_property` : return entity properties, or attribute properties, in :ref:`comprehensive format <comprehensive_format>`

    Examples
    -------
    >>> import avesterra.avial as av
    >>> auth = av.initialize()

    Create an entity for Jack and give him attributes and properties.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jacks_details = {
    ...     "Attributes":{  
    ...         "CHILD_ATTRIBUTE":[
    ...             {
    ...                 "Values": [{'UTF-8': "Jennifer"}],
    ...                 "Properties": [ 
    ...                     ["Born","", {'INTEGER': '1963'}],
    ...                     ["Mother","", {'ASCII': 'Sandra Knight'}] 
    ...                 ]
    ...             },
    ...             {
    ...                 "Values": [{'UTF-8': "Caleb"}],
    ...                 "Properties": [ 
    ...                     ["Born","", {'INTEGER': "1970"}],
    ...                     [
    ...                         "Paternity", 
    ...                         "open question", 
    ...                         {'UTF-8': "not established"}],
    ...                     ["Mother","", {'UTF-8': "Susan Anspach"}],
    ...                 ]
    ...             },
    ...             {"Values": [{'UTF-8': "Honey"}]},
    ...             {"Values": [{'UTF-8': "Lorraine"}]},
    ...             {
    ...                 "Values": [{'UTF-8': "Raymond"}],
    ...                 "Properties": [ 
    ...                     ["Born","youngest", {'INTEGER': "1992"}],
    ...                     ["Mother","", {'UTF-8': "Rebecca Broussard"}] 
    ...                 ]
    ...             }]},
    ...     "Properties":[
    ...         ["known for","most popular role", {'UTF-8': "The Shining"}],
    ...         ["fan of","famous fan", {"UTF-8": "Los Angeles Lakers"}],
    ...         ["fan of", "", {"UTF-8": "Bob Dylan"}],
    ...         ["also known for","best performance",{"UTF-8": "Chinatown"}]
    ...         ]
    ... }
    >>> av.store_entity(jack, jacks_details, auth)

    Retrieve the contents of Jack, in comprehensive format.

    >>> av.retrieve_entity(jack)
    {
        'Properties': [
            ['known for', 'most popular role', {'UTF-8': 'The Shining'}], 
            ['fan of', 'famous fan', {'UTF-8': 'Los Angeles Lakers'}], 
            ['fan of', '', {'UTF-8': 'Bob Dylan'}], 
            ['also known for', 'best performance', {'UTF-8': 'Chinatown'}]
        ], 
        'Attributes': {
            'CHILD_ATTRIBUTE': [
                {
                    'Values': [{'UTF-8': 'Jennifer'}],
                    'Properties': [
                        ['Born', '', {'INTEGER': '1963'}], 
                        ['Mother', '', {'ASCII': 'Sandra Knight'}]
                    ]
                }, 
                {
                    'Values': [{'UTF-8': 'Caleb'}], 
                    'Properties': [
                        ['Born', '', {'INTEGER': '1970'}], 
                        ['Paternity', 'open question', {'UTF-8': 'not established'}], 
                        ['Mother', '', {'UTF-8': 'Susan Anspach'}]
                    ]
                }, 
                {'Values': [{'UTF-8': 'Honey'}]}, 
                {'Values': [{'UTF-8': 'Lorraine'}]}, 
                {
                    'Values': [{'UTF-8': 'Raymond'}], 
                    'Properties': [
                        ['Born', 'youngest', {'INTEGER': '1992'}], 
                        ['Mother', '', {'UTF-8': 'Rebecca Broussard'}]
                    ]
                }
            ]
        }, 
        'Label': 'Jack Nicholson'
    }

    Clean up.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """ 
    return _validate_and_simplify(_retrieve_raw(entity))

def _validate_and_simplify(comprehensive_content):
    """Validate that the content conforms to spec, and simplify it."""
    _maybe_validate_content(comprehensive_content)
    return simplify_store_format(comprehensive_content)

def simplify_store_format(content):
    """Simplify content, removing unnecessary empty stuff."""
    simpler = {}
    if 'Values' in content and content['Values']:
        simpler['Values'] = content['Values']
    if 'Properties' in content and content['Properties']:
        simpler['Properties'] = content['Properties']

    if 'Attributes' in content:
        attributes = {
        k: v for (k, v) in ((k2, _simplify_attribute(v2)) 
                            for k2, v2 in content['Attributes'].items() )
        if v
        }
        if attributes:
            simpler['Attributes'] = attributes 

    if 'Label' in content and content['Label']:
        simpler['Label'] = content['Label']

    return simpler 

def _simplify_attribute(attribute_instances):
    """Simplify list of attribute instances."""
    return [inst for inst in (_simplify_instance(i2) 
                              for i2 in attribute_instances)
            if inst]

def _simplify_instance(attribute_instance):
    """Simplify single attribute instance."""
    simpler = {}
    if 'Values' in attribute_instance and attribute_instance['Values']:
        simpler['Values'] = attribute_instance['Values']
    if 'Properties' in attribute_instance and attribute_instance['Properties']:
        simpler['Properties'] = attribute_instance['Properties']
    if 'Label' in attribute_instance and attribute_instance['Label']:
        simpler['Label'] = attribute_instance['Label']
    return simpler

def _retrieve_raw(entity):
    """Retrieve content."""
    return invoke(entity, Method.RETRIEVE, return_results=True)

def _maybe_validate_content(content):
    """Validate content if a store schema exists."""
    try:
        if store_schema:
            jsonschema.validate(content, store_schema)
    except Exception:
        raise AvialError(
            '{} does not comply with comprehensive format'.format(content))


################################################################################
#
# Value operations
#

@manage_exceptions(
    'while getting value from {0}', check_for_naked_instance=True)
def get_value(entity, *, attribute=None, instance=None, index=None):
    """
    get_value(entity, *, attribute=None, instance=None, index=None)
    Return the value of an attribute.

    Typically :func:`get_value` is used to return the value of an attribute on
    an entity, the attribute specified as ``attribute``. If no attribute is 
    provided, the value associated with the entity itself is returned.

    Sometimes an attribute of an entity has more than one instance. In
    that situation, :func:`get_value` returns the last instance, as long
    as ``instance`` is not specified. If ``instance`` is provided, it specifies
    the numeric index of the attribute instance to be returned. For example, if
    ``instance`` is 2, the second attribute instance is returned.

    Sometimes an attribute instance has multiple values. In that 
    situation, :func:`get_value` will return the last of the values, as long 
    as ``index`` is not specified. If ``index`` is provided, it specifies
    the numeric index of the value to be returned. For example, if ``index`` is 
    1, the first value is returned.

    When ``attribute`` is given, either ``instance`` and ``index`` can be 
    provided, or both. For example, if ``attribute`` is ``CHILD``, ``instance``
    is 3, and ``index`` is 2, the second value of the third CHILD attribute
    instance is returned.

    When ``attribute`` is ``None``, ``index`` can be specified, as an entity
    can have more than one value. When ``index`` is not specified, the last 
    value is returned. But when ``attribute`` is ``None``, ``instance`` cannot 
    be provided; unlike its attributes, an entity has only a single instance.

    Parameters
    ----------
    entity : Entity
        the entity whose value is to be returned  

    attribute : Attribute, optional
        the attribute of ``entity`` whose value is to be returned. The default 
        is ``None``: return the value of the entity itself rather than one of 
        its attributes.

    instance : int, optional
        the attribute instance of ``entity`` to be returned. The default is 
        ``None`` (or equivalently: 0): return the last attribute instance.   
        If ``instance`` is
        greater than the number of instances, an :class:`AvialError` exception
        is raised.

    index : int, optional
        which value to return, if there are multiple values on the attribute
        instance---or on the entity itself, if ``attribute`` is ``None``. The
        default is ``None``: return the last value. If
        ``index`` is 0, the last value is returned. If ``index`` is
        greater than the number of values, an :class:`AvialError` exception
        is raised.

    Returns
    -------
    int or float or bool or str or Entity or list or dict
        the value of the entity's attribute (or of the entity itself)

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``attribute`` 
        is not an attribute, or no such attribute is found for the entity, or
        an instance is specified but no attribute, or the instance provided
        is greater than the number of instances, or the index provided is 
        greater than the number of values.

    See also
    --------
    :func:`set_value` : change the value of an attribute of an entity

    :func:`clear_value` : clear the value of an attribute or of the entity

    :func:`insert_value` : insert an additional value on the entity or an attribute

    :func:`remove_value` : remove a single value from an attribute or from the entity

    :func:`replace_value` : replace a value from an attribute of from the entity with another value

    :func:`erase_value` : erase values from an entity

    :func:`find_value` : find the index or a known value

    :func:`retrieve_value` : retrieve multiple values, in :ref:`comprehensive format <comprehensive_format>`

    :func:`value_count`: return the number of values on an attribute instance

    :func:`create_entity` : create an entity 

    :func:`store_entity` : set attributes, properties, and values of an entity

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize()

    Create an entity, with some initial attributes and values.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> mini_jack = {
    ...    'Values': ['actor', 'player'],
    ...    'Attributes': {
    ...        'AGE_ATTRIBUTE': [{'Values': [81]}],
    ...        'LOCATION_ATTRIBUTE': [{'Values': ['Los Angeles', 'Aspen']}],
    ...        'CHILD_ATTRIBUTE': [
    ...            {'Values': ['Jennifer']},
    ...            {'Values': ['Caleb']},
    ...            {'Values': ['Honey', 'Honey Duffy']},
    ...            {'Values': ['Lorraine']},
    ...            {'Values': ['Raymond']}
    ...        ]
    ...    }
    ... }
    >>> av.store_entity(jack, mini_jack, auth)

    Get Jack's age.

    >>> av.get_value(jack, attribute=av.Attribute.AGE)
    81

    Get Jack's location. The last location value is returned.

    >>> av.get_value(jack, attribute=av.Attribute.LOCATION)
    'Aspen'

    Get the first location.

    >>> av.get_value(jack, attribute=av.Attribute.LOCATION, index=1)
    'Los Angeles'

    Get Jack's child. The value of last attribute instance is returned.

    >>> av.get_value(jack, attribute=av.Attribute.CHILD)
    'Raymond'

    To get a different child, use ``instance``. The last value of 
    the specified attribute instance is returned.

    >>> av.get_value(jack, attribute=av.Attribute.CHILD, instance=3)
    'Honey Duffy'

    To get a different value of the third child, use ``index`` as well as
    ``instance``.

    >>> av.get_value(jack, attribute=av.Attribute.CHILD, instance=3, index=1)
    'Honey'

    Get a value associated with the entity Jack, rather than an attribute
    value. The last such value is returned.

    >>> av.get_value(jack)
    'player'

    Get a different value associated with the entity, using ``index``.

    >>> av.get_value(jack, index=1)
    'actor'

    Clean up the example and end the session.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """
    return invoke(
        entity, Method.GET, attribute=attribute, instance=instance, 
        index=index, parameter=Argument.VALUE, return_results=True)

@manage_exceptions(
    'while setting value on {0} to {1}', check_for_naked_instance=True)
def set_value(entity, value, auth, *, attribute=None, instance=None, 
              index=None):
    """
    set_value(entity, value, auth, *, attribute=None, instance=None, index=None)
    Set the value of an attribute.

    Typically :func:`set_value` is used to change the value of an attribute on
    an entity, the attribute specified as ``attribute``. If no attribute is 
    provided, the value associated with the entity itself is changed.

    Sometimes an attribute of an entity has more than one instance. In
    that situation, :func:`set_value` will change the last instance, as long
    as ``instance`` is not specified. If ``instance`` is provided, it specifies
    the numeric index of the attribute instance to be changed. For example, if
    ``instance`` is 2, the second attribute instance is changed.

    Sometimes an attribute instance has multiple values. In that 
    situation, :func:`set_value` will change the last of the values, as long 
    as ``index`` is not specified. If ``index`` is provided, it specifies
    the numeric index of the value to be changed. For example, if ``index`` is 
    1, the first value is changed.

    When ``attribute`` is given, either ``instance`` and ``index`` can be 
    provided, or both. For example, if ``attribute`` is ``CHILD``, ``instance``
    is 3, and ``index`` is 2, the second value of the third CHILD attribute
    instance is changed.

    When ``attribute`` is ``None``, ``index`` can be specified, as an entity
    can have more than one value. When ``index`` is not specified, the last 
    value is changed. But when ``attribute`` is ``None``, ``instance`` cannot 
    be provided; unlike its attributes, an entity has only a single instance.

    Parameters
    ----------
    entity : Entity
        the entity to be changed

    value : int or float or bool or str or Entity or list or dict or Value
        the new value for ``entity``

    auth : Authorization
        an object that authorizes changing the value of ``entity``

    attribute : Attribute, optional
        the attribute of ``entity`` to be set to ``value``. The default is 
        ``None``: change the value of the entity itself rather than one of its
        attributes.

    instance : int, optional
        the attribute instance of ``entity`` to be changed. The default is 
        ``None``: change the last attribute instance. If ``instance`` is greater
        than the count of instances, a new instance is added. If  
        ``instance`` is 0, the last instance is changed.

    index : int, optional
        the value to change, if there are multiple values on the attribute
        instance---or on the entity itself, if ``attribute`` is ``None``. The
        default is ``None``: change the last value. If ``index`` is greater
        than the count of values, a new value is added. If 
        ``index`` is 0, the last value is changed.

    Returns
    -------
    None

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``auth`` is not a valid  authorization, or ``attribute`` 
        is not an attribute, or an instance is specified but no attribute.

    See also
    --------
    :func:`get_value` : return the value of an attribute of an entity

    :func:`clear_value` : clear the value of an attribute or of the entity

    :func:`insert_value` : insert an additional value on the entity or an attribute

    :func:`remove_value` : remove a single value from an attribute or from the entity

    :func:`replace_value` : replace a value from an attribute of from the entity with another value

    :func:`erase_value` : erase values from an entity

    :func:`find_value` : find the index or a known value

    :func:`retrieve_value` : retrieve multiple values, in :ref:`comprehensive format <comprehensive_format>`

    :func:`value_count`: return the number of values on an attribute instance

    :func:`create_entity` : create an entity 

    :func:`retrieve_entity` : return all attributes, properties, and values of an entity, in :ref:`comprehensive format <comprehensive_format>`

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize()

    Create an entity.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)

    Set Jack's age and location.

    >>> av.set_value(jack, 80, auth, attribute=av.Attribute.AGE)
    >>> av.set_value(jack, 'Los Angeles', auth, attribute=av.Attribute.LOCATION)

    Take a look at Jack, so far.

    >>> av.retrieve_entity(jack)
    {'Attributes': {
        'AGE_ATTRIBUTE': [{'Values': ['80']}],
        'LOCATION_ATTRIBUTE': [{'Values': ['Los Angeles']}]}}

    Update Jack's age.

    >>> av.set_value(jack, 81, auth, attribute=av.Attribute.AGE)

    Add a second location.

    >>> av.set_value(jack, 'Aspen', auth, attribute=av.Attribute.LOCATION, index=2)

    Now what for Jack?

    >>> av.retrieve_entity(jack)
    {'Attributes': {
        'AGE_ATTRIBUTE': [{'Values': ['81']}],
        'LOCATION_ATTRIBUTE': [{'Values': ['Los Angeles', 'Aspen']}]}}

    Add Jack's occupations, as values on the Jack entity.

    >>> av.set_value(jack, 'actor', auth)
    >>> av.set_value(jack, 'director', auth, index=2)
    >>> av.retrieve_entity(jack)
    {
        'Values': ['actor', 'director'],
        'Attributes': {
            'AGE_ATTRIBUTE': [{'Values': ['81']}],
            'LOCATION_ATTRIBUTE': [{'Values': ['Los Angeles', 'Aspen']}]
        }
    }

    Hmm. Maybe we should ignore 
    `The Two Jakes <https://www.imdb.com/title/tt0100828/>`_, as it was 
    disappointing. Replace ``director`` with something Jack is good at.

    >>> av.set_value(jack, 'player', auth, index=2)
    >>> av.retrieve_entity(jack)
    {
        'Values': ['actor', 'player'],
        'Attributes': {
            'AGE_ATTRIBUTE': [{'Values': ['81']}],
            'LOCATION_ATTRIBUTE': [{'Values': ['Los Angeles', 'Aspen']}]
        }
    }

    Jack has five children. Add his children
    as attribute instances, so we can later annotate each with properties.

    >>> av.set_value(jack, 'Jennifer', auth, attribute=av.Attribute.CHILD)
    >>> av.set_value(jack, 'Caleb', auth, attribute=av.Attribute.CHILD, instance=2)
    >>> av.set_value(jack, 'Honey', auth, attribute=av.Attribute.CHILD, instance=3)
    >>> av.set_value(jack, 'Lorraine', auth, attribute=av.Attribute.CHILD, instance=4)
    >>> av.set_value(jack, 'Raymond', auth, attribute=av.Attribute.CHILD, instance=5)
    >>> av.retrieve_entity(jack)
    {
        'Values': ['actor', 'player'],
        'Attributes': {
            'AGE_ATTRIBUTE': [{'Values': ['81']}],
            'LOCATION_ATTRIBUTE': [{'Values': ['Los Angeles', 'Aspen']}],
            'CHILD_ATTRIBUTE': [
                {'Values': ['Jennifer']},
                {'Values': ['Caleb']},
                {'Values': ['Honey']},
                {'Values': ['Lorraine']},
                {'Values': ['Raymond']}
            ]
        }
    }

    Jack's daughter Honey is the actress Honey Duffy. Let's update the
    third child attribute with a second value.

    >>> av.set_value(jack, 'Honey Duffy', auth, attribute=av.Attribute.CHILD, instance=3, index=2)
    >>> av.retrieve_entity(jack)
    {
        'Values': ['actor', 'player'],
        'Attributes': {
            'AGE_ATTRIBUTE': [{'Values': ['81']}],
            'LOCATION_ATTRIBUTE': [{'Values': ['Los Angeles', 'Aspen']}],
            'CHILD_ATTRIBUTE': [
                {'Values': ['Jennifer']},
                {'Values': ['Caleb']},
                {'Values': ['Honey', 'Honey Duffy']},
                {'Values': ['Lorraine']},
                {'Values': ['Raymond']}
            ]
        }
    } 

    Clean up the example and end the session.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """ 
    invoke(
        entity, Method.SET, attribute=attribute, value=value, 
        authorization=auth, instance=instance, index=index, 
        parameter=Argument.VALUE)

@manage_exceptions('while clearing value on {0}', check_for_naked_instance=True)
def clear_value(entity, auth, *, attribute=None, instance=None, index=None):
    """
    clear_value(entity, auth, *, attribute=None, instance=None, index=None)
    Clear a value of an attribute, or a value from the entity itself.

    The most typical and simplest situation is an attribute on an entity that
    has a single instance and a single value for that instance, with no 
    attribute properties. In that situation, :func:`clear_value` clears the
    sole value of the attribute, removing that attribute from the entity
    entirely.
    
    Sometimes an attribute of an entity has more than one instance. In that
    situation, :func:`clear_value` clears the last instance, as long as 
    ``instance`` is not provided. If ``instance`` is provided, it specifies
    the numeric index of the attribute instance to be cleared. For example, if
    ``instance`` is 2, the second attribute instance is cleared.

    Sometimes an attribute instance has multiple values. In that situation, 
    :func:`clear_value` will clear the last of the values, as long 
    as ``index`` is not provided. If ``index`` is provided, it specifies
    the numeric index of the value to be cleared. For example, if ``index`` is 
    1, the first value is cleared.

    When ``attribute`` is given, either ``instance`` and ``index`` can be 
    provided, or both. For example, if ``attribute`` is ``CHILD``, ``instance``
    is 3, and ``index`` is 2, the second value of the third CHILD attribute
    instance is cleared.

    Clearing an attribute value will remove an attribute from an entity 
    entirely if three conditions are met: 

    #. there is only a single attribute instance

    #. there is only a single value of that attribute instance

    #. there are no properties of that attribute instance

    Similarly, clearing an attribute value will remove an attribute instance
    from the entity if there is only a single value of that attribute instance
    and no properties.

    When ``attribute`` is not provided, an entity value is cleared. If there 
    are multiple entity values, the last one is cleared, as long as ``index``
    is not provided. If provided, ``index`` indicates which value is to be 
    cleared. For example, if ``index`` is 3, the third value is cleared, and
    the fourth value (if it exists) becomes the new third value.

    When ``attribute`` is not provided, ``instance`` cannot be provided 
    either; unlike its attributes, an entity has only a single instance.

    Parameters
    ----------
    entity : Entity
        the entity whose value is to be cleared

    auth : Authorization
        an object that authorizes clearing a value from ``entity``

    attribute : Attribute, optional
        the attribute of ``entity`` whose value is cleared. The defualt is 
        ``None``: clear an entity value instead of an attribute value.

    instance : int, optional
        the attribute instance of ``entity`` whose value is to be cleared.
        The default is ``None``: clear a value from the last attribute instance.

    index : int, optional
        the value to be cleared, if there are multiple values on the attribute
        instance---or on the entity itself, if ``attribute`` is not provided.
        The default is ``None``: clear the last value. 

    Returns
    -------
    None

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``auth`` is not a valid  authorization, or ``attribute`` 
        is not an attribute, or an instance is specified but no attribute.

    See also
    --------
    :func:`get_value` : return the value of an attribute of an entity

    :func:`set_value` : change the value of an attribute of an entity  

    :func:`insert_value` : insert an additional value on the entity or an attribute

    :func:`remove_value` : remove a single value from an attribute or from the entity

    :func:`retrieve_value` : retrieve multiple values, in :ref:`comprehensive format <comprehensive_format>`

    :func:`replace_value` : replace a value from an attribute of from the entity with another value

    :func:`erase_value` : erase values from an entity

    :func:`find_value` : find the index or a known value
    
    :func:`value_count`: return the number of values on an attribute instance

    :func:`create_entity` : create an entity 

    :func:`store_entity` : set attributes, properties, and values of an entity

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize()
    >>> import pprint
    >>> pp = pprint.PrettyPrinter(indent=4)

    Create an entity for Jack Nicholson.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jacks_details = {
    ...     "Values": ["actor", "player", "director"],
    ...     "Attributes":{
    ...         "AGE_ATTRIBUTE":[{"Values":["80"]}],
    ...         "LOCATION_ATTRIBUTE":[{"Values":["Los Angeles", "Aspen", "Malibu"]}],
    ...         "CHILD_ATTRIBUTE":[
    ...             {"Values": ["Jennifer"]},
    ...             {
    ...                 "Values": ["Caleb"],
    ...                 "Properties": [ 
    ...                     ["Born","","1970"],
    ...                     ["Mother","","Susan Anspach"],
    ...                     ["Paternity", "Paternity", "not established"]
    ...                 ]
    ...             },
    ...             {"Values": ["Honey"]},
    ...             {"Values": ["Lorraine"]},
    ...             {"Values": ["Raymond"]}
    ...         ]
    ...     }
    ... }
    >>> av.store_entity(jack, jacks_details, auth)

    Clear Jack's age, and examine the Jack's attributes. Note that he is now
    ageless.

    >>> av.clear_value(jack, auth, attribute=av.Attribute.AGE) 
    >>> pp.pprint(av.retrieve_entity(jack)['Attributes'])
    {   'CHILD_ATTRIBUTE': [   {'Values': ['Jennifer']},
                               {   'Properties': [
                                        ['Born', '', '1970'], 
                                        ['Mother', '', 'Susan Anspach'],
                                        ['Paternity', 'not established']],
                                   'Values': ['Caleb']},           
                               {'Values': ['Honey']},
                               {'Values': ['Lorraine']},
                               {'Values': ['Raymond']}],
        'LOCATION_ATTRIBUTE': [{'Values': ['Los Angeles', 'Aspen', 'Malibu']}]}

    Clear Jack's child, and examine the result. He now has only four attribute
    instances of CHILD.

    >>> av.clear_value(jack, auth, attribute=av.Attribute.CHILD)
    >>> pp.pprint(av.retrieve_entity(jack)['Attributes'])
    {   'CHILD_ATTRIBUTE': [   {'Values': ['Jennifer']},
                               {   'Properties': [
                                        ['Born', '', '1970'], 
                                        ['Mother', '', 'Susan Anspach'],
                                        ['Paternity', 'not established']],
                                   'Values': ['Caleb']},           
                               {'Values': ['Honey']},
                               {'Values': ['Lorraine']}],
        'LOCATION_ATTRIBUTE': [{'Values': ['Los Angeles', 'Aspen', 'Malibu']}]}

    Clear the third instance of CHILD. The prior fourth instance becomes the
    third

    >>> av.clear_value(jack, auth, attribute=av.Attribute.CHILD, instance=3)
    >>> pp.pprint(av.retrieve_entity(jack)['Attributes'])
    {   'CHILD_ATTRIBUTE': [   {'Values': ['Jennifer']},
                               {   'Properties': [
                                        ['Born', '', '1970'], 
                                        ['Mother', '', 'Susan Anspach'],
                                        ['Paternity', 'not established']],
                                   'Values': ['Caleb']},               
                               {'Values': ['Lorraine']}],
        'LOCATION_ATTRIBUTE': [{'Values': ['Los Angeles', 'Aspen', 'Malibu']}]}

    Clear the second instance of CHILD. Note that the properties of that instance
    remain.

    >>> av.clear_value(jack, auth, attribute=av.Attribute.CHILD, instance=1)
    >>> pp.pprint(av.retrieve_entity(jack)['Attributes'])
    {   'CHILD_ATTRIBUTE': [   {'Values': ['Jennifer']},
                               {'Properties': [   
                                    ['Born', '', '1970'],
                                    ['Mother', '', 'Susan Anspach'],
                                    ['Paternity', 'Paternity', 'not established']
                                    ]},
                               {'Values': ['Lorraine']}],
        'LOCATION_ATTRIBUTE': [{'Values': ['Los Angeles', 'Aspen', 'Malibu']}]}

    Clear a location. The last value of his sole attribute instance of LOCATION
    is cleared.

    >>> av.clear_value(jack, auth, attribute=av.Attribute.LOCATION)
    >>> pp.pprint(av.retrieve_entity(jack)['Attributes'])
    {   'CHILD_ATTRIBUTE': [   {'Values': ['Jennifer']},
                               {'Properties': [   
                                    ['Born', '', '1970'],
                                    ['Mother', '', 'Susan Anspach'],
                                    ['Paternity', 'Paternity', 'not established']
                                    ]},
                               {'Values': ['Lorraine']}],
        'LOCATION_ATTRIBUTE': [{'Values': ['Los Angeles', 'Aspen']}]}

    Clear the first location, using ``index``.

    >>> av.clear_value(jack, auth, attribute=av.Attribute.LOCATION, index=1)
    >>> pp.pprint(av.retrieve_entity(jack)['Attributes'])
    {   'CHILD_ATTRIBUTE': [   {'Values': ['Jennifer']},
                               {'Properties': [   
                                    ['Born', '', '1970'],
                                    ['Mother', '', 'Susan Anspach'],
                                    ['Paternity', 'Paternity', 'not established']
                                    ]},
                               {'Values': ['Lorraine']}],
        'LOCATION_ATTRIBUTE': [{'Values': ['Aspen']}]}

    Take a look at the values on the Jack entity, rather than on any attribute
    of Jack.

    >>> av.retrieve_entity(jack)['Values']
    ['actor', 'player', 'director']

    Clear the last value.

    >>> av.clear_value(jack, auth)
    >>> av.retrieve_entity(jack)['Values']
    ['actor', 'player']

    Clear the first value.

    >>> av.clear_value(jack, auth, index=1)
    >>> av.retrieve_entity(jack)['Values']
    ['player']

    Clean up the example and end the session.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """
    invoke(
        entity, Method.CLEAR, attribute=attribute, instance=instance,
        index=index, authorization=auth, parameter=Argument.VALUE)

@manage_exceptions(
    'while inserting value {1} on {0}', check_for_naked_instance=True)
def insert_value(entity, value, auth, *, attribute=None, instance=None, 
                 index=None):
    """
    insert_value(entity, value, auth, *, attribute=None, instance=None, index=None)
    Insert an additional value on an entity.

    Insert an additional value, either on an attribute of the entity or on the
    entity as a whole. The existing values are not changed with the insertion,
    but a new value is added.

    When ``attribute`` is not provided, a new value is inserted on the entity
    as a whole. If ``index`` is provided, the new value is inserted at a 
    particular position on the list of values. If ``index`` is not provided, 
    the new value is inserted at the end of the list.

    When ``attribute`` is provided, a new value is inserted on that attribute,
    either at a particular position if ``index`` is provided, or at the end
    of the list of values if ``index`` is not provided.

    Sometimes an attribute of an entity has more than one instance. In the 
    situation :func:`insert_value` inserts the value on the last instance,
    as long as ``instance`` is not specified. If ``instance`` is provided, it
    specifies which attribute instance is to have a new value. For example,
    if ``instance`` is 4, the fourth attribute instance is changed.

    See examples below.

    Parameters
    ----------
    entity : Entity
        the entity to be changed

    value : int or float or bool or str or Entity or list or dict or Value
        the new value for ``entity``

    auth : Authorization
        an object that authorizes inserting a new value

    attribute : Attribute, optional
        the attribute of ``entity`` which is given an additional value. The
        default is ``None``: insert a value on the entity itself rather than
        one of its attributes.

    instance : int, optional
        the attribute instance of ``entity`` to be changed. The default is 
        ``None``: change the last attribute instance.  

    index : int, optional
        the position on the list of values to insert the new value. For example,
        if ``index`` is 2, the new value becomes the second value on the list
        and the value that was formerly second is now third, the value that
        was formerly third is now fourth, and so on. The default is ``None``:
        insert the new value at the end of the list of existing values.

    Returns
    -------
    None

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``auth`` is not a valid  authorization, or ``attribute`` 
        is not an attribute, or an instance is specified but no attribute, 
        there is no such instance.

    See also
    --------
    :func:`get_value` : return the value of an attribute of an entity

    :func:`set_value` : change the value of an attribute of an entity

    :func:`clear_value` : clear the value of an attribute or of the entity

    :func:`remove_value` : remove a single value from an attribute or from the entity

    :func:`replace_value` : replace a value from an attribute of from the entity with another value

    :func:`erase_value` : erase values from an entity

    :func:`find_value` : find the index or a known value

    :func:`retrieve_value` : retrieve multiple values, in :ref:`comprehensive format <comprehensive_format>`

    :func:`value_count`: return the number of values on an attribute instance

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize()

    Create an entity, with values and attributes.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jacks_details = {
    ...     "Attributes":{ 
    ...         "LOCATION_ATTRIBUTE":[{"Values":[
    ...             {'UTF-8': "Los Angeles"}, 
    ...             {'UTF-8': "Aspen"},
    ...             {'UTF-8': "Malibu"}]}],
    ...         "CHILD_ATTRIBUTE":[
    ...             {"Values": [{"UTF-8": "Jennifer"}]},
    ...             {"Values": [{"UTF-8": "Caleb"}]},
    ...             {"Values": [{'UTF-8': "Honey"}]},
    ...             {"Values": [{"UTF-8": "Lorraine"}]},
    ...             {"Values": [{"UTF-8": "Raymond"}] 
    ...             }]}, 
    ...     "Values": [{'UTF-8': 'actor'}, {'UTF-8': 'player'}, {'UTF-8': 'filmmaker'}]
    ... }
    >>> av.store_entity(jack, jacks_details, auth)

    Get Jack's values.

    >>> av.retrieve_value(jack)
    {'Values': [
        {'UTF-8': 'actor'}, 
        {'UTF-8': 'player'}, 
        {'UTF-8': 'filmmaker'}
        ]}

    Insert a new value on the end of the list.

    >>> av.insert_value(jack, 'screenwriter', auth )
    >>> av.retrieve_value(jack)
    {'Values': [
        {'UTF-8': 'actor'}, 
        {'UTF-8': 'player'}, 
        {'UTF-8': 'filmmaker'}, 
        {'UTF-8': 'screenwriter'}
        ]}

    Insert a new value at the second position of the list.

    >>> av.insert_value(jack, 'basketball fan', auth, index=2)
    >>> av.retrieve_value(jack)
    {'Values': [
        {'UTF-8': 'actor'}, 
        {'UTF-8': 'basketball fan'}, 
        {'UTF-8': 'player'}, 
        {'UTF-8': 'filmmaker'}, 
        {'UTF-8': 'screenwriter'}
        ]}

    Get Jack's locations.

    >>> av.retrieve_attribute(jack, attribute=av.Attribute.LOCATION)
    {'Attributes': {'LOCATION_ATTRIBUTE': [{'Values': [
        {'UTF-8': 'Los Angeles'}, 
        {'UTF-8': 'Aspen'}, 
        {'UTF-8': 'Malibu'}
        ]}]}}

    Insert a new location at the end of the list.

    >>> av.insert_value(jack, 'Beverly Hills', auth, attribute=av.Attribute.LOCATION)
    >>> av.retrieve_attribute(jack, attribute=av.Attribute.LOCATION)
    {'Attributes': {'LOCATION_ATTRIBUTE': [{'Values': [
        {'UTF-8': 'Los Angeles'}, 
        {'UTF-8': 'Aspen'}, 
        {'UTF-8': 'Malibu'}, 
        {'UTF-8': 'Beverly Hills'}
        ]}]}}

    Get Jack's children.

    >>> av.retrieve_attribute(jack, attribute=av.Attribute.CHILD)
    {'Attributes': {'CHILD_ATTRIBUTE': [
        {'Values': [{'UTF-8': 'Jennifer'}]}, 
        {'Values': [{'UTF-8': 'Caleb'}]}, 
        {'Values': [{'UTF-8': 'Honey'}]}, 
        {'Values': [{'UTF-8': 'Lorraine'}]}, 
        {'Values': [{'UTF-8': 'Raymond'}]}
        ]}}

    Add a nickname to his third child.

    >>> av.insert_value(jack, 'Honning', auth, attribute=av.Attribute.CHILD, instance=3, index=1)
    >>> av.retrieve_attribute(jack, attribute=av.Attribute.CHILD)
    {'Attributes': {'CHILD_ATTRIBUTE': [
        {'Values': [{'UTF-8': 'Jennifer'}]}, 
        {'Values': [{'UTF-8': 'Caleb'}]}, 
        {'Values': [{'UTF-8': 'Honning'}, {'UTF-8': 'Honey'}]}, 
        {'Values': [{'UTF-8': 'Lorraine'}]}, 
        {'Values': [{'UTF-8': 'Raymond'}]}
        ]}}

    Clean up.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()  
    """ 
    invoke(
        entity, Method.INSERT, parameter=Argument.VALUE, value=value, 
        attribute=attribute, instance=instance, index=index, authorization=auth)

@manage_exceptions(
    'while removing value from {0}', check_for_naked_instance=True)
def remove_value(entity, auth, *, attribute=None, instance=None, index=None):   
    """
    remove_value(entity, auth, *, attribute=None, instance=None, index=None)
    Remove a value from an entity.

    Remove a value, either from an attribute of the entity, or from the entity
    itself. 

    When ``attribute`` is not provided, a value is removed from the entity
    rather than from an attribute of the entity. If ``index`` is also not
    provided, the last value of the entity is removed. If ``index`` is 
    provided, it specifies which value to remove. For example, an index
    of 2 indicates that the second value is removed, the previous third value
    becomes the second value, the previous fourth value becomes the third,
    and so on.

    When ``attribute`` is provided, a value is removed from that attribute,
    either from a particular position if ``index`` is also provided, or the
    last value if ``index`` is not provided.

    Sometimes an attribute of an entity has more than one instance. In that 
    situation :func:`remove_value` removes a value from the last instance,
    as long as ``instance`` is not specified. If ``instance`` is provided, it
    indicates which attribute instance is to have a value removed. For 
    example, if ``instance`` is 12, a value is removed from the twelth 
    instance.

    See examples below.

    Parameters
    ----------
    entity : Entity
        the entity to be changed

    auth : Authorization
        an object that authorizes removing a value

    attribute : Attribute, optional
        the attribute of ``entity`` from which a value is removed. The
        default is ``None``: remove a value from the entity itself rather 
        than from one of its attributes.

    instance : int, optional
        the attribute instance of ``entity`` to be changed. The default is 
        ``None``: remove a value from the last attribute instance.  

    index : int, optional
        the position on the list of values that is removed. For example,
        if ``index`` is 3, the third value is removed, and the value that was
        formerly fourth becomes third, the formerly fifth becomes fourth, and
        so on. The default is ``None``: remove the last value.

    Returns
    -------
    None

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``auth`` is not a valid  authorization, or ``attribute`` 
        is not an attribute, or an instance is specified but no attribute, or 
        there is no such instance.

    See also
    --------
    :func:`get_value` : return the value of an attribute of an entity

    :func:`set_value` : change the value of an attribute of an entity

    :func:`clear_value` : clear the value of an attribute or of the entity

    :func:`insert_value` : insert an additional value on the entity or an attribute 

    :func:`replace_value` : replace a value from an attribute of from the entity with another value

    :func:`erase_value` : erase values from an entity

    :func:`find_value` : find the index or a known value

    :func:`retrieve_value` : retrieve multiple values, in :ref:`comprehensive format <comprehensive_format>`

    :func:`value_count`: return the number of values on an attribute instance

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize() 

    Create an entity, with values and attributes.

    >>> jack = av.create_entity(
    ...     'Jack Nicholson', av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jacks_details = {
    ...     'Attributes':{ 
    ...         'LOCATION_ATTRIBUTE':[{'Values':[
    ...             {'UTF-8': 'Los Angeles'}, 
    ...             {'UTF-8': 'Aspen'},
    ...             {'UTF-8': 'Malibu'}]}],
    ...         'CHILD_ATTRIBUTE':[
    ...             {'Values': [{'UTF-8': 'Jennifer'}]},
    ...             {'Values': [{'UTF-8': 'Caleb'}]},
    ...             {'Values': [{'UTF-8': 'Honey'}, {'UTF-8': 'Honning'}]},
    ...             {'Values': [{'UTF-8': 'Lorraine'}]},
    ...             {'Values': [{'UTF-8': 'Raymond'}]},
    ...             {'Values': [{'UTF-8': 'Elmer'}]}
    ...             ]}, 
    ...     'Values': [
    ...         {'UTF-8': 'actor'}, 
    ...         {'UTF-8': 'player'}, 
    ...         {'UTF-8': 'filmmaker'},
    ...         {'UTF-8': 'screenwriter'}
    ...     ]
    ... }
    >>> av.store_entity(jack, jacks_details, auth)

    Get Jack's values.

    >>> av.retrieve_value(jack)
    {'Values': [
        {'UTF-8': 'actor'}, 
        {'UTF-8': 'player'}, 
        {'UTF-8': 'filmmaker'}, 
        {'UTF-8': 'screenwriter'}
        ]}

    Remove the last value.

    >>> av.remove_value(jack, auth)
    >>> av.retrieve_value(jack)
    {'Values': [
        {'UTF-8': 'actor'}, 
        {'UTF-8': 'player'}, 
        {'UTF-8': 'filmmaker'}
        ]}

    Remove the second value.

    >>> av.remove_value(jack, auth, index=2)
    >>> av.retrieve_value(jack)
    {'Values': [
        {'UTF-8': 'actor'}, 
        {'UTF-8': 'filmmaker'}
        ]}

    Get Jack's locations.

    >>> av.retrieve_attribute(jack, attribute=av.Attribute.LOCATION)
    {'Attributes': {'LOCATION_ATTRIBUTE': [{'Values': [
        {'UTF-8': 'Los Angeles'}, 
        {'UTF-8': 'Aspen'}, 
        {'UTF-8': 'Malibu'}
        ]}]}}

    Remove the last location.

    >>> av.remove_value(jack, auth, attribute=av.Attribute.LOCATION)
    >>> av.retrieve_attribute(jack, attribute=av.Attribute.LOCATION)
    {'Attributes': {'LOCATION_ATTRIBUTE': [{'Values': [
        {'UTF-8': 'Los Angeles'}, 
        {'UTF-8': 'Aspen'}
        ]}]}}

    Remove the first location.

    >>> av.remove_value(jack, auth, attribute=av.Attribute.LOCATION, index=1)
    >>> av.retrieve_attribute(jack, attribute=av.Attribute.LOCATION)
    {'Attributes': {'LOCATION_ATTRIBUTE': [{'Values': [{'UTF-8': 'Aspen'}]}]}}

    Get Jack's children. Note the fictional sixth child, Elmer. Note also
    the third child has two values: her name and her Danish nickname.

    >>> av.retrieve_attribute(jack, attribute=av.Attribute.CHILD)
    {'Attributes': {'CHILD_ATTRIBUTE': [
        {'Values': [{'UTF-8': 'Jennifer'}]}, 
        {'Values': [{'UTF-8': 'Caleb'}]}, 
        {'Values': [{'UTF-8': 'Honey'}, {'UTF-8': 'Honning'}]}, 
        {'Values': [{'UTF-8': 'Lorraine'}]}, 
        {'Values': [{'UTF-8': 'Raymond'}]}, 
        {'Values': [{'UTF-8': 'Elmer'}]}
        ]}}

    Remove a value from the last child instance. Since there is only a single
    value on that instance, removing the value removes the instance entirely.

    >>> av.remove_value(jack, auth, attribute=av.Attribute.CHILD)
    >>> av.retrieve_attribute(jack, attribute=av.Attribute.CHILD)
    {'Attributes': {'CHILD_ATTRIBUTE': [
        {'Values': [{'UTF-8': 'Jennifer'}]}, 
        {'Values': [{'UTF-8': 'Caleb'}]}, 
        {'Values': [{'UTF-8': 'Honey'}, {'UTF-8': 'Honning'}]}, 
        {'Values': [{'UTF-8': 'Lorraine'}]}, 
        {'Values': [{'UTF-8': 'Raymond'}]}
        ]}}

    Remove a value from the third child instance. The instance remains as she 
    still has another value.

    >>> av.remove_value(jack, auth, attribute=av.Attribute.CHILD, instance=3)
    >>> av.retrieve_attribute(jack, attribute=av.Attribute.CHILD)
    {'Attributes': {'CHILD_ATTRIBUTE': [
        {'Values': [{'UTF-8': 'Jennifer'}]}, 
        {'Values': [{'UTF-8': 'Caleb'}]}, 
        {'Values': [{'UTF-8': 'Honey'}]}, 
        {'Values': [{'UTF-8': 'Lorraine'}]}, 
        {'Values': [{'UTF-8': 'Raymond'}]}
        ]}}

    Clean up.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """  
    invoke(
        entity, Method.REMOVE, parameter=Argument.VALUE,  
        attribute=attribute, instance=instance, index=index, authorization=auth)

@manage_exceptions(
    'while replacing value on {0} with {1}', check_for_naked_instance=True)
def replace_value(entity, value, auth, *, attribute=None, instance=None, 
                  index=None):
    """
    replace_value(entity, value, auth, *, attribute=None, instance=None, index=None)
    Replace the value of an attribute, or the value of an entity itself.

    In its simplest form, :func:`replace_value` is called with no ``attribute``,
    ``instance``, or ``index``. The result of the call is that the current
    value of the entity is replaced with ``value``. If ``entity`` has multiple
    values, the last one is replaced. If ``entity`` has no values, 
    :func:`replace_value` raises an exception.

    By specifying an ``index``, a particular value can be replaced, instead of
    the last one. For example, calling :func:`replace_value` with an ``index`` 
    of 2 will replace the second value, leaving other values undisturbed. If the
    entity has only a single value---or no values at all---an exception is
    raised.

    If ``attribute`` is specified, the value of that attribute is replaced,
    instead of an entity value. As with entity values, a particular attribute
    value can be replaced by specifying ``index``. If no index is specified,
    the last value of the attribute is replaced.

    Sometimes an attribute will have multiple instances. If ``instance`` is
    not specified, the last instance of the attribute will get a new value. Or
    an ``instance`` can be specified, identifying the attribute instance to
    be changed.

    Parameters
    ----------
    entity : Entity
        the entity whose value is to be replaced

    value : int or float or bool or str or Entity or list or dict
        the new value, to replace some existing value on the entity

    auth : Authorization
        an object that authorizes replacing a value on ``entity``

    attribute : Attribute, optional
        the attribute of ``entity`` whose value is replaced. The default is 
        ``None``: replace a value on the entity itself, rather than on some
        attribute of the entity

    instance : int, optional
        the attribute instance of ``entity`` whose value is replaced.
        The default is ``None``: replace a value on the last attribute instance

    index : int, optional
        the position of the value to be replaced.
        The default is None: replace the last value

    Returns
    -------
    None

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``auth`` does not authorize replacing a value, or there is
        no value to replace, or ``index`` is greater than the number of values,
        or the entity does not have that ``attribute``, or an instance is 
        specified but no attribute

    See also
    --------
    :func:`get_value` : return the value of an attribute of an entity

    :func:`set_value` : change the value of an attribute of an entity

    :func:`clear_value` : clear the value of an attribute or of the entity

    :func:`insert_value` : insert an additional value on the entity or an attribute

    :func:`remove_value` : remove a single value from an attribute or from the entity

    :func:`erase_value` : erase values from an entity

    :func:`find_value` : find the index or a known value

    :func:`retrieve_value` : retrieve multiple values, in :ref:`comprehensive format <comprehensive_format>`

    :func:`value_count`: return the number of values on an attribute instance

    :func:`create_entity` : create an entity 

    :func:`store_entity` : set attributes, properties, and values of an entity

    Examples
    --------
    >>> import avesterra.avial as av
    >>> auth = av.initialize()

    Create an entity for Jack Nicholson.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)

    Set some entity values and attribute values on Jack.

    >>> jacks_details = {
    ...     "Attributes":{ 
    ...         "LOCATION_ATTRIBUTE":[{"Values":[
    ...             {'UTF-8': "Los Angeles"}, 
    ...             {'UTF-8': "Aspen"},
    ...             {'UTF-8': "Malibu"}]}],
    ...         "CHILD_ATTRIBUTE":[
    ...             {"Values": [{'UTF-8': "Jennifer"}]},
    ...             {"Values": [{'UTF-8': "Caleb"}]},
    ...             {"Values": [{'UTF-8': "Honey"}]},
    ...             {"Values": [{'UTF-8': "Lorraine"}]},
    ...             {"Values": [{'UTF-8': "Raymond"}]}]}, 
    ...     "Values": [{'UTF-8': 'actor'}, {'UTF-8': 'player'}, {'UTF-8': 'filmmaker'}]
    ... }
    >>> av.store_entity(jack, jacks_details, auth)

    Find Jack's last entity value.

    >>> av.get_value(jack)
    'filmmaker'

    Examine all of Jack's entity values.

    >>> av.retrieve_value(jack)
    {'Values': [{'UTF-8': 'actor'}, {'UTF-8': 'player'}, {'UTF-8': 'filmmaker'}]}

    Replace the last of Jack's entity values with a new one.

    >>> av.replace_value(jack, 'screenwriter', auth)

    Look at Jack's new last value.

    >>> av.get_value(jack)
    'screenwriter'

    Look at all of Jack's entity values.

    >>> av.retrieve_value(jack)
    {'Values': [
        {'UTF-8': 'actor'}, {'UTF-8': 'player'}, {'UTF-8': 'screenwriter'}]}  

    Replace the first of Jack's entity values and examine the result.

    >>> av.replace_value(jack, 'leading man', auth, index=1) 
    >>> av.retrieve_value(jack)
    {'Values': [{'UTF-8': 'leading man'}, {'UTF-8': 'player'}, {'UTF-8': 'screenwriter'}]}

    Look at Jack's values for the location attribute.

    >>> av.retrieve_value(jack, attribute=av.Attribute.LOCATION)
    {'Attributes': {'LOCATION_ATTRIBUTE': [
        {'Values': [
            {'UTF-8': 'Los Angeles'}, 
            {'UTF-8': 'Aspen'}, 
            {'UTF-8': 'Malibu'}]}]}}

    Replace the last location and examine the result.

    >>> av.replace_value(jack, 'Kailua', auth, attribute=av.Attribute.LOCATION)
    >>> av.retrieve_value(jack, attribute=av.Attribute.LOCATION)
    {'Attributes': {'LOCATION_ATTRIBUTE': [
        {'Values': [
            {'UTF-8': 'Los Angeles'}, 
            {'UTF-8': 'Aspen'}, 
            {'UTF-8': 'Kailua'}]}]}}

    Examine the value for the third instance of Jack's child attribute, his
    third child.

    >>> av.retrieve_value(jack, attribute=av.Attribute.CHILD, instance=3)
    {'Attributes': {'CHILD_ATTRIBUTE': [{'Values': [{'UTF-8': 'Honey'}]}]}}

    Replace the value of the third instance of Jack's children. Examine the 
    result.

    >>> av.replace_value(jack, 'Honning', auth, attribute=av.Attribute.CHILD, instance=3)
    >>> av.retrieve_value(jack, attribute=av.Attribute.CHILD, instance=3)
    {'Attributes': {'CHILD_ATTRIBUTE': [{'Values': [{'UTF-8': 'Honning'}]}]}}

    Clean up
    
    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """
    invoke(
        entity, Method.REPLACE, parameter=Argument.VALUE, value=value,
        attribute=attribute, instance=instance, index=index, authorization=auth)

@manage_exceptions('while erasing value of {0}', check_for_naked_instance=True)
def erase_value(entity, auth, *, attribute=None, instance=None):
    """
    erase_value(entity, auth, *, attribute=None, instance=None)
    Erase a value of an attribute, or all the values from the entity itself.

    The most typical and simplest situation is an attribute on an entity that
    has a single instance, with no attribute properties. In that situation, 
    :func:`erase_value` erases that attribute from the entity entirely.
    
    Sometimes an attribute of an entity has more than one instance. In that
    situation, :func:`erase_value` erases the last instance, as long as 
    ``instance`` is not provided. If ``instance`` is provided, it specifies
    the numeric index of the attribute instance to be erased. For example, if
    ``instance`` is 2, the second attribute instance is erased.

    Sometimes an attribute instance has multiple values. In that situation, 
    :func:`erase_value` erases all the values of the instance.

    Sometimes an attribute instance has both a value (or multiple values) and 
    properties. In that situation, :func:`erase_value` erases the values of the
    instance, but leaves the properties as they were.

    Erasing an attribute value will remove an attribute from an entity 
    entirely if there is only a single attribute instance, and if there are no 
    properties of that attribute instance.

    Similarly, erasing an attribute value will remove an attribute instance
    from the entity if the attribute instance contains no properties.

    When ``attribute`` is not provided, all the entity values are erased.  

    When ``attribute`` is not provided, ``instance`` cannot be provided 
    either; unlike its attributes, an entity has only a single instance.

    Parameters
    ----------
    entity : Entity
        the entity whose values are to be erased

    auth : Authorization
        an object that authorizes erasing values from ``entity``

    attribute : Attribute, optional
        the attribute of ``entity`` whose value is erased. The default is 
        ``None``: erase all the entity values instead of an attribute value.

    instance : int, optional
        the attribute instance of ``entity`` whose value is to be erased.
        The default is ``None``: erase a value from the last attribute instance.

    Returns
    -------
    None

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``auth`` is not a valid  authorization, or ``attribute`` 
        is not an attribute, or an instance is specified but no attribute.

    See also
    --------
    :func:`get_value` : return the value of an attribute of an entity

    :func:`set_value` : change the value of an attribute of an entity

    :func:`retrieve_value` : retrieve multiple values, in :ref:`comprehensive format <comprehensive_format>`

    :func:`clear_value` : clear the value of an attribute or of the entity

    :func:`insert_value` : insert an additional value on the entity or an attribute

    :func:`remove_value` : remove a single value from an attribute or from the entity

    :func:`replace_value` : replace a value from an attribute of from the entity with another value

    :func:`find_value` : find the index or a known value 

    :func:`value_count`: return the number of values on an attribute instance

    :func:`create_entity` : create an entity 

    :func:`store_entity` : set attributes, properties, and values of an entity 

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize()
    >>> import pprint
    >>> pp = pprint.PrettyPrinter(indent=4)

    Create an entity for Jack, with values and attributes.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jacks_details = {
    ...     "Attributes":{ 
    ...         "HEIGHT_ATTRIBUTE":[{"Values":["177"]}], 
    ...         "LOCATION_ATTRIBUTE":[{"Values":["Los Angeles", "Aspen"]}],
    ...         "CHILD_ATTRIBUTE":[
    ...             {
    ...                 "Values": ["Jennifer"],
    ...                 "Properties": [ 
    ...                     ["Born","","1963"],
    ...                     ["Mother","","Sandra Knight"] 
    ...                 ]
    ...             },
    ...             {
    ...                 "Values": ["Caleb"],
    ...                 "Properties": [ 
    ...                     ["Born","","1970"],
    ...                     ["Mother","","Susan Anspach"],
    ...                     ["Paternity", "Paternity", "not established"]
    ...                 ]
    ...             },
    ...             {"Values": ["Honey"]},
    ...             {"Values": ["Lorraine"]},
    ...             {"Values": ["Raymond", "Ray"]}, 
    ...         ]}, 
    ...     "Values": ["actor", "filmmaker"]
    ... }
    >>> av.store_entity(jack, jacks_details, auth)
    >>> pp.pprint(av.retrieve_entity(jack))
    {   'Attributes': {   'CHILD_ATTRIBUTE': [   {   'Properties': [   [   'Born',
                                                                           '',
                                                                           '1963'],
                                                                       [   'Mother',
                                                                           '',
                                                                           'Sandra '
                                                                           'Knight']],
                                                     'Values': ['Jennifer']},
                                                 {   'Properties': [   [   'Born',
                                                                           '',
                                                                           '1970'],
                                                                       [   'Mother',
                                                                           '',
                                                                           'Susan '
                                                                           'Anspach'],
                                                                       [   'Paternity',
                                                                           'Paternity',
                                                                           'not '
                                                                           'established']],
                                                     'Values': ['Caleb']},
                                                 {'Values': ['Honey']},
                                                 {'Values': ['Lorraine']},
                                                 {'Values': ['Raymond', 'Ray']}],
                          'HEIGHT_ATTRIBUTE': [{'Values': ['177']}],
                          'LOCATION_ATTRIBUTE': [   {   'Values': [   'Los Angeles',
                                                                      'Aspen']}]},
        'Values': ['actor', 'filmmaker']}

    Erase the values for Jack. Note that both entity values are erased, both
    actor and filmmaker.

    >>> av.erase_value(jack, auth)
    >>> pp.pprint(av.retrieve_entity(jack))
    {   'Attributes': {   'CHILD_ATTRIBUTE': [   {   'Properties': [   [   'Born',
                                                                           '',
                                                                           '1963'],
                                                                       [   'Mother',
                                                                           '',
                                                                           'Sandra '
                                                                           'Knight']],
                                                     'Values': ['Jennifer']},
                                                 {   'Properties': [   [   'Born',
                                                                           '',
                                                                           '1970'],
                                                                       [   'Mother',
                                                                           '',
                                                                           'Susan '
                                                                           'Anspach'],
                                                                       [   'Paternity',
                                                                           'Paternity',
                                                                           'not '
                                                                           'established']],
                                                     'Values': ['Caleb']},
                                                 {'Values': ['Honey']},
                                                 {'Values': ['Lorraine']},
                                                 {'Values': ['Raymond', 'Ray']}],
                          'HEIGHT_ATTRIBUTE': [{'Values': ['177']}],
                          'LOCATION_ATTRIBUTE': [   {   'Values': [   'Los Angeles',
                                                                      'Aspen']}]}}

    Since Jack only has attributes now, simplify the display by showing only
    attributes.

    >>> pp.pprint(av.retrieve_entity(jack)['Attributes'])
    {   'CHILD_ATTRIBUTE': [   {   'Properties': [   ['Born', '', '1963'],
                                                     [   'Mother',
                                                         '',
                                                         'Sandra Knight']],
                                   'Values': ['Jennifer']},
                               {   'Properties': [   ['Born', '', '1970'],
                                                     [   'Mother',
                                                         '',
                                                         'Susan Anspach'],
                                                     [   'Paternity',
                                                         'Paternity',
                                                         'not established']],
                                   'Values': ['Caleb']},
                               {'Values': ['Honey']},
                               {'Values': ['Lorraine']},
                               {'Values': ['Raymond', 'Ray']}],
        'HEIGHT_ATTRIBUTE': [{'Values': ['177']}],
        'LOCATION_ATTRIBUTE': [{'Values': ['Los Angeles', 'Aspen']}]}

    Erase Jack's height.

    >>> av.erase_value(jack, auth, attribute=av.Attribute.HEIGHT)
    >>> pp.pprint(av.retrieve_entity(jack)['Attributes'])
    {   'CHILD_ATTRIBUTE': [   {   'Properties': [   ['Born', '', '1963'],
                                                     [   'Mother',
                                                         '',
                                                         'Sandra Knight']],
                                   'Values': ['Jennifer']},
                               {   'Properties': [   ['Born', '', '1970'],
                                                     [   'Mother',
                                                         '',
                                                         'Susan Anspach'],
                                                     [   'Paternity',
                                                         'Paternity',
                                                         'not established']],
                                   'Values': ['Caleb']},
                               {'Values': ['Honey']},
                               {'Values': ['Lorraine']},
                               {'Values': ['Raymond', 'Ray']}],
        'LOCATION_ATTRIBUTE': [{'Values': ['Los Angeles', 'Aspen']}]}

    Erase Jack's location. Note that both locations are erased, since both 
    values are part of the same attribute instance.

    >>> av.erase_value(jack, auth, attribute=av.Attribute.LOCATION)
    >>> pp.pprint(av.retrieve_entity(jack)['Attributes'])
    {   'CHILD_ATTRIBUTE': [   {   'Properties': [   ['Born', '', '1963'],
                                                     [   'Mother',
                                                         '',
                                                         'Sandra Knight']],
                                   'Values': ['Jennifer']},
                               {   'Properties': [   ['Born', '', '1970'],
                                                     [   'Mother',
                                                         '',
                                                         'Susan Anspach'],
                                                     [   'Paternity',
                                                         'Paternity',
                                                         'not established']],
                                   'Values': ['Caleb']},
                               {'Values': ['Honey']},
                               {'Values': ['Lorraine']},
                               {'Values': ['Raymond', 'Ray']}]}

    Jack has only child attributes, so we can further simplify the display.

    >>> pp.pprint(av.retrieve_entity(jack)['Attributes']['CHILD_ATTRIBUTE'])
    [   {   'Properties': [['Born', '', '1963'], ['Mother', '', 'Sandra Knight']],
            'Values': ['Jennifer']},
        {   'Properties': [   ['Born', '', '1970'],
                              ['Mother', '', 'Susan Anspach'],
                              ['Paternity', 'Paternity', 'not established']],
            'Values': ['Caleb']},
        {'Values': ['Honey']},
        {'Values': ['Lorraine']},
        {'Values': ['Raymond', 'Ray']}]

    Erase Jack's child attribute. The last instance of CHILD is erased.

    >>> av.erase_value(jack, auth, attribute=av.Attribute.CHILD)
    >>> pp.pprint(av.retrieve_entity(jack)['Attributes']['CHILD_ATTRIBUTE'])
    [   {   'Properties': [['Born', '', '1963'], ['Mother', '', 'Sandra Knight']],
            'Values': ['Jennifer']},
        {   'Properties': [   ['Born', '', '1970'],
                              ['Mother', '', 'Susan Anspach'],
                              ['Paternity', 'Paternity', 'not established']],
            'Values': ['Caleb']},
        {'Values': ['Honey']},
        {'Values': ['Lorraine']}]

    Erase Jack's third child.

    >>> av.erase_value(jack, auth, attribute=av.Attribute.CHILD, instance=3)
    >>> pp.pprint(av.retrieve_entity(jack)['Attributes']['CHILD_ATTRIBUTE'])
    [   {   'Properties': [['Born', '', '1963'], ['Mother', '', 'Sandra Knight']],
            'Values': ['Jennifer']},
        {   'Properties': [   ['Born', '', '1970'],
                              ['Mother', '', 'Susan Anspach'],
                              ['Paternity', 'Paternity', 'not established']],
            'Values': ['Caleb']},
        {'Values': ['Lorraine']}]

    Erase Jack's first child. Note that the value of the child instance is
    erased, but because the instance also has properties, the instance remains.

    >>> av.erase_value(jack, auth, attribute=av.Attribute.CHILD, instance=1)
    >>> pp.pprint(av.retrieve_entity(jack)['Attributes']['CHILD_ATTRIBUTE'])
    [   {'Properties': [['Born', '', '1963'], ['Mother', '', 'Sandra Knight']]},
        {   'Properties': [   ['Born', '', '1970'],
                              ['Mother', '', 'Susan Anspach'],
                              ['Paternity', 'Paternity', 'not established']],
            'Values': ['Caleb']},
        {'Values': ['Lorraine']}]

    Clean up.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """ 
    invoke(
        entity, Method.ERASE, parameter=Argument.VALUE, attribute=attribute, 
        instance=instance, authorization=auth)

@manage_exceptions(
    'while finding value {1} on {0}', check_for_naked_instance=True)
def find_value(entity, value, *, attribute=None, instance=None, index=None): 
    """
    find_value(entity, value, *, attribute=None, instance=None, index=None)
    Returns the index corresponding to a particular value.

    In its simplest form, :func:`find_value` is called with no ``attribute``,
    ``instance``, or ``index``, and returns the index of ``value`` among
    the entity values. For example, if ``value`` is the float 173.4 and 
    the values of an entity are 29.1, 173.4, and 173.4, :func:`find_value`
    will return 2, as 173.4 is the second value. Note that 173.4 is also
    the third value, but :func:`find_value` finds the index of the first 
    occurence of the value. If ``value`` does not appear 
    among the entity values, :func:`find_value` raises an exception.

    If ``attribute`` is specified, :func:`find_value` looks for ``value``
    among the values of ``attribute``, rather than looking among entity values.

    Some attributes have multiple instances. If ``instance`` is specified,
    :func:`find_value` will look on a particular instance of ``attribute``
    rather than on the last instance. For example is ``instance`` is 3,
    :func:`find_value` will look for ``value`` among the values on the third
    instance of the attribute.

    If ``index`` is specified, :func:`find_value` does not start its search
    with the first value, but instead starts with the indexed value. 

    Parameters
    ----------
    entity : Entity
        the entity whose values are searched

    value : int or float or bool or str or Entity or list or dict
        the value whose index is to be found

    attribute : Attribute, optional
        the attribute of ``entity`` whose values are searched. 
        The default is ``None``: look among the entity values, rather than 
        attribute values.

    instance : int, optional
        the attribute instance of ``entity`` whose values are searched.
        The default is ``None``: search on the last attribute instance.

    index : int, optional
        where to start the search for the value. The default is ``None``: start
        with the first value

    Returns
    -------
    int
        the index position of ``value``

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``value`` does not appear among the values,  
        or the entity does not have that ``attribute``, or an instance is 
        specified but no attribute.

    See also
    --------
    :func:`get_value` : return the value of an attribute of an entity
    
    :func:`set_value` : change the value of an attribute of an entity

    :func:`clear_value` : clear the value of an attribute or of the entity

    :func:`insert_value` : insert an additional value on the entity or an attribute

    :func:`remove_value` : remove a single value from an attribute or from the entity

    :func:`erase_value` : erase values from an entity

    :func:`retrieve_value` : retrieve multiple values, in :ref:`comprehensive format <comprehensive_format>`

    :func:`value_count`: return the number of values on an attribute instance

    :func:`create_entity` : create an entity 

    :func:`store_entity` : set attributes, properties, and values of an entity

    Examples
    --------
    >>> import avesterra.avial as av
    >>> auth = av.initialize()

    Create an entity for Jack Nicholson. Store some entity values and attribute
    values on Jack.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jacks_details = {
    ...     "Attributes":{ 
    ...         "LOCATION_ATTRIBUTE":[{"Values":[
    ...             {'UTF-8': "Los Angeles"}, 
    ...             {'UTF-8': "Aspen"},
    ...             {'UTF-8': "Malibu"}]}],
    ...         "CHILD_ATTRIBUTE":[
    ...             {"Values": [{'UTF-8': "Jennifer"}]},
    ...             {"Values": [{'UTF-8': "Caleb"}]},
    ...             {"Values": [{'UTF-8': "Honey"}, {'UTF-8': "Honning"}]},
    ...             {"Values": [{'UTF-8': "Lorraine"}]},
    ...             {"Values": [{'UTF-8': "Raymond"}]}]}, 
    ...     "Values": [{'UTF-8': 'actor'}, {'UTF-8': 'player'}, {'UTF-8': 'filmmaker'}]
    ... }
    >>> av.store_entity(jack, jacks_details, auth)

    Find the index of the entity value "actor".

    >>> av.find_value(jack, 'actor')
    1

    Find the index of the entity value "filmmaker".
    
    >>> av.find_value(jack, 'filmmaker')
    3

    Find the index of the entity value "husband". It does not exist, so an
    exception is raised.

    >>> av.find_value(jack, 'husband') 
    avesterra.avial.AvialNotFound: Value not found

    Find the index of 'Aspen' among the location attribute values.

    >>> av.find_value(jack, 'Aspen', attribute=av.Attribute.LOCATION)
    2

    Find the index of 'Raymond' among the child attribute values. Note that
    there are five instances of CHILD. The last one is searched for 'Raymond'.

    >>> av.find_value(jack, 'Raymond', attribute=av.Attribute.CHILD)
    1

    Find the index of 'Honning' among the third instance of the child 
    attribute.

    >>> av.find_value(jack, 'Honning', attribute=av.Attribute.CHILD, instance=3)
    2

    Clean up.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """
    pos = invoke(
        entity, Method.FIND, parameter=Argument.VALUE, value=value,
        attribute=attribute, instance=instance, index=index, 
        return_results=True)
    if pos == 0:
        raise AvialNotFound('Value not found')
    else:
        return pos

@manage_exceptions(
    'while retriving value from {0}', check_for_naked_instance=True)
def retrieve_value(entity, *, attribute=None, instance=None, index=None, 
                   count=None):
    """
    retrieve_value(entity, *, attribute=None, instance=None, index=None, count=None)
    Retrieve values from entity or attribute instance, in comprehensive format.

    Comprehensive format is a json schema
    used for communicating all of the contents of an entity, or some part of the
    contents. See :ref:`comprehensive format <comprehensive_format>` for 
    more detail.

    If no attribute, no index, and no count are specified, :func:`retrieve_value` 
    returns all the entity values. If no attribute is specified, but an index 
    or a count is specified (or both), some subset of the entity values are 
    returned, starting with the ``index`` value and of ``count`` values in 
    total. For example, if ``index`` is 2, ``count`` is 3, and the values of the
    entity are the strings "New York", "Los Angeles", "Chicago", 
    "San Francisco", and "Toronto", then the values "Los Angeles", "Chicago", 
    and "San Francisco" are returned.

    If an attribute is specified, :func:`retrieve_value` returns the values of
    that attribute, rather than entity values. If the attribute has multiple
    values, all are returned, unless ``index`` or ``count`` are specified. 
    When specified with values of an attribute, ``index`` and ``count`` behave 
    just as they do with entity values. For example, if ``attribute`` is
    ``Attribute.LOCATION``, ``index`` is 3, ``count`` is 1, and the locations
    are "New York", "Malibu", "Jackson Hole", and "London", then only a single
    value is returned: "Jackson Hole", in comprehensive format.

    Sometimes an attribute of an entity has multiple instances.
    If an attribute is specified
    and no instance is specified, values of the last instance of that attribute
    are returned. If both an attribute and an instance are specified, 
    ``instance`` indicates the numeric index of the instance to be returned.
    For example, if ``instance`` is 3, the third attribute instance is returned.

    See examples below.

    Parameters
    ----------
    entity : Entity
        the entity whose values are returned, in comprehensive format

    attribute : Attribute, optional
        the attribute of ``entity`` whose values are returned. The default is
        ``None``: return entity values instead of attribute values.

    instance : int, optional
        the attribute instance of ``entity`` whose values are returned. The 
        default is ``None`` (or equivalently: 0): return the values of the last
        attribute instance. If ``instance`` is greater than the number of 
        instances, an :class:`AvialError` exception is raised.

    index : int, optional
        of the multiple values to be returned, where to start? The default is
        ``None``: start with the first value. If ``index`` is greater than the
        number of values, an empty dict is returned.

    count : int , optional
        how many values to return? The default is ``None``: return all the 
        values from ``index`` until the last value. If count is more than 
        the number of values until the last value, return all that exist.

    Returns
    -------
    dict 
        the values in :ref:`comprehensive format <comprehensive_format>`.
        Only values are returned: no labels or properties or other items.

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``attribute`` 
        is not an attribute, or no such attribute is found for the entity, or
        an instance is specified but no attribute, or the instance provided
        is greater than the number of instances, or the index provided is 
        greater than the number of values.

    See also
    --------
    :func:`retrieve_entity` : return all attributes, properties, and values of an entity, in :ref:`comprehensive format <comprehensive_format>`

    :func:`retrieve_attribute` : return attribute values and properties, in :ref:`comprehensive format <comprehensive_format>`

    :func:`retrieve_property` : return entity properties, or attribute properties, in :ref:`comprehensive format <comprehensive_format>`

    :func:`get_value` : return the value of an attribute of an entity

    :func:`set_value` : change the value of an attribute of an entity

    :func:`insert_value` : insert an additional value on the entity or an attribute

    :func:`remove_value` : remove a single value from an attribute or from the entity

    :func:`replace_value` : replace a value from an attribute of from the entity with another value

    :func:`erase_value` : erase values from an entity

    :func:`find_value` : find the index or a known value

    :func:`retrieve_value` : retrieve multiple values, in :ref:`comprehensive format <comprehensive_format>`

    :func:`value_count`: return the number of values on an attribute instance

    :func:`create_entity` : create an entity 

    :func:`store_entity` : set attributes, properties, and values of an entity
    
    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize() 

    Create an entity, with some attributes and values.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jacks_details = {
        "Attributes":{ 
            "HEIGHT_ATTRIBUTE":[{"Values":["177"]}], 
            "LOCATION_ATTRIBUTE":[{"Values":["Los Angeles", "Aspen", "Malibu"]}],
            "CHILD_ATTRIBUTE":[
                {
                    "Values": ["Jennifer"],
                    "Properties": [ 
                        ["Born","","1963"],
                        ["Mother","","Sandra Knight"] 
                    ]
                },
                {
                    "Values": ["Caleb"],
                    "Properties": [ 
                        ["Born","","1970"],
                        ["Mother","","Susan Anspach"],
                        ["Paternity", "Paternity", "not established"]
                    ]
                },
                {"Values": ["Honey", "Honning", 'Honeybear']},
                {"Values": ["Lorraine"]},
                {"Values": ["Raymond", "Ray"]}, 
            ]}, 
        "Values": ["actor", "filmmaker", "player", "bad boy"]
    }
    av.store_entity(jack, jacks_details, auth) 

    Retrieve the values of the jack entity. Note that the values are contained
    within in a larger dict, with the ``Values`` key, as prescribed by 
    the comprehensive format.

    >>> av.retrieve_value(jack)
    {'Values': ['actor', 'filmmaker', 'player', 'bad boy']}

    Retrieve Jack's values, starting with the third one.

    >>> av.retrieve_value(jack, index=3)
    {'Values': ['player', 'bad boy']}

    Retrieve one of Jack's values. Note that the first entity value is returned.

    >>> av.retrieve_value(jack, count=1)
    {'Values': ['actor']}

    Retrieve two of Jack's values, starting with the second one.

    >>> av.retrieve_value(jack, index=2, count=2)
    {'Values': ['filmmaker', 'player']}

    Retrieve the values of Jack's location. Note that the values are contained
    within ``Attributes``, then within ``LOCATION_ATTRIBUTE``, then within
    ``Values``.

    >>> av.retrieve_value(jack, attribute=av.Attribute.LOCATION)
    {'Attributes': {'LOCATION_ATTRIBUTE': [{'Values': ['Los Angeles', 'Aspen', 'Malibu']}]}}

    Retrieve the values of Jack's child. Note that Jack has multiple children.
    The value of his last child is returned.

    >>> av.retrieve_value(jack, attribute=av.Attribute.CHILD)
    {'Attributes': {'CHILD_ATTRIBUTE': [{'Values': ['Raymond', 'Ray']}]}}

    Retrieve the values of Jack's third child.

    >>> av.retrieve_value(jack, attribute=av.Attribute.CHILD, instance=3)
    {'Attributes': {'CHILD_ATTRIBUTE': [{'Values': ['Honey', 'Honning', 'Honeybear']}]}}

    Retrieve the second value of Jack's third child.

    >>> av.retrieve_value(jack, attribute=av.Attribute.CHILD, instance=3, index=2, count=1)
    {'Attributes': {'CHILD_ATTRIBUTE': [{'Values': ['Honning']}]}}

    Clean up.
    
    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """ 
    return _validate_and_simplify(invoke(
        entity, Method.RETRIEVE, parameter=Argument.VALUE, attribute=attribute,
        instance=instance, index=index, count=count, return_results=True))

@manage_exceptions(
    'while counting values on {0}', check_for_naked_instance=True)
def value_count(entity, *, attribute=None, instance=None):
    """
    value_count(entity, *, attribute=None, instance=None)
    Count the number of values on the entity or on an attribute instance.

    Typically :func:`value_count` is used to return the count of values on an
    attribute. If no attribute is provided, the count of value on the
    entity as a whole is returned instead.

    Sometimes an attribute of an entity has more than one instance. In that 
    situation, :func:`value_count` counts the values on the last instance,
    as long as ``instance`` is not provided as an argument. If ``instance``
    is provided, it specifies the numeric index of the attribute instance
    on which to count values. For example, if ``instance`` is provided as
    5, :func:`value_count` counts the values of the fifth instance.

    When ``attribute`` is provided, ``instance`` can also be provided. But when 
    ``attribute`` is ``None`` (i.e. not provided), ``instance`` cannot be
    provided; unlike its attributes, an entity has only a single instance.

    Parameters
    ----------
    entity : Entity
        the entity whose values are counted

    attribute : Attribute, optional
        the attribute of ``entity`` whose values are counted. The default is 
        ``None``: count the values of the entity itself rather than of one of
        its attributes.

    instance : int, optional
        the attribute instance of ``entity`` to be value counted. The default
        is ``None``: count the values of the last attribute instance.

    Returns
    -------
    int
        the number of values

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``attribute`` 
        is not an attribute, or no such attribute is found for the entity, or
        an instance is specified but no attribute, or the instance provided
        is greater than the number of instances.

    See also
    --------
    :func:`get_value` : return the value of an attribute of an entity
    
    :func:`set_value` : change the value of an attribute of an entity

    :func:`clear_value` : clear the value of an attribute or of the entity

    :func:`insert_value` : insert an additional value on the entity or an attribute

    :func:`remove_value` : remove a single value from an attribute or from the entity

    :func:`replace_value` : replace a value from an attribute of from the entity with another value

    :func:`erase_value` : erase values from an entity

    :func:`find_value` : find the index or a known value

    :func:`retrieve_value` : retrieve multiple values, in :ref:`comprehensive format <comprehensive_format>`

    :func:`create_entity` : create an entity 

    :func:`store_entity` : set attributes, properties, and values of an entity

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize()

    Create an entity, with some initial attributes and values.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jacks_details = {
    ...     "Values": ["actor", "player", "director"],
    ...     "Attributes":{
    ...         "LOCATION_ATTRIBUTE":[{"Values":["Los Angeles", "Aspen", "Malibu"]}],
    ...         "CHILD_ATTRIBUTE":[
    ...             {"Values": ["Jennifer"]},
    ...             {
    ...                 "Values": ["Caleb"],
    ...                 "Properties": [ 
    ...                     ["Born","","1970"],
    ...                     ["Mother","","Susan Anspach"],
    ...                     ["Paternity", "Paternity", "not established"]
    ...                 ]
    ...             },
    ...             {"Values": ["Honey"]},
    ...             {"Values": ["Lorraine"]},
    ...             {"Values": ["Raymond"]}
    ...         ]
    ...     }
    ... }
    >>> av.store_entity(jack, jacks_details, auth)

    How many values for Jack's location?

    >>> av.value_count(jack, attribute=av.Attribute.LOCATION)
    3

    How many values of the second CHILD instance?

    >>> av.value_count(jack, attribute=av.Attribute.CHILD, instance=2)
    1

    How many values on the Jack entity itself?

    >>> av.value_count(jack)
    3

    Clean up the example and end the session.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """
    return invoke(
        entity, Method.COUNT, attribute=attribute, instance=instance,
        return_results=True)


################################################################################
#
# Label operations
#

@manage_exceptions(
    'while getting label on entity {0}', check_for_naked_instance=True)
def get_label(entity, *, attribute=None, instance=None):
    """
    get_label(entity, *, attribute=None, instance=None)
    """
    return invoke(
        entity, Method.GET, parameter=Argument.LABEL, attribute=attribute, 
        instance=instance, return_results=True, results_as_string=True)

@manage_exceptions(
    'while setting label on entity {0} to {1}', check_for_naked_instance=True)
def set_label(entity, label, auth, *, attribute=None, instance=None):
    """
    set_label(entity, label, auth, *, attribute=None, instance=None)
    """
    if isinstance(label, (bytes, bytearray)):
        raise AvialError(f'Label {label} must be string, not {type(label)}')
    else:
        invoke(
            entity, Method.SET, parameter=Argument.LABEL, name=label, 
            attribute=attribute, instance=instance, authorization=auth)

@manage_exceptions(
    'while clearing label on entity {0}', check_for_naked_instance=True)
def clear_label(entity, auth, *, attribute=None, instance=None):
    """
    clear_label(entity, auth, *, attribute=None, instance=None)
    """
    invoke(
        entity, Method.CLEAR, parameter=Argument.LABEL, attribute=attribute,
        instance=instance, authorization=auth)

@manage_exceptions('while erasing label on entity {0}')
def erase_label(entity, auth, *, attribute=None):
    """
    erase_label(entity, auth, *, attribute=None)
    """
    invoke(
        entity, Method.ERASE, parameter=Argument.LABEL, attribute=attribute,
        authorization=auth)

@manage_exceptions('while finding label {2} on entity {0}, attribute {1}')
def find_label(entity, attribute, name, *, index=None):
    """
    find_label(entity, attribute, name, *, index=None)
    """
    return invoke(
        entity, Method.FIND, parameter=Argument.LABEL, attribute=attribute,
        name=name, index=index, return_results=True)


################################################################################
#
# Attribute operations
#

@manage_exceptions('while getting attribute {1} of entity {0}')
def get_attribute(entity, attribute): 
    """
    get_attribute(entity, attribute)
    Return the value of an attribute.

    :func:`get_attribute` returns the value of an attribute on an entity. It is 
    intended for a simple, common case: a single attribute instance and a
    single value for that instance. For other, more complex situations,
    :func:`get_value` or :func:`retrieve_attribute` may be more appropriate.

    When there is a single attribute instance and a single value for that 
    instance, :func:`get_attribute`
    returns the sole value. If the attribute has more than one instance,
    the first one is used. If the attribute instance has more than one value,
    the first one is returned.

    :func:`get_attribute` raises an exception if there is no such attribute,
    or the attribute has no values.

    Parameters
    ----------
    entity : Entity
        the entity with the attribute value

    attribute : Attribute 
        the attribute of ``entity`` whose value is to be returned  

    Returns
    -------
    int or float or bool or str or Entity or list or dict
        the value of the attribute

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``attribute`` 
        is not an attribute, or no such attribute is found for the entity 

    See also
    --------
    :func:`get_value` : return the value of an attribute of an entity

    :func:`set_attribute` : set the value of an attribute on an entity

    :func:`clear_attribute` : clear the value of an attribute on an entity

    :func:`erase_attribute` : erase an attribute from an entity

    :func:`find_attribute` : find the position of an attribute on an entity

    :func:`retrieve_attribute` : retrieve everything for a single attribute on an entity

    :func:`attribute_item` : return the attribute at a position on the entity

    :func:`attribute_count` : return count of instances of an attribute, or count of attributes on entity

    Examples
    --------
    >>> import avesterra.avial as av
    >>> auth = av.initialize()

    Create an entity, filling in some attributes.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jacks_details = {
    ...     "Attributes":{ 
    ...         "HEIGHT_ATTRIBUTE":[{"Values":[{"INTEGER": "177"}]}],
    ...         "LOCATION_ATTRIBUTE":[{"Values":[
    ...             {'UTF-8': "Los Angeles"}, 
    ...             {'UTF-8': "Aspen"},
    ...             {'UTF-8': "Malibu"}]}],
    ...         "CHILD_ATTRIBUTE":[
    ...             {"Values": [{'UTF-8': "Jennifer"}]},
    ...             {"Values": [{'UTF-8': "Caleb"}]},
    ...             {"Values": [{'UTF-8': "Honey"}, {'UTF-8': "Honning"}]},
    ...             {"Values": [{'UTF-8': "Lorraine"}]},
    ...             {"Values": [{'UTF-8': "Raymond"}]}]}
    ... }
    >>> av.store_entity(jack, jacks_details, auth)

    Find Jack's height.

    >>> av.get_attribute(jack, av.Attribute.HEIGHT)
    177

    Find Jack's location. There are three values for location;
    the first is returned.

    >>> av.get_attribute(jack, av.Attribute.LOCATION)
    'Los Angeles'

    Find Jack's child. There are three child instances. The value of the first
    is returned.

    >>> av.get_attribute(jack, av.Attribute.CHILD)
    'Jennifer'

    Clean up.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize() 
    """
    return invoke(
        entity, Method.GET, parameter=Argument.ATTRIBUTE, attribute=attribute,
        return_results=True)

@manage_exceptions('while setting attribute {1} of entity {0} to {2}')
def set_attribute(entity, attribute, value, auth): 
    """
    set_attribute(entity, attribute, value, auth)
    Set the value of an entity's attribute.

    :func:`set_attribute` sets the value of an attribute on an entity. It is 
    intended for a simple, common case: keeping a single value on an attribute,
    rather than multiple values or multiple attribute instances. For more
    complex situations, :func:`set_value` is better.

    If there are multiple values on the attribute, :func:`set_attribute` changes
    the first value. If there are multiple attribute instances, 
    :func:`set_attribute` changes the first.

    Parameters
    ----------
    entity : Entity 
        the entity whose attribute is to be set

    attribute : Attribute
        the attribute of ``entity`` to be set

    value : int or float or bool or str or Entity or list or dict
        the new value of ``attribute``

    auth : Authorization
        authorization token permitting the attribute setting

    Returns
    -------
    None

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``attribute`` is not a valid attribute, or ``auth`` does
        not authorize the setting.

    See also
    --------
    :func:`set_value` : change the value of an attribute of an entity

    :func:`get_attribute` : return the value of an attribute on an entity

    :func:`clear_attribute` : clear the value of an attribute on an entity

    :func:`erase_attribute` : erase an attribute from an entity

    :func:`find_attribute` : find the position of an attribute on an entity

    :func:`retrieve_attribute` : retrieve everything for a single attribute on an entity

    :func:`attribute_item` : return the attribute at a position on the entity

    :func:`attribute_count` : return count of instances of an attribute, or count of attributes on entity

    Examples
    --------
    >>> import avesterra.avial as av 
    >>> auth = av.initialize()

    Create an entity and fill it with attribute values.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jacks_details = {
    ...     "Attributes":{ 
    ...         "HEIGHT_ATTRIBUTE":[{"Values":[{"INTEGER": "177"}]}],
    ...         "LOCATION_ATTRIBUTE":[{"Values":[
    ...             {'UTF-8': "Los Angeles"}, 
    ...             {'UTF-8': "Aspen"},
    ...             {'UTF-8': "Malibu"}]}],
    ...         "CHILD_ATTRIBUTE":[
    ...             {"Values": [{'UTF-8': "Jennifer"}]},
    ...             {"Values": [{'UTF-8': "Caleb"}]},
    ...             {"Values": [{'UTF-8': "Honey"}, {'UTF-8': "Honning"}]},
    ...             {"Values": [{'UTF-8': "Lorraine"}]},
    ...             {"Values": [{'UTF-8': "Raymond"}]}]}
    ... }
    >>> av.store_entity(jack, jacks_details, auth)

    Set Jack's age. 

    >>> av.set_attribute(jack, av.Attribute.AGE, 82, auth)

    Find Jack's age.

    >>> av.get_attribute(jack, av.Attribute.AGE)
    82

    Examine Jack's locations.

    >>> av.retrieve_attribute(jack, attribute=av.Attribute.LOCATION)
    {'Attributes': {'LOCATION_ATTRIBUTE': [
        {'Values': [{'UTF-8': 'Los Angeles'}, 
        {'UTF-8': 'Aspen'}, 
        {'UTF-8': 'Malibu'}]}]}}

    Set Jack's location and examine the result. Note that only the first 
    location is changed.

    >>> av.set_attribute(jack, av.Attribute.LOCATION, 'Mulholland Drive', auth)
    >>> av.retrieve_attribute(jack, attribute=av.Attribute.LOCATION)
    {'Attributes': {'LOCATION_ATTRIBUTE': [{'Values': [
        {'UTF-8': 'Mulholland Drive'}, 
        {'UTF-8': 'Aspen'}, 
        {'UTF-8': 'Malibu'}]}]}}

    Get Jack's location.

    >>> av.get_attribute(jack, av.Attribute.LOCATION)
    'Mulholland Drive'

    Examine Jack's children. 

    >>> av.retrieve_attribute(jack, attribute=av.Attribute.CHILD)
    {'Attributes': {'CHILD_ATTRIBUTE': [
        {'Values': [{'UTF-8': 'Jennifer'}]}, 
        {'Values': [{'UTF-8': 'Caleb'}]}, 
        {'Values': [{'UTF-8': 'Honey'}, {'UTF-8': 'Honning'}]}, 
        {'Values': [{'UTF-8': 'Lorraine'}]}, 
        {'Values': [{'UTF-8': 'Raymond'}]}]}}

    Set Jack's child, and examine the results. Note that only the first
    attribute instance is changed.

    >>> av.set_attribute(jack, av.Attribute.CHILD, 'Jen', auth)
    >>> av.retrieve_attribute(jack, attribute=av.Attribute.CHILD)
    {'Attributes': {'CHILD_ATTRIBUTE': [
        {'Values': [{'UTF-8': 'Jen'}]}, 
        {'Values': [{'UTF-8': 'Caleb'}]}, 
        {'Values': [{'UTF-8': 'Honey'}, {'UTF-8': 'Honning'}]}, 
        {'Values': [{'UTF-8': 'Lorraine'}]}, 
        {'Values': [{'UTF-8': 'Raymond'}]}]}}

    Get Jack's child.

    >>> av.get_attribute(jack, av.Attribute.CHILD)
    'Jen'

    Clean up.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """
    invoke(
        entity, Method.SET, parameter=Argument.ATTRIBUTE, attribute=attribute,
        value=value, authorization=auth)

@manage_exceptions('while clearing attribute {1} of entity {0}')
def clear_attribute(entity, attribute, auth): 
    """
    clear_attribute(entity, attribute, auth)
    Clear the value of an attribute on an entity.

    :func:`clear_attribute` clears the value of an attribute on an entity. It is
    intended for a simple, common case: keeping a single value on an attribute,
    rather than multiple values or multiple attribute instances. For more
    complex situations, :func:`clear_value` is better.

    If there are multiple values on the attribute, :func:`clear_attribute` 
    clears the first one. If there are no values, :func:`clear_attribute` does
    nothing. 

    If there are multiple attribute instances of a single attribute---e.g.
    multiple instances of the ``CHILD`` attribute---:func:`clear_attribute`
    clears a value from the first one.

    Parameters
    ----------
    entity : Entity 
        the entity whose attribute is to be cleared

    attribute : Attribute
        the attribute of ``entity`` to be cleared

    auth : Authorization
        authorization token permitting the attribute clearing

    Returns
    -------
    None

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``attribute`` is not a valid attribute, or ``auth`` does
        not authorize the clearing.

    See also
    --------
    :func:`clear_value` : clear the value of an attribute or of the entity

    :func:`get_attribute` : return the value of an attribute on an entity

    :func:`set_attribute` : set the value of an attribute on an entity

    :func:`erase_attribute` : erase an attribute from an entity

    :func:`find_attribute` : find the position of an attribute on an entity

    :func:`retrieve_attribute` : retrieve everything for a single attribute on an entity

    :func:`attribute_item` : return the attribute at a position on the entity

    :func:`attribute_count` : return count of instances of an attribute, or count of attributes on entity  

    Examples
    --------
    >>> import avesterra.avial as av
    >>> auth = av.initialize()

    Create an entity, and populate with attribute values.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jacks_details = {
    ...     "Attributes":{ 
    ...         "HEIGHT_ATTRIBUTE":[{"Values":[{"INTEGER": "177"}]}],
    ...         "LOCATION_ATTRIBUTE":[{"Values":[
    ...             {'UTF-8': "Los Angeles"}, 
    ...             {'UTF-8': "Aspen"},
    ...             {'UTF-8': "Malibu"}]}],
    ...         "CHILD_ATTRIBUTE":[
    ...             {"Values": [{'UTF-8': "Jennifer"}]},
    ...             {
    ...                 "Values": [{'UTF-8': "Caleb"}],
    ...                 "Properties": [ 
    ...                     ["Born","", {'INTEGER': "1970"}], 
    ...                     ["Mother","", {'UTF-8': "Susan Anspach"}]
    ...                 ]
    ...             },
    ...             {"Values": [{'UTF-8': "Honey"}, {'UTF-8': "Honning"}]},
    ...             {"Values": [{'UTF-8': "Lorraine"}]},
    ...             {"Values": [{'UTF-8': "Raymond"}]}]}
    ... }
    >>> av.store_entity(jack, jacks_details, auth)

    Clear Jack's age.

    >>> av.clear_attribute(jack, av.Attribute.AGE, auth)

    Look at Jack's age. There is nothing there.

    >>> av.retrieve_attribute(jack, attribute=av.Attribute.AGE)
    {}

    Clear Jack's location.

    >>> av.clear_attribute(jack, av.Attribute.LOCATION, auth)

    Jack now has only two locations. The first one is Aspen.

    >>> av.retrieve_attribute(jack, attribute=av.Attribute.LOCATION)
    {'Attributes': {'LOCATION_ATTRIBUTE': [{'Values': [{'UTF-8': 'Aspen'}, {'UTF-8': 'Malibu'}]}]}}
    >>> av.get_attribute(jack, av.Attribute.LOCATION)
    'Aspen'
    >>> av.clear_attribute(jack, av.Attribute.LOCATION, auth)
    >>> av.get_attribute(jack, av.Attribute.LOCATION)
    'Malibu'

    Examine Jack's children. Note that Caleb, his second child, has properties
    as well as values.

    >>> av.retrieve_attribute(jack, attribute=av.Attribute.CHILD)
    {'Attributes': {'CHILD_ATTRIBUTE': [
        {'Values': [{'UTF-8': 'Jennifer'}]}, 
        {
            'Values': [{'UTF-8': 'Caleb'}], 
            'Properties': [
                ['Born', '', {'INTEGER': '1970'}], 
                ['Mother', '', {'UTF-8': 'Susan Anspach'}]
            ]
        }, 
        {'Values': [{'UTF-8': 'Honey'}, {'UTF-8': 'Honning'}]}, 
        {'Values': [{'UTF-8': 'Lorraine'}]}, 
        {'Values': [{'UTF-8': 'Raymond'}]}]}}

    Clear Jack's child.

    >>> av.clear_attribute(jack, av.Attribute.CHILD, auth)

    There are four children left.

    >>> av.retrieve_attribute(jack, attribute=av.Attribute.CHILD)
    {'Attributes': {'CHILD_ATTRIBUTE': [
        {
            'Values': [{'UTF-8': 'Caleb'}],
            'Properties': [
                ['Born', '', {'INTEGER': '1970'}], 
                ['Mother', '', {'UTF-8': 'Susan Anspach'}]
            ]
        }, 
        {'Values': [{'UTF-8': 'Honey'}, {'UTF-8': 'Honning'}]}, 
        {'Values': [{'UTF-8': 'Lorraine'}]}, 
        {'Values': [{'UTF-8': 'Raymond'}]}]}}

    Clear another child.

    >>> av.clear_attribute(jack, av.Attribute.CHILD, auth)

    There are still four children. The call of :func:`clear_attribute`
    cleared the (sole) value, but left the properties unchanged.

    >>> av.retrieve_attribute(jack, attribute=av.Attribute.CHILD)
    {'Attributes': {'CHILD_ATTRIBUTE': [
        {
            'Properties': [
                ['Born', '', {'INTEGER': '1970'}], 
                ['Mother', '', {'UTF-8': 'Susan Anspach'}]
            ]
        }, 
        {'Values': [{'UTF-8': 'Honey'}, {'UTF-8': 'Honning'}]}, 
        {'Values': [{'UTF-8': 'Lorraine'}]}, 
        {'Values': [{'UTF-8': 'Raymond'}]}]}}

    Clear again. This time there is no effect at all.

    >>> av.clear_attribute(jack, av.Attribute.CHILD, auth)
    >>> av.retrieve_attribute(jack, attribute=av.Attribute.CHILD)
    {'Attributes': {'CHILD_ATTRIBUTE': [
        {
            'Properties': [
                ['Born', '', {'INTEGER': '1970'}], 
                ['Mother', '', {'UTF-8': 'Susan Anspach'}]
            ]
        }, 
        {'Values': [{'UTF-8': 'Honey'}, {'UTF-8': 'Honning'}]}, 
        {'Values': [{'UTF-8': 'Lorraine'}]}, 
        {'Values': [{'UTF-8': 'Raymond'}]}]}} 

    Clean up. 

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """
    invoke(
        entity, Method.CLEAR, parameter=Argument.ATTRIBUTE, attribute=attribute,
        authorization=auth)

@manage_exceptions('while erasing attribute {1} of entity {0}')
def erase_attribute(entity, attribute, auth): 
    """
    erase_attribute(entity, attribute, auth)
    Erase an attribute from an entity.

    :func:`erase_attribute` erases an attribute from an entity. It is intended
    for a simple, common case: when the entity has a single value for an 
    attribute, rather than multiple values or multiple instances. For more
    complex situations, consider :func:`erase_value` or :func:`erase_entity`.

    If ``entity`` has multiple values for ``attribute``, 
    :func:`erase_attribute` erases all of them. If ``entity`` has attribute
    properties on ``attribute``, :func:`erase_attribute` erases them as well.

    If ``entity`` has multiple
    attribute instances for ``attribute``, :func:`erase_attribute` erases
    only one attribute instance---the first one---leaving the rest in place.  

    Parameters
    ----------
    entity : Entity 
        the entity whose attribute is to be erased

    attribute : Attribute
        the attribute of ``entity`` to be erased 

    auth : Authorization
        authorization token permitting the attribute setting   

    Returns
    -------
    None

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``attribute`` is not a valid attribute, or ``auth`` does
        not authorize the erasing.

    See also
    --------
    :func:`erase_value` : erase values from an entity

    :func:`erase_entity` : erase all attributes, properties, and values of an entity

    :func:`get_attribute` : return the value of an attribute on an entity

    :func:`set_attribute` : set the value of an attribute on an entity

    :func:`clear_attribute` : clear the value of an attribute on an entity

    :func:`find_attribute` : find the position of an attribute on an entity

    :func:`retrieve_attribute` : retrieve everything for a single attribute on an entity

    :func:`attribute_item` : return the attribute at a position on the entity

    :func:`attribute_count` : return count of instances of an attribute, or count of attributes on entity

    Examples
    --------
    >>> import avesterra.avial as av
    >>> auth = av.initialize()

    Create an entity. Populate with attribute values.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jacks_details = {
    ...     "Attributes":{ 
    ...         "HEIGHT_ATTRIBUTE":[{"Values":[{"INTEGER": "177"}]}],
    ...         "LOCATION_ATTRIBUTE":[{"Values":[
    ...             {'UTF-8': "Los Angeles"}, 
    ...             {'UTF-8': "Aspen"},
    ...             {'UTF-8': "Malibu"}]}],
    ...         "CHILD_ATTRIBUTE":[
    ...             {"Values": [{'UTF-8': "Jennifer"}]},
    ...             {
    ...                 "Values": [{'UTF-8': "Caleb"}],
    ...                 "Properties": [ 
    ...                     ["Born","", {'INTEGER': "1970"}], 
    ...                     ["Mother","", {'UTF-8': "Susan Anspach"}]
    ...                 ]
    ...             },
    ...             {"Values": [{'UTF-8': "Honey"}, {'UTF-8': "Honning"}]},
    ...             {"Values": [{'UTF-8': "Lorraine"}]},
    ...             {"Values": [{'UTF-8': "Raymond"}]}]}
    ... }
    >>> av.store_entity(jack, jacks_details, auth)

    Erase Jack's height

    >>> av.erase_attribute(jack, av.Attribute.HEIGHT, auth)
    >>> av.retrieve_attribute(jack, attribute=av.Attribute.HEIGHT)
    {}

    Erase Jack's location. Note that all the values are erased.

    >>> av.erase_attribute(jack, av.Attribute.LOCATION, auth)
    >>> av.retrieve_attribute(jack, attribute=av.Attribute.LOCATION)
    {}

    Examine Jack's children.

    >>> av.retrieve_attribute(jack, attribute=av.Attribute.CHILD)
    {'Attributes': {'CHILD_ATTRIBUTE': [
        {'Values': [{'UTF-8': 'Jennifer'}]}, 
        {
            'Values': [{'UTF-8': 'Caleb'}], 
            'Properties': [
                ['Born', '', {'INTEGER': '1970'}], 
                ['Mother', '', {'UTF-8': 'Susan Anspach'}]
            ]
        }, 
        {'Values': [{'UTF-8': 'Honey'}, {'UTF-8': 'Honning'}]}, 
        {'Values': [{'UTF-8': 'Lorraine'}]}, 
        {'Values': [{'UTF-8': 'Raymond'}]}
    ]}}

    Erase the first instance of the child attribute.

    >>> av.erase_attribute(jack, av.Attribute.CHILD, auth)
    >>> av.retrieve_attribute(jack, attribute=av.Attribute.CHILD)
    {'Attributes': {'CHILD_ATTRIBUTE': [ 
        {
            'Values': [{'UTF-8': 'Caleb'}], 
            'Properties': [
                ['Born', '', {'INTEGER': '1970'}], 
                ['Mother', '', {'UTF-8': 'Susan Anspach'}]
            ]
        }, 
        {'Values': [{'UTF-8': 'Honey'}, {'UTF-8': 'Honning'}]}, 
        {'Values': [{'UTF-8': 'Lorraine'}]}, 
        {'Values': [{'UTF-8': 'Raymond'}]}
    ]}}

    Erase another attribute instance. Note that both values and properties
    are erased, unlike the behavior of :func:`clear_attribute`.

    >>> av.erase_attribute(jack, av.Attribute.CHILD, auth)
    >>> av.retrieve_attribute(jack, attribute=av.Attribute.CHILD)
    {'Attributes': {'CHILD_ATTRIBUTE': [  
        {'Values': [{'UTF-8': 'Honey'}, {'UTF-8': 'Honning'}]}, 
        {'Values': [{'UTF-8': 'Lorraine'}]}, 
        {'Values': [{'UTF-8': 'Raymond'}]}
    ]}}

    Clean up.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """
    invoke(
        entity, Method.ERASE, parameter=Argument.ATTRIBUTE,
        attribute=attribute, authorization=auth)

@manage_exceptions('while finding attribute {1} of entity {0}')
def find_attribute(entity, attribute, *, index=None): 
    """
    find_attribute(entity, attribute, *, index=None)
    Return the positon of ``attribute``, among all the attributes of ``entity``.

    :func:`find_attribute` returns the 1-based position of ``attribute``, e.g.
    if ``attribute`` is the first attribute, it returns 1 rather than 0. 
    If entity does not have that attribute, raises AvialNotFound.

    If ``index`` is provided, the search for ``attribute`` starts at the
    position identified by ``index``, ignoring all prior attributes. 

    Parameters
    ----------
    entity : Entity
        the entity on which the attribute is to be found

    attribute : Attribute 
        the attribute to find

    index : int, optional
        The attribute position to start the search for ``attribute``. The
        default is None: start at the beginning.

    Returns
    -------
    int
        the position of ``attribute`` among all the attributes of entity.

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter,  or ``attribute`` is not an attribute.

    AvialNotFound
        if ``attribute`` is not found 

    See also
    --------
    :func:`get_attribute` : return the value of an attribute on an entity

    :func:`set_attribute` : set the value of an attribute on an entity

    :func:`clear_attribute` : clear the value of an attribute on an entity

    :func:`erase_attribute` : erase an attribute from an entity

    :func:`retrieve_attribute` : retrieve everything for a single attribute on an entity

    :func:`attribute_item` : return the attribute at a position on the entity

    :func:`attribute_count` : return count of instances of an attribute, or count of attributes on entity

    Examples
    --------
    >>> import avesterra.avial as av
    >>> auth = av.initialize()

    Create an entity, and fill it with attribute values.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jacks_details = {
    ...     "Attributes":{ 
    ...         "HEIGHT_ATTRIBUTE":[{"Values":[{"INTEGER": "177"}]}],
    ...         "LOCATION_ATTRIBUTE":[{"Values":[
    ...             {'UTF-8': "Los Angeles"}, 
    ...             {'UTF-8': "Aspen"},
    ...             {'UTF-8': "Malibu"}]}],
    ...         "CHILD_ATTRIBUTE":[
    ...             {"Values": [{'UTF-8': "Jennifer"}]},
    ...             {
    ...                 "Values": [{'UTF-8': "Caleb"}],
    ...                 "Properties": [ 
    ...                     ["Born","", {'INTEGER': "1970"}], 
    ...                     ["Mother","", {'UTF-8': "Susan Anspach"}]
    ...                 ]
    ...             },
    ...             {"Values": [{'UTF-8': "Honey"}, {'UTF-8': "Honning"}]},
    ...             {"Values": [{'UTF-8': "Lorraine"}]},
    ...             {"Values": [{'UTF-8': "Raymond"}]}]}
    ... }
    >>> av.store_entity(jack, jacks_details, auth)

    Find the position of the height attribute.

    >>> av.find_attribute(jack, av.Attribute.HEIGHT)
    1

    Find the position of the location attribute.

    >>> av.find_attribute(jack, av.Attribute.LOCATION)
    2

    Find the position of the child attribute.

    >>> av.find_attribute(jack, av.Attribute.CHILD)
    3

    Find the position of the (non-existant) spouse attribute.

    >>> av.find_attribute(jack, av.Attribute.SPOUSE) 
    avesterra.avial.AvialNotFound: Attribute not found

    Clean up

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """
    pos = invoke(
        entity, Method.FIND, parameter=Argument.ATTRIBUTE, attribute=attribute,
        index=index, return_results=True)
    if pos == 0:
        raise AvialNotFound('Attribute not found')
    else:
        return pos

@manage_exceptions('while retrieving attributes of entity {0}')
def retrieve_attribute(entity, *, attribute=None): 
    """
    retrieve_attribute(entity, *, attribute=None)
    Retrieve everything for a single attribute, in comprehensive format.

    Comprehensive format is a json schema
    used for communicating all of the contents of an entity, or some part of the
    contents. See :ref:`comprehensive format <comprehensive_format>` for more detail.

    If ``attribute`` is specified---the typical usage---everything about that 
    single attribute is returned, in comprehensive format. Everything includes
    all attribute instances, with values, properties, and labels. 
 
    The most common usage of :func:`retrieve_attribute` is specifying an
    attribute to retrieve. But ``attribute`` is optional. If no attribute
    is specified, all of the attribute instances of all the entity's 
    attributes are returned, in comprehensive format. The resulting dict
    is similar to the dict returned from a call to :func:`retrieve_entity`,
    except that the latter also includes entity values and entity labels. 

    Parameters
    ----------
    entity : Entity
        the entity whose attribute is retrieved

    attribute : Attribute, optional 
        the attribute of ``entity`` to be returned, in comprehensive format,
        If not provided, all attributes are the entity are returned, again
        in comprehensive format.

    Returns
    -------
    dict
        in comprehensive format

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``attribute`` does not exist on ``entity``.

    See also
    --------    
    :func:`retrieve_entity` : return all attributes, properties, and values of an entity, in :ref:`comprehensive format <comprehensive_format>`

    :func:`get_attribute` : return the value of an attribute on an entity

    :func:`set_attribute` : set the value of an attribute on an entity

    :func:`clear_attribute` : clear the value of an attribute on an entity

    :func:`erase_attribute` : erase an attribute from an entity

    :func:`find_attribute` : find the position of an attribute on an entity

    :func:`attribute_item` : return the attribute at a position on the entity

    :func:`attribute_count` : return count of instances of an attribute, or count of attributes on entity

    Examples
    --------
    >>> import avesterra.avial as av
    >>> auth = av.initialize()

    Create an entity and give it some attributes.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jacks_details = {
    ...     "Attributes":{ 
    ...         "HEIGHT_ATTRIBUTE":[{"Values":[{"INTEGER": "177"}]}],
    ...         "LOCATION_ATTRIBUTE":[{"Values":[
    ...             {'UTF-8': "Los Angeles"}, 
    ...             {'UTF-8': "Aspen"},
    ...             {'UTF-8': "Malibu"}]}],
    ...         "CHILD_ATTRIBUTE":[
    ...             {"Values": [{'UTF-8': "Jennifer"}], "Label": "Jen"},
    ...             {
    ...                 "Values": [{'UTF-8': "Caleb"}],
    ...                 "Properties": [ 
    ...                     ["Born","", {'INTEGER': "1970"}], 
    ...                     ["Mother","", {'UTF-8': "Susan Anspach"}]
    ...                 ],
    ...                 "Label": "C"
    ...             },
    ...             {"Values": [{'UTF-8': "Honey"}, {'UTF-8': "Honning"}]},
    ...             {"Values": [{'UTF-8': "Lorraine"}]},
    ...             {"Values": [{'UTF-8': "Raymond"}]}]}, 
    ...     "Values": [{'UTF-8': 'actor'}, {'UTF-8': 'player'}, {'UTF-8': 'filmmaker'}]
    ... }
    >>> av.store_entity(jack, jacks_details, auth)

    Retrieve Jack's height, in comprehensive format.

    >>> av.retrieve_attribute(jack, attribute=av.Attribute.HEIGHT)
    {'Attributes': {'HEIGHT_ATTRIBUTE': [{'Values': [{'INTEGER': '177'}]}]}}

    Retrieve Jack's location. Note that there are three values for location.

    >>> av.retrieve_attribute(jack, attribute=av.Attribute.LOCATION)
    {'Attributes': {'LOCATION_ATTRIBUTE': [{'Values': 
        [{'UTF-8': 'Los Angeles'}, 
        {'UTF-8': 'Aspen'}, 
        {'UTF-8': 'Malibu'}
    ]}]}}

    Retrieve Jack's children. Note that there are five attribute instances
    for child.

    >>> av.retrieve_attribute(jack, attribute=av.Attribute.CHILD)
    {'Attributes': {'CHILD_ATTRIBUTE': [
        {'Values': [{'UTF-8': 'Jennifer'}], 'Label': 'Jen'}, 
        {
            'Values': [{'UTF-8': 'Caleb'}], 
            'Properties': [
                ['Born', '', {'INTEGER': '1970'}], 
                ['Mother', '', {'UTF-8': 'Susan Anspach'}]
            ], 
            'Label': 'C'
        }, 
        {'Values': [{'UTF-8': 'Honey'}, {'UTF-8': 'Honning'}]}, 
        {'Values': [{'UTF-8': 'Lorraine'}]}, 
        {'Values': [{'UTF-8': 'Raymond'}]}
    ]}}

    Retrieve all of Jack's attributes.

    >>> av.retrieve_attribute(jack)
    {'Attributes': {
        'HEIGHT_ATTRIBUTE': [{'Values': [{'INTEGER': '177'}]}], 'LOCATION_ATTRIBUTE': [{'Values': [
            {'UTF-8': 'Los Angeles'}, 
            {'UTF-8': 'Aspen'}, 
            {'UTF-8': 'Malibu'}
        ]}], 
        'CHILD_ATTRIBUTE': [
            {'Values': [{'UTF-8': 'Jennifer'}], 'Label': 'Jen'}, 
            {
                'Values': [{'UTF-8': 'Caleb'}], 
                'Properties': [
                    ['Born', '', {'INTEGER': '1970'}], 
                    ['Mother', '', {'UTF-8': 'Susan Anspach'}]
                ], 
                'Label': 'C'
            }, 
            {'Values': [{'UTF-8': 'Honey'}, {'UTF-8': 'Honning'}]}, 
            {'Values': [{'UTF-8': 'Lorraine'}]}, 
            {'Values': [{'UTF-8': 'Raymond'}]}
        ]
    }} 

    Clean up.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """
    return _validate_and_simplify(invoke(
        entity, Method.RETRIEVE, parameter=Argument.ATTRIBUTE, 
        attribute=attribute, return_results=True))

@manage_exceptions('while retrieving attribute of entity {0} at position {1}')
def attribute_item(entity, instance):
    """
    attribute_item(entity, instance)
    Return attribute at the instance position.

    What attribute is third, among the attributes for this entity? Which
    attribute is 17th? 

    Parameters
    ----------
    entity : Entity
        the entity on which the attribute lives

    instance : int
        the position of the attribute in question. An instance of 0 returns the
        last attribute.
 

    Returns
    -------
    Attribute
        the attribute at the ``instance`` position

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or ``entity`` is not connected to an
        adapter, or instance is greater than the count of attributes for this
        entity.

    See also
    --------
    :func:`get_attribute` : return the value of an attribute on an entity

    :func:`set_attribute` : set the value of an attribute on an entity

    :func:`clear_attribute` : clear the value of an attribute on an entity

    :func:`erase_attribute` : erase an attribute from an entity

    :func:`find_attribute` : find the position of an attribute on an entity

    :func:`retrieve_attribute` : retrieve everything for a single attribute on an entity

    :func:`attribute_count` : return count of instances of an attribute, or count of attributes on entity

    :func:`attribute_count` : how many attributes are on this entity?


    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize()

    Create an entity.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)

    Set the attributes and properties for Jack.
    
    >>> jacks_details = {
    ...     "Attributes":{
    ...         "SEX_ATTRIBUTE":[{"Values":["M"]}],
    ...         "AGE_ATTRIBUTE":[{"Values":["80"]}],
    ...         "HEIGHT_ATTRIBUTE":[{"Values":["177"]}], 
    ...         "LOCATION_ATTRIBUTE":[{"Values":["Los Angeles", "Aspen"]}],
    ...         "CHILD_ATTRIBUTE":[
    ...             {
    ...                 "Values": ["Jennifer"],
    ...                 "Properties": [ 
    ...                     ["Born","","1963"],
    ...                     ["Mother","","Sandra Knight"] 
    ...                 ]
    ...             },
    ...             {
    ...                 "Values": ["Caleb"],
    ...                 "Properties": [ 
    ...                     ["Born","","1970"],
    ...                     ["Mother","","Susan Anspach"],
    ...                     ["Paternity", "Paternity", "not established"]
    ...                 ]
    ...             },
    ...             {"Values": ["Honey"]},
    ...             {"Values": ["Lorraine"]},
    ...             {
    ...                 "Values": ["Raymond"],
    ...                 "Properties": [ 
    ...                     ["Born","","1992"],
    ...                     ["Mother","","Rebecca Broussard"] 
    ...                 ]
    ...             }]},
    ...     "Properties":[
    ...         ["known for","No.1","The Shining"],
    ...         ["fan of","","Los Angeles Lakers"],
    ...         ["fan of", "", "Bob Dylan"],
    ...         ["known for","","Chinatown"]
    ...         ]
    ... }
    >>> av.store_entity(jack, jacks_details, auth)

    What is Jack's second attribute?

    >>> av.attribute_item(jack, 2)
    <Attribute.AGE: 35>

    What is Jack's fifth attribute?

    >>> av.attribute_item(jack, 5)
    <Attribute.CHILD: 47>

    Clean up the example and end the session.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()

    """ 
    return Attribute(invoke(
        entity, Method.ATTRIBUTE, parameter=Argument.ATTRIBUTE,
        instance=instance, return_results=True))

@manage_exceptions('while counting attributes on entity {0}')
def attribute_count(entity, *, attribute=None):
    """
    attribute_count(entity, *, attribute=None)
    Return count of instances of attribute, or count of attributes on entity

    How many child attribute instances are on the entity? How many location
    attribute instances? Or how many attributes on the entity?

    Parameters
    ----------
    entity : Entity
        the entity on which to count

    attribute : Attribute, optional
        the attribute of which to count instances. If not provided, the
        number of attributes on the entity is counted instead.

    Returns
    -------
    int
        either the count of attribute instances of ``attribute`` (if provided), 
        or the count of attributes (if ``attribute`` is not provided)

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or ``entity`` is not connected to an
        adapter 

    See also
    --------
    :func:`get_attribute` : return the value of an attribute on an entity

    :func:`set_attribute` : set the value of an attribute on an entity

    :func:`clear_attribute` : clear the value of an attribute on an entity

    :func:`erase_attribute` : erase an attribute from an entity

    :func:`find_attribute` : find the position of an attribute on an entity

    :func:`retrieve_attribute` : retrieve everything for a single attribute on an entity

    :func:`attribute_item` : return the attribute at a position on the entity


    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize()

    Create an entity.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)

    Set the attributes and properties for Jack.
    
    >>> jacks_details = {
    ...     "Attributes":{
    ...         "SEX_ATTRIBUTE":[{"Values":["M"]}],
    ...         "AGE_ATTRIBUTE":[{"Values":["80"]}],
    ...         "HEIGHT_ATTRIBUTE":[{"Values":["177"]}], 
    ...         "LOCATION_ATTRIBUTE":[{"Values":["Los Angeles", "Aspen"]}],
    ...         "CHILD_ATTRIBUTE":[
    ...             {
    ...                 "Values": ["Jennifer"],
    ...                 "Properties": [ 
    ...                     ["Born","","1963"],
    ...                     ["Mother","","Sandra Knight"] 
    ...                 ]
    ...             },
    ...             {
    ...                 "Values": ["Caleb"],
    ...                 "Properties": [ 
    ...                     ["Born","","1970"],
    ...                     ["Mother","","Susan Anspach"],
    ...                     ["Paternity", "Paternity", "not established"]
    ...                 ]
    ...             },
    ...             {"Values": ["Honey"]},
    ...             {"Values": ["Lorraine"]},
    ...             {
    ...                 "Values": ["Raymond"],
    ...                 "Properties": [ 
    ...                     ["Born","","1992"],
    ...                     ["Mother","","Rebecca Broussard"] 
    ...                 ]
    ...             }]},
    ...     "Properties":[
    ...         ["known for","No.1","The Shining"],
    ...         ["fan of","","Los Angeles Lakers"],
    ...         ["fan of", "", "Bob Dylan"],
    ...         ["known for","","Chinatown"]
    ...         ]
    ... }
    >>> av.store_entity(jack, jacks_details, auth)

    How many attributes for Jack?

    >>> av.attribute_count(jack)
    5

    How many instances of location?

    >>> av.attribute_count(jack, av.Attribute.LOCATION)
    1

    How many instances of child?

    >>> av.attribute_count(jack, av.Attribute.CHILD)
    5

    How many instances of the car attribute?

    >>> av.attribute_count(jack, av.Attribute.CAR)
    0

    Clean up the example and end the session.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()

    """ 
    return invoke(
        entity, Method.COUNT, parameter=Argument.ATTRIBUTE, attribute=attribute,
        return_results=True)


################################################################################
#
# Property operations
#

@manage_exceptions(
    'while getting the value of a property on entity {0}', 
    check_for_naked_instance=True)
def get_property(entity, *, key=None, index=None, attribute=None, 
                 instance=None):
    """
    get_property(entity, *, key=None, index=None, attribute=None, instance=None)
    Get the value of some property.

    Get the value of a property on ``entity``. With no arguments, returns the
    value of the last entity property. If ``key`` is specified, returns
    the value of the entity property with that key. If ``index`` is 
    specified---and ``key`` is not specified---returns the value of the 
    property at numeric position ``index``. 

    If ``attribute`` is specified, :func:`get_property` returns the value
    of an attribute property instead of an entity property, a
    property of ``attribute``. The property returned is identified by ``key``---
    if specified---or ``index``---if specified and ``key`` is not. If neither
    ``key`` nor ``index`` are specified, the value of the last property of 
    ``attribute`` is returned.

    Sometimes an entity has more than one instance of ``attribute``. In that
    case, the value of a property of the last instance is returned, unless
    ``instance`` is specified.

    Parameters
    ----------
    entity : Entity
        the entity whose property value is returned

    key : str, optional
        the key of the property whose value is returned

    index : int, optionally
        the numeric position of the property whose value is returned

    attribute : Attribute, optional
        If provided, return the value of an attribute property, and in 
        particular return a property of ``attribute``. The default
        is None: return the value of an entity property.

    instance : int, optional
        If provided and ``attribute`` is also provided, return the value
        of a property on a particular
        instance of an attribute property. For example, if ``attribute`` is 
        ``Attribute.CHILD`` and ``instance`` is  
        3, the property value of some property on the third child instance
        is returned. The default is None: return a value of a property on
        the last instance of ``attribute``.

    Returns
    -------
    int or float or bool or str or Entity or list or dict
        the value of the property

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``key`` is not found among the properties, or there are
        fewer than ``index`` properties, or ``attribute`` is not found on the
        entity, or ``instance`` is greater
        than the number of instances of ``attribute``,
        or ``instance`` is specified but ``attribute`` is not.

    See also
    --------

    Examples
    --------
    >>> import avesterra.avial as av
    >>> auth = av.initialize()

    Create an entity and fill its attributes and properties.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jacks_details = {
    ...     "Attributes":{  
    ...         "CHILD_ATTRIBUTE":[
    ...             {
    ...                 "Values": [{'UTF-8': "Jennifer"}],
    ...                 "Properties": [ 
    ...                     ["Born","", {'INTEGER': '1963'}],
    ...                     ["Mother","", {'ASCII': 'Sandra Knight'}] 
    ...                 ]
    ...             },
    ...             {
    ...                 "Values": [{'UTF-8': "Caleb"}],
    ...                 "Properties": [ 
    ...                     ["Born","", {'INTEGER': "1970"}],
    ...                     [
    ...                         "Paternity", 
    ...                         "open question", 
    ...                         {'UTF-8': "not established"}],
    ...                     ["Mother","", {'UTF-8': "Susan Anspach"}],
    ...                 ]
    ...             },
    ...             {"Values": [{'UTF-8': "Honey"}]},
    ...             {"Values": [{'UTF-8': "Lorraine"}]},
    ...             {
    ...                 "Values": [{'UTF-8': "Raymond"}],
    ...                 "Properties": [ 
    ...                     ["Born","youngest", {'INTEGER': "1992"}],
    ...                     ["Mother","", {'UTF-8': "Rebecca Broussard"}] 
    ...                 ]
    ...             }]},
    ...     "Properties":[
    ...         ["known for","most popular role", {'UTF-8': "The Shining"}],
    ...         ["fan of","famous fan", {"UTF-8": "Los Angeles Lakers"}],
    ...         ["fan of", "", {"UTF-8": "Bob Dylan"}],
    ...         ["also known for","best performance",{"UTF-8": "Chinatown"}]
    ...         ]
    ... }
    >>> av.store_entity(jack, jacks_details, auth)

    Get the value of Jack's last entity property.

    >>> av.get_property(jack)
    'Chinatown'

    Get the value of Jack's first entity property.

    >>> av.get_property(jack, index=1)
    'The Shining'

    Get the value of the entity property with the key 'famous fan'.

    >>> av.get_property(jack, key='famous fan')
    'Los Angeles Lakers'

    Get the value of the last property of the last instance of Jack's CHILD 
    attribute.

    >>> av.get_property(jack, attribute=av.Attribute.CHILD)
    'Rebecca Broussard'

    Get the value of the last property of the first instance of Jack's CHILD
    attribute.

    >>> av.get_property(jack, attribute=av.Attribute.CHILD, instance=1)
    'Sandra Knight'

    Get the value of the property with key 'open question' on the second
    instance of Jack's child attribute.

    >>> av.get_property(jack, attribute=av.Attribute.CHILD, instance=2, key='open question')
    'not established'

    Clean up.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize() 
    """ 
    return invoke(
        entity, Method.GET, parameter=Argument.PROPERTY, key=key, index=index,
        attribute=attribute, instance=instance, return_results=True)

@manage_exceptions(
    'while setting the name or value of a property on entity {0}',
    check_for_naked_instance=True)
def set_property(entity, auth, *, name=None, value=None, key=None, 
                 attribute=None, instance=None, index=None):
    """
    set_property(entity, auth, *, name=None, key=None, value=None, attribute=None, instance=None, index=None)
    Set the name or value (or both) of some property.

    :func:`set_property` sets the name or value of an existing property. If
    the ``name`` parameter is specified, the name of a property is changed. If
    the ``value`` parameter is specified, the value of a property is changed.
    If both are specified, both are changed.

    The property to be changed is identified with the ``key``, 
    ``index``, ``attribute``, and ``instance`` parameters. If ``attribute``
    is not specified, an entity property is changed, instead of an attribute
    property. In that case, if ``key`` is specified, the entity property
    with that key is changed. Or if ``index`` is specified, the entity
    property at that numeric position is changed. Or if neither ``key`` nor
    ``index`` are specified, the last entity property is changed.

    If ``attribute`` is specified, an attribute property is changed instead
    of an entity property, and in particular, one of the properties of 
    ``attribute`` is changed. ``key`` or ``index`` identify which attribute
    property is changed. If neither are specified, the last property of
    ``attribute`` is changed.

    Sometimes an entity will have multiple attribute instances. In that 
    situation, an attribute property of the last instance of ``attribute`` is
    changed, unless ``instance`` is specified. If ``instance`` is specified,
    it identifies the numeric position of the attribute instance that contains
    the property to be changed. For example, if ``attribute`` is CHILD and
    ``instance`` is 1, the first child instance is changed.

    Parameters
    ----------
    entity : Entity
        the entity whose property is changed

    auth : Authorization
        authorization token permitting the property change

    name : str, optional
        the new name of the property. If not provided, the name of the property
        is left unchanged

    value : int or float or bool or str or Entity or list or dict, optional
        the new value of the property. If not provided, the value of the 
        property is unchanged

    key : str, optional
        the key of the property to be changed. If not provided, the property
        is identified by ``index``. If ``index`` is also not provided, the
        last property is changed.

    index : int, optional
        the position of the property to be changed. If not provided---and
        ``key`` is also not provided---the last property is changed. 

    attribute : Attribute, optional
        If provided, an attribute property is changed instead of an entity
        property, and in particular a property of ``attribute`` is changed. If
        not provided, an entity property is changed.

    instance : int, optional
        If provided and ``attribute`` is also provided, a particular instance
        of ``attribute`` is changed, the one at position ``instance``. 
        For example, if ``attribute`` is ``Attribute.CHILD`` and ``instance`` is
        7, a property of the seventh child is changed. If not provided, the
        last instance of ``attribute`` is changed.

    Returns
    -------
    None

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``auth`` does not authorize changing a property, or 
        ``key`` is not found among the properties, or ``index`` is greater
        than the number of properties, or 
        ``attribute`` is not found on the entity, or ``instance`` is greater
        than the number of instances of ``attribute``, or ``instance`` is 
        provided but ``attribute`` is not.

    See also
    --------

    Examples
    --------
    >>> import avesterra.avial as av
    >>> auth = av.initialize()

    Create an entity and fill it with attributes and properties.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jacks_details = {
    ...     "Attributes":{  
    ...         "CHILD_ATTRIBUTE":[
    ...             {
    ...                 "Values": [{'UTF-8': "Jennifer"}],
    ...                 "Properties": [ 
    ...                     ["Born","", {'INTEGER': '1963'}],
    ...                     ["Mother","", {'ASCII': 'Sandra Knight'}] 
    ...                 ]
    ...             },
    ...             {
    ...                 "Values": [{'UTF-8': "Caleb"}],
    ...                 "Properties": [ 
    ...                     ["Born","", {'INTEGER': "1970"}],
    ...                     [
    ...                         "Paternity", 
    ...                         "open question", 
    ...                         {'UTF-8': "not established"}],
    ...                     ["Mother","", {'UTF-8': "Susan Anspach"}],
    ...                 ]
    ...             },
    ...             {"Values": [{'UTF-8': "Honey"}]},
    ...             {"Values": [{'UTF-8': "Lorraine"}]},
    ...             {
    ...                 "Values": [{'UTF-8': "Raymond"}],
    ...                 "Properties": [ 
    ...                     ["Born","youngest", {'INTEGER': "1992"}],
    ...                     ["Mother","", {'UTF-8': "Rebecca Broussard"}] 
    ...                 ]
    ...             }]},
    ...     "Properties":[
    ...         ["known for","most popular role", {'UTF-8': "The Shining"}],
    ...         ["fan of","famous fan", {"UTF-8": "Los Angeles Lakers"}],
    ...         ["fan of", "", {"UTF-8": "Bob Dylan"}],
    ...         ["also known for","best performance",{"UTF-8": "Chinatown"}]
    ...         ]
    ... }
    >>> av.store_entity(jack, jacks_details, auth)

    Change the value and name of Jack's last property.

    >>> av.set_property(jack, auth, value='Mars Attacks!', name='very best performance')
    >>> av.retrieve_property(jack)
    {'Properties': [
        ['known for', 'most popular role', {'UTF-8': 'The Shining'}], 
        ['fan of', 'famous fan', {'UTF-8': 'Los Angeles Lakers'}], 
        ['fan of', '', {'UTF-8': 'Bob Dylan'}], 
        ['very best performance', 'best performance', {'UTF-8': 'Mars Attacks!'}]
    ]}

    Change the value of Jack's property, the one with key 'famous fan'.

    >>> av.set_property(jack, auth, value='Los Angeles Clippers', key='famous fan')
    >>> av.retrieve_property(jack)
    {'Properties': [
        ['known for', 'most popular role', {'UTF-8': 'The Shining'}], 
        ['fan of', 'famous fan', {'UTF-8': 'Los Angeles Clippers'}], 
        ['fan of', '', {'UTF-8': 'Bob Dylan'}], 
        ['very best performance', 'best performance', {'UTF-8': 'Mars Attacks!'}]
    ]}

    Change the name of Jack's second property.

    >>> av.set_property(jack, auth, name='not a fan of', index=2)
    >>> av.retrieve_property(jack)
    {'Properties': [
        ['known for', 'most popular role', {'UTF-8': 'The Shining'}], 
        ['not a fan of', 'famous fan', {'UTF-8': 'Los Angeles Clippers'}], 
        ['fan of', '', {'UTF-8': 'Bob Dylan'}], 
        ['very best performance', 'best performance', {'UTF-8': 'Mars Attacks!'}]
    ]}

    Change the value of the last property of Jack's last child.

    >>> av.set_property(jack, auth, attribute=av.Attribute.CHILD, value='Becca Brousard')
    >>> av.retrieve_property(jack, attribute=av.Attribute.CHILD)
    {'Attributes': {'CHILD_ATTRIBUTE': [{'Properties': [
        ['Born', 'youngest', {'INTEGER': '1992'}], 
        ['Mother', '', {'UTF-8': 'Becca Brousard'}]
    ]}]}}

    Change the value of the first property of Jack's second child.

    >>> av.set_property(jack, auth, attribute=av.Attribute.CHILD, instance=2, index=1, value=1971)
    >>> av.retrieve_property(jack, attribute=av.Attribute.CHILD, instance=2)
    {'Attributes': {'CHILD_ATTRIBUTE': [{'Properties': [
        ['Born', '', {'INTEGER': '1971'}], 
        ['Paternity', 'open question', {'UTF-8': 'not established'}], 
        ['Mother', '', {'UTF-8': 'Susan Anspach'}]
    ]}]}}

    Clean up.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """ 
    invoke(
        entity, Method.SET, parameter=Argument.PROPERTY, name=name, key=key, 
        value=value, attribute=attribute, instance=instance, index=index,
        authorization=auth)

@manage_exceptions(
    'while clearing property on entity {0}', check_for_naked_instance=True)
def clear_property(entity, auth, *, key=None, index=None, attribute=None, 
                   instance=None): 
    """
    clear_property(entity, auth, *, key=None, index=None, attribute=None, instance=None)
    Clear the name and value of some property.

    :func:`set_property` clears both the name and the value of an existing 
    property. Clearing a property does not remove the property from the entity;
    the property remains but with empty strings for both name and value.

    The property to be cleared is
    identified with the ``key``, ``index``, ``attribute``, and ``instance`` 
    parameters. If ``attribute`` is not specified, an entity property is 
    to be cleared, instead of an attribute
    property. In that case, if ``key`` is specified, the entity property
    with that key is cleared. Or if ``index`` is specified, the entity
    property at that numeric position is cleared. Or if neither ``key`` nor
    ``index`` are specified, the last entity property is cleared.

    If ``attribute`` is specified, an attribute property is cleared instead
    of an entity property, and in particular, one of the properties of 
    ``attribute`` is cleared. ``key`` or ``index`` identify which attribute
    property is cleared. If neither are specified, the last property of
    ``attribute`` is cleared.

    Sometimes an entity will have multiple attribute instances. In that 
    situation, an attribute property of the last instance of ``attribute`` is
    cleared, unless ``instance`` is specified. If ``instance`` is specified,
    it identifies the numeric position of the attribute instance that contains
    the property to be cleared. For example, if ``attribute`` is CHILD and
    ``instance`` is 1, the first child instance is cleared.

    Parameters
    ----------
    entity : Entity
        the entity whose property is cleared

    auth : Authorization
        authorization token permitting the property clearing

    key : str, optional
        the key of the property to be cleared. If not provided, the property
        is identified by ``index``. If ``index`` is also not provided, the
        last property is cleared.

    index : int, optional
        the position of the property to be cleared. If not provided---and
        ``key`` is also not provided---the last property is cleared. 

    attribute : Attribute, optional
        If provided, an attribute property is cleared instead of an entity
        property, and in particular a property of ``attribute`` is cleared. If
        not provided, an entity property is cleared.

    instance : int, optional
        If provided and ``attribute`` is also provided, a particular instance
        of ``attribute`` is cleared, the one at position ``instance``. 
        For example, if ``attribute`` is ``Attribute.CHILD`` and ``instance`` is
        7, a property of the seventh child is cleared. If not provided, the
        last instance of ``attribute`` is cleared.

    Returns
    -------
    None

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``auth`` does not authorize changing a property, or 
        ``key`` is not found among the properties, or ``index`` is greater
        than the number of properties, or 
        ``attribute`` is not found on the entity, or ``instance`` is greater
        than the number of instances of ``attribute``, or ``instance`` is 
        provided but ``attribute`` is not.

    See also
    --------

    Examples
    --------
    >>> import avesterra.avial as av
    >>> auth = av.initialize()

    Create an entity and fill it with attributes and properties.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jacks_details = {
    ...     "Attributes":{  
    ...         "CHILD_ATTRIBUTE":[
    ...             {
    ...                 "Values": [{'UTF-8': "Jennifer"}],
    ...                 "Properties": [ 
    ...                     ["Born","", {'INTEGER': '1963'}],
    ...                     ["Mother","", {'ASCII': 'Sandra Knight'}] 
    ...                 ]
    ...             },
    ...             {
    ...                 "Values": [{'UTF-8': "Caleb"}],
    ...                 "Properties": [ 
    ...                     ["Born","", {'INTEGER': "1970"}],
    ...                     [
    ...                         "Paternity", 
    ...                         "open question", 
    ...                         {'UTF-8': "not established"}],
    ...                     ["Mother","", {'UTF-8': "Susan Anspach"}],
    ...                 ]
    ...             },
    ...             {"Values": [{'UTF-8': "Honey"}]},
    ...             {"Values": [{'UTF-8': "Lorraine"}]},
    ...             {
    ...                 "Values": [{'UTF-8': "Raymond"}],
    ...                 "Properties": [ 
    ...                     ["Born","youngest", {'INTEGER': "1992"}],
    ...                     ["Mother","", {'UTF-8': "Rebecca Broussard"}] 
    ...                 ]
    ...             }]},
    ...     "Properties":[
    ...         ["known for","most popular role", {'UTF-8': "The Shining"}],
    ...         ["fan of","famous fan", {"UTF-8": "Los Angeles Lakers"}],
    ...         ["fan of", "", {"UTF-8": "Bob Dylan"}],
    ...         ["also known for","best performance",{"UTF-8": "Chinatown"}]
    ...         ]
    ... }
    >>> av.store_entity(jack, jacks_details, auth)

    Clear Jack's last property.

    >>> av.clear_property(jack, auth)
    >>> av.retrieve_property(jack)
    {'Properties': [
        ['known for', 'most popular role', {'UTF-8': 'The Shining'}], 
        ['fan of', 'famous fan', {'UTF-8': 'Los Angeles Lakers'}], 
        ['fan of', '', {'UTF-8': 'Bob Dylan'}], 
        ['', 'best performance', '']
    ]}

    Clear Jack's property, the one with key 'famous fan'.

    >>> av.clear_property(jack, auth, key='famous fan')
    >>> av.retrieve_property(jack)
    {'Properties': [
        ['known for', 'most popular role', {'UTF-8': 'The Shining'}], 
        ['', 'famous fan', ''], 
        ['fan of', '', {'UTF-8': 'Bob Dylan'}], 
        ['', 'best performance', '']
    ]}

    Clear Jack's first property.

    >>> av.clear_property(jack, auth, index=1)
    >>> av.retrieve_property(jack)
    {'Properties': [
        ['', 'most popular role', ''], 
        ['', 'famous fan', ''], 
        ['fan of', '', {'UTF-8': 'Bob Dylan'}], 
        ['', 'best performance', '']
    ]}

    Clear the last property of Jack's last child.

    >>> av.clear_property(jack, auth, attribute=av.Attribute.CHILD)
    >>> av.retrieve_property(jack, attribute=av.Attribute.CHILD)
    {'Attributes': {'CHILD_ATTRIBUTE': [{'Properties': [
        ['Born', 'youngest', {'INTEGER': '1992'}], 
        ['', '', '']
    ]}]}}

    Clear the first proeprty of Jack's second child.

    >>> av.clear_property(jack, auth, attribute=av.Attribute.CHILD, instance=2, index=1)
    >>> av.retrieve_property(jack, attribute=av.Attribute.CHILD, instance=2)
    {'Attributes': {'CHILD_ATTRIBUTE': [{'Properties': [
        ['', '', ''], 
        ['Paternity', 'open question', {'UTF-8': 'not established'}], 
        ['Mother', '', {'UTF-8': 'Susan Anspach'}]
    ]}]}}

    Clean up.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """
    invoke(
        entity, Method.CLEAR, parameter=Argument.PROPERTY, key=key, index=index,
        attribute=attribute, instance=instance, authorization=auth)

@manage_exceptions(
    'while erasing properties on entity {0}', check_for_naked_instance=True)
def erase_property(entity, auth, *, attribute=None, instance=None):
    """
    erase_property(entity, auth, *, attribute=None, instance=None)
    Erase all the properties, either all the entity properties, or all the 
    properties of an attribute.

    If ``attribute`` and ``instance`` are not specified, :func:`erase_property`
    erases all the entity properties of ``entity``, leaving no properties at
    all. If ``attribute`` is provided, attribute properties are erased instead 
    of entity properties, and in particular, the properties of ``attribute``
    are erased.

    Sometimes an entity has multiple instances of an attribute. In that case,
    :func:`erase_property` erases the properties of the last instance, unless
    ``instance`` is provided to specify the numeric position of the instance
    whose attributes are erased.

    Parameters
    ----------
    entity : Entity
        the entity whose properties are erased

    auth : Authorization
        authorization token permitting property erasure 

    attribute : Attribute, optional
        If provided, attribute properties are erased instead of an entity
        property, and in particular the properties of ``attribute`` are
        erased. If not provided, entity properties are erased.

    instance : int, optional
        If provided and ``attribute`` is also provided, the properties of 
        a particular instance of ``attribute`` are erased, the instance at
        position ``instance``. For example, if ``attribute`` is 
        ``Attribute.CHILD`` and ``instance`` is 4, the properties of the fourth
        child are erased. If not provided, the properties of the last instance
        of ``attribute`` are erased.

    Returns
    -------
    None

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``auth`` does not authorize property erasure, or
        ``attribute`` is not found on the entity, or ``instance`` is greater
        than the number of instances of ``attribute``, or ``instance`` is 
        provided but ``attribute`` is not.

    See also
    --------

    Examples
    --------
    >>> import avesterra.avial as av
    >>> auth = av.initialize()

    Create an entity and add attributes and properties.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jacks_details = {
    ...     "Attributes":{  
    ...         "CHILD_ATTRIBUTE":[
    ...             {
    ...                 "Values": [{'UTF-8': "Jennifer"}],
    ...                 "Properties": [ 
    ...                     ["Born","", {'INTEGER': '1963'}],
    ...                     ["Mother","", {'ASCII': 'Sandra Knight'}] 
    ...                 ]
    ...             },
    ...             {
    ...                 "Values": [{'UTF-8': "Caleb"}],
    ...                 "Properties": [ 
    ...                     ["Born","", {'INTEGER': "1970"}],
    ...                     [
    ...                         "Paternity", 
    ...                         "open question", 
    ...                         {'UTF-8': "not established"}],
    ...                     ["Mother","", {'UTF-8': "Susan Anspach"}],
    ...                 ]
    ...             },
    ...             {"Values": [{'UTF-8': "Honey"}]},
    ...             {"Values": [{'UTF-8': "Lorraine"}]},
    ...             {
    ...                 "Values": [{'UTF-8': "Raymond"}],
    ...                 "Properties": [ 
    ...                     ["Born","youngest", {'INTEGER': "1992"}],
    ...                     ["Mother","", {'UTF-8': "Rebecca Broussard"}] 
    ...                 ]
    ...             }]},
    ...     "Properties":[
    ...         ["known for","most popular role", {'UTF-8': "The Shining"}],
    ...         ["fan of","famous fan", {"UTF-8": "Los Angeles Lakers"}],
    ...         ["fan of", "", {"UTF-8": "Bob Dylan"}],
    ...         ["also known for","best performance",{"UTF-8": "Chinatown"}]
    ...         ]
    ... }
    >>> av.store_entity(jack, jacks_details, auth)

    Erase all of Jack's properties.

    >>> av.erase_property(jack, auth)
    >>> av.retrieve_entity(jack)
    {
        'Attributes': {'CHILD_ATTRIBUTE': [
            {
                'Values': [{'UTF-8': 'Jennifer'}], 
                'Properties': [
                    ['Born', '', {'INTEGER': '1963'}], 
                    ['Mother', '', {'ASCII': 'Sandra Knight'}]
                ]
            }, 
            {
                'Values': [{'UTF-8': 'Caleb'}], 
                'Properties': [
                    ['Born', '', {'INTEGER': '1970'}], 
                    ['Paternity', 'open question', {'UTF-8': 'not established'}], 
                    ['Mother', '', {'UTF-8': 'Susan Anspach'}]
                ]
            }, 
            {'Values': [{'UTF-8': 'Honey'}]}, 
            {'Values': [{'UTF-8': 'Lorraine'}]}, 
            {
                'Values': [{'UTF-8': 'Raymond'}], 
                'Properties': [
                    ['Born', 'youngest', {'INTEGER': '1992'}], 
                    ['Mother', '', {'UTF-8': 'Rebecca Broussard'}]
                ]
            }
        ]}, 
        'Label': 'Jack Nicholson'
    }

    Erase all the properties of Jack's last child.

    >>> av.erase_property(jack, auth, attribute=av.Attribute.CHILD)
    >>> av.retrieve_entity(jack)
    {
        'Attributes': {'CHILD_ATTRIBUTE': [
            {
                'Values': [{'UTF-8': 'Jennifer'}], 
                'Properties': [
                    ['Born', '', {'INTEGER': '1963'}], 
                    ['Mother', '', {'ASCII': 'Sandra Knight'}]
                ]
            }, 
            {
                'Values': [{'UTF-8': 'Caleb'}], 
                'Properties': [
                    ['Born', '', {'INTEGER': '1970'}], 
                    ['Paternity', 'open question', {'UTF-8': 'not established'}], 
                    ['Mother', '', {'UTF-8': 'Susan Anspach'}]
                ]
            }, 
            {'Values': [{'UTF-8': 'Honey'}]}, 
            {'Values': [{'UTF-8': 'Lorraine'}]}, 
            {'Values': [{'UTF-8': 'Raymond'}]} 
        ]}, 
        'Label': 'Jack Nicholson'
    }

    Erase all the properties of Jack's second child.

    >>> av.erase_property(jack, auth, attribute=av.Attribute.CHILD, instance=2)
    >>> av.retrieve_entity(jack)
    {
        'Attributes': {'CHILD_ATTRIBUTE': [
            {
                'Values': [{'UTF-8': 'Jennifer'}], 
                'Properties': [
                    ['Born', '', {'INTEGER': '1963'}], 
                    ['Mother', '', {'ASCII': 'Sandra Knight'}]
                ]
            }, 
            {'Values': [{'UTF-8': 'Caleb'}]},  
            {'Values': [{'UTF-8': 'Honey'}]}, 
            {'Values': [{'UTF-8': 'Lorraine'}]}, 
            {'Values': [{'UTF-8': 'Raymond'}]} 
        ]}, 
        'Label': 'Jack Nicholson'
    } 

    Clean up.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """
    invoke(
        entity, Method.ERASE, parameter=Argument.PROPERTY, attribute=attribute,
        instance=instance, authorization=auth)

@manage_exceptions(
    'while finding property named {1} on entity {0}', 
    check_for_naked_instance=True)
def find_property(entity, name, *, attribute=None, instance=None, index=None):
    """
    find_property(entity, name, *, attribute=None, instance=None, index=None)
    Return the position of a property with a particular name.

    Return the 1-based position of the first property with name ``name``.
    If the name is not found, raise AvialNotFound

    Parameters
    ----------
    entity : Entity
        The entity whose properties are searched for ``name``.

    name : str
        The name to search for.

    index : int or None, optional
        The property position to start the search for ``name``. The default is
        None: start at the beginning.

    attribute : Attribute or None, optional
        If provided, attribute properties are searched instead of entity
        properties, and in particular, the attribute properties of ``attribute`` 
        are searched. The default is None: search entity properties.

    instance : int or None, optional
        If provided and ``attribute`` is also provided, search a particular
        instance of the attribute property. For example, if ``attribute`` is 
        given as ``Attribute.POPULATION`` and ``instance`` is provided as 
        2, the second attribute instance of the population attribute is 
        searched, instead of the last instance. The default is None: search the 
        last instance.

    Returns
    -------
    int 
        the position of ``name`` among the properties 

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter,  or ``attribute`` 
        is not an attribute, or an instance is specified but no attribute.

    AvialNotFound
        if the property is not found 

    See also
    --------
    :func:`lookup_property` : find the value of a property by key

    :func:`property_count` : count the number of properties on an entity

    :func:`property_name` : find the name of a property by its index

    :func:`property_key` : find the key of a property by its index

    :func:`property_value` : find the value of a property by its index

    :func:`insert_property` : insert a new property 

    :func:`remove_property` : remove an existing property

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize()
    >>> import pprint
    >>> pp = pprint.PrettyPrinter(indent=4)

    Create an entity for Jack Nicholson

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jacks_details = {
    ...     "Attributes":{
    ...         "SEX_ATTRIBUTE":[{"Values":["M"]}],
    ...         "AGE_ATTRIBUTE":[{"Values":["80"]}],
    ...         "HEIGHT_ATTRIBUTE":[{"Values":["177"]}], 
    ...         "LOCATION_ATTRIBUTE":[{"Values":["Los Angeles", "Aspen"]}],
    ...         "CHILD_ATTRIBUTE":[
    ...             {
    ...                 "Values": ["Jennifer"],
    ...                 "Properties": [ 
    ...                     ["Born","","1963"],
    ...                     ["Mother","","Sandra Knight"] 
    ...                 ]
    ...             },
    ...             {
    ...                 "Values": ["Caleb"],
    ...                 "Properties": [ 
    ...                     ["Born","","1970"],
    ...                     ["Paternity", "Paternity", "not established"],
    ...                     ["Mother","","Susan Anspach"],
    ...                 ]
    ...             },
    ...             {"Values": ["Honey"]},
    ...             {"Values": ["Lorraine"]},
    ...             {
    ...                 "Values": ["Raymond"],
    ...                 "Properties": [ 
    ...                     ["Born","","1992"],
    ...                     ["Mother","","Rebecca Broussard"] 
    ...                 ]
    ...             }]},
    ...     "Properties":[
    ...         ["known for","most popular role","The Shining"],
    ...         ["fan of","","Los Angeles Lakers"],
    ...         ["fan of", "", "Bob Dylan"],
    ...         ["known for","best performance","Chinatown"]
    ...         ]
    ... }
    >>> av.store_entity(jack, jacks_details, auth)

    Find the position of Jack's first ``known for`` property.

    >>> find_property(jack, 'known for')
    1

    Find the position of Jack's first ``fan of`` property.

    >>> find_property(jack, 'fan of')
    2

    Find the position of Jack's first ``known for`` property, at or after 2

    >>> find_property(jack, 'known for', index=2)
    4

    Find the position of Jack's first ``Celtic gear`` property. (Does not 
    exist).

    >>> find_property(jack, 'Celtic gear')
    AvialNotFound: Property not found

    Find the position of the ``Born`` property, on Jack's child attribute

    >>> find_property(jack, 'Born', attribute=Attribute.CHILD)
    1

    Find the position of the ``Mother`` property, on the 5th instance of 
    Jack's child attribute

    >>> find_property(jack, 'Mother', attribute=Attribute.CHILD, instance=5)
    2

    Find the position of the ``Born`` property, on the 5th instance of Jack's
    child attribute, at or after the second position. (Does not exist.)

    >>> find_property(jack, 'Born', attribute=Attribute.CHILD, instance=5, index=2)
    AvialNotFound: Property not found

    Attempt to find a name on the (non-existent) sixth instance of Jack's
    child attribute.

    >>> find_property(jack, 'Born', attribute=Attribute.CHILD, instance=6)
    AvialError: Error Server reported APPLICATION error: Attempt to access nonexistant attribute instance: CHILD_ATTRIBUTE 6 while attempting to find name Born on entity <2906857743|167772516|5080827> with index 0, attribute CHILD, and instance 6

    Attempt to find a name of the second instance but without an attribute.

    >>> find_property(jack, 'Born', instance=2)
    AvialError: Attempting to find instance 2 on properties of entity <2906857743|167772516|5080827>
    """ 
    pos = invoke(
        entity, Method.FIND, attribute=attribute,
        instance=instance, index=index, name=name, return_results=True)
    if pos == 0:
        raise AvialNotFound('Property not found')
    else:
        return pos

@manage_exceptions(
    'while retrieving property on entity {0}', check_for_naked_instance=True)
def retrieve_property(entity, *, attribute=None, instance=None, index=None, 
                      count=None): 
    """
    retrieve_property(entity, *, attribute=None, instance=None, index=None, count=None)
    """
    return _validate_and_simplify(invoke(
        entity, Method.RETRIEVE, parameter=Argument.PROPERTY, 
        attribute=attribute, instance=instance, index=index, count=count,
        return_results=True))

@manage_exceptions(
    'while inserting property on entity {0}', check_for_naked_instance=True)
def insert_property(entity, authorization, *, attribute=None, instance=None, 
                    name=None, key=None, value=None, index=None):
    """
    insert_property(entity, authorization, *, attribute=None, instance=None, name=None, key=None, value=None, index=None)
    Insert a name/key/value triple as a new property of the entity.

    Insert a name/key/value triple, either as an entity property, or as a 
    property of one of the entity's attributes.

    Parameters
    ----------
    entity : Entity
        the entity that will soon have a new property

    auth : Authorization
        authorization token permitting the insertion of a new property.

    name : str, optional
        the name of the new property. Need not be unique. If not specified,
        the empty string is used.

    key : str, optional
        the key of the new property. Must be either unique or an empty string.
        If not specified, the empty string is used.

    value : int or float or bool or str or Entity or list or dict, optional
        the value of the new property. If not specified, the empty string
        is used.

    attribute : Attribute or None, optional
        If provided, insert the new property on an attribute of the entity
        instead of on the entity as a whole, and in particular insert the
        new property on the attribute provided by ``attribute``. The default 
        is None: insert the new property on the entity as a whole.

    instance : int, optional
        If provided and ``attribute`` is also provided, insert the new property
        on a particular
        instance of an attribute property. For example, if ``attribute`` is 
        ``Attribute.CHILD`` and ``instance`` is  
        2, the new property is inserted on the second instance of the child
        attribute. The default is None: insert the new property on the last 
        instance of the attribute.

    index : int, optional
        if provided, the position where the new property is to be inserted. 
        The default is None: insert at the end of the properties.

    Returns
    -------
    None

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``auth`` is not a valid  authorization, or ``key`` is 
        already present among the properties, or ``attribute`` 
        is not an attribute, or an instance is specified but no attribute.

    See also
    --------
    :func:`remove_property` : remove an existing property

    :func:`property_name` : find the name of a property by its index

    :func:`property_key` : find the key of a property by its index

    :func:`property_value` : find the value of a property by its index

    :func:`property_count` : count the number of properties on an entity

    :func:`find_property` : find the position of a property with some name

    :func:`lookup_property` : find the value of a property by key

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize()
    >>> import pprint
    >>> pp = pprint.PrettyPrinter(indent=4)

    Create an entity for Jack Nicholson

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jacks_details = {
    ...     "Attributes":{
    ...         "SEX_ATTRIBUTE":[{"Values":["M"]}],
    ...         "AGE_ATTRIBUTE":[{"Values":["80"]}],
    ...         "HEIGHT_ATTRIBUTE":[{"Values":["177"]}], 
    ...         "LOCATION_ATTRIBUTE":[{"Values":["Los Angeles", "Aspen"]}],
    ...         "CHILD_ATTRIBUTE":[
    ...             {
    ...                 "Values": ["Jennifer"],
    ...                 "Properties": [ 
    ...                     ["Born","","1963"],
    ...                     ["Mother","","Sandra Knight"] 
    ...                 ]
    ...             },
    ...             {
    ...                 "Values": ["Caleb"],
    ...                 "Properties": [ 
    ...                     ["Born","","1970"],
    ...                     ["Mother","","Susan Anspach"],
    ...                     ["Paternity", "Paternity", "not established"]
    ...                 ]
    ...             },
    ...             {"Values": ["Honey"]},
    ...             {"Values": ["Lorraine"]},
    ...             {
    ...                 "Values": ["Raymond"],
    ...                 "Properties": [ 
    ...                     ["Born","","1992"],
    ...                     ["Mother","","Rebecca Broussard"] 
    ...                 ]
    ...             }]},
    ...     "Properties":[
    ...         ["known for","No.1","The Shining"],
    ...         ["fan of","","Los Angeles Lakers"],
    ...         ["fan of", "", "Bob Dylan"],
    ...         ["known for","","Chinatown"]
    ...         ]
    ... }
    >>> av.store_entity(jack, jacks_details, auth)

    Insert a new property for Jack, and examine the resultant properties.

    >>> av.insert_property(
    ...     jack, auth, name='known for', key='worst movie', value='The Two Jakes')
    >>> pp.pprint(av.retrieve_entity(jack)['Properties'])
    [   ['known for', 'No.1', 'The Shining'],
        ['fan of', '', 'Los Angeles Lakers'],
        ['fan of', '', 'Bob Dylan'],
        ['known for', '', 'Chinatown'],
        ['known for', 'worst movie', 'The Two Jakes']]

    Attempt to insert a property with a key that already exists.

    >>> av.insert_property(
    ...     jack, auth, name='known for', key='No.1', value="Prizzi's Honor")  
    AvialError: Error: Server reported APPLICATION error: Key already in list: No.1 while inserting property into entity <2906857743|167772516|1253605>with name='known for', key='No.1', value="Prizzi's Honor"

    Insert a new property at position 2.

    >>> av.insert_property(
    ...     jack, auth, name='known for', value='Mars Attacks!', index=2)
    >>> pp.pprint(av.retrieve_entity(jack)['Properties'])
    [   ['known for', 'No.1', 'The Shining'],
        ['known for', '', 'Mars Attacks!'],
        ['fan of', '', 'Los Angeles Lakers'],
        ['fan of', '', 'Bob Dylan'],
        ['known for', '', 'Chinatown'],
        ['known for', 'worst movie', 'The Two Jakes']]

    Insert a new property at a position well beyond the end.

    >>> av.insert_property(jack, auth, name='known for', key='last great role', value='The Departed', index=10)
    >>> pp.pprint(av.retrieve_entity(jack)['Properties'])
    [   ['known for', 'No.1', 'The Shining'],
        ['known for', '', 'Mars Attacks!'],
        ['fan of', '', 'Los Angeles Lakers'],
        ['fan of', '', 'Bob Dylan'],
        ['known for', '', 'Chinatown'],
        ['known for', 'worst movie', 'The Two Jakes'],
        ['known for', 'last great role', 'The Departed']]

    Look at the last child attribute instance.

    >>> pp.pprint(av.retrieve_entity(jack)['Attributes']['CHILD_ATTRIBUTE'][-1])
    {   'Properties': [['Born', '', '1992'], ['Mother', '', 'Rebecca Broussard']],
        'Values': ['Raymond']}

    Insert a new property on that last child attribute instance.

    >>> av.insert_property(
    ...     jack, auth, name='stepfather',  value='Alex Kelly', attribute=av.Attribute.CHILD)
    >>> pp.pprint(av.retrieve_entity(jack)['Attributes']['CHILD_ATTRIBUTE'][-1])
    {   'Properties': [   ['Born', '', '1992'],
                          ['Mother', '', 'Rebecca Broussard'],
                          ['stepfather', '', 'Alex Kelly']],
        'Values': ['Raymond']}

    Examine the fourth instance of child attribute.

    >>> pp.pprint(av.retrieve_entity(jack)['Attributes']['CHILD_ATTRIBUTE'][3])
    {'Values': ['Lorraine']}

    Insert a new property on that fourth instance.

    >>> av.insert_property(
    ...     jack, auth, name='Mother',  value='Rebecca Broussard', attribute=av.Attribute.CHILD,
    ...     instance=4)
    >>> pp.pprint(av.retrieve_entity(jack)['Attributes']['CHILD_ATTRIBUTE'][3])
    {'Properties': [['Mother', '', 'Rebecca Broussard']], 'Values': ['Lorraine']}

    Clean up the example and end the session.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """ 
    invoke(
        entity, method=Method.INSERT, parameter=Argument.PROPERTY,
        index=index, attribute=attribute, instance=instance, name=name, 
        key=key, value=value, authorization=authorization)

@manage_exceptions(
    'while removing property from entity {0}', check_for_naked_instance=True)
def remove_property(entity, authorization, *, attribute=None, instance=None, 
                    key=None, index=None):
    """
    remove_property(entity, authorization, *, attribute=None, instance=None, key=None, index=None)
    Remove a property from the entity.

    Remove a single property---a name/key/value triple---from the entity as a 
    whole, or from one of the entity's attributes.

    If ``key`` is provided, the property with that key is removed. If
    ``key`` is not provided but ``index`` is provided, the indexed property is
    removed. For example, if ``index`` is 5, the fifth property is removed. If
    neither ``key`` not ``index`` are provided, the last property is removed.

    Parameters
    ----------
    entity : Entity
        the entity whose property is removed.

    auth : Authorization
        authorization token permitting the removal of a property.

    attribute : Attribute or None, optional
        If provided, a property is removed from an attribute of the entity
        instead of from the entity as a whole, and in particular, removed 
        from the  attribute ``attribute``. The default is None: a property is
        removed from the entity as a whole.

    instance : int, optional
        If provided and ``attribute`` is also provided, a property is removed 
        from a particular
        instance of an attribute property. For example, if ``attribute`` is 
        ``Attribute.CHILD`` and ``instance`` is  
        2, a property is removed from the second instance of the child
        attribute. The default is None: a property is removed from the last
        instance of the attribute.

    key : str, optional
        If provided, the property with key ``key`` is removed. The default is
        None: remove the property at position ``index`` or the last
        property, if ``index`` is not provided.

    index : int, optional
        the position of the property to remove. The default is None: remove the 
        last property. Note that ``index`` is ignored if ``key`` is provided.

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``auth`` does not permit property removal, or ``attribute`` 
        is not an attribute, or an instance is specified but no attribute.

    See also
    --------
    :func:`insert_property` : insert a new property 

    :func:`property_name` : find the name of a property by its index

    :func:`property_key` : find the key of a property by its index

    :func:`property_value` : find the value of a property by its index

    :func:`property_count` : count the number of properties on an entity

    :func:`find_property` : find the position of a property with some name

    :func:`lookup_property` : find the value of a property by key 

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize()
    >>> import pprint
    >>> pp = pprint.PrettyPrinter(indent=4)

    Create an entity for Jack.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jacks_details = {
    ...     "Attributes":{
    ...         "SEX_ATTRIBUTE":[{"Values":["M"]}],
    ...         "AGE_ATTRIBUTE":[{"Values":["80"]}],
    ...         "HEIGHT_ATTRIBUTE":[{"Values":["177"]}], 
    ...         "LOCATION_ATTRIBUTE":[{"Values":["Los Angeles", "Aspen"]}],
    ...         "CHILD_ATTRIBUTE":[
    ...             {
    ...                 "Values": ["Jennifer"],
    ...                 "Properties": [ 
    ...                     ["Born","","1963"],
    ...                     ["Mother","","Sandra Knight"] 
    ...                 ]
    ...             },
    ...             {
    ...                 "Values": ["Caleb"],
    ...                 "Properties": [ 
    ...                     ["Born","","1970"],
    ...                     ["Paternity", "Paternity", "not established"],
    ...                     ["Mother","","Susan Anspach"],
    ...                 ]
    ...             },
    ...             {"Values": ["Honey"]},
    ...             {"Values": ["Lorraine"]},
    ...             {
    ...                 "Values": ["Raymond"],
    ...                 "Properties": [ 
    ...                     ["Born","","1992"],
    ...                     ["Mother","","Rebecca Broussard"] 
    ...                 ]
    ...             }]},
    ...     "Properties":[
    ...         ["known for","No.1","The Shining"],
    ...         ["fan of","","Los Angeles Lakers"],
    ...         ["fan of", "", "Bob Dylan"],
    ...         ["known for","","Chinatown"]
    ...         ]
    ... }
    >>> av.store_entity(jack, jacks_details, auth)

    Examine at Jack's properties.

    >>> pp.pprint(av.retrieve_entity(jack)['Properties'])
    [   ['known for', 'No.1', 'The Shining'],
        ['fan of', '', 'Los Angeles Lakers'],
        ['fan of', '', 'Bob Dylan'],
        ['known for', '', 'Chinatown']]

    Remove the last of Jack's properties.

    >>> av.remove_property(jack, auth)
    >>> pp.pprint(av.retrieve_entity(jack)['Properties'])
    [   ['known for', 'No.1', 'The Shining'],
        ['fan of', '', 'Los Angeles Lakers'],
        ['fan of', '', 'Bob Dylan']]

    Remove Jack's second property.

    >>> av.remove_property(jack, auth, index=2)
    >>> pp.pprint(av.retrieve_entity(jack)['Properties'])
    [['known for', 'No.1', 'The Shining'], ['fan of', '', 'Bob Dylan']]

    Remove the property with key 'No.1'. Afterwards, Jack has only a single
    property.

    >>> av.remove_property(jack, auth, key='No.1', index=2)
    >>> pp.pprint(av.retrieve_entity(jack)['Properties'])
    [['fan of', '', 'Bob Dylan']]

    Remove the last of Jack's properties, by providing an index that is greater
    than the property count. Afterwards, Jack has no properties at all.

    >>> av.remove_property(jack, auth, index=12)
    >>> av.property_count(jack)
    0
    
    Look at Jack's child attribute.

    >>> pp.pprint(av.retrieve_entity(jack)['Attributes']['CHILD_ATTRIBUTE'])
    [   {   'Properties': [['Born', '', '1963'], ['Mother', '', 'Sandra Knight']],
            'Values': ['Jennifer']},
        {   'Properties': [   ['Born', '', '1970'],
                              ['Paternity', 'Paternity', 'not established'],
                              ['Mother', '', 'Susan Anspach']],
            'Values': ['Caleb']},
        {'Values': ['Honey']},
        {'Values': ['Lorraine']},
        {   'Properties': [   ['Born', '', '1992'],
                              ['Mother', '', 'Rebecca Broussard']],
            'Values': ['Raymond']}]

    Remove the last property from the last attribute instance. 

    >>> av.remove_property(jack, auth, attribute=av.Attribute.CHILD)
    >>> pp.pprint(av.retrieve_entity(jack)['Attributes']['CHILD_ATTRIBUTE'])
    [   {   'Properties': [['Born', '', '1963'], ['Mother', '', 'Sandra Knight']],
            'Values': ['Jennifer']},
        {   'Properties': [   ['Born', '', '1970'],
                              ['Paternity', 'Paternity', 'not established'],
                              ['Mother', '', 'Susan Anspach']],
            'Values': ['Caleb']},
        {'Values': ['Honey']},
        {'Values': ['Lorraine']},
        {'Properties': [['Born', '', '1992']], 'Values': ['Raymond']}]

    Remove the last property from the first attribute instance.

    >>> av.remove_property(jack, auth, attribute=av.Attribute.CHILD, instance=1)
    >>> pp.pprint(av.retrieve_entity(jack)['Attributes']['CHILD_ATTRIBUTE'])
    [   {'Properties': [['Born', '', '1963']], 'Values': ['Jennifer']},
        {   'Properties': [   ['Born', '', '1970'],
                              ['Paternity', 'Paternity', 'not established'],
                              ['Mother', '', 'Susan Anspach']],
            'Values': ['Caleb']},
        {'Values': ['Honey']},
        {'Values': ['Lorraine']},
        {'Properties': [['Born', '', '1992']], 'Values': ['Raymond']}]

    Remove the property with key 'Paternity' from the second attribute instance.

    >>> av.remove_property(
    ...     jack, auth, attribute=av.Attribute.CHILD, instance=2, key='Paternity')
    >>> pp.pprint(av.retrieve_entity(jack)['Attributes']['CHILD_ATTRIBUTE'])
    [   {'Properties': [['Born', '', '1963']], 'Values': ['Jennifer']},
        {   'Properties': [['Born', '', '1970'], ['Mother', '', 'Susan Anspach']],
            'Values': ['Caleb']},
        {'Values': ['Honey']},
        {'Values': ['Lorraine']},
        {'Properties': [['Born', '', '1992']], 'Values': ['Raymond']}]

    Remove the first property from the second attribute instance.

    >>> av.remove_property(
    ...     jack, auth, attribute=av.Attribute.CHILD, instance=2, index=1)
    >>> pp.pprint(av.retrieve_entity(jack)['Attributes']['CHILD_ATTRIBUTE'])
    [   {'Properties': [['Born', '', '1963']], 'Values': ['Jennifer']},
        {'Properties': [['Mother', '', 'Susan Anspach']], 'Values': ['Caleb']},
        {'Values': ['Honey']},
        {'Values': ['Lorraine']},
        {'Properties': [['Born', '', '1992']], 'Values': ['Raymond']}]

    Clean up the example and end the session.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """ 
    invoke(
        entity, method=Method.REMOVE, parameter=Argument.PROPERTY, 
        attribute=attribute, instance=instance, index=index, 
        key=key, authorization=authorization)

@manage_exceptions(
    'while replacing property on entity {0} with name {1} key {2} value {3}', 
    check_for_naked_instance=True)
def replace_property(entity, name, key, value, authorization, *, 
                     attribute=None, instance=None, index=None):  
    """
    replace_property(entity, name, key, value, authorization, *, attribute=None, instance=None, index=None)
    """
    invoke(
        entity, Method.REPLACE, parameter=Argument.PROPERTY, name=name, key=key,
        value=value, attribute=attribute, instance=instance, index=index, 
        authorization=authorization)

@manage_exceptions(
    'while updating property on entity {0} with name {1} and value {2}', 
    check_for_naked_instance=True)
def update_property(entity, name, value, authorization, *, attribute=None, 
                    instance=None, key=None):
    """
    update_property(entity, name, value, authorization, *, attribute=None, instance=None, key=None)
    Update an existing property, or insert new one if property does not exist.

    Update an existing property---a name/key/value triple---on an entity as a
    whole, or on one of the entity's attributes.
    If the property already exists, update its name and value. If the property
    does not exist, insert a new one at the end of the existing properties.

    If ``key`` is provided, the property with that key is updated with the
    specified name and value, if such
    a property exists. If no property with that key exists, a new property
    is inserted, with name, key, and value as specified.

    If ``key`` is not provided, the first property with a name the same as
    ``name`` is updated with the new value, if such a property exists. 
    If no property with that name exists, a new property is inserted, with 
    name and value as specified.

    Parameters
    ----------
    entity : Entity
        the entity that has the property to be updated

    name : str 
        the name of the property. ``name`` plays two roles, either specifying
        which property is to be updated, or providing the new name for an 
        updated property. If ``key`` is
        not specified, the properties are searched by name. If a property 
        with the matching name is found, the value of that property is
        changed to that specified as ``value``. If no such property is found,
        a new property is inserted, with name and value as specified. If ``key``
        is specified, and a property with that key exists, its name is replaced
        with the name specified. If no such property exists, a new property is
        inserted, with name, key and value as specified.

    value : int or float or bool or str or Entity or list or dict
        the value of the property. If an existing property is updated (either
        specified by ``key`` or by ``name``), the property's value is changed
        to the value specified. If a new property is inserted, the new property
        takes the value specified

    auth : Authorization
        authorization token permitting the updating of a property

    key : str, optional
        the key of the property to update. If not present on the entity (or
        on the attribute of the entity if ``attribute`` is specified), a new
        property is inserted at the end.

    attribute : Attribute, optional
        If provided, update a property on an attribute of the entity
        instead of on the entity as a whole, and in particular update a
        property on the attribute provided by ``attribute``. The default 
        is None: update a property on the entity as a whole.

    instance : int, optional
        If provided and ``attribute`` is also provided, update a property
        on a particular
        instance of an attribute property. For example, if ``attribute`` is 
        ``Attribute.CHILD`` and ``instance`` is  
        2, update one of the properties on the second instance of the child
        attribute. The default is None: update a property on the last 
        instance of the attribute.

    Returns
    -------
    None

    Raises
    ------
    AvialError        
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``auth`` is not a valid  authorization,  or ``attribute`` 
        is not an attribute, or an instance is specified but no attribute.

    See also
    --------
    :func:`insert_property` : insert a new property 

    :func:`remove_property` : remove an existing property

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize()
    >>> import pprint
    >>> pp = pprint.PrettyPrinter(indent=4)

    Create an entity for Jack Nicholson

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jacks_details = {
    ...     "Attributes":{
    ...         "SEX_ATTRIBUTE":[{"Values":["M"]}],
    ...         "AGE_ATTRIBUTE":[{"Values":["80"]}],
    ...         "HEIGHT_ATTRIBUTE":[{"Values":["177"]}], 
    ...         "LOCATION_ATTRIBUTE":[{"Values":["Los Angeles", "Aspen"]}],
    ...         "CHILD_ATTRIBUTE":[
    ...             {
    ...                 "Values": ["Jennifer"],
    ...                 "Properties": [ 
    ...                     ["Born","","1963"],
    ...                     ["Mother","","Sandra Knight"] 
    ...                 ]
    ...             },
    ...             {
    ...                 "Values": ["Caleb"],
    ...                 "Properties": [ 
    ...                     ["Born","","1970"],
    ...                     ["Paternity", "Paternity", "not established"],
    ...                     ["Mother","","Susan Anspach"],
    ...                 ]
    ...             },
    ...             {"Values": ["Honey"]},
    ...             {"Values": ["Lorraine"]},
    ...             {
    ...                 "Values": ["Raymond"],
    ...                 "Properties": [ 
    ...                     ["Born","","1992"],
    ...                     ["Mother","","Rebecca Broussard"] 
    ...                 ]
    ...             }]},
    ...     "Properties":[
    ...         ["known for","most popular role","The Shining"],
    ...         ["fan of","","Los Angeles Lakers"],
    ...         ["fan of", "", "Bob Dylan"],
    ...         ["known for","best performance","Chinatown"]
    ...         ]
    ... }
    >>> av.store_entity(jack, jacks_details, auth)

    Take a look at Jack's properties.

    >>> pp.pprint(av.retrieve_entity(jack)['Properties'])
    [   ['known for', 'most popular role', 'The Shining'],
        ['fan of', '', 'Los Angeles Lakers'],
        ['fan of', '', 'Bob Dylan'],
        ['known for', 'best performance', 'Chinatown']]

    Update the best performance property, with a dubious choice.

    >>> av.update_property(
    ...     jack, '', 'Mars Attacks!', auth, key="best performance")
    >>> pp.pprint(av.retrieve_entity(jack)['Properties'])
    [   ['known for', 'most popular role', 'The Shining'],
        ['fan of', '', 'Los Angeles Lakers'],
        ['fan of', '', 'Bob Dylan'],
        ['', 'best performance', 'Mars Attacks!']]

    Update the (non-existing) worst performance property, resulting in a new
    property inserted at the end.

    >>> av.update_property(
    ...     jack, 'pretty bad', 'The Two Jakes', auth,  key="worst performance")
    >>> pp.pprint(av.retrieve_entity(jack)['Properties'])
    [   ['known for', 'most popular role', 'The Shining'],
        ['fan of', '', 'Los Angeles Lakers'],
        ['fan of', '', 'Bob Dylan'],
        ['', 'best performance', 'Mars Attacks!'],
        ['pretty bad', 'worst performance', 'The Two Jakes']]

    Update the first property with name "fan of".

    >>> av.update_property(jack, 'fan of, value='New York Yankees', auth)
    >>> pp.pprint(av.retrieve_entity(jack)['Properties'])
    [   ['known for', 'most popular role', 'The Shining'],
        ['fan of', '', 'New York Yankees'],
        ['fan of', '', 'Bob Dylan'],
        ['', 'best performance', 'Mars Attacks!'],
        ['pretty bad', 'worst performance', 'The Two Jakes']]

    Attempt to update the property with name "also known for", resulting
    in a new property inserted at the end.

    >>> av.update_property(jack, 'also known for', 'The Departed', auth)
    >>> pp.pprint(av.retrieve_entity(jack)['Properties'])
    [   ['known for', 'most popular role', 'The Shining'],
        ['fan of', '', 'New York Yankees'],
        ['fan of', '', 'Bob Dylan'],
        ['', 'best performance', 'Mars Attacks!'],
        ['pretty bad', 'worst performance', 'The Two Jakes'],
        ['also known for', '', 'The Departed']]

    Take a look at the second child attribute

    >>> pp.pprint(av.retrieve_entity(jack)['Attributes']['CHILD_ATTRIBUTE'][1])
    {   'Properties': [   ['Born', '', '1970'],
                          ['Paternity', 'Paternity', 'not established'],
                          ['Mother', '', 'Susan Anspach']],
        'Values': ['Caleb']}

    Update the paternity property of the second child attribute.

    >>> av.update_property(
    ...     jack, 'Paternity', 'established', auth, 
    ...     attribute=av.Attribute.CHILD, instance=2, key='Paternity')
    >>> pp.pprint(av.retrieve_entity(jack)['Attributes']['CHILD_ATTRIBUTE'][1])
    {   'Properties': [   ['Born', '', '1970'],
                          ['Paternity', 'Paternity', 'established'],
                          ['Mother', '', 'Susan Anspach']],
        'Values': ['Caleb']}

    Clean up the example and end the session.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """ 
    invoke(
        entity, method=Method.UPDATE, attribute=attribute, 
        instance=instance, name=name, key=key, value=value,
        authorization=authorization)

@manage_exceptions(
    'while looking up property with key {1} on entity {0}', 
    check_for_naked_instance=True)
def lookup_property(entity, key, *, attribute=None, instance=None):
    """
    lookup_property(entity, key, *, attribute=None, instance=None)
    Find the value of a property identified by key.

    Lookup a property by key, and return two values. If the property is found,
    return True and the value of that property. If not found, return False
    and None.

    Parameters
    ----------
    entity : Entity
        The entity whose properties are searched for ``name``.

    key : str
        the key by which to find the property

    attribute : Attribute or None, optional
        If provided, find a property on an attribute of the entity
        instead of on the entity as a whole, and in particular find a property
        on the attribute provided by ``attribute``. The default 
        is None: find a property on the entity as a whole.

    instance : int, optional
        If provided and ``attribute`` is also provided, find a property
        on a particular
        instance of an attribute property. For example, if ``attribute`` is 
        ``Attribute.ADDRESS`` and ``instance`` is  
        3, the property is to be found on the third instance of the address
        attribute. The default is None: find a property on the last 
        instance of the attribute.

    Returns
    -------
    key_found : bool
        whether a property with key ``key`` was found

    value : int or float or bool or str or Entity or list or dict or None
        the value of the property with the key ``key``, or None if no such key
        exists

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``key`` is not a string, or ``attribute`` 
        is not an attribute, or an instance is specified but no attribute.

    See also
    --------
    :func:`find_property` : find the position of a property with some name

    :func:`property_count` : count the number of properties on an entity

    :func:`property_name` : find the name of a property by its index

    :func:`property_key` : find the key of a property by its index

    :func:`property_value` : find the value of a property by its index

    :func:`insert_property` : insert a new property 

    :func:`remove_property` : remove an existing property

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize() 

    Create an entity for Jack, and give him attributes and properties.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jacks_details = {
    ...     "Attributes":{
    ...         "SEX_ATTRIBUTE":[{"Values":["M"]}],
    ...         "AGE_ATTRIBUTE":[{"Values":["80"]}],
    ...         "HEIGHT_ATTRIBUTE":[{"Values":["177"]}], 
    ...         "LOCATION_ATTRIBUTE":[{"Values":["Los Angeles", "Aspen"]}],
    ...         "CHILD_ATTRIBUTE":[
    ...             {
    ...                 "Values": ["Jennifer"],
    ...                 "Properties": [ 
    ...                     ["Born","","1963"],
    ...                     ["Mother","","Sandra Knight"] 
    ...                 ]
    ...             },
    ...             {
    ...                 "Values": ["Caleb"],
    ...                 "Properties": [ 
    ...                     ["Born","","1970"],
    ...                     ["Paternity", "Paternity", "not established"],
    ...                     ["Mother","","Susan Anspach"],
    ...                 ]
    ...             },
    ...             {"Values": ["Honey"]},
    ...             {"Values": ["Lorraine"]},
    ...             {
    ...                 "Values": ["Raymond"],
    ...                 "Properties": [ 
    ...                     ["Born","","1992"],
    ...                     ["Mother","","Rebecca Broussard"] 
    ...                 ]
    ...             }]},
    ...     "Properties":[
    ...         ["known for","most popular role","The Shining"],
    ...         ["fan of","","Los Angeles Lakers"],
    ...         ["fan of", "", "Bob Dylan"],
    ...         ["known for","best performance","Chinatown"]
    ...         ]
    ... }
    >>> av.store_entity(jack, jacks_details, auth)

    Lookup the value of Jack's best performance. Note that the result includes
    both that the property is found and the value of the property.

    >>> av.lookup_property(jack, 'best performance')
    (True, 'Chinatown')

    Lookup the value of Jack's favorite NFL team.

    >>> av.lookup_property(jack, 'favorite NFL team')
    (False, None)

    Lookup the value of Jack's paternity of his second child.

    >>> av.lookup_property(
    ...     jack, 'Paternity', attribute=av.Attribute.CHILD, instance=2)
    (True, 'not established')

    Lookup the value of Jack's paternity of his last child.

    >>> av.lookup_property(jack, 'Paternity', attribute=av.Attribute.CHILD)
    (False, None)

    Clean up.
    
    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """ 
    with suppress_console_error_logging('Server reported APPLICATION error'):
        try:
            val = property_value(
                entity, attribute=attribute, instance=instance, key=key,
                handle_exceptions=False)
            return True, val
        except at.AvesTerraError as err:
            if 'Index/key not found' in err.message:
                return False, None 
            elif 'Attribute not found' in err.message:
                return False, None
            else:
                raise  

@manage_exceptions(
    'while sorting properties on entity {0}', check_for_naked_instance=True)
def sort_property(entity, auth, *, attribute=None, instance=None, name=None, 
                  key=None, value=None, options=None, timeout=None):
    """
    sort_property(entity, auth, *, attribute=None, instance=None, name=None, key=None, value=None, options=None, timeout=None)
    Sort the order of properties.

    Sort the order of properties of the entity, either the properties on a 
    particular attribute instance, or the properties for the entity as a 
    whole.

    The attributes ``name``, ``key``, and ``value`` are used to indicate the
    criteria by which properties are sorted, either sorting by name or sorting 
    by key or sorting by value. If none of these three attributes are provided,
    the call to :func:`sort_property` has no effect: the property order remains
    the same.

    If multiple criteria are provided---e.g. if both
    ``name`` and ``value`` are provided---the properties are sorted by multiple
    criteria. When properties are sorted by multiple criteria, the first sort
    criteria is value---if supplied, then key---if supplied, and then name---if
    supplied. For example, if both ``name`` and ``value`` are provided, the
    properties are sorted by value, and in cases where multiple properties have 
    the same value, those properties are then sorted by name. 

    If ``attribute`` is not provided, the properties associated with the 
    entity as a whole are sorted. If ``attribute`` is provided, only the 
    properties associate with a single attribute instance are sorted, an
    instance of the attribute ``attribute``. If ``instance`` is also provided,
    the properties of the numbered instance are sorted. For example, 
    if ``attribute`` is ``attribute.POPULATION`` and ``instance`` is 2, the
    properties of the second population instance are sorted. If ``instance``
    is not provided, the properties of the last instance of the attribute are
    sorted.

    Parameters
    ----------
    entity : Entity
        the entity to be sorted

    auth : Authorization
        an object that authorizes changing the order of properties

    attribute : Attribute or None, optional
        if provided, sort the properties of an attribute instance, an instance
        of ``attribute``. The default is None: sort the properties on the entity
        itself.

    instance : int, optional
        if provided and ``attribute`` is also provided, sort this particular
        attribute instance. For example, if ``attribute`` is ``Attribute.CHILD``
        and ``instance`` is 3, the properties of the third child instance are
        sorted. The default is None: sort the last instance of ``attribute``.

    name : str, optional
        if provided, sort the properties by their names. If ``name`` is 
        provided, it indicates how the properties are to be sorted, either 
        alphanumerically---if ``name`` is 'STRING', or as integers---if ``name``
        is 'INTEGER', or as floating point values---if ``name`` is 'FLOAT', or
        as booleans---if ``name`` is 'BOOLEAN', or as entities, if ``name``
        is 'ENTITY'. A preceding minus indicates the properties are sorted
        backwards. For example is ``name`` is '-STRING', the properties are 
        sorted by name alphanumerically, backwards from Z to A. The default is 
        None: don't use names as a sort criteria. See examples below.

    key : str, optional
        if provided, sort the properties by their keys. If ``key`` is 
        provided, it indicates how the properties are to be sorted, either 
        alphanumerically---if ``key`` is 'STRING', or as integers---if ``key``
        is 'INTEGER', or as floating point values---if ``key`` is 'FLOAT', or
        as booleans---if ``key`` is 'BOOLEAN' (although properties with 
        boolean keys would seem quite unlikely), or as entities, if ``key``
        is 'ENTITY'. A preceding minus indicates the properties are sorted
        backwards. For example is ``key`` is '-STRING', the properties are 
        sorted by key alphanumerically, backwards from Z to A. The default is 
        None: don't use keys as a sort criteria. See examples below.

    value : str, optional
        if provided, sort the properties by their values. If ``value`` is 
        provided, it indicates how the properties are to be sorted, either 
        alphanumerically---if ``value`` is 'STRING', or as integers---if 
        ``value`` is 'INTEGER', or as floating point values---if ``value`` 
        is 'FLOAT', or as booleans---if ``value`` is 'BOOLEAN', or as entities,
        if ``value`` is 'ENTITY'. A preceding minus indicates the properties 
        are sorted backwards. For example is ``key`` is '-STRING', the 
        properties are sorted by value alphanumerically, backwards from Z to A.
        The default is None: don't use values as a sort criteria. See 
        examples below.

    timeout : int, optional
        How long (in seconds) should the sort be allowed to run, before it is
        interrupted? The default is None: sort with a 60 second timeout.

    Returns
    -------
    None    

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``auth`` is not a valid  authorization, or ``attribute`` 
        is not an attribute, or an instance is specified but no attribute, or
        the sort times out before completing.

    See also
    --------
    :func:`create_entity` : create an entity 

    :func:`store_entity` : set attributes, properties, and values of an entity

    :func:`retrieve_entity` : return all attributes, properties, and values of an entity, in :ref:`comprehensive format <comprehensive_format>`

    :func:`erase_entity` : erase all attributes, properties, and values of an entity


    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize()
    >>> import pprint
    >>> pp = pprint.PrettyPrinter(indent=4, compact=True)

    Create three entities.

    >>> clippers = av.create_entity(
    ...     'Los Angeles Clippers', av.Class.ORGANIZATION, av.Subclass.TEAM,
    ...     auth, outlet=av.object_outlet(), autosave=True)
    >>> sparks = av.create_entity(
    ...     'Los Angeles Sparks', av.Class.ORGANIZATION, av.Subclass.TEAM,
    ...     auth, outlet=av.object_outlet(), autosave=True)
    >>> los_angeles = av.create_entity(
    ...     'Los Angeles', av.Class.PLACE, av.Subclass.CITY, auth,
    ...     outlet=av.object_outlet(), autosave=True)

    Set the attributes and properties of Los Angeles.

    >>> la_stuff = {
    ...         'Properties': [
    ...             ['nickname', 'most popular nickname', 'city of angels'],
    ...             ['nickname', '', 'The Big Orange'],
    ...             ['nickname', '', 'La-la-land'],
    ...             ['nickname', '', 'Tinseltown'],
    ...             ['basketball team', '', sparks],
    ...             ['basketball team', '', clippers],
    ...             ['newspaper', 'largest circulation newspaper', 
    ...              'Los Angeles Times'],
    ...             ['newspaper', '', 'Variety'],
    ...             ['nickname', 'least popular nickname', 'Shaky Town'],
    ...             ],
    ...         'Attributes': {
    ...                     'POPULATION_ATTRIBUTE': [
    ...                         {'Properties': [
    ...                             # remove str()s on comprehensive format
    ...                             ['2010 census', '2010 census', str(3_792_621)], 
    ...                             ['2000 census', '2000 census', str(3_694_820)], 
    ...                             ['1950 census', '1950 census', str(1_970_358)], 
    ...                             ['1960 census', '1960 census', str(2_479_015)], 
    ...                             ['1970 census', '1970 census', str(2_816_061)], 
    ...                             ['1980 census', '1980 census', str(2_966_850)], 
    ...                             ['1990 census', '1990 census', str(3_485_398)], 
    ...                             ['1900 census', '1900 census', str(102_500)], 
    ...                             ['1910 census', '1910 census', str(319_200)], 
    ...                             ['1920 census', '1920 census', str(576_700)], 
    ...                             ['1930 census', '1930 census', str(1_238_048)], 
    ...                             ['1940 census', '1940 census', str(1_504_277)], 
    ...                             ]},
    ...                         {'Properties': [
    ...                             # remove str()s on comprehensive format
    ...                             ['urban area', '', str(12_150_996)],
    ...                             ['metro area', '', str(13_131_431)],
    ...                             ['combined statistical area', 'most inclusive',
    ...                              str(18_679_763)],
    ...                             ['city', 'city, 2017 estimate', str(3_999_759)],
    ...                             ['city', 'city, 2010 census', str(3_792_621)]
    ...                             ]},
    ...                     ]
    ...                 }
    ...     }
    >>> av.store_entity(los_angeles, la_stuff, auth)

    Examine the properties.

    >>> pp.pprint(av.retrieve_entity(los_angeles)['Properties'])
    [   ['nickname', 'most popular nickname', 'city of angels'],
        ['nickname', '', 'The Big Orange'], 
        ['nickname', '', 'La-la-land'],
        ['nickname', '', 'Tinseltown'],
        ['basketball team', '', '<2906857743|167772516|1253602>'],
        ['basketball team', '', '<2906857743|167772516|1253601>'],
        ['newspaper', 'largest circulation newspaper', 'Los Angeles Times'],
        ['newspaper', '', 'Variety'],
        ['nickname', 'least popular nickname', 'Shaky Town']]

    Sort the properties by name, alphabetically.

    >>> av.sort_property(los_angeles, auth, name='STRING')
    >>> pp.pprint(av.retrieve_entity(los_angeles)['Properties'])
    [   ['basketball team', '', '<2906857743|167772516|1253602>'],
        ['basketball team', '', '<2906857743|167772516|1253601>'],
        ['newspaper', 'largest circulation newspaper', 'Los Angeles Times'],
        ['newspaper', '', 'Variety'],
        ['nickname', 'most popular nickname', 'city of angels'],
        ['nickname', '', 'The Big Orange'], 
        ['nickname', '', 'La-la-land'],
        ['nickname', '', 'Tinseltown'],
        ['nickname', 'least popular nickname', 'Shaky Town']]

    Sort the properties by key. All the properties without a key are
    now first, before the properties with a key.

    >>> av.sort_property(los_angeles, auth, key='STRING')
    >>> pp.pprint(av.retrieve_entity(los_angeles)['Properties'])
    [   ['basketball team', '', '<2906857743|167772516|1253602>'],
        ['basketball team', '', '<2906857743|167772516|1253601>'],
        ['newspaper', '', 'Variety'], 
        ['nickname', '', 'The Big Orange'],
        ['nickname', '', 'La-la-land'], 
        ['nickname', '', 'Tinseltown'],
        ['newspaper', 'largest circulation newspaper', 'Los Angeles Times'],
        ['nickname', 'least popular nickname', 'Shaky Town'],
        ['nickname', 'most popular nickname', 'city of angels']]

    Sort by value. Note that “city of angels” appears after “Variety” rather 
    than before “La-la-land”. STRING sort arranges all lowercase characters 
    after all uppercase characters, so “Dog” comes before “caT”, and “caT” 
    comes before “camel”.

    >>> av.sort_property(los_angeles, auth, value='STRING')
    >>> pp.pprint(av.retrieve_entity(los_angeles)['Properties'])
    [   ['basketball team', '', '<2906857743|167772516|1253601>'],
        ['basketball team', '', '<2906857743|167772516|1253602>'],
        ['nickname', '', 'La-la-land'],
        ['newspaper', 'largest circulation newspaper', 'Los Angeles Times'],
        ['nickname', 'least popular nickname', 'Shaky Town'],
        ['nickname', '', 'The Big Orange'], 
        ['nickname', '', 'Tinseltown'],
        ['newspaper', '', 'Variety'],
        ['nickname', 'most popular nickname', 'city of angels']]

    Sort by both name and key. Key takes precedence. The properties with the 
    same (empty string) key are sorted by name.

    >>> av.sort_property(los_angeles, auth, name='STRING', key='STRING')
    >>> pp.pprint(av.retrieve_entity(los_angeles)['Properties'])
    [   ['basketball team', '', '<2906857743|167772516|1253601>'],
        ['basketball team', '', '<2906857743|167772516|1253602>'],
        ['newspaper', '', 'Variety'], 
        ['nickname', '', 'The Big Orange'],
        ['nickname', '', 'Tinseltown'], 
        ['nickname', '', 'La-la-land'],
        ['newspaper', 'largest circulation newspaper', 'Los Angeles Times'],
        ['nickname', 'least popular nickname', 'Shaky Town'],
        ['nickname', 'most popular nickname', 'city of angels']]

    Before we sort the population properties, look at the order.

    >>> pp.pprint(av.retrieve_entity(los_angeles)['Attributes'][
    ...     'POPULATION_ATTRIBUTE'])
    [   {   'Properties': [   ['2010 census', '2010 census', '3792621'],
                              ['2000 census', '2000 census', '3694820'],
                              ['1950 census', '1950 census', '1970358'],
                              ['1960 census', '1960 census', '2479015'],
                              ['1970 census', '1970 census', '2816061'],
                              ['1980 census', '1980 census', '2966850'],
                              ['1990 census', '1990 census', '3485398'],
                              ['1900 census', '1900 census', '102500'],
                              ['1910 census', '1910 census', '319200'],
                              ['1920 census', '1920 census', '576700'],
                              ['1930 census', '1930 census', '1238048'],
                              ['1940 census', '1940 census', '1504277']]},
        {   'Properties': [   ['urban area', '', '12150996'],
                              ['metro area', '', '13131431'],
                              [   'combined statistical area', 'most inclusive',
                                  '18679763'],
                              ['city', 'city, 2017 estimate', '3999759'],
                              ['city', 'city, 2010 census', '3792621']]}]

    Look at the properties of the last instance.

    >>> pp.pprint(av.retrieve_entity(los_angeles)['Attributes'][
    ...     'POPULATION_ATTRIBUTE'][-1]['Properties'])
    [   ['urban area', '', '12150996'], 
        ['metro area', '', '13131431'],
        ['combined statistical area', 'most inclusive', '18679763'],
        ['city', 'city, 2017 estimate', '3999759'],
        ['city', 'city, 2010 census', '3792621']]

    Sort the properties of the last population instance by name.

    >>> av.sort_property(los_angeles, auth, attribute=av.Attribute.POPULATION, name='STRING')
    >>> pp.pprint(av.retrieve_entity(los_angeles)['Attributes'][
    ...     'POPULATION_ATTRIBUTE'][-1]['Properties'])
    [   ['city', 'city, 2017 estimate', '3999759'],
        ['city', 'city, 2010 census', '3792621'],
        ['combined statistical area', 'most inclusive', '18679763'],
        ['metro area', '', '13131431'], 
        ['urban area', '', '12150996']]

    Sort by value. Note that 18.7 million is sorted before 3.7 million, because
    the values are interpreted as strings.

    >>> av.sort_property(los_angeles, auth, attribute=av.Attribute.POPULATION, value='STRING')
    >>> pp.pprint(av.retrieve_entity(los_angeles)['Attributes'][
    ...     'POPULATION_ATTRIBUTE'][-1]['Properties']) 
    [   ['urban area', '', '12150996'], 
        ['metro area', '', '13131431'],
        ['combined statistical area', 'most inclusive', '18679763'],
        ['city', 'city, 2010 census', '3792621'],
        ['city', 'city, 2017 estimate', '3999759']]

    Sort by value, interpreting the values as integers instead of strings.

    >>> av.sort_property(los_angeles, auth, attribute=av.Attribute.POPULATION, value='INTEGER')
    >>> pp.pprint(av.retrieve_entity(los_angeles)['Attributes'][
    ...     'POPULATION_ATTRIBUTE'][-1]['Properties'])
    [   ['city', 'city, 2010 census', '3792621'],
        ['city', 'city, 2017 estimate', '3999759'], 
        ['urban area', '', '12150996'],
        ['metro area', '', '13131431'],
        ['combined statistical area', 'most inclusive', '18679763']]

    Before we sort the properties of the first instance of the
    population attribute, consider their haphazard initial order.

    >>> pp.pprint(av.retrieve_entity(los_angeles)['Attributes'][
    ...     'POPULATION_ATTRIBUTE'][0]['Properties'])
    [   ['2010 census', '2010 census', '3792621'],
        ['2000 census', '2000 census', '3694820'],
        ['1950 census', '1950 census', '1970358'],
        ['1960 census', '1960 census', '2479015'],
        ['1970 census', '1970 census', '2816061'],
        ['1980 census', '1980 census', '2966850'],
        ['1990 census', '1990 census', '3485398'],
        ['1900 census', '1900 census', '102500'],
        ['1910 census', '1910 census', '319200'],
        ['1920 census', '1920 census', '576700'],
        ['1930 census', '1930 census', '1238048'],
        ['1940 census', '1940 census', '1504277']]

    Sort the properties.

    >>> av.sort_property(
    ...     los_angeles, auth, attribute=av.Attribute.POPULATION, 
    ...     instance=1, name='STRING')
    >>> pp.pprint(av.retrieve_entity(los_angeles)['Attributes'][
    ...     'POPULATION_ATTRIBUTE'][0]['Properties'])
    [   ['1900 census', '1900 census', '102500'],
        ['1910 census', '1910 census', '319200'],
        ['1920 census', '1920 census', '576700'],
        ['1930 census', '1930 census', '1238048'],
        ['1940 census', '1940 census', '1504277'],
        ['1950 census', '1950 census', '1970358'],
        ['1960 census', '1960 census', '2479015'],
        ['1970 census', '1970 census', '2816061'],
        ['1980 census', '1980 census', '2966850'],
        ['1990 census', '1990 census', '3485398'],
        ['2000 census', '2000 census', '3694820'],
        ['2010 census', '2010 census', '3792621']]

    Clean up the example, and end the session.

    >>> av.delete_entity(los_angeles, auth)
    >>> av.finalize()
    """  
    invoke(
        entity, Method.SORT, attribute=attribute, instance=instance, name=name,
        key=key, value=value, options=options, timeout=timeout, 
        authorization=auth)

@manage_exceptions(
    'while finding name of property on entity {0}', 
    check_for_naked_instance=True)
def property_name(entity, *, attribute=None, instance=None, key=None, 
                  index=None):
    """
    property_name(entity, *, attribute=None, instance=None, key=None, index=None)
    Return the name of a property.

    Return the name of the property at position ``index``, as a string. 
    Alternatively, return the name of the property with key ``key``. If there
    is no such property, raise an error. 

    Parameters
    ----------
    entity : Entity
        the entity whose property has the name.

    attribute : Attribute, optional
        If provided, return the name of an attribute property instead of an
        entity property, and in particular the name of the attribute property
        ``attribute``. The default is None: use the entity property.

    instance : int, optional
        If provided and ``attribute`` is also provided, return the name of 
        a particular
        instance of an attribute property. For example, if ``attribute`` is 
        ``Attribute.CHILD`` and ``instance`` is  
        2, the name is found in the second instance of the child attribute.
        The default is None: use the last instance.

    key : str, optional
        If provided, return the name of the property with that key.

    index : int, optional
        If provided, find the name of the property at the ``index`` position.
        For example, if ``index`` is 2, the name of the second property is
        found.  If not provided,
        and ``key`` is also not provided, the name of the last property is
        returned.

    Returns
    -------
    str
        the name of the property at the position, or with that key

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``attribute`` 
        is not an attribute, or an instance is specified but no attribute, or 
        no such ``key`` is known, or no such ``index`` is known.

    See also
    --------
    :func:`property_key` : find the key of a property

    :func:`property_value` : find the value of a property 

    :func:`insert_property` : insert a new property 

    :func:`remove_property` : remove an existing property

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize()

    Create an entity for Jack, and give him attributes and properties.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jacks_details = {
    ...     "Attributes":{
    ...         "AGE_ATTRIBUTE":[{"Values":["80"]}],
    ...         "CHILD_ATTRIBUTE":[
    ...             {
    ...                 "Values": ["Jennifer"],
    ...                 "Properties": [ 
    ...                     ["Born","","1963"],
    ...                     ["Mother","","Sandra Knight"] 
    ...                 ]
    ...             },
    ...             {
    ...                 "Values": ["Caleb"],
    ...                 "Properties": [ 
    ...                     ["Born","","1970"],
    ...                     ["Paternity", "open question 2", "not established"],
    ...                     ["Mother","","Susan Anspach"],
    ...                 ]
    ...             },
    ...             {"Values": ["Honey"]},
    ...             {"Values": ["Lorraine"]},
    ...             {
    ...                 "Values": ["Raymond"],
    ...                 "Properties": [ 
    ...                     ["Born","","1992"],
    ...                     ["Mother","","Rebecca Broussard"] 
    ...                 ]
    ...             }]},
    ...     "Properties":[
    ...         ["known for","No.1","The Shining"],
    ...         ["fan of","","Los Angeles Lakers"],
    ...         ["fan of", "", "Bob Dylan"],
    ...         ["also known for","","Chinatown"]
    ...         ]
    ... }
    >>> av.store_entity(jack, jacks_details, auth)

    Find the name of Jack's property. No index or key is provided, so the name
    of the last property is found.

    >>> av.property_name(jack)
    'also known for'

    Find the name of Jack's second property.

    >>> av.property_name(jack, index=2)
    'fan of'

    Find the name of the property with key 'No.1'

    >>> av.property_name(jack, key='No.1')
    'known for'

    Find the name of the property on Jack's child. Neither an instance nor
    an index is provided, so the name of the last property of the last 
    instance of CHILD is found.

    >>> av.property_name(jack, attribute=av.Attribute.CHILD)
    'Mother'

    Find the name of the first property on Jack's child. No instance is 
    provided, so the first property of the last instance of CHILD is found.

    >>> av.property_name(jack, attribute=av.Attribute.CHILD, index=1)
    'Born'

    Find the name of the last property on Jack's second child.

    >>> av.property_name(jack, attribute=av.Attribute.CHILD, instance=2)
    'Mother'

    Find the name of the first property on Jack's second child.

    >>> av.property_name(jack, attribute=av.Attribute.CHILD, instance=2, index=1)
    'Born'

    Find the name of the property on Jack's second child that has the key
    'open question 2'

    >>> av.property_name(jack, attribute=av.Attribute.CHILD, instance=2, key='open question 2')
    'Paternity'

    Clean up.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """ 
    return invoke(
        entity, Method.NAME, index=index, attribute=attribute, 
        instance=instance, key=key, return_results=True, 
        results_as_string=True)

@manage_exceptions(
    'while finding key of property on entity {0}', 
    check_for_naked_instance=True)
def property_key(entity, *, attribute=None, instance=None, index=None):
    """
    property_key(entity, *, attribute=None, instance=None, index=None)
    Return the key of a property.

    Return the key of the property at position ``index``, as a string. If the 
    property has no key, return an empty string. If there is no such property, 
    raise an error.

    Parameters
    ----------
    entity : Entity
        the entity whose property has the key.

    attribute : Attribute, optional
        If provided, return the key of an attribute property instead of an
        entity property, and in particular the key of the attribute property
        ``attribute``. The default is None: use the entity property.

    instance : int, optional
        If provided and ``attribute`` is also provided, return the key of 
        a particular
        instance of an attribute property. For example, if ``attribute`` is 
        ``Attribute.CHILD`` and ``instance`` is  
        2, the key is found on the second instance of the child attribute.
        The default is None: use the last instance.

    index : int, optional
        If provided, return the key at the position of ``index``.
        For example, if ``index`` is 3, the key of the third property is 
        returned. The default is None: return the key of the last property.

    Returns
    -------
    str 
        the key of the property at the position 

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``attribute`` 
        is not an attribute, or an instance is specified but no attribute, 
        or no such ``index`` is known.

    See also
    --------
    :func:`property_name` : find the name of a property 

    :func:`property_value` : find the value of a property 

    :func:`property_index`: find the index of a property identified by key

    :func:`insert_property` : insert a new property 

    :func:`remove_property` : remove an existing property

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize()

    Create an entity for Jack, and give him attributes and properties.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jacks_details = {
    ...     "Attributes":{
    ...         "AGE_ATTRIBUTE":[{"Values":["80"]}],
    ...         "CHILD_ATTRIBUTE":[
    ...             {
    ...                 "Values": ["Jennifer"],
    ...                 "Properties": [ 
    ...                     ["Born","","1963"],
    ...                     ["Mother","","Sandra Knight"] 
    ...                 ]
    ...             },
    ...             {
    ...                 "Values": ["Caleb"],
    ...                 "Properties": [ 
    ...                     ["Born","","1970"],
    ...                     ["Paternity", "open question 2", "not established"],
    ...                     ["Mother","","Susan Anspach"],
    ...                 ]
    ...             },
    ...             {"Values": ["Honey"]},
    ...             {"Values": ["Lorraine"]},
    ...             {
    ...                 "Values": ["Raymond"],
    ...                 "Properties": [ 
    ...                     ["Born","youngest","1992"],
    ...                     ["Mother","","Rebecca Broussard"] 
    ...                 ]
    ...             }]},
    ...     "Properties":[
    ...         ["known for","most popular role","The Shining"],
    ...         ["fan of","famous fan","Los Angeles Lakers"],
    ...         ["fan of", "", "Bob Dylan"],
    ...         ["also known for","best movie","Chinatown"]
    ...         ]
    ... }
    >>> av.store_entity(jack, jacks_details, auth)

    Find the key of Jack's property. No index is provided, so the key of the
    last property is found.

    >>> av.property_key(jack)
    'best movie'

    Find the key of Jack's first property.

    >>> av.property_key(jack, index=1)
    'most popular role'

    Find the key of the property on Jack's child. Neither an instance nor an
    index is provided, so the key of the last proeprty of the last instance
    of CHILD is found.

    >>> av.property_key(jack, attribute=av.Attribute.CHILD)
    ''
    Find the key of the first property on Jack's child. No instance is 
    provided, so the first property of the last instance of CHILD is found.

    >>> av.property_key(jack, attribute=av.Attribute.CHILD, index=1)
    'youngest'

    Find the key of the last property on Jack's second child.

    >>> av.property_key(jack, attribute=av.Attribute.CHILD, instance=2)
    ''

    Find the key of the second property on Jack's second child.

    >>> av.property_key(jack, attribute=av.Attribute.CHILD, instance=2, index=2)
    'open question 2'

    Clean up.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """ 
    return invoke(
        entity, Method.KEY, index=index, attribute=attribute, 
        instance=instance, return_results=True, results_as_string=True)

@manage_exceptions(
    'while finding value of property on entity {0}', 
    check_for_naked_instance=True)
def property_value(entity, *, index=None, attribute=None, instance=None, 
                   key=None):
    """
    property_value(entity, *, index=None, attribute=None, instance=None, key=None)
    Return the value of a property.

    Return the value of the property at position ``index``. 
    Alternatively, return the value of the property with key ``key``.
    If there is no such property, raise an error.

    Parameters
    ----------
    entity : Entity
        The entity whose property has the value.

    index : int, optional
        If provided, find the value of the property at the ``index`` position.
        For example, if ``index`` is 4, the value of the fourth property is
        found.  If not provided,
        and ``key`` is also not provided, the value of the last property is
        returned. 

    attribute : Attribute, optional
        If provided, return the value of an attribute property instead of an
        entity property, and in particular the value of the attribute property
        ``attribute``. The default is None: use the entity property.

    instance : int, optional
        If provided and ``attribute`` is also provided, return the value of 
        a particular
        instance of an attribute property. For example, if ``attribute`` is 
        ``Attribute.CHILD`` and ``instance`` is  
        2, the value is found in the second instance of the child attribute.
        The default is None: use the last instance.

    key : str, optional
        If provided, return the value of the property with that key.

    Returns
    -------
    int or float or bool or str or Entity or list or dict or Value
        the value of the property at the position, or with that key 

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``attribute`` 
        is not an attribute, or an instance is specified but no attribute, or 
        no such ``key`` is known, or no such ``index`` is knownn.

    See also
    --------
    :func:`property_name` : find the name of a property 

    :func:`property_key` : find the key of a property

    :func:`insert_property` : insert a new property 

    :func:`remove_property` : remove an existing property

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize()

    Create an entity for Jack, and give him attributes and properties.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jacks_details = {
    ...     "Attributes":{
    ...         "AGE_ATTRIBUTE":[{"Values":["80"]}],
    ...         "CHILD_ATTRIBUTE":[
    ...             {
    ...                 "Values": ["Jennifer"],
    ...                 "Properties": [ 
    ...                     ["Born","","1963"],
    ...                     ["Mother","","Sandra Knight"] 
    ...                 ]
    ...             },
    ...             {
    ...                 "Values": ["Caleb"],
    ...                 "Properties": [ 
    ...                     ["Born","","1970"],
    ...                     ["Paternity", "open question 2", "not established"],
    ...                     ["Mother","","Susan Anspach"],
    ...                 ]
    ...             },
    ...             {"Values": ["Honey"]},
    ...             {"Values": ["Lorraine"]},
    ...             {
    ...                 "Values": ["Raymond"],
    ...                 "Properties": [ 
    ...                     ["Born","youngest","1992"],
    ...                     ["Mother","","Rebecca Broussard"] 
    ...                 ]
    ...             }]},
    ...     "Properties":[
    ...         ["known for","most popular role","The Shining"],
    ...         ["fan of","famous fan","Los Angeles Lakers"],
    ...         ["fan of", "", "Bob Dylan"],
    ...         ["also known for","best movie","Chinatown"]
    ...         ]
    ... }
    >>> av.store_entity(jack, jacks_details, auth)

    Find the value of Jack's property. No index or key is provided, so the
    value of the last property is found.

    >>> av.property_value(jack)
    'Chinatown'

    Find the value of Jack's third property.

    >>> av.property_value(jack, index=3)
    'Bob Dylan'

    Find the value of Jack's property that has the key 'most popular role'.

    >>> av.property_value(jack, key='most popular role')
    'The Shining'

    Find the value of the property on Jack's child. Neither an instance nor
    an index is provided, so the value of the last property of the last 
    instance of CHILD is found.

    >>> av.property_value(jack, attribute=av.Attribute.CHILD)
    'Rebecca Broussard'

    Find the value of the first proeprty on Jack's child. No instance is
    provided, so the first property of the last instance of CHILD is found.

    >>> av.property_value(jack, attribute=av.Attribute.CHILD, index=1)
    '1992'

    Find the value of the last property on Jack's second child.

    >>> av.property_value(jack, attribute=av.Attribute.CHILD, instance=2)
    'Susan Anspach'

    Find the value of the first property on Jack's second child.

    >>> av.property_value(jack, attribute=av.Attribute.CHILD, instance=2, index=1)
    '1970'

    Find the value of the property on Jack's second child with the key
    'open question 2'.

    >>> av.property_value(jack, attribute=av.Attribute.CHILD, instance=2, key='open question 2')
    'not established'

    Clean up.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """  
    return invoke(
        entity, Method.VALUE, index=index, attribute=attribute, 
        instance=instance, key=key, return_results=True)

@manage_exceptions(
    'while counting the properties on entity {0}', 
    check_for_naked_instance=True)
def property_count(entity, *, attribute=None, instance=None):
    """
    property_count(entity, *, attribute=None, instance=None)
    Return the count of properties.

    Return the count of properties, either the count of entity properties, or
    the count of attribute properties of some attribute instance.

    Parameters
    ----------
    entity : Entity
        The entity whose properties are to be counted.

    attribute : Attribute or None, optional
        If provided, the attribute properties of 
        ``attribute`` are counted instead of entity properties. 
        The default is None: count entity properties.

    instance : int or None, optional
        If provided and ``attribute`` is also provided, count properties
        of a particular attribute instance. For example, if ``attribute`` is 
        given as ``Attribute.CHILD`` and ``instance`` is provided as 
        2, the properties of the second CHILD attribute are counted, instead
        of the last CHILD attribute. The default is None: count the last 
        instance.

    Returns
    -------
    int 
        the count of the properties

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``attribute`` is not an attribute, or an instance is 
        specified but no attribute.

    See also
    --------
    :func:`find_property` : find the position of a property by name

    :func:`lookup_property` : find the value of a property by key

    :func:`property_name` : find the name of a property by its index

    :func:`property_key` : find the key of a property by its index

    :func:`property_value` : find the value of a property by its index

    :func:`insert_property` : insert a new property 

    :func:`remove_property` : remove an existing property

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize()
    >>> import pprint
    >>> pp = pprint.PrettyPrinter(indent=4)

    Create an entity for Jack Nicholson

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jacks_details = {
    ...     "Attributes":{
    ...         "SEX_ATTRIBUTE":[{"Values":["M"]}],
    ...         "AGE_ATTRIBUTE":[{"Values":["80"]}],
    ...         "HEIGHT_ATTRIBUTE":[{"Values":["177"]}], 
    ...         "LOCATION_ATTRIBUTE":[{"Values":["Los Angeles", "Aspen"]}],
    ...         "CHILD_ATTRIBUTE":[
    ...             {
    ...                 "Values": ["Jennifer"],
    ...                 "Properties": [ 
    ...                     ["Born","","1963"],
    ...                     ["Mother","","Sandra Knight"] 
    ...                 ]
    ...             },
    ...             {
    ...                 "Values": ["Caleb"],
    ...                 "Properties": [ 
    ...                     ["Born","","1970"],
    ...                     ["Mother","","Susan Anspach"],
    ...                     ["Paternity", "Paternity", "not established"]
    ...                 ]
    ...             },
    ...             {"Values": ["Honey"]},
    ...             {"Values": ["Lorraine"]},
    ...             {
    ...                 "Values": ["Raymond"],
    ...                 "Properties": [ 
    ...                     ["Born","","1992"],
    ...                     ["Mother","","Rebecca Broussard"] 
    ...                 ]
    ...             }]},
    ...     "Properties":[
    ...         ["known for","No.1","The Shining"],
    ...         ["fan of","","Los Angeles Lakers"],
    ...         ["fan of", "", "Bob Dylan"],
    ...         ["known for","","Chinatown"]
    ...         ]
    ... }
    >>> av.store_entity(jack, jacks_details, auth)

    Count the number of Jack's properties.

    >>> property_count(jack)
    4

    Count the number of properties of Jack's child attribute.

    >>> property_count(jack, attribute=Attribute.CHILD)
    2

    Count the number of properties on the second instance of Jack's child
    attribute.

    >>> property_count(jack, attribute=Attribute.CHILD, instance=2)
    3

    Count the number of properties on the third instance of 
    Jack's child attribute.

    >>> property_count(jack, attribute=Attribute.CHILD, instance=3)
    0

    Attempt to count the number of properties on the (non-existent) sixth
    instance of Jack's child attribute.

    >>> property_count(jack, attribute=Attribute.CHILD, instance=6)
    AvialError: Error Server reported APPLICATION error: Attempt to access nonexistant attribute instance: CHILD_ATTRIBUTE 6 while attempting to count properies on entity <2906857743|167772516|5081984> with attribute CHILD and instance 6

    Attempt to count properties of the second instance but without an attribute.

    >>> property_count(jack, instance=2)
    AvialError: Attempting to find instance 2 on properties of entity <2906857743|167772516|5081984>
    """
    return invoke(
        entity, method=Method.COUNT, attribute=attribute, instance=instance, 
        parameter=Argument.PROPERTY, return_results=True)

@manage_exceptions(
    'while determining if key {1} is found on entity {0}', 
    check_for_naked_instance=True)
def property_member(entity, key, *, attribute=None, instance=None): 
    """
    property_member(entity, key, *, attribute=None, instance=None)
    """
    try:
        found, ignore = lookup_property(
            entity, key, attribute=attribute, instance=instance, 
            handle_exceptions=False)
        return found
    except at.AvesTerraError as err:
        if 'Attribute not found' in err.message:
            return False
        else:
            raise 


################################################################################
#
# Annotation operations
#

@manage_exceptions('while getting annotation of attribute {1} of entity {0}')
def get_annotation(entity, attribute, *, key=None, index=None):
    """
    get_annotation(entity, attribute, *, key=None, index=None)
    """
    return invoke(
        entity, Method.GET, parameter=Argument.ANNOTATION, attribute=attribute,
        key=key, index=index, return_results=True)

@manage_exceptions(
    'while setting annotation {2} of attribute {1} of entity {0}')
def set_annotation(entity, attribute, value, auth, *, key=None, index=None):
    """
    set_annotation(entity, attribute, value, auth, *, key=None, index=None)
    Set the annotation of a property.

    Set the annotation of a single property to some value. The property is 
    identified by either key or index. If the property already has a annotation
    for that attribute, the  value is changed. If neither a key nor
    an index is specified, the annotation is set on the last property of the 
    entity.

    Parameters
    ----------
    entity : Entity
        the entity that gets a new annotation

    attribute : Attribute
        the attribute of the property that gets a new annotation

    value : int or float or bool or str or Entity or list or dict or Value or None, optional
        the new annotation value  

    auth : Authorization
        an object that authorizes the annotation setting

    key : str or None, optional
        the key of the property whose annotation is set

    index : int or None, optional
        the index of the property whose annotation is set

    Returns
    -------
    None

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``auth`` is not a valid  authorization, or ``attribute`` 
        is not an attribute, or ``key`` is not present among
        the properties, or ``index`` is too large, or not an 
        integer.

    See also
    --------
    :func:`clear_annotation`: remove an annotation from a property

    :func:`erase_annotation`: remove all annotations from a property

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize()
    >>> import pprint
    >>> pp = pprint.PrettyPrinter(indent=4)

    Create an entity for the actor Jack Nicholson.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)

    Set some properties for Jack.

    >>> jacks_details = { 
    ...     "Properties":[
    ...         ["known for","most popular role","The Shining"],
    ...         ["fan of","","Los Angeles Lakers"],
    ...         ["fan of", "", "Bob Dylan"],
    ...         ["known for","best performance","Chinatown"]
    ...         ]
    ... }
    >>> av.store_entity(jack, jacks_details, auth)
    >>> pp.pprint(av.retrieve_entity(jack)['Properties'])
    [   ['known for', 'most popular role', 'The Shining'],
        ['fan of', '', 'Los Angeles Lakers'],
        ['fan of', '', 'Bob Dylan'],
        ['known for', 'best performance', 'Chinatown']]

    Set the role attribute of *The Shining* property, identified by index.

    >>> av.set_annotation(jack, av.Attribute.ROLE, 'Jack Torrance', auth, index=1)
    >>> pp.pprint(av.retrieve_entity(jack)['Properties'])
    [   [   'known for',
            'most popular role',
            'The Shining',
            {'ROLE_ATTRIBUTE': 'Jack Torrance'}],
        ['fan of', '', 'Los Angeles Lakers'],
        ['fan of', '', 'Bob Dylan'],
        ['known for', 'best performance', 'Chinatown']]

    Set the role attribute of *Chinatown*, identified by key.

    >>> av.set_annotation(jack, av.Attribute.ROLE, 'J.J. Gittes', auth, key='best performance')
    >>> pp.pprint(av.retrieve_entity(jack)['Properties'])
    [   [   'known for',
            'most popular role',
            'The Shining',
            {'ROLE_ATTRIBUTE': 'Jack Torrance'}],
        ['fan of', '', 'Los Angeles Lakers'],
        ['fan of', '', 'Bob Dylan'],
        [   'known for',
            'best performance',
            'Chinatown',
            {'ROLE_ATTRIBUTE': 'J.J. Gittes'}]]

    Set the year attribute of the last property, also *Chinatown*.

    >>> av.set_annotation(jack, av.Attribute.YEAR, 1974, auth)
    >>> pp.pprint(av.retrieve_entity(jack)['Properties'])
    [   [   'known for',
            'most popular role',
            'The Shining',
            {'ROLE_ATTRIBUTE': 'Jack Torrance'}],
        ['fan of', '', 'Los Angeles Lakers'],
        ['fan of', '', 'Bob Dylan'],
        [   'known for',
            'best performance',
            'Chinatown',
            {'ROLE_ATTRIBUTE': 'J.J. Gittes', 'YEAR_ATTRIBUTE': '1974'}]]

    Clean up.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """ 
    invoke(
        entity, Method.SET, attribute=attribute, value=value, 
        authorization=auth, key=key, index=index, 
        parameter=Argument.ANNOTATION)

@manage_exceptions('while clearing annotation of attribute {1} of entity {0}')
def clear_annotation(entity, attribute, auth, *, key=None, index=None):
    """
    clear_annotation(entity, attribute, auth, *, key=None, index=None)
    Clear the attribute value of a single property.

    Clear the attribute of a single property to no value. The property is 
    identified by either key or index. If the property has no such annotation,
    the operation has no effect. If neither a key nor an index is specified,
    an annotation on the last property of the entity is cleared.

    Parameters
    ----------
    entity: Entity
        the entity on which a property's annotation is cleared

    attribute : Attribute
        the annotation of the property that is cleared

    auth : Authorization
        an object that authorizes the attribute clearing

    key : str or None, optional
        the key of the property whose annotation is cleared

    index : int or None, optional
        the index of the property whose annotation is cleared

    Returns
    -------
    None

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``auth`` is not a valid  authorization, or ``attribute`` 
        is not an attribute, or ``key`` is not present among
        the properties, or ``index`` is too large, or not an 
        integer.

    See also
    --------
    :func:`set_annotation`: set the value of an annotation of a property

    :func:`erase_annotation`: remove all annotations from a property

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize() 
    >>> import pprint
    >>> pp = pprint.PrettyPrinter(indent=4)

    Create an entity for the actor Jack Nicholson.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)

    Set some properties for Jack, including annotations.

    >>> jacks_details = { 
    ...     'Properties':[
    ...         ['known for','most popular role','The Shining', 
    ...             {'ROLE_ATTRIBUTE': 'Jack Torrance'}],
    ...         ['known for', '', 'The Departed', 
    ...             {'ROLE_ATTRIBUTE': 'Frank Costello', 
    ...                 'YEAR_ATTRIBUTE': '2006'}],
    ...         ['known for', '', 'Wolf', {'ROLE_ATTRIBUTE': 'Will Randall'}], 
    ...         ['known for','best performance','Chinatown', 
    ...             {'ROLE_ATTRIBUTE': 'J.J. Gittes', 'YEAR_ATTRIBUTE': '1974'}]
    ...         ]
    ... }
    >>> av.store_entity(jack, jacks_details, auth)
    >>> pp.pprint(av.retrieve_entity(jack)['Properties'])
    [   [   'known for',
            'most popular role',
            'The Shining',
            {'ROLE_ATTRIBUTE': 'Jack Torrance'}],
        [   'known for',
            '',
            'The Departed',
            {'ROLE_ATTRIBUTE': 'Frank Costello', 'YEAR_ATTRIBUTE': '2006'}],
        ['known for', '', 'Wolf', {'ROLE_ATTRIBUTE': 'Will Randall'}],
        [   'known for',
            'best performance',
            'Chinatown',
            {'ROLE_ATTRIBUTE': 'J. J. Gittes', 'YEAR_ATTRIBUTE': '1974'}]]

    Clear the year annotation of the last property. The last property is 
    cleared because no index or key is provided.

    >>> av.clear_annotation(jack, av.Attribute.YEAR, auth)
    >>> pp.pprint(av.retrieve_entity(jack)['Properties'])
    [   [   'known for',
            'most popular role',
            'The Shining',
            {'ROLE_ATTRIBUTE': 'Jack Torrance'}],
        [   'known for',
            '',
            'The Departed',
            {'ROLE_ATTRIBUTE': 'Frank Costello', 'YEAR_ATTRIBUTE': '2006'}],
        ['known for', '', 'Wolf', {'ROLE_ATTRIBUTE': 'Will Randall'}],
        [   'known for',
            'best performance',
            'Chinatown',
            {'ROLE_ATTRIBUTE': 'J. J. Gittes'}]]

    Clear the role annotation of the third property. That property ends up with 
    no annotations at all.

    >>> av.clear_annotation(jack, av.Attribute.ROLE, auth, index=3)
    >>> pp.pprint(av.retrieve_entity(jack)['Properties'])
    [   [   'known for',
            'most popular role',
            'The Shining',
            {'ROLE_ATTRIBUTE': 'Jack Torrance'}],
        [   'known for',
            '',
            'The Departed',
            {'ROLE_ATTRIBUTE': 'Frank Costello', 'YEAR_ATTRIBUTE': '2006'}],
        ['known for', '', 'Wolf'],
        [   'known for',
            'best performance',
            'Chinatown',
            {'ROLE_ATTRIBUTE': 'J. J. Gittes'}]]

    Clear the role property of the property with the key 'most popular role'.

    >>> av.clear_annotation(jack, av.Attribute.ROLE, auth, key='most popular role')
    >>> pp.pprint(av.retrieve_entity(jack)['Properties'])
    [   ['known for', 'most popular role', 'The Shining'],
        [   'known for',
            '',
            'The Departed',
            {'ROLE_ATTRIBUTE': 'Frank Costello', 'YEAR_ATTRIBUTE': '2006'}],
        ['known for', '', 'Wolf'],
        [   'known for',
            'best performance',
            'Chinatown',
            {'ROLE_ATTRIBUTE': 'J. J. Gittes'}]]

    Clean up.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """ 
    invoke(
        entity, Method.CLEAR, attribute=attribute, authorization=auth, 
        key=key, index=index, parameter=Argument.ANNOTATION)

@manage_exceptions('while erasing annotations of entity {0}')
def erase_annotation(entity, auth, *, key=None, index=None):
    """
    erase_annotation(entity, auth, *, key=None, index=None)
    Erase all annotations of a single property.

    Erase all the annotations of a single property, leaving it with no
    annotations at all. The property to be erased is identified by either key or
    index. If neither a key nor an index is specified, the annotations of the
    last property are erased.

    Parameters
    ---------
    entity: Entity
        the entity on which to erase annotations

    auth : Authorization
        an object that authorizes the erase

    key : str or None, optional
        the key of the property whose annotations are erased

    index : int or None, optional
        the index of the property whose annotations are erased

    Raises
    ------
    AvialError
        if ``entity`` is not an entity, or is an entity but connected to no
        adapter, or ``auth`` is not a valid  authorization, 
        or ``key`` is not present among
        the properties, or ``index`` is too large, or not an 
        integer.

    See also
    --------
    :func:`set_annotation`: set the value of an annotation of a property

    :func:`clear_annotation`: remove an annotation from a property

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize()
    >>> import pprint
    >>> pp = pprint.PrettyPrinter(indent=4)

    Create an entity for Jack.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)

    Set some properties for Jack, including annotations.

    >>> jacks_details = { 
    ...     'Properties':[
    ...         ['known for','most popular role','The Shining', 
    ...             {'ROLE_ATTRIBUTE': 'Jack Torrance'}],
    ...         ['known for', '', 'The Departed', 
    ...             {'ROLE_ATTRIBUTE': 'Frank Costello', 
    ...                 'YEAR_ATTRIBUTE': '2006'}],
    ...         ['known for', '', 'Wolf', {'ROLE_ATTRIBUTE': 'Will Randall'}], 
    ...         ['known for','best performance','Chinatown', 
    ...             {'ROLE_ATTRIBUTE': 'J.J. Gittes', 'YEAR_ATTRIBUTE': '1974'}]
    ...         ]
    ... }
    >>> av.store_entity(jack, jacks_details, auth)
    >>> pp.pprint(av.retrieve_entity(jack)['Properties'])
    [   [   'known for',
            'most popular role',
            'The Shining',
            {'ROLE_ATTRIBUTE': 'Jack Torrance'}],
        [   'known for',
            '',
            'The Departed',
            {'ROLE_ATTRIBUTE': 'Frank Costello', 'YEAR_ATTRIBUTE': '2006'}],
        ['known for', '', 'Wolf', {'ROLE_ATTRIBUTE': 'Will Randall'}],
        [   'known for',
            'best performance',
            'Chinatown',
            {'ROLE_ATTRIBUTE': 'J. J. Gittes', 'YEAR_ATTRIBUTE': '1974'}]]

    Erase the annotations of the last property. The last property is erased
    because no key or index is provided.

    >>> av.erase_annotation(jack,  auth)
    >>> pp.pprint(av.retrieve_entity(jack)['Properties'])
    [   [   'known for',
            'most popular role',
            'The Shining',
            {'ROLE_ATTRIBUTE': 'Jack Torrance'}],
        [   'known for',
            '',
            'The Departed',
            {'ROLE_ATTRIBUTE': 'Frank Costello', 'YEAR_ATTRIBUTE': '2006'}],
        ['known for', '', 'Wolf', {'ROLE_ATTRIBUTE': 'Will Randall'}],
        ['known for', 'best performance', 'Chinatown']]

    Erase the annotations of the second property.

    >>> av.erase_annotation(jack, auth, index=2)
    >>> pp.pprint(av.retrieve_entity(jack)['Properties'])
    [   [   'known for',
            'most popular role',
            'The Shining',
            {'ROLE_ATTRIBUTE': 'Jack Torrance'}],
        ['known for', '', 'The Departed'],
        ['known for', '', 'Wolf', {'ROLE_ATTRIBUTE': 'Will Randall'}],
        ['known for', 'best performance', 'Chinatown']]

    Erase the annotations of the property with the key 'most popular role'. 

    >>> av.erase_annotation(jack, auth, key='most popular role')
    >>> pp.pprint(av.retrieve_entity(jack)['Properties'])
    [   ['known for', 'most popular role', 'The Shining'],
        ['known for', '', 'The Departed'],
        ['known for', '', 'Wolf', {'ROLE_ATTRIBUTE': 'Will Randall'}],
        ['known for', 'best performance', 'Chinatown']]

    Clean up.

    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """ 
    invoke(
        entity, Method.ERASE, authorization=auth, key=key, index=index,
        parameter=Argument.ANNOTATION)

@manage_exceptions('while finding index of annotation {1} on entity {0}')
def find_annotation(entity, attribute, *, instance=None, key=None, index=None):
    """
    find_annotation(entity, attribute, *, instance=None, key=None, index=None)
    """
    return invoke(
        entity, Method.FIND, parameter=Argument.ANNOTATION, 
        attribute=attribute, instance=instance, key=key, index=index,
        return_results=True)

@manage_exceptions('while counting annotations on {0}')
def annotation_count(entity, *, key=None, index=None):
    """
    annotation_count(entity, *, key=None, index=None)
    """
    return invoke(
        entity, Method.COUNT, parameter=Argument.ANNOTATION, key=key, 
        index=index, return_results=True)

@manage_exceptions('while finding annotation at position {1} on entity {0}')
def annotation_item(entity, instance, *, key=None, index=None):
    """
    annotation_item(entity, instance, *, key=None, index=None)
    """
    return Attribute(invoke(
        entity, Method.ATTRIBUTE, parameter=Argument.ANNOTATION,
        instance=instance, key=key, index=index, return_results=True))

################################################################################
#
# Connection operations
#

@manage_exceptions('while counting connections of {0}')
def connection_count(entity):
    """
    connection_count(entity)
    """
    return atapi.connections(entity)

@manage_exceptions('while connecting entity {0} to outlet {1}')
def connect_method(entity, outlet, auth, *, method=None, precedence=None):
    """
    connect_method(entity, outlet, auth, *, method=None, precedence=None)
    """
    atapi.connect(
        TranslateFromAvialToAPI.entity(entity),
        TranslateFromAvialToAPI.entity(outlet),
        authorization=TranslateFromAvialToAPI.authorization(auth), 
        method=TranslateFromAvialToAPI.method(method),
        precedence=TranslateFromAvialToAPI.precedence(precedence))

@manage_exceptions('while disconnecting entity {0}')
def disconnect_method(entity, auth, *, method=None, precedence=None):
    """
    disconnect_method(entity, auth, *, method=None, precedence=None)
    """
    atapi.disconnect(
        TranslateFromAvialToAPI.entity(entity),
        TranslateFromAvialToAPI.entity(None),
        authorization=TranslateFromAvialToAPI.authorization(auth), 
        method=TranslateFromAvialToAPI.method(method),
        precedence=TranslateFromAvialToAPI.precedence(precedence))

@manage_exceptions('while determining if entity {0} is connected to an outlet')
def method_connected(entity, *, method=None, precedence=None):
    """
    method_connected(entity, *, method=None, precedence=None)
    """
    return atapi.connected(
        TranslateFromAvialToAPI.entity(entity),
        method=TranslateFromAvialToAPI.method(method),
        precedence=TranslateFromAvialToAPI.precedence(precedence))

@manage_exceptions('while determining the method of {0} connection {1}')
def connection_method(entity, index):
    """
    connection_method(entity, index)
    """
    outlet, method, precedence = atapi.connection(
        TranslateFromAvialToAPI.entity(entity),
        index=TranslateFromAvialToAPI.index(index))
    return TranslateFromAPItoAvial.method(method)

@manage_exceptions('while determining the precedence of {0} connection {1}')
def connection_precedence(entity, index):
    """
    connection_precedence(entity, index)
    """
    outlet, method, precedence = atapi.connection(
        TranslateFromAvialToAPI.entity(entity),
        index=TranslateFromAvialToAPI.index(index))
    return TranslateFromAPItoAvial.precedence(precedence)

@manage_exceptions('while determining the outlet of {0} connection {1}')
def connection_outlet(entity, index):
    """
    connection_outlet(entity, index)
    """
    outlet, method, precedence = atapi.connection(
        TranslateFromAvialToAPI.entity(entity),
        index=TranslateFromAvialToAPI.index(index))
    return outlet

################################################################################
#
# Attachment operations
#

@manage_exceptions('while counting attachments of entity {0}')
def attachment_count(entity):
    """
    attachment_count(entity)
    How many attributes of entity have attached outlets?
    """ 
    return atapi.attachments(entity)

@manage_exceptions('while attaching outlet {1} to entity {0}')
def attach_attribute(entity, outlet, auth, *, attribute=None, precedence=None):
    """
    attach_attribute(entity, outlet, auth, *, attribute=None, precedence=None)
    Attach an outlet to an entity at a particular attribute.
    """ 
    atapi.attach(
        entity, 
        outlet, 
        attribute=TranslateFromAvialToAPI.attribute(attribute), 
        precedence=TranslateFromAvialToAPI.precedence(precedence),
        authorization=TranslateFromAvialToAPI.authorization(auth))

@manage_exceptions('while detaching outlet from entity {0}')
def detach_attribute(entity, auth, *, attribute=None, precedence=None): 
    """
    detach_attribute(entity, auth, *, attribute=None, precedence=None)
    """
    atapi.detach(
        entity, 
        attribute=TranslateFromAvialToAPI.attribute(attribute),  
        precedence=TranslateFromAvialToAPI.precedence(precedence),
        authorization=TranslateFromAvialToAPI.authorization(auth))

@manage_exceptions('while checking if an outlet is attached on entity {0}')
def attribute_attached(entity, *, attribute=None, precedence=None):
    """
    attribute_attached(entity, *, attribute=None, precedence=None)
    """
    return atapi.attached(
        entity,
        attribute=TranslateFromAvialToAPI.attribute(attribute), 
        precedence=TranslateFromAvialToAPI.precedence(precedence))

@manage_exceptions(
    'while finding the attribute of the outlet attached at index {1} of {0}')
def attachment_attribute(entity, index): 
    """
    attachment_attribute(entity, index)
    """ 
    (outlet, attribute, precedence) = atapi.attachment(
        entity, index=TranslateFromAvialToAPI.index(index))
    return Attribute(attribute)

@manage_exceptions(
    'while finding the precedence of the outlet attached at index {1} of {0}')
def attachment_precedence(entity, index): 
    """
    attachment_precedence(entity, index)
    """
    (outlet, attribute, precedence)  = atapi.attachment(
        entity, index=TranslateFromAvialToAPI.index(index))
    return Precedence(precedence)

@manage_exceptions('while finding the outlet attached at index {1} of {0}')
def attachment_outlet(entity, index): 
    """
    attachment_outlet(entity, index)
    """
    (outlet, item, precedence) = atapi.attachment(
        entity, index=TranslateFromAvialToAPI.index(index))
    return outlet


################################################################################
#
# Event operations
#

@manage_exceptions('while publishing event on entity {0}')
def publish_event(entity, auth, *, event=None, attribute=None, 
                  instance=None, name=None, key=None, value=None, options=None,
                  parameter=None, index=None, count=None, mode=None ):
    """
    publish_event(entity, auth, *, event=None, attribute=None, instance=None, name=None, key=None, value=None, options=None, parameter=None, index=None, count=None, mode=None )
    Publish an event on an entity.

    Publish an event on an entity. The parameters are passed to the event, and
    can be received by any subscribers.

    Parameters
    ----------
    entity : Entity
        the publisher of the event.

    auth : Authorization
        an object that authorizes publishing an event.

    event : Event or None, optional
        the event to publish. The default is None: publish ``Event.NULL``

    attribute : Attribute or None, optional
        the attribute to publish on the event. The default is None,
        publish ``Attribute.NULL``

    instance : int or None, optional
        the instance to publish on the event. The default is None, publish 
        instance 0

    name : str or None, optional
        the name to publish on the event. The default is None, publish empty 
        string

    key : str or None, optional
        the key to publish on the event. The default is None, publish empty 
        string

    value : int or float or bool or str or Entity or list or dict or Value or None, optional
        the value to publish on the event. The default is None, publish empty 
        string

    options : str or None, optional
        the options to publish on the event. The default is None, publish 
        empty string

    parameter : int or None, optional
        the parameter to publish on the event. The default is None, publish 
        parameter 0

    index : int or None, optional
        the index to publish on the event. The default is None, publish 
        index 0

    count : int or None, optional
        the count to publish on the event. The default is None, publish 
        count 0

    mode : Mode or None, optional
        the mode to publish on the event. The default is None, publish 
        ``Mode.NULL``

    Returns
    -------
    None

    Raises
    ------
    AvialError
        If ``entity`` is not an entity, or ``auth`` does not permit an event
        to be published, or ``event`` is not an event, or one of the other
        parameters is invalid.

    See also
    --------
    :func:`create_outlet` : create a new outlet entity, to subscribe to some publishers

    :func:`subscribe_event` : an outlet subscribes to a publisher

    :func:`wait_event` : an outlet waits for an event to be published

    :func:`flush_event`: delete any events waiting on an outlet

    Examples
    --------
    An example for :func:`publish_event` requires code in two different
    processes, one process for the calls to :func:`publish_event`, and the
    other process for the calls to :func:`wait_event`, that receive the event
    as it is published. *Start by setting up process 1.*

    >>> import avesterra.avial as av  
    >>> auth = av.initialize()

    Create a publisher, an entity on which we will publish events. We will
    make the publisher a person, a musician who occasionally tweets, but it 
    could be any kind of entity.

    >>> ye = av.create_entity(
    ...     'Kanye West', av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> str(ye)
    '<2906857743|167772516|15631586>'

    *Now switch to process 2*, and set it up.

    >>> import avesterra.avial as av  
    >>> auth = av.initialize()

    Create an outlet, an entity that will wait for events. The outlet could
    be of any AvesTerra class and subclass. We will make the outlet another
    person, a fan of the musician.

    >>> ye_fan = av.create_outlet('Kanye subscriber', av.Class.PERSON, av.Subclass.PERSON, auth)

    Subscribe to the publisher. Note that we need to reference the publisher
    entity via :func:`entity_of`, as the variable ``ye`` in the other process
    does not exist in this process.

    >>> av.subscribe_event(av.entity_of('<2906857743|167772516|15631586>'), ye_fan, auth)


    Define a function to call when an event occurs. The function must
    be defined with a signature that includes ``outlet``, ``publisher``,
    ``event``, and so on, all 14 parameters of the event. Our function will
    just print the parameters, but it could do anything.

    >>> def print_event(outlet, publisher, event, attribute, instance, name, key, value, 
    ...                 options, parameter, index, count, mode, authorization):
    ...     print('Event:')
    ...     print(f'  Outlet:    {outlet}')
    ...     print(f'  Publisher: {publisher}')
    ...     print(f'  Event:     {event!s}')
    ...     print(f'  Attribute  {attribute!s}')
    ...     print(f'  Instance:  {instance}')
    ...     print(f'  Name:      {name}')
    ...     print(f'  Key:       {key}')
    ...     print(f'  Value:     {value}')
    ...     print(f'  Options:   {options}')
    ...     print(f'  Parameter: {parameter}')
    ...     print(f'  Index:     {index}')
    ...     print(f'  Count:     {count}')
    ...     print(f'  Mode:      {mode!s}')  
    ...     print('')

    Wait for the event, and when it occurs, call :func:`print_event`.

    >>> av.wait_event(out, print_event)

    :func:`wait_event` does not return, as it waits forever for an event.

    *Switch back to the first prcoess.* Now the musician publishes an event, a
    tweet.

    >>> av.publish_event(
    ...     ye, auth, value='To my fans: thank you for being loyal and patient')

    Nothing happens in this process, *so switch once more to process 2.* 

    (The call to :func:`wait_event` is
    repeated for clarity, although we have only called it once, so far.)

    As you can see, :func:`wait_event` has now run, printing the outlet
    and the publisher, and all the other parameters with None.

    >>> av.wait_event(out, print_event)
    Event:
      Outlet:    <2906857743|167772516|15631587>
      Publisher: <2906857743|167772516|15631586>
      Event:     None
      Attribute  None
      Instance:  None
      Name:      None
      Key:       None
      Value:     To my fans: thank you for being loyal and patient
      Options:   None
      Parameter: None
      Index:     None
      Count:     None
      Mode:      None

    The published event has only the outlet, publisher, and a value.

    :func:`wait_event` has now finished. Each call to :func:`wait_event`
    waits for a single event. So call it again, to wait for another event.

    >>> av.wait_event(out, print_event)

    *Switch to process 1.* Publish an event with some parameters 
    specified.

    >>> av.publish_event(
    ...     ye, auth, event=av.Event.UPDATE, attribute=av.Attribute.AGE, 
    ...     value=42)

    *Switch to process 2.* As before, the call to :func:`wait_event` is 
    repeated. for clarity.

    >>> av.wait_event(ye_fan, print_event)
    Event:
      Outlet:    <2906857743|167772516|15631587>
      Publisher: <2906857743|167772516|15631586>
      Event:     Event.UPDATE
      Attribute  Attribute.AGE
      Instance:  None
      Name:      None
      Key:       None
      Value:     42
      Options:   None
      Parameter: None
      Index:     None
      Count:     None
      Mode:      None

    Clean up process 2.

    >>> av.delete_outlet(ye_fan, auth)
    >>> av.finalize()

    *Switch to process 1.* Clean up.

    >>> av.delete_entity(ye, auth)
    >>> av.finalize()
    """
    atapi.publish(
        entity, 
        auth,
        event=TranslateFromAvialToAPI.event(event),
        attribute=TranslateFromAvialToAPI.attribute(attribute),
        instance=TranslateFromAvialToAPI.instance(instance),
        name=TranslateFromAvialToAPI.name(name),
        key=TranslateFromAvialToAPI.key(key),
        value=TranslateFromAvialToAPI.value(value),
        options=TranslateFromAvialToAPI.options(options),
        parameter= TranslateFromAvialToAPI.parameter(parameter),
        index=TranslateFromAvialToAPI.index(index),
        count=TranslateFromAvialToAPI.count(count),
        mode=TranslateFromAvialToAPI.mode(mode) 
    )

@manage_exceptions('while {1} subscribes to events published by {0}')
def subscribe_event(publisher, outlet, auth, *, event=None, timeout=None):
    """
    subscribe_event(publisher, outlet, auth, *, event=None, timeout=None)
    Subscribe outlet to events published by publisher.

    Outlet subscribes to events published by publisher, allowing a later 
    :func:`wait` to respond to events. 

    Parameters
    ----------
    publisher : Entity
        the entity that will later be publishing events.

    outlet : Entity
        the entity that will later be listening for published events.

    auth : Authorization
        an object that authorizes subscription.

    event : Event or None, optional
        which events to subscribe to. If supplied, ``outlet`` will ignore 
        other events, events that do not include ``event``. The default is
        None: subscribe to all events on ``publisher``.

    timeout : int, optional
        the duration of the subscription, in seconds. The default is None: the
        subscription lasts forever.

    Returns
    -------
    None

    Raises
    ------
    AvialError
        If ``entity`` is not an entity, or ``outlet`` is not an entity, or 
        ``auth`` does not permit event subscription, or ``timeout`` is 
        non-numeric, or ``event`` is not an event.

    See also
    --------
    :func:`create_outlet` : create a new outlet entity, to subscribe to some publishers
    
    :func:`publish_event` : a publisher publishes an event for subscribed outlets 

    :func:`wait_event` : an outlet waits for an event to be published

    :func:`flush_event`: delete any events waiting on an outlet

    Examples
    --------
    Usage of :func:`subscribe_event` will likely involve at least two processes,
    one process for the calls to :func:`publish_event` on the entity that
    is publishing---the publisher---and the other process for the calls to 
    :func:`wait_event` on the outlet that has subscribed to the publisher. (See
    the dual process examples detailed with :func:`publish_event` and 
    :func:`wait_event`.) But to keep
    these examples simple, instead of waiting for events, we will just count 
    them, using :func:`event_count`, which we can do from the same process.

    >>> import avesterra.avial as av  
    >>> auth = av.initialize()

    Create a publisher, an entity on which we will publish events. We will
    make the entity a person, but it could be any kind of entity.

    >>> ye = av.create_entity(
    ...     'Kanye West', av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)

    Create an outlet, an entity that will wait for events. The outlet could
    be of any AvesTerra class and subclass. We will make the outlet another
    person, a fan.

    >>> fangirl = av.create_outlet(
    ...     'Fangirl', av.Class.PERSON, av.Subclass.PERSON, auth)

    Subscribe to the publisher.

    >>> av.subscribe_event(ye, fangirl, auth)

    So far there are no events on the outlet, as the publisher has published
    no events.

    >>> av.event_count(fangirl)
    0

    Publish an event.

    >>> av.publish_event(
    ...     ye, auth, event=av.Event.MESSAGE, 
    ...     value="Yo, Taylor, I'm really happy for you. I'mma let you finish")

    Now there is a single event waiting on ``fangirl``.

    >>> av.event_count(fangirl)
    1

    Publish another event.

    >>> av.publish_event(
    ...     ye, auth, event=av.Event.MESSAGE, 
    ...     value="I did not diss Taylor Swift and I’ve never dissed her…")
    >>> av.event_count(fangirl)
    2

    Subscribe to a second publisher. 

    >>> taylorswift13 = av.create_entity(
    ...     'Taylor Swift', av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> av.subscribe_event(taylorswift13, fangirl, auth)

    The new publisher publishes an event. Now there are three events in
    ``fangirl``'s queue.

    >>> av.publish_event(
    ...     taylorswift13, auth, event=av.Event.MESSAGE, 
    ...     value="That moment when Kanye West secretly records your phone call, then Kim posts it on the Internet.")
    >>> av.event_count(fangirl)
    3

    Another outlet can subscribe to the same publisher.

    >>> taytayfan = av.create_outlet(
    ...     'Taytayfan', av.Class.PERSON, av.Subclass.PERSON, auth)
    >>> av.subscribe_event(taylorswift13, taytayfan, auth)

    When Taylor publishes an event, the same event is received by both outlets.

    >>> av.publish_event(
    ...     taylorswift13, auth, event=av.Event.MESSAGE, 
    ...     value="I actually did grow up on a Christmas tree farm.")
    >>> av.event_count(fangirl)
    4
    >>> av.event_count(taytayfan)
    1

    Clean up.

    >>> av.delete_entity(ye, auth)
    >>> av.delete_entity(taylorswift13, auth)
    >>> av.delete_outlet(fangirl, auth)
    >>> av.delete_outlet(taytayfan, auth)
    >>> av.finalize()
    """ 
    if entity_available(outlet, handle_exceptions=False):
        atapi.subscribe(
            publisher, 
            outlet,
            event=TranslateFromAvialToAPI.event(event),
            timeout=TranslateFromAvialToAPI.timeout(timeout),
            authorization=auth)
    else: 
        raise AvialError(f'Outlet {outlet} is not an entity')

@manage_exceptions('while canceling subscription of {1} to events on {0}')
def cancel_event(publishee, outlet, auth, *, event=None): 
    """
    cancel_event(publishee, outlet, auth, *, event=None)
    """
    atapi.cancel(
        publishee, outlet, event=TranslateFromAvialToAPI.event(event), 
        authorization=auth)

@manage_exceptions('while flushing events from outlet {0}')
def flush_event(outlet, auth):
    """
    flush_event(outlet, auth)
    Delete all events waiting on the outlet.

    Events may be waiting on the outlet ``outlet`` because ``outlet`` 
    has subscribed to one or more entities, and some of those entities have
    published events. Delete all such events.

    Parameters
    ----------
    outlet : Entity
        the entity on which events are waiting

    auth : Authorization
        an object that authorizes the deleting of the events

    Returns
    -------
    None

    Raises
    ------
    AvialError
        If ``outlet`` is not an entity or not an outlet, or ``auth`` does not
        permit event flushing.

    See also
    --------
    :func:`create_outlet` : create a new outlet entity, to subscribe to some publishees

    :func:`subscribe_event` : an outlet subscribes to a publishee
    
    :func:`publish_event` : a publishee publishes an event for subscribed outlets 

    :func:`wait_event` : an outlet waits for an event to be published

    Examples
    --------
    Usage of :func:`flush_event` will likely involve at least two processes,
    one process for the calls to :func:`publish_event` on the entity that
    is publishing---the publisher---and the other process for the calls to 
    :func:`wait_event` and :func:`flush_event` on the outlet that has 
    subscribed to the publisher. (See
    the dual process examples detailed with :func:`publish_event` and 
    :func:`wait_event`.) But to keep
    these examples simple, we will just count 
    events, using :func:`event_count`, which we can do from the same process.

    >>> import avesterra.avial as av  
    >>> auth = av.initialize()

    Create entities for two musician celebrities.

    >>> ye = av.create_entity(
    ...     'Kanye West', av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> taylorswift13 = av.create_entity(
    ...     'Taylor Swift', av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)

    Create entity for a fangirl follower of these celebrities.

    >>> fangirl = av.create_outlet(
    ...     'Fangirl', av.Class.PERSON, av.Subclass.PERSON, auth)

    Fangirl follows both, subscribing to events they publish.

    >>> av.subscribe_event(ye, fangirl, auth)
    >>> av.subscribe_event(taylorswift13, fangirl, auth)

    So far there are no events.

    >>> av.event_count(fangirl)
    0

    Kanye tweets. Then Taylor tweets. Then Kanye tweets again.

    >>> av.publish_event(
    ...     ye, auth, event=av.Event.MESSAGE, 
    ...     value="Yo, Taylor, I'm really happy for you. I'mma let you finish")
    >>> av.publish_event(
    ...     taylorswift13, auth, event=av.Event.MESSAGE, 
    ...     value="That moment when Kanye West secretly records your phone call, then Kim posts it on the Internet.")
    >>> av.publish_event(
    ...     ye, auth, event=av.Event.MESSAGE, 
    ...     value="I did not diss Taylor Swift and I’ve never dissed her…")

    Fangirl has three events in her queue.

    >>> av.event_count(fangirl)
    3

    Fangirl flushes the events. Afterwards she has no events in her queue.

    >>> av.flush_event(fangirl, auth)
    >>> av.event_count(fangirl)
    0

    Clean up.

    >>> av.delete_entity(ye, auth)
    >>> av.delete_entity(taylorswift13, auth)
    >>> av.delete_outlet(fangirl, auth)
    >>> av.finalize()
    """ 
    atapi.flush(outlet, auth)

@manage_exceptions('while waiting on outlet {0}')
def wait_event(outlet, *, callback=None, timeout=None, authorization=None):
    """
    wait_event(outlet, *, callback=None, timeout=None, authorization=None)
    Wait for an event. Then call ``callback``.

    Wait for an event, then call the callback, with 14 arguments.
    If timeout is specified, and the event does not occur within that duraction,
    the function times out, and raises :class:`AvialTimeout`. If timeout is not
    specified, the function waits for an event forever. 

    Parameters
    ----------
    outlet : Entity
        the entity waiting for the event. Typically ``outlet`` has already
        subscribed to one or more publishees with :func:`subscribe_event`.

    callback : callable or None, optional
        a Python callable with 14 required arguments, as listed below. Most of 
        these arguments take the values given on the original call to
        :func:`publish_event`, the call that created the event. The default is
        None: when the event occurs, call no callback function, and instead
        just silently proceed.

        outlet 
            the outlet entity to which the event was published
        publishee
            the entity on which the event was pulbished
        event
            the instance of :class:`Event` originally provided to 
            :func:`publish_event`, or None, if no Event instance was provided
        attribute
            the instance of :class:`Attribute` originally provided to 
            :func:`publish_event`, or None, if no Attribute instance was 
            provided
        instance
            the instance integer originally provided to :func:`publish_event`, 
            or None, if no instance was provided
        name
            the name string originally provided to :func:`publish_event`, or 
            None, if no name was provided
        key
            the key string originally provided to :func:`publish_event`, or 
            None, if no key was provided
        value
            the value (an int, float, bool, str, at.Entity, list, or dict) 
            originally provded to :func:`publish_event`, or 
            None, if no value was provided
        options
            the options string originally provided to :func:`publish_event`, or 
            None, if no options was provided
        parameter
            the parameter integer originally provided to :func:`publish_event`, 
            or None, if no parameter was provided
        index
            the index integer originally provided to :func:`publish_event`, or 
            None, if no index was provided
        count
            the count integer originally provided to :func:`publish_event`, or 
            None, if no count was provided
        mode
            the instance of Mode originally provided to :func:`publish_event`, 
            or None, if no mode was provided
        authorization
            the instance of :class:`Authorization` originally provided to 
            :func:`publish_event`, or None, if no authorization was provided

    timeout : int or None, optional
        the maximum duration to wait for an event, in seconds. If no event 
        occurs within the timeout duration, an :class:`AvialTimeout`
        exception is raised. The default is None: wait forever.

    authorization : Authorization or None, optional
        an object authorizing waiting for an event. Authorization is generally
        not required for :func:`wait_event`. 

    Returns
    -------
    None

    Raises
    ------
    AvialTimeout
        if no event has occured before ``timeout`` seconds has passed

    AvialError
        if ``outlet`` is not an entity, or an entity but not an outlet, or
        ``timeout`` is non-numeric, or ``callback`` is not a Python callable

    See also
    --------
    :func:`create_outlet` : create a new outlet entity, to subscribe to some publishees

    :func:`publish_event` : a publishee publishes an event for subscribed outlets 

    :func:`subscribe_event` : an outlet subscribes to a publishee

    Examples
    --------
    An example for :func:`wait_event` requires code in two different
    processes, one process for the calls to :func:`publish_event` that 
    publishes the event, and the
    other process for the calls to :func:`wait_event`, that receive the event
    as it is published. *Start by setting up process 1.*

    >>> import avesterra.avial as av  
    >>> auth = av.initialize()

    Create a publishee, an entity on which we will publish events.  

    >>> pub = av.create_registry('Publishee', True, auth)
    >>> str(pub)
    '<2906857743|167772516|11680352>'

    *Now switch to process 2*, and set it up.

    >>> import avesterra.avial as av  
    >>> auth = av.initialize()

    Create an outlet, an entity that will wait for events.  

    >>> out = av.create_outlet('Test subscriber', av.Class.AVESTERRA, av.Subclass.AVESTERRA, auth)

    Subscribe to the publishee. Note that we need to reference the publishee
    entity via :func:`entity_of`, as the variable ``pub`` in the other process
    does not exist in this process.

    >>> av.subscribe_event(av.entity_of('<2906857743|167772516|11680352>'), out, auth)

    Define a function to call when an event occurs. The function must
    be defined with a signature that includes ``outlet``, ``publishee``,
    ``event``, and so on, all 14 parameters of the event. Our function will
    just print the parameters, but it could do anything.

    >>> def print_event(outlet, publishee, event, attribute, instance, name, key, value, 
    ...                 options, parameter, index, count, mode, authorization):
    ...     print('Event:')
    ...     print(f'  Outlet:    {outlet}')
    ...     print(f'  Publishee: {publishee}')
    ...     print(f'  Event:     {event!s}')
    ...     print(f'  Attribute  {attribute!s}')
    ...     print(f'  Instance:  {instance}')
    ...     print(f'  Name:      {name}')
    ...     print(f'  Key:       {key}')
    ...     print(f'  Value:     {value}')
    ...     print(f'  Options:   {options}')
    ...     print(f'  Parameter: {parameter}')
    ...     print(f'  Index:     {index}')
    ...     print(f'  Count:     {count}')
    ...     print(f'  Mode:      {mode!s}')  
    ...     print('')

    Wait for the event, and when it occurs, call :func:`print_event`.

    >>> av.wait_event(out, print_event)

    :func:`wait_event` does not return, as it waits forever for an event.

    *Switch back to process 1.* Publish an event.

    >>> av.publish_event(pub, auth)

    Nothing happens in this process, *so switch once more to process 2.* 

    (The call to :func:`wait_event` is
    repeated for clarity, although we have only called it once, so far.)

    >>> av.wait_event(out, print_event)
    Event:
      Outlet:    <2906857743|167772516|508302>
      Publishee: <2906857743|167772516|508061>
      Event:     None
      Attribute  None
      Instance:  None
      Name:      None
      Key:       None
      Value:     None
      Options:   None
      Parameter: None
      Index:     None
      Count:     None
      Mode:      None

    As you can see, :func:`wait_event` has now run, printing the outlet
    and the publishee, and all the other parameters with None.
    The published event has nothing on it, except the outlet and the publishee.

    :func:`wait_event` has now finished. Each call to :func:`wait_event`
    waits for a single event. So call it again, to wait for another event.

    >>> av.wait_event(out, print_event)

    *Switch to process 1.* Publish an event with some parameters 
    specified.

    >>> av.publish_event(
    ...     pub, auth, event=av.Event.UPDATE, attribute=av.Attribute.AGE, value=20)

    *Switch to process 2.* As before, the call to :func:`wait_event` is 
    repeated. for clarity.

    >>> av.wait_event(out, print_event)
    Event:
      Outlet:    <2906857743|167772516|1088440>
      Publishee: <2906857743|167772516|1088251>
      Event:     Event.UPDATE
      Attribute  Attribute.AGE
      Instance:  None
      Name:      None
      Key:       None
      Value:     20
      Options:   None
      Parameter: None
      Index:     None
      Count:     None
      Mode:      None

    Wait once more, this time with a short 3 second timeout. Before we can
    even switch back to process 1, :func:`wait_event` times out.

    >>> av.wait_event(out, print_event, timeout=3)
    AvialTimeout: Timeout: Server reported TIMEOUT error: Wait timeout - outlet: <2906857743|167772516|11680353> while waiting on outlet <2906857743|167772516|11680353> with callback=<function print_event at 0x10f288598>, timeout=3

    Clean up process 2.

    >>> av.delete_outlet(out, auth)
    >>> av.finalize()

    *Switch to process 1.* Clean up.

    >>> av.delete_registry(pub, auth) 
    >>> av.finalize()
    """
    return _call_callback_after(
        _wait_event_limited_dur, outlet, callback, timeout, authorization,
        f'Waiting on {outlet} with callback {callback}')

def _call_callback_after(after_fn, outlet, callback, timeout, authorization,
                         msg):
    """Call after_fn, repeatedly if timeout is None."""
    if timeout:
        logger.debug(msg)
        return after_fn(outlet, callback, timeout, authorization)
    else:
        while True:
            try:
                logger.debug(msg)
                return after_fn(outlet, callback, timeout, authorization)
            except at.TimeoutError:
                logger.debug('Timed out, trying again')
                pass

def _wait_event_limited_dur(outlet, callback, timeout, authorization):
    """Wait for an event, or until timeout occurs."""
    # If timeout is None, the call will time out after a fixed duration,
    # currently 60 seconds.
    with suppress_console_error_logging('Outlet timeout'):
        return atapi.wait(
            outlet, 
            _translate_wait_callback(callback),  
            timeout=TranslateFromAvialToAPI.timeout(timeout),
            authorization=TranslateFromAvialToAPI.authorization(authorization) 
        )

def _translate_wait_callback(avial_callback):
    """From an avial callback expecting avial args, return one for API args."""
    if avial_callback is None:
        return None
    elif callable(avial_callback):
        def _callback(outlet, publishee, event, attr, instance, name, key,
                      value, options, parameter, index, count, mode, 
                      auth):
            avial_callback(
                outlet, 
                publishee, 
                TranslateFromAPItoAvial.event(event),
                TranslateFromAPItoAvial.attribute(attr),
                TranslateFromAPItoAvial.instance(instance),
                TranslateFromAPItoAvial.name(name),
                TranslateFromAPItoAvial.key(key),
                TranslateFromAPItoAvial.value(value),
                TranslateFromAPItoAvial.options(options),
                TranslateFromAPItoAvial.parameter(parameter),
                TranslateFromAPItoAvial.index(index),
                TranslateFromAPItoAvial.count(count),
                TranslateFromAPItoAvial.mode(mode),
                TranslateFromAPItoAvial.authorization(auth))
        return _callback
    else:
        raise AvialError(
            f'{avial_callback} is neither a callable function nor None')

@manage_exceptions('while counting events on outlet {0}')
def event_count(outlet): 
    """
    event_count(outlet)
    """
    return atapi.pending(outlet)

@manage_exceptions('while counting subscriptions on entity {0}')
def subscription_count(entity):
    """
    subscription_count(entity)
    """
    return atapi.subscriptions(entity)


################################################################################
#
# Outlet operations
#

@manage_exceptions('while creating outlet named {0} of class {1} subclass {2}')
def create_outlet(name, klass, subklass, auth, *, self_connect=False):
    """
    create_outlet(name, klass, subklass, auth, *, self_connect=False)
    Create and return a new outlet.
    """ 
    outlet = atapi.create(
        name=TranslateFromAvialToAPI.name(name), 
        authorization=auth, 
        klass=klass, 
        subklass=subklass)

    if self_connect:
        atapi.connect(outlet, outlet, authorization=auth)
    atapi.activate(outlet, authorization=auth)
    atapi.authorize(outlet, auth, auth)
    atapi.reference(outlet, authorization=auth)
    return outlet 

@manage_exceptions('while deleting outlet {0}')
def delete_outlet(outlet, auth): 
    """
    delete_outlet(outlet, auth)
    """
    atapi.deactivate(outlet, auth)
    atapi.delete(outlet, auth)

def activate_outlet(*args, **kwargs):
    raise NotImplementedError

def deactivate_outlet(*args, **kwargs):
    raise NotImplementedError

@manage_exceptions('while determining whether entity {0} is activated')
def entity_activated(entity): 
    """
    entity_activated(entity)
    Is the entity an outlet?

    Parameters
    ----------
    entity : Entity
        The entity that may be an outlet

    Returns
    -------
    bool
        whether ``entity`` is an outlet

    Raises
    ------
    AvialError
        if ``entity`` is not an entity

    See also
    --------
    :func:`entity_extinct` : has the entity been deleted?

    :func:`entity_available` : is the entity alive?

    :func:`entity_ready` : is the entity ready to be invoked?  

    :func:`create_outlet` : create a new outlet entity 

    Examples
    --------
    >>> import avesterra.avial as av  
    >>> auth = av.initialize()

    Create an outlet.

    >>> out = av.create_outlet(
    ...     'Test outlet', av.Class.AVESTERRA, av.Subclass.OUTLET, auth)

    Verify that it is an outlet.

    >>> av.entity_activated(out)
    True

    Create an entity that is not an outlet.

    >>> jack = av.create_entity(
    ...     'Jack Nicholson', av.Class.PERSON, av.Subclass.PERSON, auth)

    Verify that it is not an outlet.

    >>> av.entity_activated(jack)
    False

    Clean up.

    >>> av.delete_outlet(out, auth)
    >>> av.delete_entity(jack, auth)
    >>> av.finalize()  
    """
    return atapi.activated(entity)

@manage_exceptions('while adapting outlet {0} with callback {1}')
def adapt_outlet(outlet, callback, authorization, *, timeout=None):
    """
    adapt_outlet(outlet, callback, authorization, *, timeout=None)
    Fasten a callback to an outlet, to be executed on a later invoke.

    Fasten a callback---a Python callable---to an outlet. The callback is 
    executed sometime in the future, when a method is invoked (via
    :func:`invoke_method`) on a entity that is connected to the outlet. 
    Whatever is returned from the execution of the callback is passed back
    to the original entity. 

    Multiple callbacks may be adapted to the same outlet, with multiple calls
    to :func:`adapt_outlet`. But only a single adapter is executed for
    any given invocation of a connected entity. And only a single adapter
    is executed on an outlet at any one time; execution of a callback blocks
    other callbacks (e.g. on other connected entities) until the execution of
    the first callback completes.

    Typically an entity is connected to an outlet when it is first created, as
    specified in the arguments to :func:`create_entity`.

    Parameters
    ----------
    outlet : Entity
        the outlet to which the callback is fastened

    callback : callable
        a Python callable with 15 positional arguments, as listed below. For
        most of these arguments, the amount of the original 
        :func:`invoke_entity` is provided to the callback, e.g. the value of
        the ``name`` argument is the value of the ``name`` on the original
        call to :func:`invoke_entity`.

        outlet 
            the outlet entity on which the callback was fastened
        entity
            the entity that received the original :func:`invoke_entity`
        auxiliary
            the auxiliary entity originally provided to :func:`invoke_entity`,
            or None, if no auxiliary was provided
        method
            the instance of :class:`Method` originally provided to 
            :func:`invoke_entity`, or None, if no method was provided
        attribute
            the instance of :class:`Attribute` originally provided to 
            :func:`invoke_entity`, or None, if no Attribute instance was 
            provided
        instance
            the instance integer originally provided to :func:`invoke_entity`, 
            or None, if no instance was provided
        name
            the name string originally provided to :func:`invoke_entity`, or 
            None, if no name was provided
        key
            the key string originally provided to :func:`invoke_entity`, or 
            None, if no key was provided
        value
            the value (an int, float, bool, str, Entity, list, or dict) 
            originally provded to :func:`invoke_entity`, or 
            None, if no value was provided
        options
            the options string originally provided to :func:`invoke_entity`, or 
            None, if no options was provided
        parameter
            the parameter integer originally provided to :func:`invoke_entity`, 
            or None, if no parameter was provided
        index
            the index integer originally provided to :func:`invoke_entity`, or 
            None, if no index was provided
        count
            the count integer originally provided to :func:`invoke_entity`, or 
            None, if no count was provided
        mode
            the instance of Mode originally provided to :func:`invoke_entity`, 
            or None, if no mode was provided
        authorization
            the instance of :class:`Authorization` originally provided to 
            :func:`invoke_entity`, or None, if no authorization was provided

    authorization : Authorization
        an object authorizing the fastening of a callback to an outlet

    timeout : int or None, optional
        the maximum duration to wait for an :func:`invoke_entity`, in seconds.
        If no invoke occurs with the timeout duration, an :class:`AvialTimeout`
        exception is raised. The default is None: wait forever.

    Returns
    -------
    None

    Raises
    ------
    AvialTimeout
        if no :func:`invoke_entity` has occured before ``timeout`` seconds has 
        passed

    AvialError
        if ``outlet`` is not an entity, or an entity but not an outlet, 
        or ``timeout`` is non-numeric,
        or ``authorization`` does not authorize the operation, 
        or ``callback`` is not a Python callable,
        or ``callback`` raises an exception in its operation.

    See also
    --------
    :func:`create_outlet` : create a new outlet entity, to subscribe to some publishees

    :func:`invoke_entity` : invoke a method on an entity

    Examples
    --------
    An example for :func:`adapt_outlet` requires code in two different 
    processes, one process for the calls to :func:`invoke_event` and the other
    process for adapter, for the calls to :func:`adapt_event`. *Start by 
    setting up the adapter, in its own process.*

    >>> import avesterra.avial as av  
    >>> auth = av.initialize()

    Create an adapter, an outlet that other entities can use to handle methods.
    We will create a very simple homemade adapter. Note that the adapter is
    *self-connected*: it is connected to itself, and handles its own methods.

    >>> homemade = av.create_outlet(
    ...     'Homemade echo adapter', av.Class.AVESTERRA, av.Subclass.ADAPTER, 
    ...     auth, self_connect=True)
    >>> str(homemade)
    '<2906857743|167772516|15641004>'

    Now for the adapter code. Normally the adapter will include
    error handling, logging, and persistence management. But our adapter does
    none of that; it is
    very simple. If the invoked entity is the homemade outlet itself, it ends
    operation on a **CLEAR** method. If the invoked entity is any other 
    entity other than the homemade entity itself, it echoes the **value**
    parameter on an **ECHO** method, or does nothing otherwise. It ignores
    all its paramters, except **outlet**, **entity**, **method**, and 
    **value**.

    >>> still_active = True 
    >>> def echo(outlet, entity, auxiliary, method, attribute, instance, name, 
    ...          key, value, options, parameter, index, count, mode, 
    ...          authorization):
    ...     global still_active
    ...     if outlet == entity:
    ...         if method == av.Method.CLEAR:
    ...             still_active = False
    ...             return
    ...         else:
    ...             return
    ...     else:
    ...         if method == av.Method.ECHO:
    ...             return value
    ...         else:
    ...             return

    Note that the adapter handles all possible methods.

    Now we execute :func:`adapt_outlet`. It blocks until some entity connected
    to our homemade adapter receives an :func:`invoke_entity`. When it receives
    an invocation, it handles it, with the :func:`echo` function above. Then
    it loops, blocking again until the next invocation.

    >>> while still_active:
    ...     av.adapt_outlet(homemade, echo, authorization=auth)

    This process is blocked, *so switch to another process and set it up.*

    >>> import avesterra.avial as av  
    >>> auth = av.initialize()

    Create an entity, and connect it to our newly created homemade adapter.

    >>> homemade = av.entity_of('<2906857743|167772516|15641004>')
    >>> echoed = av.create_entity(
    ...     'Counted', av.Class.OBJECT, av.Subclass.BUILDING, auth,
    ...     outlet=homemade)

    Invoke **ECHO** on our new entity, with an integer value. The adapter in
    the other process echoes the integer.

    >>> av.invoke_entity(echoed, method=av.Method.ECHO, value=27)
    27

    Invoke **ECHO**, with a more complex (but jsonifiable) value.

    >>> av.invoke_entity(echoed, method=av.Method.ECHO, value=['abc', {'foo': 12, 'bar': 13}])
    ['abc', {'foo': 12, 'bar': 13}]

    Invoke **ECHO**, with a value that is an entity, in this case the homemade
    adapter itself.

    >>> str(av.invoke_entity(echoed, method=av.Method.ECHO, value=homemade))
    '<2906857743|167772516|15641004>'

    Invoke another method.

    >>> av.invoke_entity(echoed, method=av.Method.COUNT)

    The **COUNT** method is handled, but nothing is returned.

    Delete our entity. Note that we need to delete the entity before we
    shut down the adapter, as the adapter is needed to handle the **DELETE**
    method within :func:`delete_entity`, in case the adapter needs (e.g.) 
    delete the persistence for the entity.

    >>> av.delete_entity(echoed, auth)

    We stop the adapter by invoking **CLEAR** on it.

    >>> av.invoke_entity(homemade, method=av.Method.CLEAR)

    Clean up this second process.

    >>> av.finalize()

    Return to the original process where the adapter was running. Now we 
    discover that it has finished. Handling **CLEAR** caused **still_active** 
    to be set to False, and the loop exits.

    Delete the adapter and clean up.

    >>> av.delete_outlet(homemade, auth)
    >>> av.finalize()
    """ 
    _call_callback_after(
        _adapt_outlet_limited_dur, outlet, callback, timeout, authorization,
        f'Adapting {outlet} with callback {callback}')

def _adapt_outlet_limited_dur(outlet, callback, timeout, authorization):
    with suppress_console_error_logging('The socket * was unexpectedly closed'):
        atapi.adapt(
            outlet, 
            adapter=_translate_adapt_callback(callback),
            timeout=TranslateFromAvialToAPI.timeout(timeout),
            authorization=TranslateFromAvialToAPI.authorization(authorization) )

def _translate_adapt_callback(avial_callback):
    """From an avial callback expecting avial args, return one for API args."""
    if callable(avial_callback):
        def _callback(outlet, entity, auxiliary, method, attr, instance, name, 
                      key, value, options, parameter, index, count, mode, auth):
            response = avial_callback(
                outlet, 
                entity, 
                TranslateFromAPItoAvial.auxiliary(auxiliary),
                TranslateFromAPItoAvial.method(method), 
                TranslateFromAPItoAvial.attribute(attr),
                TranslateFromAPItoAvial.instance(instance),
                TranslateFromAPItoAvial.name(name),
                TranslateFromAPItoAvial.key(key),
                TranslateFromAPItoAvial.value(value),
                TranslateFromAPItoAvial.options(options),
                TranslateFromAPItoAvial.parameter(parameter),
                TranslateFromAPItoAvial.index(index),
                TranslateFromAPItoAvial.count(count),
                TranslateFromAPItoAvial.mode(mode),
                TranslateFromAPItoAvial.authorization(auth))
            return TranslateFromAPItoAvial.value(response)
        return _callback
    else:
        raise AvialError(f'{avial_callback} is not a callable')

@manage_exceptions('while resetting outlet {0}')
def reset_outlet(outlet, auth): 
    """
    reset_outlet(outlet, auth)
    """
    atapi.reset(outlet, auth)

@manage_exceptions('while locking outlet {0}')
def lock_outlet(outlet, auth, *, timeout=None): 
    """
    lock_outlet(outlet, auth, *, timeout=None)
    """
    atapi.lock(
        outlet, 
        timeout=TranslateFromAvialToAPI.timeout(timeout),
        authorization=TranslateFromAvialToAPI.authorization(auth))

@manage_exceptions('while unlocking outlet {0}')
def unlock_outlet(outlet, auth):
    """
    unlock_outlet(outlet, auth)
    """
    atapi.unlock(
        outlet, authorization=TranslateFromAvialToAPI.authorization(auth))

@manage_exceptions('while determining whether entity {0} is locked')
def entity_locked(entity): 
    """
    entity_locked(entity)
    """
    return atapi.locked(entity)

################################################################################
#
# Data operations
#

@manage_exceptions('while reading data from {0}')
def read_data(entity, *, index=None, count=None): 
    """
    read_data(entity, *, index=None, count=None)
    """
    return invoke(
        entity, Method.READ, index=index, count=count, return_results=True)

@manage_exceptions('while writing data to {0}')
def write_data(entity, bytez, auth, *, index=None): 
    """
    write_data(entity, bytez, auth, *, index=None)
    """
    if isinstance(bytez, bytes):
        invoke(
            entity, Method.WRITE, value=bytez, index=index, authorization=auth)
    else:
        raise AvialError(
            f'write_data only writes bytes, not {type(bytez).__name__}')

@manage_exceptions('while erasing data from {0}')
def erase_data(entity, auth): 
    """
    erase_data(entity, auth)
    """
    invoke(entity, Method.ERASE, authorization=auth)

@manage_exceptions('while determing data size of {0}')
def data_count(entity): 
    """
    data_count(entity)
    """
    return invoke(
        entity, Method.COUNT, parameter=Argument.DATA, return_results=True)


################################################################################
#
# Suppressing console error logging
#


class LogFilter(logging.Filter):
    """A logging filter that checks match against log record."""
    def __init__(self, msg):
        self._message = msg
        super().__init__()

    def filter(self, record):
        return self._message not in record.getMessage()

@contextlib.contextmanager
def suppress_console_error_logging(msg=''):
    """Temporarily suppress reporting console errors with msg."""
    # Default: suppress all console logging
    filter = LogFilter(msg)
    root_logger = logging.getLogger()
    suppressed_handlers = []
    for handler in root_logger.handlers:
        if type(handler) == logging.StreamHandler:
            suppressed_handlers.append(handler)
            handler.addFilter(filter)
    yield
    for handler in suppressed_handlers:
        handler.removeFilter(filter) 

################################################################################
#
# Ontology, retrieved on initialization
#

# Gets redefined dynamically within taxonomy()
# So this is a bit of bootstrapping.
class Class(enum.IntEnum):
    """AvesTerra class."""
    NULL = 0
class Subclass(enum.IntEnum):
    """AvesTerra subclass."""
    NULL = 0
class Attribute(enum.IntEnum):
    NULL = 0
    # Used before the whole is redefined
    OTHER = 133
class Method(enum.IntEnum):
    """AvesTerra method."""
    NULL = 0
    # Used before the whole is redefined
    RETRIEVE=33
class Event(enum.IntEnum):
    NULL = 0
class Condition(enum.IntEnum):
    NULL = 0
class Mode(enum.IntEnum):
    NULL = 0
class Argument(enum.IntEnum):
    NULL = 0
class Operator(enum.IntEnum):
    NULL = 0
class Precedence(enum.IntEnum):
    NULL = 0
class Notice(enum.IntEnum):
    NULL = 0

# Note that this is unrelated to programmatic exceptions in Python
class Error(enum.IntEnum):
    NULL = 0

def _initialize_taxonomy():
    """Set up the ontology for everything else"""
    # Note this must be done early, just after logging is set up
    global Class, Subclass, Attribute, Method, Event, Condition, Mode, Argument
    global Operator, Error, Precedence, Notice
    logger.debug('Importing the ontology')
    (class_spec, subclass_spec, attribute_spec, method_spec, event_spec, 
        condition_spec, mode_spec, argument_spec, operator_spec, error_spec,
        precedence_spec, notice_spec) = _retrieve_ontology_specs()
    Class = _make_enumeration('Class', class_spec, '_CLASS')
    Subclass = _make_enumeration('Subclass', subclass_spec, '_SUBCLASS')
    Attribute = _make_enumeration('Attribute', attribute_spec, '_ATTRIBUTE')
    Method = _make_enumeration('Method', method_spec, '_METHOD')
    Event = _make_enumeration('Event', event_spec, '_EVENT')
    Condition = _make_enumeration('Condition', condition_spec, '_CONDITION')
    Mode = _make_enumeration('Mode', mode_spec, '_MODE')
    Argument = _make_enumeration('Argument', argument_spec, '_ARGUMENT')
    Operator = _make_enumeration('Operator', operator_spec, '_OPERATOR')
    Error = _make_enumeration('Error', error_spec, '_ERROR')
    Precedence = _make_enumeration('Precedence', precedence_spec, '_PRECEDENCE')
    Notice = _make_enumeration('Notice', notice_spec, '_NOTICE')

def _make_enumeration(enum_name, spec, to_be_trimmed):
    """Make an enum from the spec"""
    return enum.IntEnum(enum_name, _translate_spec(spec, len(to_be_trimmed)))

def _retrieve_ontology_specs():
    """Pull ontology specs and return them, as it is"""
    logger.debug('Pulling the ontology details.') 
    
    taxonomy_entity_IDs = _retrieve_taxonomy_entity_IDs()
    class_spec = _get_spec(taxonomy_entity_IDs['Class Taxonomy'])
    subclass_spec = _get_spec(taxonomy_entity_IDs['Subclass Taxonomy'])
    attribute_spec = _get_spec(
        taxonomy_entity_IDs['Attribute Taxonomy'])
    method_spec = _get_spec(taxonomy_entity_IDs['Method Taxonomy'])
    event_spec = _get_spec(taxonomy_entity_IDs['Event Taxonomy'])
    condition_spec = _get_spec(taxonomy_entity_IDs['Condition Taxonomy'])
    mode_spec = _get_spec(taxonomy_entity_IDs['Mode Taxonomy']) 
    argument_spec = _get_spec(taxonomy_entity_IDs['Argument Taxonomy'])
    operator_spec = _get_spec(taxonomy_entity_IDs['Operator Taxonomy'])
    error_spec = _get_spec(taxonomy_entity_IDs['Error Taxonomy'])
    precedence_spec = _get_spec(taxonomy_entity_IDs['Precedence Taxonomy'])
    notice_spec = _get_spec(taxonomy_entity_IDs['Notice Taxonomy'])
    return (
        class_spec, subclass_spec, attribute_spec, method_spec, event_spec,
        condition_spec, mode_spec, argument_spec, operator_spec, error_spec,
        precedence_spec, notice_spec)

def _retrieve_taxonomy_entity_IDs():
    """Find the entity IDs of all the taxonomies, and return in a dict"""
    logger.debug('Finding the taxonomy entity IDs')
    taxonomy_spec = _get_spec(taxonomy_registry())
    return _translate_triples_to_dict(taxonomy_spec['Properties'])

def _translate_triples_to_dict(list_of_triples):
    """Collapse the list of triples to a single dictionary"""
    def maybe_translate_entity_dict_to_UUID(maybe_dict):
        if 'ENTITY' in maybe_dict:
            return maybe_dict['ENTITY']
        else:
            return maybe_dict 

    return {k:maybe_translate_entity_dict_to_UUID(v) 
            for k, ignore, v in list_of_triples}

def _get_spec(spec_entity):
    """Get the taxonomy spec from server"""
    return retrieve_entity(entity_of(spec_entity), handle_exceptions=False)

def _translate_spec(raw_spec, suffix_length):
    """Translate the spec from AvesTerra form to enum form"""
    return {_strip_suffix(name, suffix_length):int(number)
            for name, ignore, number in raw_spec['Properties']}

def _strip_suffix(string, how_many):
    """Return a string without the last how_many characters"""
    return string[: - how_many]

def _initialize_basic_logging():
    """Initialize basic logging."""
    # does nothing if handlers already exist
    # not clear why this is necessary, since calls to logging.debug() etc.
    # should call this by default. 
    logging.basicConfig()

def _initialize_store_schema():
    """Initialize the store_schema."""
    global store_schema
    filename = 'AvesTerra_store_format.json'
    try:
        mod_path = _path_for_this_module()
        store_format_path = os.path.join(mod_path, filename)
        with open(store_format_path, 'r') as schema_file:
            store_schema = json.load(schema_file)
    except FileNotFoundError:
        print(f'Store format not found in directory {mod_path}')
        logging.warning(f'Store format not found in directory {mod_path}')
        store_schema = None

def _path_for_this_module():
    """Determine the path for the module this function lives in.""" 
    return os.path.dirname(os.path.abspath(__file__))

################################################################################
#
# Translate arguments for atapi
#

class TranslateFromAvialToAPI:
    """Translate so Avesterra_API can understand."""
    @classmethod
    def method(cls, method):
        """Translate method to a form that Avesterra_API can understand."""
        return cls._translate(method, atapi.NULL_METHOD, 'method', int)

    @classmethod
    def attribute(cls, attribute):
        """Translate attribute to a form that Avesterra_API can understand."""
        return cls._translate(attribute, atapi.NULL_ATTRIBUTE, 'attribute', int)

    @classmethod
    def instance(cls, instance):
        """Translate instance to a form that Avesterra_API can understand."""
        return cls._translate(instance, atapi.NULL_INSTANCE, 'instance', int)

    @classmethod
    def name(cls, name):
        """Translate name to a form that Avesterra_API can understand."""
        return cls._translate(name, atapi.NULL_NAME, 'name', cls._encode)

    @classmethod
    def key(cls, key):
        """Translate key to a form that Avesterra_API can understand."""
        return cls._translate(key, atapi.NULL_KEY, 'key', cls._encode)

    @classmethod
    def value(cls, value):
        """Translate value to a form that Avesterra_API can understand."""
        if value is None:
            return atapi.NULL_VALUE
        elif not isinstance(value, Value):
            return Value.from_object(value)
        else:
            return value

    @classmethod
    def options(cls, options):
        """Translate options to a form that Avesterra_API can understand."""
        return cls._translate(
            options, atapi.NULL_OPTIONS, 'options', cls._encode)

    @classmethod
    def parameter(cls, parameter):
        """Translate parameter to a form that Avesterra_API can understand."""
        return cls._translate(parameter, atapi.NULL_PARAMETER, 'parameter', int)

    @classmethod
    def index(cls, index):
        """Translate index to a form that Avesterra_API can understand."""
        return cls._translate(index, atapi.NULL_INDEX, 'index', int)

    @classmethod
    def count(cls, count):
        """Translate count to a form that Avesterra_API can understand."""
        return cls._translate(count, atapi.NULL_COUNT, 'count', int)

    @classmethod
    def mode(cls, mode):
        """Translate mode to a form that Avesterra_API can understand."""
        return cls._translate(mode, atapi.NULL_MODE, 'mode', int)

    @classmethod
    def precedence(cls, precedence):
        """Translate precedence to a form that Avesterra_API can understand."""
        return cls._translate(
            precedence, atapi.NULL_PRECEDENCE, 'precedence', int)

    @classmethod
    def timeout(cls, timeout):
        """Translate timeout to a form that Avesterra_API can understand."""
        return cls._translate(timeout, atapi.NULL_TIMEOUT, 'timeout', int)

    @classmethod
    def entity(cls, entity):
        """Translate entity to a form that AvesTerra_API can understand."""
        return cls._translate(entity, atapi.NULL_ENTITY, 'entity')

    @classmethod
    def authorization(cls, authorization):
        """Translate authorization to a form that AvesTerra_API can understand."""
        return cls._translate(
            authorization, atapi.NULL_AUTHORIZATION, 'authorization')

    @classmethod
    def event(cls, event):
        """Translate event to a form that Avesterra_API can understand."""
        return cls._translate(event, atapi.NULL_EVENT, 'event', int)

    @staticmethod
    def _translate(thing, none_value, type_string, converter=lambda x: x):
        try:
            return none_value if thing is None else converter(thing)
        except (ValueError, TypeError):
            raise AvialError(f'{thing} is not a valid {type_string}')

    @staticmethod
    def _encode(thing):
        """If thing is not a string or byte array, raise an error."""
        if isinstance(thing, str):
            return thing.encode(at.ENCODING)
        elif isinstance(thing, bytes):
            return thing
        else:
            raise TypeError() 


class TranslateFromAPItoAvial:
    """Translate from API form back to Avial form."""
    @classmethod
    def auxiliary(cls, auxiliary):
        """Translate auxiliary to a form that Avial understands."""
        return cls._translate(auxiliary, atapi.NULL_ENTITY, 'auxiliary')

    @classmethod
    def method(cls, method):
        """Translate method to a form Avial understands."""
        return cls._translate(method, atapi.NULL_METHOD, 'method', Method)
         
    @classmethod
    def event(cls, event):
        """Translate event to a form that Avial understands."""
        return cls._translate(event, atapi.NULL_EVENT, 'event', Event)

    @classmethod
    def attribute(cls, attr):
        """Translate attr to a form that Avial understands."""
        return cls._translate(
            attr, atapi.NULL_ATTRIBUTE, 'attribute', Attribute)

    @classmethod
    def instance(cls, instance):
        """Translate instance to a form that Avial understands."""
        return cls._translate(instance, atapi.NULL_INSTANCE, 'instance')

    @classmethod
    def name(cls, name):
        """Translate name to a form that Avial understands."""
        return cls._translate(name, atapi.NULL_NAME, 'name', cls._decode)

    @classmethod
    def key(cls, key):
        """Translate key to a form that Avial understands."""
        return cls._translate(key, atapi.NULL_KEY, 'key', cls._decode)

    @staticmethod
    def value(value):
        """Translate value to a form Avial understands."""
        result = Value.from_object(value).instantiate()
        if result == atapi.NULL_VALUE or result == b'':
            return None
        else:
            return result

    @classmethod
    def options(cls, options):
        """Translate options to a form that Avial understands."""
        return cls._translate(
            options, atapi.NULL_OPTIONS, 'options', cls._decode)

    @classmethod
    def parameter(cls, parameter):
        """Translate parameter to a form that Avial understands."""
        return cls._translate(parameter, atapi.NULL_PARAMETER, 'parameter')

    @classmethod
    def index(cls, index):
        """Translate index to a form that Avial understands."""
        return cls._translate(index, atapi.NULL_INDEX, 'index')

    @classmethod
    def count(cls, count):
        """Translate count to a form that Avial understands."""
        return cls._translate(count, atapi.NULL_COUNT, 'count')

    @classmethod
    def mode(cls, mode):
        """Translate mode to a form that Avial understands."""
        return cls._translate(mode, atapi.NULL_MODE, 'mode')

    @classmethod
    def precedence(cls, precedence):
        """Translate precedence to a form that Avial understands."""
        return cls._translate(
            precedence, atapi.NULL_PRECEDENCE, 'precedence', Precedence)

    @classmethod
    def authorization(cls, authorization):
        """Translate authorization to a form that Avial understands."""
        return cls._translate(
            authorization, atapi.NULL_AUTHORIZATION, 'authorization')

    @staticmethod
    def _translate(thing, none_value, type_string, converter=lambda x: x):
        try:
            return None if thing == none_value else converter(thing)
        except (ValueError, TypeError):
            raise AvialError(f'{thing} is not a valid {type_string}')

    @staticmethod
    def _decode(thing):
        """If thing is not a string or byte array, raise an error."""
        if isinstance(thing, bytes):
            return thing.decode(at.ENCODING)
        elif isinstance(thing, str):
            return thing
        else:
            raise TypeError() 


################################################################################
#
# Utility functions
#

@functools.lru_cache(maxsize=None) 
def entity_of(s):
    """
    entity_of(s)
    Intern an entity of name s.
    """
    if isinstance(s, at.Entity):
        return s
    else: 
        try: 
            return at.entity_of(s)
        except Exception:
            raise AvialError('{} not understood as entity'.format(s))

def avesterra_registry():       return entity_of('<0|0|1>')
def taxonomy_registry():        return entity_of('<0|0|2>')
def adapter_registry():         return entity_of("<0|0|3>")
def cron_registry():            return entity_of("<0|0|4>")
def test_registry():            return entity_of("<0|0|5>")
def trash_registry():           return entity_of("<0|0|6>")
def bond_registry():            return entity_of("<0|0|7>")
def tuple_registry():           return entity_of("<0|0|8>")
def health_registry():          return entity_of("<0|0|9>")
def registry_outlet():          return entity_of("<0|0|10>")
def object_outlet():            return entity_of("<0|0|11>")
def folder_outlet():            return entity_of("<0|0|12>")
def index_outlet():             return entity_of("<0|0|13>")
def timer_outlet():             return entity_of("<0|0|14>")
def test_outlet():              return entity_of("<0|0|15>")
def trash_outlet():             return entity_of("<0|0|16>")
def graph_outlet():             return entity_of("<0|0|17>")
def tuple_outlet():             return entity_of("<0|0|18>")
def workspace_outlet():         return entity_of("<0|0|19>")
def orchestra_registry():       return entity_of("<0|0|100>")
def avian_registry():           return entity_of("<0|0|101>")
def aida_registry():            return entity_of("<0|0|102>")
def community_outlet():         return entity_of("<0|0|211>")
def municipal_outlet():         return entity_of("<0|0|311>")
def directory_outlet():         return entity_of("<0|0|411>")
def traffic_outlet():           return entity_of("<0|0|511>")
def repair_outlet():            return entity_of("<0|0|611>")
def relay_outlet():             return entity_of("<0|0|711>")
def utility_outlet():           return entity_of("<0|0|811>")
def emergency_outlet():         return entity_of("<0|0|911>")
def covid_outlet():             return entity_of("<0|0|912>")
def american_registry():        return entity_of("<0|0|20016>")
def georgetown_registry():      return entity_of("<0|0|20057>")
def hanging_steel_registry():   return entity_of("<0|0|20165>")
def agent_labs_registry():      return entity_of("<0|0|21029>")
def darpa_registry():           return entity_of("<0|0|22203>")
def ornl_registry():            return entity_of("<0|0|37831>")
def ccm_registry():             return entity_of("<0|0|75006>")
def ledr_registry():            return entity_of("<0|0|94111>")
def llnl_registry():            return entity_of("<0|0|94550>")
def pnnl_registry():            return entity_of("<0|0|99354>")

def max_async_connections():
    return atapi.max_async_connections()

################################################################################
#
# Errors
#

class AvialError(at.AvesTerraError):
    """Some sort of error with Avial functionality."""
    pass 

class AvialTimeout(AvialError):
    """Something times out."""
    pass 

class AvialNotFound(AvialError):
    """Something is not found"""
    pass



