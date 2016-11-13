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

Some notes:

'''

# Global dependencies
import logging
import collections
# import collections.abc
import weakref
import threading
import abc
import traceback
import pickle
# import atexit

from golix import SecondParty
from golix import Ghid
from golix import Secret
from golix import SecurityError

from golix._getlow import GEOC
from golix._getlow import GOBD
from golix._getlow import GARQ
from golix._getlow import GDXX

# Intra-package dependencies
from .hypothetical import API
from .hypothetical import public_api
from .hypothetical import fixture_api

from .utils import _generate_threadnames
from .utils import SetMap
from .utils import NoContext
from .utils import weak_property

from .exceptions import RemoteNak
from .exceptions import HandshakeError
from .exceptions import HandshakeWarning
from .exceptions import UnknownParty
from .exceptions import DoesNotExist

from .persistence import _GobdLite
from .persistence import _GdxxLite
from .persistence import _GobsLite

# from .persisters import _PersisterBase

# from .ipc import _IPCBase
# from .ipc import _EndpointBase


# ###############################################
# Boilerplate
# ###############################################


logger = logging.getLogger(__name__)


# Control * imports. Therefore controls what is available to toplevel
# package through __init__.py
__all__ = [
    'GolixCore',
]

        
# ###############################################
# Lib
# ###############################################
            
            
class GolixCore(metaclass=API):
    ''' Wrapper around Golix library that automates much of the state
    management, holds the Agent's identity, etc etc.
    '''
    DEFAULT_LEGROOM = 7
    
    @public_api
    def __init__(self):
        ''' Create a new agent. Persister should subclass _PersisterBase
        (eventually this requirement may be changed).
        
        persister isinstance _PersisterBase
        dispatcher isinstance DispatcherBase
        _identity isinstance golix.FirstParty
        '''
        self._opslock = threading.Lock()
        
        # Added during bootstrap
        self._identity = None
        # Added during assembly
        self._librarian = None
        
    @__init__.fixture
    def __init__(self, test_agent):
        ''' Just, yknow, throw in the towel. Err, agent. Whatever.
        '''
        self._identity = test_agent
        
    def assemble(self, librarian):
        # Chicken, meet egg.
        self._librarian = weakref.proxy(librarian)
        
    def prep_bootstrap(self, identity):
        # Temporarily set our identity to a generic firstparty for loading.
        self._identity = identity
        
    def bootstrap(self, credential):
        # This must be done ASAGDFP. Must be absolute first thing to bootstrap.
        self._identity = weakref.proxy(credential.identity)
        
    @property
    @public_api
    def whoami(self):
        ''' Return the Agent's Ghid.
        '''
        return self._identity.ghid
        
    def unpack_request(self, request):
        ''' Just like it says on the label...
        Note that the request is PACKED, not unpacked.
        '''
        with self._opslock:
            unpacked = self._identity.unpack_request(request)
        return unpacked
        
    def open_request(self, unpacked):
        ''' Just like it says on the label...
        Note that the request is UNPACKED, not packed.
        '''
        requestor = SecondParty.from_packed(
            self._librarian.retrieve(unpacked.author)
        )
        payload = self._identity.receive_request(requestor, unpacked)
        return payload
        
    def make_request(self, recipient, payload):
        # Just like it says on the label...
        recipient = SecondParty.from_packed(
            self._librarian.retrieve(recipient)
        )
        with self._opslock:
            return self._identity.make_request(
                recipient = recipient,
                request = payload,
            )
        
    def open_container(self, container, secret):
        # Wrapper around golix.FirstParty.receive_container.
        author = SecondParty.from_packed(
            self._librarian.retrieve(container.author)
        )
        
        with self._opslock:
            state = self._identity.receive_container(
                author = author,
                secret = secret,
                container = container
            )
        
        return state
        
    def make_container(self, data, secret):
        # Simple wrapper around golix.FirstParty.make_container
        with self._opslock:
            return self._identity.make_container(
                secret = secret,
                plaintext = data
            )

    def make_binding_stat(self, target):
        # Note that this requires no open() method, as bindings are verified by
        # the local persister.
        with self._opslock:
            return self._identity.make_bind_static(target)
        
    def make_binding_dyn(self, target, ghid=None, history=None):
        ''' Make a new dynamic binding frame.
        If supplied, ghid is the dynamic address, and history is an 
        ordered iterable of the previous frame ghids.
        '''
        # Make a new binding!
        if (ghid is None and history is None):
            pass
            
        # Update an existing binding!
        elif (ghid is not None and history is not None):
            pass
            
        # Error!
        else:
            raise ValueError('Mixed def of ghid/history while dyn binding.')
            
        with self._opslock:
            return self._identity.make_bind_dynamic(
                target = target,
                ghid_dynamic = ghid,
                history = history
            )
        
    def make_debinding(self, target):
        # Simple wrapper around golix.FirstParty.make_debind
        with self._opslock:
            return self._identity.make_debind(target)


class GhidProxier:
    ''' Resolve the base container GHID from any associated ghid. Uses
    all weak references, so should not interfere with GCing objects.
    
    Threadsafe.
    '''
    
    def __init__(self):
        # Note that we can't really cache aliases, because their proxies will
        # not update when we change things unless the proxy is also removed
        # from the cache. Since the objects may (or may not) exist locally in
        # memory anyways, we should just take advantage of that, and allow our
        # inquisitor to more easily manage memory consumption as well.
        # self._refs = {}
        
        self._modlock = threading.Lock()
        
        self._librarian = None
        self._salmonator = None
        
    def assemble(self, librarian, salmonator):
        # Chicken, meet egg.
        self._librarian = weakref.proxy(librarian)
        self._salmonator = weakref.proxy(salmonator)
        
    def __mklink(self, proxy, target):
        ''' Set, or update, a ghid proxy.
        
        Ghids must only ever have a single proxy. Calling chain on an 
        existing proxy will update the target.
        '''
        raise NotImplementedError('Explicit link creation has been removed.')
        
        if not isinstance(proxy, Ghid):
            raise TypeError('Proxy must be Ghid.')
            
        if not isinstance(target, Ghid):
            raise TypeError('Target must be ghid.')
        
        with self._modlock:
            self._refs[proxy] = target
            
    def resolve(self, ghid):
        ''' Protect the entry point with a global lock, but don't leave
        the recursive bit alone.
        
        TODO: make this guarantee, through using the persister's 
        librarian, that the resolved ghid IS, in fact, a container.
        
        TODO: consider adding a depth limit to resolution.
        '''
        if not isinstance(ghid, Ghid):
            raise TypeError('Can only resolve a ghid.')
            
        with self._modlock:
            return self._resolve(ghid)
        
    def _resolve(self, ghid):
        ''' Recursively resolves the container ghid for a proxy (or a 
        container).
        '''
        if ghid not in self._librarian:
            self._salmonator.attempt_pull(ghid, quiet=True)
        
        try:
            obj = self._librarian.summarize(ghid)
        except KeyError:
            logger.warning(
                'Librarian missing resource record; could not verify full '
                'resolution of ' + str(ghid) + '\n' + 
                ''.join(traceback.format_exc()))
            return ghid
        
        else:
            if isinstance(obj, _GobdLite):
                return self._resolve(obj.target)
                
            else:
                return ghid
        
        
class Oracle(metaclass=API):
    ''' Source for total internal truth and state tracking of objects.
    
    Maintains <ghid>: <obj> lookup. Used by dispatchers to track obj
    state. Might eventually be used by AgentBase. Just a quick way to
    store and retrieve any objects based on an associated ghid.
    '''
    _golcore = weak_property('__golcore')
    _ghidproxy = weak_property('__ghidproxy')
    _privateer = weak_property('__privateer')
    _percore = weak_property('__percore')
    _bookie = weak_property('__bookie')
    _librarian = weak_property('__librarian')
    _postman = weak_property('__postman')
    _salmonator = weak_property('__salmonator')
    
    @public_api
    def __init__(self):
        ''' Sets up internal tracking.
        '''
        self._opslock = threading.Lock()
        self._lookup = {}
        
        self._golcore = None
        self._ghidproxy = None
        self._privateer = None
        self._percore = None
        self._bookie = None
        self._librarian = None
        self._postman = None
        self._salmonator = None
        
    @__init__.fixture
    def __init__(self):
        ''' Fixture init.
        '''
        self._lookup = {}
        self._opslock = NoContext()
        
    @fixture_api
    def RESET(self):
        ''' Simply re-call init.
        '''
        self.__init__()
        
    def assemble(self, golcore, ghidproxy, privateer, percore, bookie,
                 librarian, postman, salmonator):
        # Chicken, meet egg.
        self._golcore = golcore
        self._ghidproxy = ghidproxy
        self._privateer = privateer
        self._percore = percore
        self._bookie = bookie
        self._librarian = librarian
        self._postman = postman
        self._salmonator = salmonator
        
    @fixture_api
    def add_object(self, ghid, obj):
        ''' Add an object to the fixture.
        '''
        self._lookup[ghid] = obj
            
    @public_api
    async def get_object(self, gaoclass, ghid, *args, **kwargs):
        ''' Get an object.
        '''
        if ghid in self._lookup:
            obj = self._lookup[ghid]
            logger.debug(''.join((
                'GAO ',
                str(ghid),
                ' already exists in Oracle memory.'
            )))
            
            if not isinstance(obj, gaoclass):
                raise TypeError(
                    'Object has already been resolved, and is not the '
                    'correct GAO class.'
                )
        
        else:
            logger.info(''.join((
                'GAO ',
                str(ghid),
                ' not currently in Oracle memory. Attempting load.'
            )))
            
            # First create the actual GAO. We do not need to have the ghid
            # downloaded to do this -- object creation is just making a Python
            # object locally.
            obj = gaoclass(
                ghid,
                None,   # dynamic
                None,   # author
                7,      # legroom (will be overwritten by pull)
                *args,
                golcore = self._golcore,
                ghidproxy = self._ghidproxy,
                privateer = self._privateer,
                percore = self._percore,
                bookie = self._bookie,
                librarian = self._librarian,
                **kwargs
            )
            
            # Now immediately subscribe to the object upstream, so that there
            # is no race condition getting updates
            await self._salmonator.register(obj)
            # Explicitly pull the object from salmonator to ensure we have the
            # newest version, and that it is available locally in librarian if
            # also available anywhere else. Note that salmonator handles modal
            # switching for dynamic/static. It will also (by default, with
            # skip_refresh=False) pull in any updates that have accumulated in
            # the meantime.
            self._salmonator.attempt_pull(ghid, quiet=True)
            
            # Now actually fetch the object. This may KeyError if the ghid is
            # still unknown.
            await obj._pull()
            
            # Always do this to make sure we have the most recent version
            self._lookup[ghid] = obj
            
        return obj
        
    @get_object.fixture
    async def get_object(self, gaoclass, ghid, *args, **kwargs):
        ''' Do the easy thing and just pull it out of lookup.
        '''
        return self._lookup[ghid]
        
    @public_api
    async def new_object(self, gaoclass, dynamic, legroom, *args, **kwargs):
        ''' Creates a new object and returns it. Passes all *kwargs to
        the declared gao_class. Requires a zeroth state, and calls push
        internally.
        '''
        obj = gaoclass(
            None,                   # ghid
            dynamic,
            self._golcore.whoami,   # author
            legroom,
            *args,
            **kwargs,
            golcore = self._golcore,
            ghidproxy = self._ghidproxy,
            privateer = self._privateer,
            percore = self._percore,
            bookie = self._bookie,
            librarian = self._librarian
        )
        await obj._push()
        
        # Do this before registering with salmonator, in case the latter errors
        self._lookup[obj.ghid] = obj
        
        # Finally, register to receive any concurrent updates from other
        # simultaneous sessions, and then return the object
        await self._salmonator.register(obj)
        return obj
            
    @new_object.fixture
    async def new_object(self, *args, **kwargs):
        ''' Relies upon add_object, but otherwise just pops something
        from the lookup.
        '''
        ghid, obj = self._lookup.popitem()
        self._lookup[ghid] = obj
        return obj
        
    def forget(self, ghid):
        ''' Removes the object from the cache. Next time an application
        wants it, it will need to be acquired from persisters.
        
        Indempotent; will not raise KeyError if called more than once.
        '''
        with self._opslock:
            try:
                del self._lookup[ghid]
            except KeyError:
                logger.debug(str(ghid) + ' unknown to oracle.')
            
    def __contains__(self, ghid):
        ''' Checks for the ghid in cache (but does not check for global
        availability; that would require checking the persister for its
        existence and the privateer for access).
        '''
        return ghid in self._lookup
