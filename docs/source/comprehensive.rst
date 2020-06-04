.. _comprehensive_format:

Comprehensive format and the Avial data model
=============================================

Comprehensive format is a text format for serializing an Avial entity. 
Comprehensive format relects the Avial data model, with attributes, properties,
labels, annotations, and other characteristics of a entity. Comprehensive 
format aims to be ... comprehensive: an entity can be serialized in
comprehensive format and then recreated from the serialization.
Comprehensive format is used in the functions 
:func:`~avesterra.avial.retrieve_entity`---for
serializing a particular entity---and :func:`~avesterra.avial.store_entity`---
for recreating an entity based on a serialization.

Comprehensive format is also used for serializing part of an Avial
entity. For example, :func:`~avesterra.avial.retrieve_attribute` provides
details of a particular attribute of an entity, in comprehensive format. Other
functions also serialize part of an entity: 
:func:`~avesterra.avial.retrieve_value` and 
:func:`~avesterra.avial.retrieve_property`.

Comprehensive format is `JSON <https://www.json.org/json-en.html>`_, and in fact
comprehensive format is defined technically in a
`JSON schema <https://json-schema.org/>`_. The comprehensive format schema is 
used in Avial to ensure that the serialization provided to 
:func:`~avesterra.avial.store_entity`
is valid, not just valid JSON but compliant with the schema. One way to
understand comprehensive format is to 
`read the schema <http://avesterra.georgetown.edu/tools/schemas/avesterra_store_format.json>`_.  
But the schema is written in JSON schema format, and is difficult to understand,
at least for people without experience in JSON schemas.

A better way to understand comprehensive format is through an example. We build
an example, starting very simple and incrementally adding features of the
Avial data model, resulting in a rather complex entity that exhibits all 
aspects of the comprehensive format.

A simple entity
---------------
Suppose we created an entity for the city of Los Angeles. After creating the
entity, and before adding any
attributes, values, or properties, we examine the entity in comprehensive
format, through a call to :func:`~avesterra.avial.retrieve_entity`: 

.. code-block:: json
    :linenos:
    :caption: Los Angeles, with no attributes or properties

    {
        "Label": "Los Angeles"
    }

Neither the class nor the subclass of the new entity is included in its
serialization. Only the label is included.

An even simpler serialization is possible. If we remove the label of this 
entity (i.e. with a call to :func:`~avesterra.avial.erase_label`), the **Los
Angeles** entity in comprehensive format does not have even a label: ::

    {}

Attributes
----------
An entity can have *attributes*, and a value for each attribute. Suppose our
**Los Angeles** entity has attributes for its latitude and longitude: 34° N and 
118° W. Retrieving the entity in comprehensive format results in the 
following: 

.. code-block:: json
    :linenos:
    :caption: Los Angeles, with an approximate latitude and longitude
    :name: approximate

    {
        "Attributes": {
            "LATITUDE_ATTRIBUTE": [
                {
                    "Values": [
                        {
                            "INTEGER": "34"
                        }
                    ]
                }
            ],
            "LONGITUDE_ATTRIBUTE": [
                {
                    "Values": [
                        {
                            "INTEGER": "-118"
                        }
                    ]
                }
            ]
        },
        "Label": "Los Angeles"
    }

Lines 2-21 detail all the attributes and their values, in this case all two of
them. Lines 3-11 detail the latitude attribute, and lines 12-20 the longitude
attribute.

``LATITUDE`` is one of 400+ attributes in the AvesTerra attribute taxonomy.
``LONGITUDE`` is another attribute in the taxonomy. Other attributes in the
taxonomy include
``LABEL``, ``LABOR``, ``LANGUAGE``, ``LAPTOP``, ``LAW``, ``LEADER``, ``LENGTH``,
``LINGUISTIC``, ``LINK``, ``LIST``, ``LOCATION``, and ``LOSS``, as well as many
others that do not begin with the letter L.

You may be wondering why there is so much complex structure to show the values
for latitude and longitude. Why is **Los Angeles** not serialized more simply?:

.. code-block:: json
    :linenos:
    :caption: Los Angeles, expressed in invalid comprehensive format

    {
        "Attributes": {
            "LATITUDE_ATTRIBUTE": 34,
            "LONGITUDE_ATTRIBUTE": -118
        },
        "Label": "Los Angeles"
    }

This simpler (invalid) format does not support several aspects of the Avial
data model: data types for the value of an attribute, multiple values for
an attribute, multiple attribute instances, and properties of an attribute 
instance. All these aspects are described in detail below.

Data types
----------
The location at 34° north and 118° west is well within the Los
Angeles metro area, but it is actually a few miles ESE of the city of 
Los Angeles, in the bedroom community of Hacienda Heights.
A more accurate location
for the city of Los Angeles is 34.054° N, 118.242° W, the location of the
art deco Los Angeles City Hall building, featured in many movies and television
shows. 

.. figure:: Los_Angeles_City_Hall_2013.jpg
    :alt: Los Angeles City Hall

    Los Angeles City Hall, `By Michael J Fromholtz - Own work, CC BY-SA 3.0 <https://commons.wikimedia.org/w/index.php?curid=32276975>`_

With the more accurate location, the **Los Angeles** entity in
comprehensive format is:

.. code-block:: json
    :linenos:
    :caption: Los Angeles, with an exact latitude and longitude

    {
        "Attributes": {
            "LATITUDE_ATTRIBUTE": [
                {
                    "Values": [
                        {
                            "FLOAT": "34.054"
                        }
                    ]
                }
            ],
            "LONGITUDE_ATTRIBUTE": [
                {
                    "Values": [
                        {
                            "FLOAT": "-118.242"
                        }
                    ]
                }
            ]
        },
        "Label": "Los Angeles"
    }

The accurate value for latitude---34.054---is serialized in comprehensive format
as :code:`{"FLOAT": "34.054"}` in lines 6-8. The slightly inaccurate 
latitude---34---was serialized as :code:`{"INTEGER": "34"}` in lines 6-8 in 
:ref:`the earlier code block <approximate>`.

FLOAT is the data type tag of the latitude here, and INTEGER is the data type 
tag of the
latitude earlier. Instead of a numeric value, the value of latitude could have
been the string "34.054 degrees north". In that case it would have been 
serialized as :code:`{"ASCII": "34.054 degrees north"}`. Or the value of 
latitude could have been a string that used the degree symbol: "34.054° N".
Since the degree symbol is not a valid ASCII character, a latitude value of 
"34.054° N" is serialized rather differently: 
:code:`{"UTF-8": "34.054\xc2\xb0 N"}`. In the UTF-8 encoding of unicode,
the degree symbol is serialized as two bytes: C2 followed by B0.

INTEGER, FLOAT, ASCII, and UTF-8 are four data types tags used for serializing
values in Avial. There are several other data types tags as well, as shown in 
the following table:

============== =========== =========================================================
Data type      Tag         Example value in comprehensive format 
============== =========== =========================================================
boolean        BOOLEAN     :code:`{"BOOLEAN": "TRUE"}`
integer        INTEGER     :code:`{"INTEGER": "34"}`
float          FLOAT       :code:`{"FLOAT": "34.054"}`
ASCII string   ASCII       :code:`{"ASCII": "34.054 degrees north"}`
unicode string UTF-8       :code:`{"UTF-8": "34.054\xc2\xb0 N"}`
character      CHARACTER   :code:`{"CHARACTER": "X"}`
entity         ENTITY      :code:`{"ENTITY": "<2906857743|167772516|143400>"}`
date or time   EPOCH       :code:`{"EPOCH": "1588104972"}`
JSON           JSON        :code:`{"JSON": "[1, 2, 3, {\"four\": 4}]"}`
binary data    DATA        :code:`{"DATA": "%PDF-1.3 %\304\345\362"}`
URL or URI     URI         :code:`{"URI": "https://avesterra.georgetown.edu"}`
============== =========== =========================================================

The value of an attribute can be an entity. For example, the city of Los Angeles
is located in the US state of California. The entity **Los Angeles** has a 
STATE attribute whose value is the entity *California*, serialized as a UUID
with tag ENTITY. If *California* has
the UUID :code:`<2906857743|167772516|147522>`, the state is shown below, in
lines 21-29:

.. code-block:: json
    :linenos:
    :caption: Los Angeles, with its state

    {
        "Attributes": {
            "LATITUDE_ATTRIBUTE": [
                {
                    "Values": [
                        {
                            "FLOAT": "34.054"
                        }
                    ]
                }
            ],
            "LONGITUDE_ATTRIBUTE": [
                {
                    "Values": [
                        {
                            "FLOAT": "-118.242"
                        }
                    ]
                }
            ],
            "STATE_ATTRIBUTE": [
                {
                    "Values": [
                        {
                            "ENTITY": "<2906857743|167772516|147522>"  
                        }
                    ]
                }
            ]
        },
        "Label": "Los Angeles"
    }

The value of an attribute can be a time. For example, the city of Los Angeles
was founded on September 4, 1781, when California was part of the Spanish 
viceroyalty of New Spain. A time value is serialized with a tag of EPOCH
and a value that is an 
`epoch integer <https://en.wikipedia.org/wiki/Unix_time>`_.

The value of an attribute can be a URL, or more generally, a 
`Uniform Resource Identifier <https://en.wikipedia.org/wiki/Uniform_Resource_Identifier>`_. A URL (or URI) is serialized with the tag
URI and a value that is a legal URL (or URI). 

Although not relevant for our Los Angeles example, an entity can have an 
attribute whose value is JSON or an attribute whose value is a stream of binary
(e.g. a file). The former is serialized with the
JSON tag and the latter is serialized with the DATA tag.

It is possible (albeit uncommon) for the value of an attribute to have an 
unknown data type. An unknown data type is serialized without a tag at all,
just as a string representation of some value. For example if the value
of **Los Angeles**'s latitude were "34.054" but of an unknown data type, it
would be serialized as :code:`"34.054"` rather than :code:`{"FLOAT": "34.054"}`.

Multiple values
---------------
An attribute of an Avial entity can have more than one value. For example,
the city of Los Angeles has several name and nicknames, including 
"City of Los Angeles", "Los Ángeles", "L.A", "The Big Orange", "City of Angels", 
"La-la-land", and "Shakeytown". These names are all values of the NAME
attribute for **Los Angeles**:

.. code-block:: json
    :linenos:
    :caption: Los Angeles, with names and nicknames

    {
        "Attributes": {
            "LATITUDE_ATTRIBUTE": [
                {
                    "Values": [
                        {
                            "FLOAT": "34.054"
                        }
                    ]
                }
            ],
            "LONGITUDE_ATTRIBUTE": [
                {
                    "Values": [
                        {
                            "FLOAT": "-181.242"
                        }
                    ]
                }
            ],
            "NAME_ATTRIBUTE": [
                {
                    "Values": [
                        {
                            "ASCII": "City of Los Angeles"
                        },
                        {
                            "UTF-8": "Los \u00c1ngeles"
                        },
                        {
                            "ASCII": "L.A."
                        },
                        {
                            "ASCII": "The Big Orange"
                        },
                        {
                            "ASCII": "City of Angels"
                        },
                        {
                            "ASCII": "La-la-land"
                        },
                        {
                            "ASCII": "Shakeytown"
                        }
                    ]
                }
            ],
            "STATE_ATTRIBUTE": [
                {
                    "Values": [
                        {
                            "ENTITY": "<2906857743|167772516|147522>"
                        }
                    ]
                }
            ]
        },
        "Label": "Los Angeles"
    }

Lines 21-47 show the serialization of seven names for Los Angeles, seven
values of the NAME attribute. Note that two data types are employed. Most
of the names are ASCII, but the original (Spanish) name for the city is 
"Los Ángeles", with a non-ASCII fourth character. It is serialized as a unicode
string, using UTF-8.

Properties
----------
As of May 2020, there are 403 attributes in the Avial taxonomy. We expect 
that count to increase over time, but there will always be concepts that
cannot be expressed in Avial attributes. For example, Los Angeles has many
tourist attractions, including the Hollywood sign, the Getty Center, Griffith
Observatory, and the La Brea Tar Pits. But there is no Avial attribute for 
tourist attraction, and it is unlikely there ever will be one.

Instead of using attributes, *properties* can be used to capture the tourist
attractions of Los Angeles. Each property of an entity has three fields: a name,
a key, and a value. A property's name is some (string) label describing the 
property. Property names need not be unique; several properties can have the 
same name.

A property's key is a unique string by which the property can be looked up.
A property key can be an empty string, a string of length zero. 
No two properties can have the same non-empty key, but multiple properties
can all have keys that are empty strings.

A property's value is some typed value, much like an attribute value, as 
described above. :code:`{"INTEGER": "23"}`,
:code:`{"ASCII": "La Brea Tar Pits"}`, and 
:code:`{"ENTITY": "<2906857743|167772516|147522>"}` are all valid property
values.

Adding tourist attractions to the **Los Angeles** entity results in the follow
serialization, in comprehensive format:

.. code-block:: json
    :linenos:
    :caption: Los Angeles, with four attractions

    {
        "Attributes": {
            "LATITUDE_ATTRIBUTE": [
                {
                    "Values": [
                        {
                            "FLOAT": "34.054"
                        }
                    ]
                }
            ],
            "LONGITUDE_ATTRIBUTE": [
                {
                    "Values": [
                        {
                            "FLOAT": "-181.242"
                        }
                    ]
                }
            ],
            "NAME_ATTRIBUTE": [
                {
                    "Values": [
                        {
                            "ASCII": "City of Los Angeles"
                        },
                        {
                            "UTF-8": "Los \u00c1ngeles"
                        },
                        {
                            "ASCII": "L.A."
                        },
                        {
                            "ASCII": "The Big Orange"
                        },
                        {
                            "ASCII": "City of Angels"
                        },
                        {
                            "ASCII": "La-la-land"
                        },
                        {
                            "ASCII": "Shakeytown"
                        }
                    ]
                }
            ],
            "STATE_ATTRIBUTE": [
                {
                    "Values": [
                        {
                            "ENTITY": "<2906857743|167772516|147522>"
                        }
                    ]
                }
            ]
        },
        "Label": "Los Angeles",
        "Properties": [
            [
                "attraction",
                "",
                {
                    "ASCII": "Hollywood sign"
                }
            ],
            [
                "attraction",
                "",
                {
                    "ASCII": "The Getty Center"
                }
            ],
            [
                "attraction",
                "",
                {
                    "ASCII": "Griffith Observatory"
                }
            ],
            [
                "attraction",
                "",
                {
                    "ASCII": "La Brea Tar Pits"
                }
            ]
        ]
    }

There are four properties of **Los Angeles**, detailed in lines 59-88. Each
property has the same name: "attraction". Each has an empty key. Each has an
ASCII string as its value, the name of the attraction.

Instead of ASCII strings, the values could have been entities themselves,
one entity for the Hollywood sign, one for the Getty Center, one for the
Griffith Observatory, and one for the La Brea tar pits. In fact both the
name and the entity could have been captured, with the name of the attraction
as the key of the property, and the entity of the attraction as the value of
the property, as below. (Attributes and label are omitted, for brevity).

.. code-block:: json
    :linenos:
    :caption: Four attractions of Los Angeles

    {
        "Properties": [
            [
                "attraction",
                "Hollywood sign",
                {
                    "ENTITY": "<2906857743|167772516|147550>"
                }
            ],
            [
                "attraction",
                "The Getty Center",
                {
                    "ENTITY": "<2906857743|167772516|147551>"
                }
            ],
            [
                "attraction",
                "Griffith Observatory",
                {
                    "ENTITY": "<2906857743|167772516|147552>"
                }
            ],
            [
                "attraction",
                "La Brea Tar Pits",
                {
                    "ENTITY": "<2906857743|167772516|147553>"
                }
            ]
        ]
    }
 


Attribute properties
--------------------
An entity can have properties, like the attraction properties of 
**Los Angeles**, described above. An attribute of an entity can also have 
properties, separate from the entity properties. For example, we have expressed
the latitude and longitude of Los Angeles in decimal degrees, e.g. 34.054. 
In older maps,
latitude and longitude is often expressed in sexagesimal degrees---degrees,
minutes, and seconds---e.g. 34° 3' 14''. We can add that alternative 
expression as a property to the existing latitude and longitude attributes.
(The properties, values, and many attributes are omitted, for brevity.)

.. code-block:: json
    :linenos:
    :caption: Latitude and longitude, in both decimal degrees and sexagesimal

    {
        "Attributes": {
            "LATITUDE_ATTRIBUTE": [
                {
                    "Properties": [
                        [
                            "alternative format",
                            "sexagesimal",
                            {
                                "UTF-8": "34\u00b0 3' 14\" N"
                            }
                        ]
                    ],
                    "Values": [
                        {
                            "FLOAT": "34.054"
                        }
                    ]
                }
            ],
            "LONGITUDE_ATTRIBUTE": [
                {
                    "Properties": [
                        [
                            "alternative format",
                            "sexagesimal",
                            {
                                "UTF-8": "118\u00b0 14' 31\" W"
                            }
                        ]
                    ],
                    "Values": [
                        {
                            "FLOAT": "-181.242"
                        }
                    ]
                }
            ]
    }

Lines 3-20 detail the latitude attribute, with the value in lines 14-18 and
the new property in lines 5-13. The property value is difficult to read in
comprehensive format, but when we query the entity with 
:func:`~avesterra.avial.get_property`, the property value becomes easy to read.

.. code-block:: python
    :caption: Showing the sexagesimal property of latitude

    >>> print(av.get_property(los_angeles, attribute=av.Attribute.LATITUDE, key='sexagesimal'))
    34° 3' 14" N


In comprehensive format, attribute properties are formatted with the same
rules as entity properties. The name of a property is a (possibly empty) string.
In this example, the name of the sole property on the latitude attribute
is ``"alternative format"``. 

The key of a property is a (possible empty) string as well. No two properties
of a single attribute can have the same non-empty key, but multiple properties
can all have keys that are empty strings. In this example, the key of the
property on the latitude attribute is ``"sexagesimal"``. Note that the longitude
property has the same key; it is OK for different attributes to have properties
with matching keys. In this case it is not just OK but also convenient,
as we can both query latitude for its sexagesimal property, and query longitude
for its sexagesimal property.

The value of a property is some
typed value, using the same format as the typed values of an attribute. In this
case the value of the property is a UTF-8 string: 
:code:`{"UTF-8": "34\u00b0 3' 14\" N"}`.

.. _attribute_instances:

Attribute instances
-------------------
As we have seen, an attribute can have multiple values. There can also be 
multiple *attribute instances*, multiple instances of the same attribute on an
entity. 

Suppose we want to record the population of Los Angeles on the **Los Angeles**
entity.
The population of the city of Los Angeles is 3,792,621 people, according to
the 2010 US census. But when we talk about the population of Los
Angeles, are we talking about only those who live within city limits? What about
people who live in Beverly Hills or West Hollywood, both small cities
almost entirely surrounded by Los Angeles?

The US census defines the Los Angeles urban area, including Beverly Hills, West
Hollywood, and also Long Beach, Anaheim, and many other cities. When people
talk about living in Los Angeles, they often mean anyone who lives in the 
urban area, all 12,150,996 people (2010 US census).
There are two US census aggregations that are even more inclusive: the Los 
Angeles metropolitan area (13,131,431 people), and the Los Angeles combined 
statistical area (18,679,763 people).

Suppose we wanted our *Los Angeles* entity to include all four of these 
populations. We could represent the population of Los Angeles using multiple 
values, like this:

.. code-block:: json
    :linenos:
    :caption: The population of Los Angeles, as multiple values of one instance

    {
        "Attributes": {
            "POPULATION_ATTRIBUTE": [
                {
                    "Values": [
                        {
                            "INTEGER": "3792621"
                        },
                        {
                            "INTEGER": "12159995"
                        },
                        {
                            "INTEGER": "13131431"
                        },
                        {
                            "INTEGER": "18679763"
                        }
                    ]
                }
            ] 
        }
    }

While this representation includes all four population values, the meaning
of each is not clear. Is 13,131,431 the value for urban or metro or CSA? 
A better representation is to use four instances of the population attribute,
like this:

.. code-block:: json
    :linenos:
    :caption: The population of Los Angeles, as multiple attribute instances

    {
        "Attributes": { 
            "POPULATION_ATTRIBUTE": [
                {
                    "Label": "city",
                    "Values": [
                        {
                            "INTEGER": "3792621"
                        }
                    ]
                },
                {
                    "Label": "urban area",
                    "Values": [
                        {
                            "INTEGER": "12159995"
                        }
                    ]
                },
                {
                    "Label": "metro area",
                    "Values": [
                        {
                            "INTEGER": "13131431"
                        }
                    ]
                },
                {
                    "Label": "combined statistical area",
                    "Values": [
                        {
                            "INTEGER": "18679763"
                        }
                    ]
                }
            ] 
        } 
    }

The four attribute instances of population are in lines 4-35. Lines 4-11 is the 
first instance, with both a value---3,792,621---and a label---"city". The
other three instances are labeled as well. 

Labels for attribute instances need not be unique. But if the labels are unique,
the value of an instance can be found via its label, like this:

.. code-block:: python
    :caption: Finding the population of the Los Angeles urban area

    >>> inst = av.find_label(los_angeles, av.Attribute.POPULATION, "urban area")
    >>> av.get_value(los_angeles, attribute=av.Attribute.POPULATION, instance=inst)
    12159995

Each attribute instance has its own (optional) list of properties. For example,
we can augment the Los Angeles populations with some information about some of
the geographies included for each quantity.

.. code-block:: json
    :linenos:
    :caption: The population of Los Angeles, with included localities

    {
        "Attributes": {  
            "POPULATION_ATTRIBUTE": [
                {
                    "Label": "city",
                    "Values": [
                        {
                            "INTEGER": "3792621"
                        }
                    ]
                },
                {
                    "Label": "urban area",
                    "Properties": [
                        [
                            "includes",
                            "Beverly Hills",
                            {
                                "ENTITY": "<2906857743|167772516|145528>"
                            }
                        ],
                        [
                            "includes",
                            "West Hollywood",
                            {
                                "ENTITY": "<2906857743|167772516|145528>"
                            }
                        ],
                        [
                            "includes",
                            "Long Beach",
                            {
                                "ENTITY": "<2906857743|167772516|145528>"
                            }
                        ],
                        [
                            "includes",
                            "Anaheim",
                            {
                                "ENTITY": "<2906857743|167772516|145542>"
                            }
                        ],
                        [
                            "includes",
                            "Santa Ana",
                            {
                                "ENTITY": "<2906857743|167772516|145543>"
                            }
                        ]
                    ],
                    "Values": [
                        {
                            "INTEGER": "12159995"
                        }
                    ]
                },
                {
                    "Label": "metro area",
                    "Properties": [
                        [
                            "includes",
                            "Los Angeles County",
                            {
                                "ENTITY": "<2906857743|167772516|145902>"
                            }
                        ],
                        [
                            "includes",
                            "Orange County",
                            {
                                "ENTITY": "<2906857743|167772516|145994>"
                            }
                        ]
                    ],
                    "Values": [
                        {
                            "INTEGER": "13131431"
                        }
                    ]
                },
                {
                    "Label": "combined statistical area",
                    "Properties": [
                        [
                            "includes",
                            "Los Angeles County",
                            {
                                "ENTITY": "<2906857743|167772516|145902>"
                            }
                        ],
                        [
                            "includes",
                            "Orange County",
                            {
                                "ENTITY": "<2906857743|167772516|145994>"
                            }
                        ],
                        [
                            "includes",
                            "Ventura County",
                            {
                                "ENTITY": "<2906857743|167772516|146001>"
                            }
                        ],
                        [
                            "includes",
                            "Riverside County",
                            {
                                "ENTITY": "<2906857743|167772516|146025>"
                            }
                        ],
                        [
                            "includes",
                            "San Bernardino County",
                            {
                                "ENTITY": "<2906857743|167772516|146216>"
                            }
                        ]
                    ],
                    "Values": [
                        {
                            "INTEGER": "18679763"
                        }
                    ]
                }
            ] 
        } 
    }

The Los Angeles urban area is the second instance, serialized in lines 12-56. 
It has five properties, shown in lines 14-50, five cities in addition to 
Los Angeles that are included in the urban area. Of course many other cities 
are not listed, but are part of the urban area, including
Compton, El Segundo, Hacienda Heights, Hermosa Beach, Huntington Beach, Malibu, 
and Pasadena.

Note that Orange County is included in the properties of both the third
attribute instance (metro area)---lines 67-73---and the fourth attribute 
instance (combined statistical area)---lines 91-97. The same key is used 
for both properties: "Orange County". Keys must be unique for the properties
of a single instance, but need not be unique across multiple
instances.

The first attribute instance above (lines 4-11) has no properties, only a label
and a list of values, while the second, third and fourth instances each
have a label, properties, and values. An attribute instance can have any
combination of the three elements. For example, it can have just a label, just
values, just properties, a label and values, a label and properties, values
and properties, or all three: label, values, and properties.

Property annotations
--------------------
As described above, an entity property consists of a name, a key, and a value,
attached to an entity. An entity property can also have annotations
optionally. Annotations are attribute values, for the property itself.

For example, we have four attraction properties on the **Los Angeles** entity,
listing four tourist attractions in Los Angeles: the Hollywood sign, the
Getty Center, Griffith Observatory, and the La Brea tar pits.
It would be convenient to have a latitude and a longitude for each, like this:

.. code-block:: json
    :linenos:
    :caption: Attractions of Los Angeles, with location of each

    {
        "Properties": [
                [
                    "attraction",
                    "Hollywood sign",
                    {
                        "ENTITY": "<2906857743|167772516|147550>"
                    },
                    {
                        "LATITUDE_ATTRIBUTE": {
                            "FLOAT": "34.134"
                        },
                        "LONGITUDE_ATTRIBUTE": {
                            "FLOAT": "-118.322"
                        }
                    }
                ],
                [
                    "attraction",
                    "The Getty Center",
                    {
                        "ENTITY": "<2906857743|167772516|147551>"
                    },
                    {
                        "LATITUDE_ATTRIBUTE": {
                            "FLOAT": "34.078"
                        },
                        "LONGITUDE_ATTRIBUTE": {
                            "FLOAT": "-118.475"
                        }
                    }
                ],
                [
                    "attraction",
                    "Griffith Observatory",
                    {
                        "ENTITY": "<2906857743|167772516|147552>"
                    },
                    {
                        "LATITUDE_ATTRIBUTE": {
                            "FLOAT": "34.119"
                        },
                        "LONGITUDE_ATTRIBUTE": {
                            "FLOAT": "-118.3"
                        }
                    }
                ],
                [
                    "attraction",
                    "La Brea Tar Pits",
                    {
                        "ENTITY": "<2906857743|167772516|147553>"
                    },
                    {
                        "LATITUDE_ATTRIBUTE": {
                            "FLOAT": "34.063"
                        },
                        "LONGITUDE_ATTRIBUTE": {
                            "FLOAT": "-118.356"
                        }
                    }
                ]
            ]
    }

Lines 48-62 is the serialization for the La Brea tar pits. The attributes of
that attraction property are serialized in lines 54-61. 

Annotations of an entity property look like attributes, but they are not as 
flexible as attributes. Avial does not support multiple values for an
annotation; there is only a single value for latitude of the Hollywood sign.
An annotation cannot involve multiple instances. And an annotation cannot
have properties itself.

.. _entity_values:

Entity values
-------------
An attribute instance can have values, and a property can have a value, either 
an entity property or an attribute property. An entity can also have
values directly, aside from any values on its attributes or its properties.

Suppose our **Los Angeles** entity has two values, the string 
"Entertainment capital of the world" and the integer 2. The serialization
of the whole entity, with its values, label, attributes, and properties is
as follows:

.. code-block:: json
    :linenos:
    :caption: Los Angeles, in its entirety

    {
        "Attributes": {
            "LATITUDE_ATTRIBUTE": [
                {
                    "Properties": [
                        [
                            "alternative format",
                            "sexagesimal",
                            {
                                "UTF-8": "34\u00b0 3' 14\" N"
                            }
                        ]
                    ],
                    "Values": [
                        {
                            "FLOAT": "34.054"
                        }
                    ]
                }
            ],
            "LONGITUDE_ATTRIBUTE": [
                {
                    "Properties": [
                        [
                            "alternative format",
                            "sexagesimal",
                            {
                                "UTF-8": "118\u00b0 14' 31\" W"
                            }
                        ]
                    ],
                    "Values": [
                        {
                            "FLOAT": "-118.242"
                        }
                    ]
                }
            ],
            "NAME_ATTRIBUTE": [
                {
                    "Values": [
                        {
                            "ASCII": "City of Los Angeles"
                        },
                        {
                            "UTF-8": "Los \u00c1ngeles"
                        },
                        {
                            "ASCII": "L.A."
                        },
                        {
                            "ASCII": "The Big Orange"
                        },
                        {
                            "ASCII": "City of Angels"
                        },
                        {
                            "ASCII": "La-la-land"
                        },
                        {
                            "ASCII": "Shakeytown"
                        }
                    ]
                }
            ],
            "POPULATION_ATTRIBUTE": [
                {
                    "Label": "city",
                    "Values": [
                        {
                            "INTEGER": "3792621"
                        }
                    ]
                },
                {
                    "Label": "urban area",
                    "Properties": [
                        [
                            "includes",
                            "Beverly Hills",
                            {
                                "ENTITY": "<2906857743|167772516|145528>"
                            }
                        ],
                        [
                            "includes",
                            "West Hollywood",
                            {
                                "ENTITY": "<2906857743|167772516|145528>"
                            }
                        ],
                        [
                            "includes",
                            "Long Beach",
                            {
                                "ENTITY": "<2906857743|167772516|145528>"
                            }
                        ],
                        [
                            "includes",
                            "Anaheim",
                            {
                                "ENTITY": "<2906857743|167772516|145542>"
                            }
                        ],
                        [
                            "includes",
                            "Santa Ana",
                            {
                                "ENTITY": "<2906857743|167772516|145543>"
                            }
                        ]
                    ],
                    "Values": [
                        {
                            "INTEGER": "12159995"
                        }
                    ]
                },
                {
                    "Label": "metro area",
                    "Properties": [
                        [
                            "includes",
                            "Los Angeles County",
                            {
                                "ENTITY": "<2906857743|167772516|145902>"
                            }
                        ],
                        [
                            "includes",
                            "Orange County",
                            {
                                "ENTITY": "<2906857743|167772516|145994>"
                            }
                        ]
                    ],
                    "Values": [
                        {
                            "INTEGER": "13131431"
                        }
                    ]
                },
                {
                    "Label": "combined statistical area",
                    "Properties": [
                        [
                            "includes",
                            "Los Angeles County",
                            {
                                "ENTITY": "<2906857743|167772516|145902>"
                            }
                        ],
                        [
                            "includes",
                            "Orange County",
                            {
                                "ENTITY": "<2906857743|167772516|145994>"
                            }
                        ],
                        [
                            "includes",
                            "Ventura County",
                            {
                                "ENTITY": "<2906857743|167772516|146001>"
                            }
                        ],
                        [
                            "includes",
                            "Riverside County",
                            {
                                "ENTITY": "<2906857743|167772516|146025>"
                            }
                        ],
                        [
                            "includes",
                            "San Bernardino County",
                            {
                                "ENTITY": "<2906857743|167772516|146216>"
                            }
                        ]
                    ],
                    "Values": [
                        {
                            "INTEGER": "18679763"
                        }
                    ]
                }
            ],
            "STATE_ATTRIBUTE": [
                {
                    "Values": [
                        {
                            "ENTITY": "<2906857743|167772516|147522>"
                        }
                    ]
                }
            ]
        },
        "Label": "Los Angeles",
        "Properties": [
            [
                "attraction",
                "Hollywood sign",
                {
                    "ENTITY": "<2906857743|167772516|147550>"
                },
                {
                    "LATITUDE_ATTRIBUTE": {
                        "FLOAT": "34.134"
                    },
                    "LONGITUDE_ATTRIBUTE": {
                        "FLOAT": "-118.322"
                    }
                }
            ],
            [
                "attraction",
                "The Getty Center",
                {
                    "ENTITY": "<2906857743|167772516|147551>"
                },
                {
                    "LATITUDE_ATTRIBUTE": {
                        "FLOAT": "34.078"
                    },
                    "LONGITUDE_ATTRIBUTE": {
                        "FLOAT": "-118.475"
                    }
                }
            ],
            [
                "attraction",
                "Griffith Observatory",
                {
                    "ENTITY": "<2906857743|167772516|147552>"
                },
                {
                    "LATITUDE_ATTRIBUTE": {
                        "FLOAT": "34.11"
                    },
                    "LONGITUDE_ATTRIBUTE": {
                        "FLOAT": "-118.3"
                    }
                }
            ],
            [
                "attraction",
                "La Brea Tar Pits",
                {
                    "ENTITY": "<2906857743|167772516|147553>"
                },
                {
                    "LATITUDE_ATTRIBUTE": {
                        "FLOAT": "34.06"
                    },
                    "LONGITUDE_ATTRIBUTE": {
                        "FLOAT": "-118.356"
                    }
                }
            ]
        ],
        "Values": [
            {
                "ASCII": "Entertainment capital of the world"
            },
            {
                "INTEGER": "2"
            }
        ]
    }

The values of **Los Angeles** are serialized in lines 263-270.


