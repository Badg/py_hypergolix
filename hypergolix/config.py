'''
LICENSING
-------------------------------------------------

hypergolix: A python Golix client.
    Copyright (C) 2016 Muterra, Inc.
    
    Contributors
    ------------
    Nick Badger
        badg@muterra.io | badg@nickbadger.com | nickbadger.com

    This library is free software; you can redistribute it and/or
    modify it under the terms of the GNU Lesser General Public
    License as published by the Free Software Foundation; either
    version 2.1 of the License, or (at your option) any later version.

    This library is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
    Lesser General Public License for more details.

    You should have received a copy of the GNU Lesser General Public
    License along with this library; if not, write to the
    Free Software Foundation, Inc.,
    51 Franklin Street,
    Fifth Floor,
    Boston, MA  02110-1301 USA

------------------------------------------------------
'''

# Global dependencies
import argparse
import pathlib
import json
import collections
import copy
import webbrowser
import yaml
import inspect
import os

from golix import Ghid
from golix import Secret

# Intra-package dependencies
from .utils import _BijectDict
from .exceptions import ConfigError
from .exceptions import ConfigIncomplete
from .exceptions import ConfigMissing


# ###############################################
# Boilerplate
# ###############################################


import logging
logger = logging.getLogger(__name__)

# Control * imports.
__all__ = [
    # 'Inquisitor',
]


# ###############################################
# Helper classes and encoder/decoder
# ###############################################
        
        
class _NamedListMeta(type):
    ''' Metaclass for named lists.
    '''
    
    def __new__(metacls, name, bases, clsdict, **kwargs):
        ''' Automatically add any slots declarations (except _fields_ to
        _fields, in order.
        '''
        # Enforce usage of __slots__
        if '__slots__' not in clsdict:
            raise TypeError('_NamedLists must use slots.')
            
        # Enforce non-usage of '_fields' attr. Note that this will only apply
        # to this particular subclass, but it won't matter because all of them
        # use us as a metaclass.
        elif '_fields' in clsdict['__slots__']:
            raise TypeError(
                '_NamedLists cannot define a "_fields" attribute.'
            )
            
        # Enforce not defining fields in the class definition as well
        elif '_fields' in clsdict:
            raise TypeError(
                '_NamedLists cannot define a _fields class attribute.'
            )
            
        # Now add '_fields' to the class dict separately and create the class
        clsdict['_fields'] = []
        cls = super().__new__(metacls, name, bases, clsdict, **kwargs)
        
        # Now modify cls._fields according to the MRO, adding all applicable
        # slots.
        
        # Now we need to rewrite slots, collating everything into fields.
        # Prepend '_fields' to __slots__ and convert it to a tuple
        clsdict['__slots__'] = ('_fields', *clsdict['__slots__'])
        
        # And now add all of the __slots__ to _fields, in order of their MRO
        fields = []
        # Create a version of the MRO that ignores object, which doesn't define
        # __slots__
        stub_mro = cls.__mro__[:len(cls.__mro__) - 1]
        for c in stub_mro:
            # Add any fields that are not already defined there
            fields.extend([slot for slot in c.__slots__ if slot not in fields])
        # And assign that to cls._fields
        cls._fields = tuple(fields)
        
        # Don't forget to return the finalized class!
        return cls
            
    def __len__(cls):
        ''' Use the number of _fields for the class length.
        '''
        return len(cls._fields)


# Okay, normally I'd do these as collections.namedtuples, but those are being
# interpreted by json as tuples, so no dice.
class _NamedList(metaclass=_NamedListMeta):
    ''' Some magic to simulate a named tuple in a way that doesn't
    subclass tuple, and is therefore correctly interpreted by json. As
    an implementation side effect, this is also mutable, hence being a
    _NamedList and not _NamedTuple2.
    
    This is always a fixed-length entity. Additionally, though they may
    be modified, attributes may not be added, nor deleted.
    '''
    __slots__ = []
    __hash__ = None
    
    def __init__(self, *args, **kwargs):
        ''' Pass all *args or **kwargs to _fields.
        '''
        for ii, arg in enumerate(args):
            self[ii] = arg
            
        for key, value in kwargs.items():
            # Check to see if the attr was defined by args
            if hasattr(self, key):
                raise TypeError(
                    'Got multiple values for keyword "' + key + '"'
                )
                
            else:
                setattr(self, key, value)
                
        for field in self._fields:
            if not hasattr(self, field):
                raise TypeError('Must define all attributes to a _NamedList.')
                
    def __setitem__(self, index, value):
        ''' Convert key-based (index) access to attr access.
        '''
        attrname = self._fields[index]
        setattr(self, attrname, value)
        
    def __getitem__(self, index):
        ''' Convert key-based (index) access to attr access.
        '''
        attrname = self._fields[index]
        return getattr(self, attrname)
        
    def __repr__(self):
        ''' Also add a nice repr for all of the fields.
        '''
        clsname = type(self).__name__
        
        fieldstrs = []
        for field in self._fields:
            fieldstrs.append(field)
            fieldstrs.append('=')
            fieldstrs.append(repr(getattr(self, field)))
            fieldstrs.append(', ')
        # Strip the final ', '
        fieldstrs = fieldstrs[:len(fieldstrs) - 1]
            
        return ''.join((clsname, '(', *fieldstrs, ')'))
        
    def __iter__(self):
        ''' Needed to, yknow, iterate and stuff.
        
        Note that iterating will only work if all attrs are defined.
        '''
        for field in self._fields:
            yield getattr(self, field)
            
    def __reversed__(self):
        ''' Performs the same checks as __iter__.
        '''
        for field in reversed(self._fields):
            yield getattr(self, field)
        
    def __contains__(self, value):
        # Iterate over all possible fields.
        for field in self._fields:
            # If the field is defined, and the values match, it's here.
            if value == field:
                return True
        # Gone through everything without returning? Not contained.
        else:
            return False
            
    def __len__(self):
        ''' Statically defined as the length of the _fields classattr.
        '''
        return len(self._fields)
        
    def __eq__(self, other):
        ''' The usual equality test.
        '''
        # Ensure same lengths
        if len(other) != len(self):
            return False
            
        # Compare every value and short-circuit on failure
        for mine, theirs in zip(self, other):
            if mine != theirs:
                return False
        
        # Nothing mismatched, both are same length, must be equal
        else:
            return True


class _RemoteDef(_NamedList):
    __slots__ = [
        'host',
        'port',
        'tls'
    ]


class _UserDef(_NamedList):
    __slots__ = [
        'fingerprint',
        'user_id',
        'root_secret'
    ]


class _InstrumentationDef(_NamedList):
    __slots__ = [
        'verbosity',
        'debug',
        'traceur'
    ]


class _ProcessDef(_NamedList):
    __slots__ = [
        'ipc_port'
    ]


# Using a bijective mapping allows us to do bidirectional lookup
# This might be overkill, but if you already have one in your .utils module...
_TYPEHINTS = _BijectDict({
    '__RemoteDef__': _RemoteDef,
    '__UserDef__': _UserDef,
    '__InstrumentationDef__': _InstrumentationDef,
    '__ProcessDef__': _ProcessDef
})


class _CfgDecoder(json.JSONDecoder):
    ''' Extends the default json decoder to create the relevant objects
    from the cfg file.
    '''
    
    def __init__(self):
        ''' Hard-code the super() invocation.
        '''
        super().__init__(object_hook=self._ohook)
        
    def _ohook(self, odict):
        ''' Called for every dict (json object) encountered.
        '''
        for key in odict:
            if key in _TYPEHINTS:
                # Get the class to use
                cls = _TYPEHINTS[key]
                # Pop out the key
                odict.pop(key)
                # Create an instance of the class, expanding the rest of the
                # dict to be kwargs
                return cls(**odict)
                
        else:
            return odict
    
    
class _CfgEncoder(json.JSONEncoder):
    ''' Extends the default json encoder to allow parsing the cfg
    objects into json.
    '''
    
    def __init__(self):
        ''' Hard-code in the super() invocation.
        '''
        # Make the cfg file as human-readable as possible
        super().__init__(indent=4)
        
    def default(self, obj):
        ''' Allow for encoding of our helper objects. Note that this is
        class-strict, IE subclasses must be explicitly supported.
        '''
        try:
            type_hint = _TYPEHINTS[type(obj)]
            
        # Unknown type. Pass TypeError raising to super().
        except KeyError:
            odict = super().default(obj)
            
        else:
            # Convert all attributes into dictionary keys
            odict = {key: getattr(obj, key) for key in obj._fields}
            # Add a type hint, but make sure to error if the field is already
            # defined (fail loud, fail fast)
            if type_hint in odict:
                raise ValueError(
                    'The type hint key cannot match any attribute names for ' +
                    'the object instance.'
                )
            odict[type_hint] = True
        
        return odict
        
        
def _yaml_caster(loader, data):
    ''' Preserve order of OrderedDicts, and re-cast them as normal maps.
    See also:
    +   http://stackoverflow.com/questions/13297744/pyyaml-control-
        ordering-of-items-called-by-yaml-load
    +   http://stackoverflow.com/questions/16782112/can-pyyaml-dump-
        dict-items-in-non-alphabetical-order
    +   http://stackoverflow.com/questions/8651095/controlling-yaml-
        serialization-order-in-python
    +   http://stackoverflow.com/questions/31605131/dumping-a-
        dictionary-to-a-yaml-file-while-preserving-order
        
    Note that nothin special is needed in the reverse direction, because
    the AutoField config system is assigning everything to an
    OrderedDict regardless of how it gets loaded.
    '''
    return loader.represent_mapping('tag:yaml.org,2002:map', data.items())
    
    
yaml.add_representer(collections.OrderedDict, _yaml_caster)


# ###############################################
# Library
# ###############################################
            

_readonly_remote = collections.namedtuple(
    typename = 'Remote',
    field_names = ('host', 'port', 'tls'),
)
        
        
class AutoField:
    ''' Helper class descriptor for AutoMappers.
    
    Huh... actually, is this usable as a decorator?
    '''
    
    def __init__(self, subfield=None, *args, listed=False, decode=None,
                 encode=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.subfield = subfield
        self._encode = encode
        self._decode = decode
        
        if listed:
            if subfield:
                class ListedSubfield(list):
                    ''' Well, this doesn't support slicing, but whatevs.
                    Or extension, for that matter.
                    '''
                    def __setitem__(instance, index, value, subfield=subfield):
                        if isinstance(value, subfield):
                            super(ListedSubfield, instance).__setitem__(index,
                                                                        value)
                        else:
                            raise TypeError(value)
                            
                    def append(instance, value, subfield=subfield):
                        if isinstance(value, subfield):
                            super(ListedSubfield, instance).append(value)
                        else:
                            raise TypeError(value)
                            
                    def extend(instance, value, subfield=subfield):
                        ''' Suppress extension, because it's messy.
                        '''
                        raise NotImplementedError()
                        
                    def insert(instance, index, value, subfield=subfield):
                        if isinstance(value, subfield):
                            super(ListedSubfield, instance).insert(index,
                                                                   value)
                        else:
                            raise TypeError(value)
                            
                self.listed = ListedSubfield
                
            else:
                self.listed = list
        
        else:
            self.listed = False
        
    def encode(self, value):
        ''' Wrap encode_single to support iteration.
        '''
        if self.listed:
            result = []
            for item in value:
                result.append(self.encode_single(item))
                
        else:
            result = self.encode_single(value)
            
        return result
        
    def encode_single(self, value):
        if value is None:
            return value
        elif self.subfield is not None:
            return value.entranscode()
        elif self._encode is None:
            return value
        elif callable(self._encode):
            return self._encode(value)
        else:
            return getattr(value, self._encode)()
        
    def decode(self, value):
        ''' Wrap decode_single to support iteration.
        '''
        if self.listed:
            result = []
            for item in value:
                result.append(self.decode_single(item))
                
        else:
            result = self.decode_single(value)
            
        return result
        
    def decode_single(self, value):
        if value is None:
            return value
        elif self.subfield is not None:
            instance = self.subfield()
            instance.detranscode(value)
            return instance
        elif self._decode is None:
            return value
        elif callable(self._decode):
            return self._decode(value)
        else:
            raise TypeError('Decoding must use a callable.')
            
    @property
    def name(self):
        ''' Reading is trivial.
        '''
        try:
            return self._name
        except AttributeError:
            return None
    
    @name.setter
    def name(self, value):
        ''' Writing checks to see if we have a value; if we do, it
        silently ignores the change.
        '''
        if not hasattr(self, '_name'):
            self._name = value
        elif self._name is None:
            self._name = value
            
    def __get__(self, instance, owner):
        if instance is None:
            return self
        else:
            return instance._fields[self.name]
            
    def __set__(self, instance, value):
        ''' Set the value at the instance's _fields OrderedDict.
        '''
        if self.subfield is not None:
            raise AttributeError('Cannot set AutoMapper attribute with ' +
                                 'subfield directly.')
        
        elif self.listed:
            raise AttributeError('Cannot set listed AutoMapper attribute ' +
                                 'directly.')
        
        else:
            instance._fields[self.name] = value
        
    def __delete__(self, instance):
        ''' Set the value at the instance's _fields OrderedDict to None.
        '''
        if self.listed:
            # TODO: change this to a list subtype
            instance._fields[self.name] = self.listed()
        
        elif self.subfield:
            instance._fields[self.name] = self.subfield()
        
        else:
            instance._fields[self.name] = None
            

class _AutoMapperMixin:
    ''' Inject a control OrderedDict for the fields.
    '''
    
    def __init__(self, *args, **kwargs):
        # This is an awkward but effective way of initializing everything.
        # Create self._fields, the ordereddict equivalent of self.__dict__
        self._fields = collections.OrderedDict()
        # For each field, delete it, resulting in the descriptor performing an
        # initialization to its null state
        for field in self.fields:
            delattr(self, field)
            
        # Now, we need to assign whatever was included in *args and **kwargs.
        # First bind the signature.
        bound_args = self._signature.bind_partial(*args, **kwargs)
        # Now pop *args and **kwargs from it, defaulting to empty collections
        args = bound_args.arguments.pop('args', tuple())
        kwargs = bound_args.arguments.pop('kwargs', {})
        # Now actually assign the remaining everything.
        for name, value in bound_args.arguments.items():
            setattr(self, name, value)
        
        # Yeah, don't forget this, but we need to wait until remapping *args
        # and **kwargs in the binding process above.
        super().__init__(*args, **kwargs)
        
    def entranscode(self):
        ''' Convert the object typed self._fields into a natively
        serializable ordereddict.
        '''
        transcoded = collections.OrderedDict()
        
        cls = type(self)
        for field in self.fields:
            descriptor = getattr(cls, field)
            value = self._fields[field]
            # Note that the descriptor handles nested fields and Nones
            transcoded[field] = descriptor.encode(value)
            
        return transcoded
        
    def detranscode(self, data):
        ''' Apply the natively deserialized ordereddict into
        self._fields.
        '''
        cls = type(self)
        
        for field in self.fields:
            descriptor = getattr(cls, field)
            
            try:
                # Note that the descriptor handles nested fields
                self._fields[field] = descriptor.decode(data[field])
            
            # Make sure we can optionally support configs with incomplete data
            except KeyError as exc:
                logger.warning('Healed config w/ missing field: ' + field)
                
            except Exception as exc:
                raise ConfigError('Failed to decode field: ' + field) from exc
            
    def __eq__(self, other):
        ''' Compare type of self and all fields.
        '''
        mycls = type(self)
        othercls = type(other)
        
        comparator = True
        if issubclass(mycls, othercls) or issubclass(othercls, mycls):
            try:
                comparator &= (self._fields == other._fields)
            
            except AttributeError as exc:
                raise TypeError(other) from exc
            
        else:
            comparator &= False
            
        return comparator
        
    # Restore normal hashing
    __hash__ = object.__hash__


class _AutoMapper(type):
    ''' Metaclass used for automatically mapping a structured something
    into objects with properties and names and stuff.
    '''

    # Remember the order of class variable definitions!
    @classmethod
    def __prepare__(mcls, clsname, bases, **kwargs):
        return collections.OrderedDict()

    def __new__(mcls, clsname, bases, namespace, **kwargs):
        fields = []
        parameters = []
        for name, value in namespace.items():
            if name in {'fields', '_fields', '_signature', 'args', 'kwargs'}:
                raise ValueError('Invalid class variable name for ' +
                                 'AutoMapper: ' + name)
            elif isinstance(value, AutoField):
                fields.append(name)
                # This will be ignored if the AutoField explicitly specifies
                # the name to use.
                value.name = name
                # We want to be able to pass instance creation into the
                # automapper fields, so let's make a parameter for it
                parameters.append(
                    inspect.Parameter(
                        name = name,
                        kind = inspect.Parameter.POSITIONAL_OR_KEYWORD
                    )
                )
        
        # We also want to support inheritance; so do this to add *args and
        # **kwargs to the signature
        parameters.append(
            inspect.Parameter(
                name = 'args',
                kind = inspect.Parameter.VAR_POSITIONAL
            )
        )
        parameters.append(
            inspect.Parameter(
                name = 'kwargs',
                kind = inspect.Parameter.VAR_KEYWORD
            )
        )
        
        # Carry on then...
        bases = (_AutoMapperMixin, *bases)
        cls = super().__new__(mcls, clsname, bases, dict(namespace), **kwargs)
        cls.fields = fields
        # This signature is for aforementioned binding
        cls._signature = inspect.Signature(parameters)
        return cls
        
        
class Remote(metaclass=_AutoMapper):
    ''' How _RemoteDef should be.
    '''
    host = AutoField()
    port = AutoField()
    tls = AutoField()


class User(metaclass=_AutoMapper):
    # Note that all of these recastings should handle None correctly
    fingerprint = AutoField(decode=Ghid.from_str, encode='as_str')
    user_id = AutoField(decode=Ghid.from_str, encode='as_str')
    root_secret = AutoField(decode=Secret.from_str, encode='as_str')


class Instrumentation(metaclass=_AutoMapper):
    verbosity = AutoField()
    debug = AutoField()
    traceur = AutoField()


class Process(metaclass=_AutoMapper):
    ghidcache = AutoField(decode=pathlib.Path, encode=str)
    logdir = AutoField(decode=pathlib.Path, encode=str)
    pid_file = AutoField(decode=pathlib.Path, encode=str)
    ipc_port = AutoField()
    
    
class Config(metaclass=_AutoMapper):
    ''' Context handler for semi-atomic config updates.
    
    .hypergolix /
    
    +---logs
        +---(log file 1...)
        +---(log file 2...)
        
    +---ghidcache
        +---(ghid file 1...)
        +---(ghid file 2...)
        
    +---(hgx.pid)
    +---(hgx-cfg.json)
    '''
    process = AutoField(Process)
    instrumentation = AutoField(Instrumentation)
    user = AutoField(User)
    remotes = AutoField(Remote, listed=True)
    
    TARGET_FNAME = 'hypergolix.yml'
    OLD_FNAMES = {'hgx-cfg.json'}
    
    def __init__(self, path, *args, **kwargs):
        ''' The usual init thing!
        '''
        super().__init__(*args, **kwargs)
        
        self.path = path.absolute()
        
        self._cfg_cache = None
        self.force_rewrite = False
        self.coerce_name = False
        
        # Set defaults here so that the paths can be relative to the config
        root = self.path.parent
        self.defaults = {
            'process': {
                'ghidcache': root / 'ghidcache',
                'logdir': root / 'logdir',
                'pid_file': root / 'hypergolix.pid',
                'ipc_port': 7772
            },
            'instrumentation': {
                'verbosity': 'info',
                'debug': False,
                'traceur': False
            }
        }
    
    def __enter__(self):
        ''' Gets a configuration for hypergolix (if one exists), and
        creates a new one (with no remote persistence servers) if none
        is available.
        '''
        # Cache the existing configuration so we can check for changes
        self._cfg_cache = copy.deepcopy(self)
        # Coerce any defaults, which will force a new config to do a rewrite
        # upon __exit__, since we now differ from _cfg_cache
        self.coerce_defaults()
        # Make sure we have all the needed directories for the config
        _ensure_dir_exists(self.process.ghidcache)
        _ensure_dir_exists(self.process.logdir)
            
        # And now allow access to self.
        return self
        
    def __exit__(self, exc_type, exc_value, exc_tb):
        ''' Save any changes to configuration (including creation of a
        new configuration).
        '''
        # Only modify if there were no errors; never do a partial update.
        if exc_type is None:
            # Perform an update if forced, or if the config has changed
            if self.force_rewrite or self._cfg_cache != self:
                self.dump(self.path)
        
        # Reset the config cache (it's just wasting memory now)
        self._cfg_cache = None
        
    def coerce_defaults(self):
        ''' Finds any null fields and converts them to a default value.
        '''
        for subfield, defaults in self.defaults.items():
            # Get the actual subfield instead of just its name
            subfield = getattr(self, subfield)
            # Now for that subfield, apply defaults
            for attr, default in defaults.items():
                if getattr(subfield, attr) is None:
                    setattr(subfield, default)
        
    @classmethod
    def find(cls):
        ''' Automatically locates any existing config file. Raises
        ConfigMissing if unable to locate.
        
        Search order:
        1.  Environment variable "HYPERGOLIX_HOME"
        2.  Current directory
        3.  ~/.hypergolix
        4.  /etc/hypergolix (Unix) or %LOCALAPPDATA%/Hypergolix (Windows)
        '''
        # Get the environment config setting, if it exists. If not, use a
        # long random path which we "know" will not exist.
        envpath = os.getenv(
            'HYPERGOLIX_HOME',
            default = '/qdubuddfsyvfafhlqcqetfkokykqeulsguoasnzjkc'
        )
        appdatapath = os.getenv(
            'LOCALAPPDATA',
            default = '/qdubuddfsyvfafhlqcqetfkokykqeulsguoasnzjkc'
        )
        
        search_order = []
        search_order.append(pathlib.Path(envpath))
        search_order.append(pathlib.Path('.').absolute())
        search_order.append(pathlib.Path.home() / '.hypergolix')
        # It really doesn't matter if we do this on Windows too, since it'll
        # just not exist.
        search_order.append(pathlib.Path('/etc/hypergolix'))
        search_order.append(pathlib.Path(appdatapath) / 'Hypergolix')
        
        # Collapse the nested loop into a single for loop with a list comp
        fnames = {cls.TARGET_FNAME, *cls.OLD_FNAMES}
        fpaths = (dirpath / fname for dirpath in search_order
                  for fname in fnames)
        # Check all of those paths
        for fpath in fpaths:
            if fpath.exists():
                break
        # Not found; raise.
        else:
            raise ConfigMissing()
        
        self = cls.load(fpath)
        # If it's a deprecated filename, coerce it to the new one.
        if fpath.name in cls.OLD_FNAMES:
            self.coerce_name = True
        
        return self
        
    @classmethod
    def wherever(cls):
        ''' Create a new config in the preferred location, wherever that
        is (hint: the answer is defined in the function!).
        
        Current location-of-choice is ~/.hypergolix.
        '''
        return cls(pathlib.Path.home() / '.hypergolix' / cls.TARGET_FNAME)
                
    @classmethod
    def load(cls, path):
        ''' Load a config from a pathlib.Path.
        '''
        cfg_txt = path.read_text()
        self = cls(path)
        self.decode(cfg_txt)
        
        return self
        
    def dump(self, path):
        ''' Dump a config to a pathlib.Path.
        '''
        path.write_text(self.encode())
    
    def encode(self):
        ''' Converts the config into an encoded file ready for output.
        '''
        raw_cfg = self.entranscode()
        return yaml.dump(raw_cfg, default_flow_style=False)
        
    def decode(self, data):
        ''' Load an existing config.
        
        NOTE: json is valid yaml. This will correctly load old configs
        without any extra effort!
        '''
        raw_cfg = yaml.safe_load(data)
        self.detranscode(raw_cfg)
            
    def set_remote(self, host, port, tls=True):
        ''' Handles creation of _RemoteDef instances and insertion into
        our config. Will also update TLS configuration of existing
        remotes.
        '''
        rdef = Remote(host, port, tls)
        
        if rdef == NAMED_REMOTES['hgx']:
            # TODO: move this somewhere else? This is a bit of an awkward place
            # to put a warning.
            print('Thanks for adding hgx.hypergolix.com as a remote server!\n')
            print('We limit unregistered accounts to read-only access.')
            print('For full access, please register:')
            print('    hypergolix config --register\n')
        
        # Note that we may be overwriting an existing remote with a different
        # TLS value.
        index = self.index_remote(rdef)
        
        # This is a new remote.
        if index is None:
            self.remotes.append(rdef)
            
        # This is an existing remote. Update in-place
        else:
            self.remotes[index].tls = tls
        
    def remove_remote(self, host, port):
        ''' Removes an existing remote. Silently does nothing if it does
        not exist in the config.
        '''
        # TLS does not matter when removing stuff.
        rdef = Remote(host, port, False)
        index = self.index_remote(rdef)
        
        if index is None:
            return None
        else:
            return self.remotes.pop(index)
        
    def index_remote(self, remote):
        ''' Find the index of an existing remote, if it exists. Ignores
        the remote's TLS configuration.
        '''
        remote2 = copy.deepcopy(remote)
        remote2.tls = not remote.tls
        
        try:
            index = self.remotes.index(remote)
        except ValueError:
            try:
                index = self.remotes.index(remote2)
            except ValueError:
                return None
        
        # If we get here, one of the above was successful.
        return index


def _ensure_dir_exists(path):
    ''' Ensures the existence of a directory. Path must be to the dir,
    and not to a file therewithin.
    '''
    path = pathlib.Path(path).absolute()
    if not path.exists():
        path.mkdir(parents=True)
        
    elif not path.is_dir():
        raise FileExistsError('Path exists already and is not a directory.')


# ###############################################
# Argparse on command line invocation
# ###############################################


NAMED_REMOTES = {
    'hgx': Remote('hgx.hypergolix.com', 443, True)
}


def _named_remote(remote):
    ''' Converts a named remote to a host, port, TLS group.
    '''
    return NAMED_REMOTES[remote]


def _exclusive_named_remote(remote):
    ''' Converts an exclusive named remote to a list of host, port, TLS
    groups, of length one.
    '''
    # Manually set 'local' to an empty list
    if remote == 'local':
        return []
        
    # Otherwise, re-cast it as the pair.
    else:
        return [_named_remote(remote)]


def _handle_verbosity(config, verbosity):
    lookup = {
        'extreme': 'extreme',
        'shouty': 'shouty',
        'louder': 'debug',
        'loud': 'info',
        'normal': 'warning',
        'quiet': 'error',
        'error': 'error',
        'warning': 'warning',
        'info': 'info',
        'debug': 'debug'
    }
    config.instrumentation.verbosity = lookup[verbosity]


def _handle_debug(config, debug_enabled):
    ''' Only modify debug if it was specified.
    '''
    if debug_enabled is None:
        return
        
    elif debug_enabled:
        config.instrumentation.debug = True
        
    else:
        config.instrumentation.debug = False


def _handle_remotes(config, only_remotes, add_remotes, remove_remotes):
    ''' Manages remotes.
    '''
    # Handling an exclusive remote declaration
    if only_remotes is not None:
        # Remove all existing remotes
        for remote in config.remotes:
            config.remove_remote(remote.host, remote.port)
        
        # Do nothing for local only, but add in the named remote otherwise
        for remote in only_remotes:
            config.set_remote(
                remote.host,
                remote.port,
                remote.tls
            )
    
    # Adding and removing remotes normally.
    else:
        for remote in add_remotes:
            config.set_remote(
                remote.host,
                remote.port,
                remote.tls
            )
        for remote in remove_remotes:
            config.remove_remote(
                remote.host,
                remote.port
            )


def _typecast_remotes(args):
    ''' Performs all type checking and casting for remotes.
    '''
    # First enforce "only" actually being ONLY
    if args.only_remotes is not None and args.add_remotes:
        raise ValueError('Cannot use --only with --add or --remove.')
    elif args.only_remotes is not None and args.remove_remotes:
        raise ValueError('Cannot use --only with --add or --remove.')
        
    # Correctly defined, and we're not using an only named remote.
    elif args.only_remotes is None:
        _process_remotes(args.add_remotes)
        _process_remotes(args.remove_remotes)
        
    # We've specified a single named remote.
    elif args.only_remotes != 'local':
        args.only_remotes = [NAMED_REMOTES[args.only_remotes]]
        
    # We've specified only local.
    else:
        args.only_remotes = []


def _process_remotes(remotes):
    ''' Ensures correct definitions for all non-singular remotes, and
    type casts them appropriately.
    '''
    re_remotes = []
    for remote in remotes:
        # This is a named remote. Easy peasy.
        if isinstance(remote, str):
            re_remotes.append(NAMED_REMOTES[remote])
            
        # This is a manually-defined remote. We need to do some massaging.
        else:
            host = remote[0]
            port = int(remote[1])
            
            # Calling add_remotes specifies TLS. Use it!
            if len(remote) == 3:
                tls = _str_to_bool(
                    remote[2],
                    failure_msg = 'Failed to infer truthiness of TLS usage. ' +
                                  'Please use "true", "false", "t", "f", etc.'
                )
                
            # Calling remove_remotes omits TLS. Fake it!
            else:
                tls = True
            
            # Now make a readonly remote for the definition.
            re_remotes.append(Remote(host, port, tls))
            
    # And finally, update the original remotes in place.
    remotes.clear()
    remotes.extend(re_remotes)


def _str_to_bool(s, failure_msg='Failed to infer truthiness.'):
    ''' Attempts to convert a string to a bool.
    '''
    # Normalize case.
    s = s.lower()
    
    truisms = {'y', 'true', 't', 'yes', '1'}
    falsities = {'n', 'false', 'f', 'no', '0'}
    
    if s in truisms:
        return True
    elif s in falsities:
        return False
    else:
        raise ValueError(failure_msg)


def _handle_ipc(config, ipc):
    ''' If IPC is defined, update it.
    '''
    if ipc is not None:
        config.process.ipc_port = ipc


def _format_blockstr(long_line):
    ''' Wraps a urlsafe ghid.
    '''
    shortened_length = 36
    indent = '    '
    
    out = []
    for slice_start in range(0, len(long_line), shortened_length):
        out.append(
            indent + long_line[slice_start:slice_start + shortened_length]
        )
    
    return '\n'.join(out)


def _handle_whoami(config, whoami):
    ''' If whoami is True, prints out information about the current
    hypergolix user.
    '''
    if whoami:
        fingerprint = config.user.fingerprint
        user_id = config.user.user_id

        # Add newline just for format pretty
        print('')
            
        if user_id is None:
            print('Your user ID is undefined.')
        else:
            user_id = user_id.as_str()
            print('Your user ID is:\n' + _format_blockstr(user_id))
            print('You use that to log in.\n')
            
        if fingerprint is None:
            print('Your fingerprint is undefined.')
        else:
            fingerprint = fingerprint.as_str()
            print('Your fingerprint is:\n' + _format_blockstr(fingerprint))
            print(
                'Someone else can use that to share\n' +
                'Hypergolix objects with you.'
            )


def _handle_register(config, register):
    ''' Launches registration in a browser window if set.
    '''
    if register:
        fingerprint = config.user.fingerprint.as_str()
        reg_address = 'https://www.hypergolix.com/register.html?' + fingerprint
        
        try:
            webbrowser.open(reg_address, new=2)
            
        except Exception:
            print(
                'Failed to open web browser for registration.\n' +
                'Please navigate to this address and click "register":\n' +
                _format_blockstr(reg_address)
            )
            
        else:
            print(
                'Please complete registration in your browser window.\n' +
                'If no page was opened, navigate to this address and\n' +
                'click "register":\n' +
                _format_blockstr(reg_address)
            )


def handle_args(args):
    ''' Performs all needed actions on the passed command args.
    '''
    _typecast_remotes(args)
    
    # If no config root was passed as an argument, search for one, and if we
    # can't find the config, create a new one
    if args.cfg_root is None:
        try:
            config = Config.find()
        
        except ConfigMissing:
            print('Welcome to Hypergolix!')
            print('No existing configuration found; creating a new one.')
            config = Config.wherever()
    
    # If we passed a config root as an argument, load it directly
    else:
        config = Config.load(pathlib.Path(args.cfg_root))
    
    with config:
        _handle_remotes(
            config,
            args.only_remotes,
            args.add_remotes,
            args.remove_remotes
        )
        _handle_debug(config, args.debug)
        _handle_verbosity(config, args.verbosity)
        _handle_ipc(config, args.ipc_port)
        _handle_whoami(config, args.whoami)
        _handle_register(config, args.register)
        
    print('Configuration successful. Restart Hypergolix to apply any changes.')
