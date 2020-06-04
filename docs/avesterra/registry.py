#!/usr/bin/env python3

"""registry.py: AvesTerra layer implementing registries
"""

__author__ = "Dave Bridgeland and J. C. Smart"
__copyright__ = "Copyright 2015-2020, Georgetown University"
__patents__ = "US Patent No. 9,996,567"
__credits__ = ["J. C. Smart", "Dave Bridgeland", "Norman Kraft"]

__version__ = "2.5.3"
__maintainer__ = "Dave Bridgeland"
__email__ = "dave@hangingsteel.com"
__status__ = "Prototype"

import logging

import avesterra.avial as av 
import avesterra.api as atapi
import avesterra.base as at

logger = logging.getLogger(__name__)

################################################################################
#
# For type checking
#

class Verify(at.Verify):
    """Type checking, raising an error otherwise."""
    # Not pythonic, but necessary for working with AvesTerra
    @staticmethod
    def registry(obj):
        """Raise error if obj is not a registry."""
        at.Verify.entity(obj)
        if av.entity_subclass(obj) != av.Subclass.REGISTRY:
            raise RegistryError(f'{obj} is not a registry')


################################################################################
#
# Registry operations
#

@av.manage_exceptions('while creating registry {0} with autosave {1}')
def create_registry(name, autosave, auth):
    """
    Create and return a new registry.

    Create a new registry. Indicate whether changes (i.e. newly registered
    entities) should be saved automatially.

    Parameters
    ----------
    name : str
        the name of the registry to be created.

    autosave : bool
        should every change to the registry be automatically saved by the 
        registry adapter? Or should changes only be saved on an explicit call to
        :func:`save_entity`?

    auth : Authorization
        an object that authorizes the creation of the registry

    Returns
    -------
    at.Entity
        The newly created registry entity.

    Raises
    ------
    RegistryError
        If ``name`` is not a string, or ``auth`` does not permit registry
        creation,  or the underlying implementation raises some other error.

    See also
    --------
    :func:`delete_registry` : delete a registry

    :func:`register_entity` : registry an entity in a registry

    :func:`deregister_entity` : remove an entity from a registry

    :func:`lookup_registry` : look up a key in a registry

    :func:`create_entity` : create an entity

    Examples
    --------
    >>> import avesterra.registry as reg
    >>> import avesterra.avial as av  
    >>> auth = av.initialize() 

    Create a registry of Academy Award winners.

    >>> oscar_winners = reg.create_registry('Oscar winners', True, auth)

    Create an entity for Jack Nicholson.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jack
    Entity(2906857743, 167772516, 1419285)

    Register Jack in the Oscar registry.

    >>> reg.register_entity(oscar_winners, 'Jack Nicholson', 'Jack Nicholson', jack, auth)

    Look him up, to make sure he is there.

    >>> reg.lookup_registry(oscar_winners, 'Jack Nicholson')
    Entity(2906857743, 167772516, 1419285)

    Look up John Malkovich, who surprisingly has never won an Oscar.

    >>> reg.lookup_registry(oscar_winners, 'John Malkovich')
    False

    Clean up the example and end the session.

    >>> reg.delete_registry(oscar_winners, auth)
    >>> av.delete_entity(jack, auth)
    >>> av.finalize()
    """
    return av.create_entity(
        name, av.Class.AVESTERRA, av.Subclass.REGISTRY, auth, 
        outlet=av.registry_outlet(), autosave=autosave, 
        handle_exceptions=False)

@av.manage_exceptions('while deleting registry {0}')
def delete_registry(registry, auth):
    """
    Delete the registry, dereferencing all registered entities.

    When an entity is registered in a registry, its reference count is
    incremented, preventing it from being garbage colleted. When a registry
    is deleted, each of the registered entities is dereferenced, decrementing
    each of their reference counts. If an entity's reference count reaches
    zero, it is deleted, as garbage.

    Parameters
    ----------
    registry : Entity
        the registry to be deleted

    auth : Authorization
        an object that authorizes the deletion of the registry

    Returns
    -------
    None

    Raises
    ------
    RegistryError
        if ``registry`` is not a registry, or ``auth`` does not permit 
        registry deletion.

    See also
    --------
    :func:`create_registry` : create a registry

    :func:`register_entity` : registry an entity in a registry

    :func:`deregister_entity` : remove an entity from a registry

    :func:`lookup_registry` : look up a key in a registry

    :func:`create_entity` : create an entity
    
    Examples
    --------
    >>> import avesterra.registry as reg
    >>> import avesterra.avial as av  
    >>> auth = av.initialize() 

    Create a registry of Academy Award winners.

    >>> oscar_winners = reg.create_registry('Oscar winners', True, auth)

    Create an entity for Jack Nicholson.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jack
    Entity(2906857743, 167772516, 1419285)

    Register Jack in the Oscar registry.

    >>> reg.register_entity(oscar_winners, 'Jack Nicholson', 'Jack Nicholson', jack, auth)

    Look him up, to make sure he is there.

    >>> reg.lookup_registry(oscar_winners, 'Jack Nicholson')
    Entity(2906857743, 167772516, 1419285)

    Delete the registry and clean up

    >>> reg.delete_registry(oscar_winners, auth)
    >>> av.finalize()
    """  
    # Using delete_registry on a non-registry entity will mess up reference
    # counts and can raise difficult-to-explain errors
    # Departs from the reference implementation
    Verify.registry(registry)
    for entity in registry_entities(registry):
        av.dereference_entity(entity, auth, handle_exceptions=False)
        _release_entity(entity, auth)
    av.delete_entity(registry, auth, handle_exceptions=False)

def _release_entity(entity, auth):
    """Maybe delete an entity, if there are no more references to it."""
    if av.entity_references(entity, handle_exceptions=False) <= 0:
        av.delete_entity(entity, auth, handle_exceptions=False)

def registry_entities(registry, handle_exceptions=False, full_details=False):
    """Create a generator of entities in a registry."""
    registry_details = av.retrieve_entity(
        registry, handle_exceptions=handle_exceptions)
    if 'Properties' in registry_details:
        for property in registry_details['Properties']:
            name = property[0]
            key = property[1]
            maybe_entity = property[2]
            try:
                if full_details:
                    yield name, key, av.entity_of(maybe_entity['ENTITY'])
                else:
                    yield av.entity_of(maybe_entity['ENTITY'])
            except Exception:
                try:
                    if full_details:
                        yield name, key, av.entity_of(maybe_entity)
                    else:
                        yield av.entity_of(maybe_entity)
                except Exception:
                    # not an entity, just continue
                    pass
    else:
        return []

@av.manage_exceptions(
    'while registering entity {3} in registry {0} with name {1}, key {2}')
def register_entity(registry, name, key, entity, auth):
    """
    Register the entity in the registry.

    Register the entity in the registry, deregistering any entity that is 
    already in the registry under that key. Update reference counts.

    Parameters
    ----------
    registry : Entity
        the registry that is to include ``entity``

    name : str
        the name under which ``entity`` is to be registered

    key : str
        the key under which ``entity`` is to be registred

    entity : Entity
        the entity to be registered

    auth : Authorization
        an object that authorizes the registration of the entity

    Returns
    -------
    None

    Raises
    ------
    RegistryError
        if ``registry`` is not a registry, or ``entity`` is not an entity, or
        ``name`` is an invalid name, or ``key`` is an invalid key,
        or ``auth`` does not permit the entity to be registered, or the
        underlying implementation raises some other error.

    See also
    --------
    :func:`create_registry` : create a registry

    :func:`delete_registry` : delete a registry

    :func:`deregister_entity` : remove an entity from a registry

    :func:`lookup_registry` : look up a key in a registry

    Examples
    --------

    >>> import avesterra.registry as reg
    >>> import avesterra.avial as av  
    >>> auth = av.initialize() 

    Create a registry of Academy Award winners.

    >>> oscar_winners = reg.create_registry('Oscar winners', True, auth)

    Create an entity for Jack Nicholson.

    >>> jack = av.create_entity(
    ...     "Jack Nicholson", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> jack
    Entity(2906857743, 167772516, 1419285)

    Register Jack in the Oscar registry.

    >>> reg.register_entity(oscar_winners, 'Jack Nicholson', 'Jack Nicholson', jack, auth)

    Look him up, to make sure he is there.

    >>> reg.lookup_registry(oscar_winners, 'Jack Nicholson')
    Entity(2906857743, 167772516, 1419285)

    Look up John Malkovich, who surprisingly has never won an Oscar.

    >>> reg.lookup_registry(oscar_winners, 'John Malkovich')
    False

    Correct that oversight by the Academy of Motion Picture Arts and Sciences.

    >>> malkovich = av.create_entity(
    ...     "John Malkovich", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> reg.register_entity(
    ...     oscar_winners, 'John Malkovich', 'John Malkovich', malkovich, auth)

    Clean up the example and end the session.

    >>> reg.delete_registry(oscar_winners, auth)
    >>> av.delete_entity(jack, auth)
    >>> av.delete_entity(malkovich, auth)
    >>> av.finalize()
    """ 
    # Using register_entity on a non-registry entity will mess up reference
    # counts  
    # Departs from the reference implementation
    Verify.entity(entity)
    Verify.registry(registry)
    replaced_entity = av.invoke(
        registry, av.Method.UPDATE, name=name, key=key, value=entity, 
        authorization=auth, return_results=True)

    if replaced_entity != entity:
        # somewhat different from reference implementation in that we never
        # coerce an empty string into a null entity
        if replaced_entity:    
            av.dereference_entity(
                replaced_entity, auth, handle_exceptions=False)
            _release_entity(replaced_entity, auth)

        if entity != atapi.NULL_ENTITY:
            av.reference_entity(entity, auth, handle_exceptions=False)

@av.manage_exceptions('while deregistering entity from registry {0}')
def deregister_entity(registry, auth, *, index=None, key=None):
    """
    Remove an entity from a registry.
    
    Remove an entity from a registry, and update its reference counts, deleting
    the entity if reference count reaches zero. The entity to be deregistgered
    is identified by key or by index. If
    both a key and an index are provided, the index is ignored and the key is
    used. If neither are provided, the last entity is removed.

    Parameters
    ----------
    registry : Entity
        the registry from which the entity is to be removed

    auth : Authorization
        an object that authorizes the removal of the entity from the registry

    key : str, optional
        the key identifying the entity to be removed. If not provided, remove
        an entity by ``index``.

    index : int, optional
        the position of the entity to be removed. For example, if ``index`` is
        3, the third entity is removed from the registry. Note that if ``key`` 
        is provided, ``index`` is ignored. 

    Returns
    -------
    None

    Raises
    ------
    RegistryError
        if ``registry`` is not a registry, or ``key`` is not found in the
        registry, or ``auth`` does not permit deregistering, or the underlying
        implementation raises some other error.

    See also
    --------
    :func:`create_registry` : create a registry

    :func:`delete_registry` : delete a registry

    :func:`register_entity` : register an entity in a registry

    :func:`lookup_registry` : look up a key in a registry

    Examples
    --------
    >>> import avesterra.registry as reg
    >>> import avesterra.avial as av  
    >>> auth = av.initialize() 
    >>> import pprint
    >>> pp = pprint.PrettyPrinter(indent=4)

    Create a few people entities.

    >>> craig = av.create_entity(
    ...     "Craig Finn", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> tad = av.create_entity(
    ...     "Tad Kubler", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> galen = av.create_entity(
    ...     "Galen Polivka", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> judd = av.create_entity(
    ...     "Judd Counsell", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)

    Create a registry and add the people entities to the registry.

    >>> ths = reg.create_registry("The Hold Steady", True, auth)
    >>> reg.register_entity(ths, 'lead vocals, guitar', 'Craig', craig, auth)
    >>> reg.register_entity(ths, 'lead guitar, backing vocals', 'Tad', tad, auth)
    >>> reg.register_entity(ths, 'bass', 'Galen', galen, auth)
    >>> reg.register_entity(ths, 'drums', 'Judd', judd, auth)
    >>> pp.pprint(av.retrieve_entity(ths)['Properties'])
    [   ['lead vocals, guitar', 'Craig', '<2906857743|167772516|15626357>'],
        ['lead guitar, backing vocals', 'Tad', '<2906857743|167772516|15626358>'],
        ['bass', 'Galen', '<2906857743|167772516|15626359>'],
        ['drums', 'Judd', '<2906857743|167772516|15626360>']]

    Judd leaves the band. Deregister him by key.

    >>> reg.deregister_entity(ths, auth, key='Judd')

    The band needs a drummer. Add Bobby.

    >>> bobby = av.create_entity(
    ...     "Bobby Drake", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> reg.register_entity(ths, 'drums, percussion', 'Bobby', bobby, auth)
    >>> pp.pprint(av.retrieve_entity(ths)['Properties'])
    [   ['lead vocals, guitar', 'Craig', '<2906857743|167772516|15626357>'],
        ['lead guitar, backing vocals', 'Tad', '<2906857743|167772516|15626358>'],
        ['bass', 'Galen', '<2906857743|167772516|15626359>'],
        ['drums, percussion', 'Bobby', '<2906857743|167772516|15626362>']]

    Franz joins the band. Franz plays a lot of instruments.

    >>> franz = av.create_entity(
    ...     "Franz Nicolay", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> reg.register_entity(ths, 'piano, keyboards, accordion, harmonica, backing vocals', 'Franz', franz, auth)
    >>> pp.pprint(av.retrieve_entity(ths)['Properties'])
    [   ['lead vocals, guitar', 'Craig', '<2906857743|167772516|15626357>'],
        ['lead guitar, backing vocals', 'Tad', '<2906857743|167772516|15626358>'],
        ['bass', 'Galen', '<2906857743|167772516|15626359>'],
        ['drums, percussion', 'Bobby', '<2906857743|167772516|15626362>'],
        [   'piano, keyboards, accordion, harmonica, backing vocals',
            'Franz',
            '<2906857743|167772516|15626363>']]

    Franz leaves. Deregister him by index.

    >>> reg.deregister_entity(ths, auth, index=5)

    Steve joins.

    >>> steve = av.create_entity(
    ...     "Steve Selvidge", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> reg.register_entity(ths, 'rhythm guitar, backing vocals', 'Steve', steve, auth)
    >>> pp.pprint(av.retrieve_entity(ths)['Properties'])
    [   ['lead vocals, guitar', 'Craig', '<2906857743|167772516|15626357>'],
        ['lead guitar, backing vocals', 'Tad', '<2906857743|167772516|15626358>'],
        ['bass', 'Galen', '<2906857743|167772516|15626359>'],
        ['drums, percussion', 'Bobby', '<2906857743|167772516|15626362>'],
        [   'rhythm guitar, backing vocals',
            'Steve',
            '<2906857743|167772516|15626364>']]
    
    Franz rejoins. There is much rejoicing.

    >>> reg.register_entity(ths, 'piano, keyboards, accordion, harmonica, backing vocals', 'Franz', franz, auth)
    >>> pp.pprint(av.retrieve_entity(ths)['Properties'])
    [   ['lead vocals, guitar', 'Craig', '<2906857743|167772516|15626357>'],
        ['lead guitar, backing vocals', 'Tad', '<2906857743|167772516|15626358>'],
        ['bass', 'Galen', '<2906857743|167772516|15626359>'],
        ['drums, percussion', 'Bobby', '<2906857743|167772516|15626362>'],
        [   'rhythm guitar, backing vocals',
            'Steve',
            '<2906857743|167772516|15626364>'],
        [   'piano, keyboards, accordion, harmonica, backing vocals',
            'Franz',
            '<2906857743|167772516|15626363>']]

    Delete everything and clean up.

    >>> reg.delete_registry(ths, auth)
    >>> av.finalize()
    """ 
    Verify.registry(registry)
    entity = av.property_value(
        registry, index=index, key=key, handle_exceptions=False)

    av.invoke(
        registry, av.Method.REMOVE, index=index, key=key, authorization=auth)
    if entity != atapi.NULL_ENTITY:
        av.dereference_entity(entity, auth, handle_exceptions=False)
        _release_entity(entity, auth)

@av.manage_exceptions('while saving registry {0}')
def save_registry(registry, auth):
    """
    save_registry(registry, auth)
    Persist any non-persisted changes in the registry.

    Persist any non-persisted changed. Has no effect if the registry is 
    autosaved.
    """ 
    Verify.registry(registry)
    av.save_entity(registry, auth, handle_exceptions=False)

@av.manage_exceptions('while sorting registry {0}')
def sort_registry(registry, auth):
    """
    sort_registry(registry, auth)
    Sort the properties in the registry by property name.""" 
    Verify.registry(registry)
    av.sort_property(registry, auth, name='string', handle_exceptions=False)

@av.manage_exceptions('while looking up key {1} in registry {0}')
def lookup_registry(registry, key):
    """
    lookup_registry(registry, key)
    Lookup a key in a registry, returning whether found and the entity.

    Lookup a key in a registry, and return two values. If an entity by that
    key is found in the registry, return True and the entity. If not found,
    return False and None.

    Parameters
    ----------
    registry : Entity
        the registry that might include ``key``

    key : str
        the key to lookup

    Returns
    -------
    key_found : bool
        whether an entity with key ``key`` was found

    entity : Entity 
        the entity found, or None if not found

    Raises
    ------
    RegistryError
        if ``registry`` is not an entity, or is an entity but connected to no
        adapter, or ``key`` is not a string, or
        the underlying implementation raises some other error.

    See also
    --------
    :func:`create_registry` : create a registry

    :func:`delete_registry` : delete a registry

    :func:`register_entity` : register an entity in a registry

    :func:`deregister_entity` : remove an entity from a registry 

    Examples
    --------
    >>> import avesterra.registry as reg
    >>> import avesterra.avial as av  
    >>> auth = av.initialize() 

    Create a few people entities, 

    >>> craig = av.create_entity(
    ...     "Craig Finn", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> tad = av.create_entity(
    ...     "Tad Kubler", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)
    >>> franz = av.create_entity(
    ...     "Franz Nicolay", av.Class.PERSON, av.Subclass.PERSON, auth, 
    ...     outlet=av.object_outlet(), autosave=True)

    Create a registry and put the people in the registry.

    >>> ths = reg.create_registry("The Hold Steady", True, auth)
    >>> reg.register_entity(ths, 'Craig Finn', 'Craig', craig, auth)
    >>> reg.register_entity(ths, 'Tad Kubler', 'Tad', tad, auth)
    >>> reg.register_entity(ths, 'Franz Nicolay', 'Franz', franz, auth)

    Look up 'Craig', finding the person entity.

    >>> reg.lookup_registry(ths, 'Craig')
    (True, Entity(2906857743, 167772516, 15626322))

    Look up 'Franz', finding the person entity.

    >>> reg.lookup_registry(ths, 'Franz')
    (True, Entity(2906857743, 167772516, 15626324))

    Attempt to look up 'Judd', finding no entity.

    >>> reg.lookup_registry(ths, 'Judd')
    (False, None)

    Delete everything and clean up.

    >>> reg.delete_registry(ths, auth)
    >>> av.delete_entity(craig, auth)
    >>> av.delete_entity(tad, auth)
    >>> av.delete_entity(franz, auth)
    >>> av.finalize()
    """ 
    Verify.registry(registry)
    with av.suppress_console_error_logging(
            'Server reported APPLICATION error: Key not found'):
        try:
            ent = av.invoke(
                registry, method=av.Method.LOOKUP, key=key, return_results=True)
            return True, ent
        except at.ApplicationError as err:
            msg = err.message
            if 'Server reported APPLICATION error: Key not found' in msg:
                return False, None
            else:
                raise 

@av.manage_exceptions('while finding name {1} in registry {0}')
def find_registry(registry, name, *, index=None):
    """
    find_registry(registry, name, *, index=None)
    Return the entity with a particular name.""" 
    Verify.registry(registry)
    return av.find_property(
        registry, name, index=index, handle_exceptions=False)

@av.manage_exceptions('while finding item in registry {0}')
def registry_item(registry, *, index=None):
    """
    registry_item(registry, *, index=None)
    Return the entity at a particular index position in the registry.""" 
    Verify.registry(registry)
    item = av.property_value(registry, index=index)
    Verify.entity(item)
    return item

@av.manage_exceptions('while counting entities in registry {0}')
def item_count(registry):
    """
    item_count(registry)
    Return count of entities in the registry.""" 
    Verify.registry(registry)
    return av.property_count(registry, handle_exceptions=False)

@av.manage_exceptions('while determining whether registry {0} contains key {1}')
def registry_member(registry, key):
    """
    registry_member(registry, key)
    Does registry contain an entity with this key?""" 
    (_ignore, found) = lookup_registry(registry, key, handle_exceptions=False)
    return found


################################################################################
#
# Error and error handling
#

class RegistryError(av.AvialError):
    """Some sort of error with registry functionality."""
    pass 