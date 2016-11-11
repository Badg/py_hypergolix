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
import logging
import asyncio
import traceback
import collections
import functools
import weakref

from golix import Ghid
from loopa.utils import await_coroutine_threadsafe
from loopa.utils import await_coroutine_loopsafe
from loopa.utils import make_background_future

# Local dependencies
from .hypothetical import API
from .hypothetical import public_api
from .hypothetical import fixture_api

from .utils import SetMap
from .utils import WeakSetMap
from .utils import ApiID
from .utils import _reap_wrapped_task
from .utils import weak_property
from .utils import readonly_property
from .utils import immortal_property
from .utils import immutable_property

from .exceptions import HGXLinkError
from .exceptions import DeadObject
from .exceptions import RatchetError
from .exceptions import RatchetChainError
from .exceptions import RatchetStateError

from .persistence import _GobdLite
from .persistence import _GdxxLite
from .persistence import _GobsLite
from .persistence import _GeocLite

# from .objproxy import ObjBase
# from .objproxy import ObjCore


# ###############################################
# Boilerplate
# ###############################################


logger = logging.getLogger(__name__)


# Control * imports.
__all__ = [
    # 'PersistenceCore',
]


# ###############################################
# Utils
# ###############################################


class Deferrable(type):
    ''' Use this to construct GAOs that use deferred-action methods that
    can store deltas before flushing.
    
    TODO: support this. Currently, it's just one big race condition
    waiting for contention problems.
    '''
    

def deferred(func):
    ''' Decorator to make a deferred-action method.
    '''
    try:
        func.__deferred__ = True
    
    except AttributeError:
        @functools.wraps(func)
        def func(*args, _func=func, **kwargs):
            _func(*args, **kwargs)
        
        func.__deferred__ = True
    
    return func
    
    
class DefermentTracker:
    ''' Tracks all deferred objects, and allows for a single flush()
    call to push all changes.
    '''
    
    def __init__(self):
        # Create a set of all tracked objects.
        self.tracked = weakref.WeakSet()
        
    def add(self, gao):
        ''' Track a gao.
        '''
        self.tracked.add(gao)
        
    def remove(self, gao):
        ''' Remove a gao.
        '''
        self.tracked.remove(gao)
        
    async def flush(self):
        ''' Push all of the tracked GAOs. Currently dumb (in that it
        does not check for modifications, and simply always pushes.)
        '''
        tasks = set()
        for gao in self.tracked:
            tasks.add(make_background_future(gao.push()))
            
        # And wait for them all to complete. Note that make_background_future
        # handles their exception and result handling.
        await asyncio.wait(
            fs = tasks,
            return_when = asyncio.ALL_COMPLETED
        )


# ###############################################
# Lib
# ###############################################


class GAOCore(metaclass=API):
    ''' Adds functions to a GAO.
    
    Notes:
    1.  GAO are only ever created through the oracle, via either
        oracle.new_object or oracle.get_object.
    2.  Note that callbacks are only used when defined in subclasses.
        IE, Dispatchable extends pull() to notify applications of the
        update (if applicable)
    3.  Updates for internal-use GAO should defer until a flush() call
    4.  Updates for dispatchables should immediately be pushed
    5.  Salmonator pushing should probably wait to return until all
        remotes have been contacted
    6.  Internal GAOs should probably have a delta-tracking mechanism
        for conflict resolution
    7.  Dispatchables should rely upon immediate pushing, and then raise
        immediately for any conflicts
    '''
    
    # Default a few things to prevent attributeerrors
    _legroom = None
    _frame_history = tuple()
    _target_history = tuple()
    
    # Make weak properties for the various thingajobbers
    _golcore = weak_property('__golcore')
    _ghidproxy = weak_property('__ghidproxy')
    _privateer = weak_property('__privateer')
    _percore = weak_property('__percore')
    _bookie = weak_property('__bookie')
    _librarian = weak_property('__librarian')
    
    # Make readonly properties for dynamic, ghid, and author. Note that the
    # author field is technically deprecated and pending removal, but is
    # currently used to infer the binder for applications.
    dynamic = readonly_property('_dynamic')
    author = readonly_property('_author')
    # This is immutable, so that it may be set just after initting.
    ghid = immutable_property('_ghid')
    _master_secret = readonly_property('__msec')
    
    # Also, an un-deletable property for history (even if unused), etc
    isalive = immortal_property('_isalive')
    # Most recent FRAME ghids
    frame_history = immortal_property('_frame_history')
    # Most recent TARGET ghids
    target_history = immortal_property('_target_history')
    
    @property
    def legroom(self):
        ''' Do the thing with the thing.
        '''
        return self._legroom
        
    @legroom.setter
    def legroom(self, value):
        ''' Cast value as int and then assign it both internally and to
        the two history deques.
        '''
        legroom = int(value)
        
        if legroom != self._legroom:
            self._legroom = legroom
            # We actually have to create new deques for this, because you
            # cannot resize existing ones.
            self.frame_history = collections.deque(self.frame_history,
                                                   maxlen=legroom)
            self.target_history = collections.deque(self.target_history,
                                                    maxlen=legroom)
            
    @property
    def _local_secret(self):
        ''' This determines if the secret will be committed locally only
        (for master_secreted objects), or if it will be stored
        persistently for the account.
        '''
        return bool(self._master_secret)
    
    def __init__(self, ghid, dynamic, author, legroom, *, golcore, ghidproxy,
                 privateer, percore, bookie, librarian, master_secret=None):
        ''' Init should be used only to create a representation of an
        EXISTING (or about to be existing) object. If any fields are
        unknown, they must be explicitly passed None.
        
        If master_secret is None, ratcheting will be iterative.
        If master_secret is a Secret, ratcheting will use the primary
            bootstrap ratcheting mechanism.
        '''
        self._golcore = golcore
        self._ghidproxy = ghidproxy
        self._privateer = privateer
        self._percore = percore
        self._bookie = bookie
        self._librarian = librarian
        
        # Dynamic and author be explicitly None; ghid should always be defined
        self.ghid = ghid
        self._dynamic = dynamic
        self._author = author
        
        # Note that this also initializes frame_history and target_history
        self.legroom = legroom
        self.isalive = True
        
        # This determines our ratcheting behavior. Set it with setattr to
        # bypass both name mangling AND the readonly property.
        setattr(self, '__msec', master_secret)
        
        # We will only ever be created from within an event loop, so this is
        # fine to do without an explicit loop.
        self._update_lock = asyncio.Lock()
        
    async def apply_delete(self, debinding):
        ''' Executes an external delete, caused by the debinding at the
        passed address. By default, just makes sure the debinding target
        is valid.
        
        Debinding is a _GdxxLite.
        
        Note that this gets used by Dispatchable to dispatch deletion to
        applications.
        '''
        if debinding.target != self.ghid:
            raise ValueError(
                'Debinding target does not match GAO applying delete.'
            )
        
    async def pack_gao(self):
        ''' Packs self into a bytes object. May be overwritten in subs
        to pack more complex objects. Should always be a staticmethod or
        classmethod.
        
        May be used to implement, for example, packing self into a
        DispatchableState, etc etc.
        '''
        pass
        
    async def unpack_gao(self, packed):
        ''' Unpacks state from a bytes object and applies state to self.
        May be overwritten in subs to unpack more complex objects.
        
        May be used to implement, for example, dicts performing a
        clear() operation before an update() instead of just reassigning
        the object.
        '''
        pass
            
    async def freeze(self):
        ''' Creates a static binding for the most current state of a
        dynamic binding. Returns the frozen ghid.
        '''
        if not self.dynamic:
            raise TypeError('Cannot freeze a static GAO.')
            
        container_ghid = self._ghidproxy.resolve(self.ghid)
        binding = self._golcore.make_binding_stat(container_ghid)
        self._percore.ingest_gobs(binding)
        
        return container_ghid
        
    async def hold(self):
        ''' Make a static binding for the gao.
        '''
        binding = self._golcore.make_binding_stat(self.ghid)
        self._percore.ingest_gobs(binding)
        
    async def delete(self):
        ''' Permanently removes the object. This method is only called
        locally; upstream deletes should call self.apply_delete.
        '''
        if self.dynamic:
            debinding = self._golcore.make_debinding(self.ghid)
            self._percore.ingest_gdxx(debinding)
            
        else:
            # Get frozenset of binding ghids
            bindings = self._bookie.bind_status()
            
            for binding in bindings:
                obj = self._librarian.summarize(binding)
                if isinstance(obj, _GobsLite):
                    if obj.author == self._golcore.whoami:
                        debinding = self._golcore.make_debinding(obj.ghid)
                        self._percore.ingest_gdxx(debinding)
            
    def _get_new_secret(self):
        ''' Gets a new secret for self.
        '''
        # If we're getting a new secret and we already have a ghid, then we
        # MUST be a dynamic object.
        if self.ghid:
            current_target = self.target_history[0]
            secret = self._privateer.ratchet_chain(
                self.ghid,
                current_target,
                self._master_secret
            )
        
        # This is a new object, and we therefore don't have a secret. Note that
        # the first secret for a bootstrapped chain will always be discarded,
        # because the salt process needs to start somewhere.
        else:
            secret = self._privateer.new_secret()
            
        return secret
                        
    async def push(self):
        ''' Pushes the state upstream. Must be called explicitly. Unless
        push() is invoked, the state will not be synchronized.
        '''
        if not self.isalive:
            raise DeadObject('Cannot push a deleted object. Create a new one.')
        
        # We're alive. Don't do object creation here; do it in oracle. This is
        # strictly updating.
        elif self.dynamic:
            # We need to make sure we're not pushing and pulling at the same
            # time.
            async with self._update_lock:
                try:
                    await self._push()
                
                # TODO: narrow which exceptions can cause this.
                except Exception:
                    logger.error(''.join((
                        'GAO ',
                        str(self.ghid),
                        ' PUSH: failed to update object; forcibly restoring ',
                        'state w/ traceback:\n',
                        traceback.format_exc()
                    )))
                    # We had a problem, so we're going to forcibly restore the
                    # object to the last known good state. Use _pull to avoid
                    # the lock, as well as any extra baggage in "normal" pull
                    await self._pull()
                    raise
            
        else:
            raise TypeError('Static objects cannot be updated.')
            
    async def _push(self):
        ''' The actual "meat and bones" for pushing.
        '''
        secret = self._get_new_secret()
        
        # We have a secret. Now we need a container and a binding frame.
        try:
            packed = await self.pack_gao()
            container = self._golcore.make_container(packed, secret)
            self._privateer.stage(container.ghid, secret)
            
            if self.dynamic:
                binding = self._golcore.make_binding_dyn(
                    target = container.ghid,
                    ghid = self.ghid,
                    history = self._history
                )
                # Update ghid if it was not defined (new object)
                self._conditional_init(
                    binding.ghid_dynamic,
                    True,
                    self._golcore.whoami
                )
                
                # Publish to persister
                self._percore.ingest_gobd(binding)
            
            # Static object.
            else:
                binding = self._golcore.make_binding_stat(
                    target = container.ghid
                )
                # Update ghid if it was not defined (new object)
                self._conditional_init(
                    container.ghid,
                    False,
                    self._golcore.whoami
                )
                self._percore.ingest_gobs(binding)
                
            # Finally, ingest the object itself.
            self._percore.ingest_geoc(container)
        
        # Necessary for else clause (grumble grumble)
        except:
            # Anything that got here means that the container hasn't been
            # ingested (that was the last thing above), so abandon its secret.
            self._privateer.abandon(container.ghid, quiet=True)
            raise
            
        # We created a container and binding frame, and then we successfully
        # uploaded them. Update our frame and target history accordingly and
        # commit the container secret.
        else:
            self._privateer.commit(container.ghid, localize=self._local_secret)
            # NOTE THE DISCREPANCY between the Golix dynamic binding version
            # of ghid and ours! This is recording the frame ghid.
            # I mean, for static stuff this isn't (strictly speaking) relevant,
            # but it also doesn't really hurt anything, sooo...
            self.frame_history.appendleft(binding.ghid)
            self.target_history.appendleft(container.ghid)
        
    async def pull(self, notification):
        ''' Pulls state from upstream and applies it. Does not check for
        recency.
        '''
        # Is this a good idea? It is actually possible to un-delete an object,
        # if you re-bind it, soooo...
        # TODO: think darüber
        if not self.isalive:
            raise DeadObject('Cannot pull a deleted object. Create a new one.')
            
        elif self.dynamic:
            # If everything is running on our software, and there aren't any
            # bugs, this path should never get triggered. But, just in case...
            if notification in self.frame_history:
                logger.debug(''.join((
                    'GAO at',
                    str(self.ghid),
                    ' PULL IGNORED w/ notification ',
                    str(notification)
                )))
            
            # This notification is not known to us. It could either be a frame
            # for an update, or it could be a deletion notice.
            else:
                summary = self._librarian.summarize(notification)
                # We've been deleted.
                if isinstance(summary, _GdxxLite):
                    async with self._update_lock:
                        await self.apply_delete(summary)
                        logger.info(''.join((
                            'GAO at ',
                            str(self.ghid),
                            ' PULL COMPLETED; deleted.'
                        )))
                        
                # We're being updated.
                elif summary.ghid == self.ghid:
                    async with self._update_lock:
                        await self._pull(summary)
                        logger.info(''.join((
                            'GAO at ',
                            str(self.ghid),
                            ' PULL COMPLETED with updates.'
                        )))
                
                # The update did not match us. This is sufficient to verify
                # both that the update was a dynamic binding, and that there's
                # no upstream bug for us.
                else:
                    raise ValueError(
                        'Update failed pull; mismatched binding ghid.'
                    )
            
        else:
            raise TypeError('Static objects cannot be pulled.')
        
    async def _pull(self):
        ''' The actual "meat and bones" for pulling.
        
        This is what you'll extend in Dispatchable to update
        applications.
        '''
        # Make sure we have the most recent binding, regardless of what was
        # recently passed.
        binding = self.librarian.summarize(self.ghid)
        
        # Okay, if this is calling _pull from oracle._get_object, we may be
        # going for either a dynamic binding or a static object (container).
        if isinstance(binding, _GobdLite):
            # Also don't forget to update history. Do this first, because it
            # will create a canonical update, regardless of success in
            # unpacking.
            try:
                # This will only update history. It will not add our current
                # frame to the history. So, we preserve the maximum depth to
                # heal the ratchet at this point.
                self._advance_history(binding)
                self._privateer.heal_chain(gao=self, binding=binding)
            
            # Now, we need to be sure our local history doesn't forget about
            # our current-most-recent frame when making an update.
            finally:
                # Finally, appendleft the newest frame and the newest target.
                self.frame_history.appendleft(binding.frame_ghid)
                self.target_history.appendleft(binding.target)
                
            # Okay, now let's actually do the thing with the new copy.
            container_ghid = binding.target
            dynamic = True
                    
        # Static object, so this is the actual container (and not the binding).
        elif isinstance(binding, _GeocLite):
            container_ghid = binding.ghid
            dynamic = False
            
        # None of the above. TypeError.
        else:
            raise TypeError('Update failed pull; mismatched Golix primitive.')
        
        secret = self._privateer.get(container_ghid)
        packed = self._librarian.retrieve(container_ghid)
        
        # If this was just pulled for the first time, init the dynamic and
        # author attributes.
        self._conditional_init(dynamic=dynamic, author=binding.author)
        
        try:
            # TODO: fix the leaky abstraction of jumping into the _identity
            unpacked = self._golcore._identity.unpack_container(packed)
            packed_state = self._golcore.open_container(unpacked, secret)
        
        except SecurityError:
            self._privateer.abandon(container_ghid)
            raise
            
        else:
            self._privateer.commit(container_ghid, localize=self._local_secret)
        
        # Finally, with all of the administrative stuff handled, unpack the
        # actual payload.
        await self.unpack_gao(packed_state)
        
    def _advance_history(self, new_obj):
        ''' Updates our history to match the new one.
        '''
        old_history = self.frame_history
        new_history = new_obj.history
        new_legroom = len(new_history)
        
        # Find how far offset the new_history is from the old_history.
        for offset in range(new_legroom):
            # Align the histories by checking the ii'th new element against an
            # offset ii'th old element.
            for ii in range(new_legroom - offset):
                # The new element matches the offset old element, so don't
                # change the offset.
                if new_history[offset + ii] == old_history[ii]:
                    continue
                
                # It didn't match, so we need to up the offset by one. Short
                # circuit the inner loop via break.
                else:
                    break
                
            # We found a match. Short-circuit parent loop.
            else:
                break
    
        # We never found a match. Offset should be made into the length of the
        # entire thing.
        else:
            offset += 1
                    
        # Now we need to make sure that our legroom matches the new object's.
        # Do this after advancing the history so that we don't accidentally
        # infer offsets between frames that are so far gone that we don't know
        # their history. Note that this can only happen when there's a race
        # between the persistence ingestion updating the object, and the update
        # being applied to the actual GAO.
        self.legroom = new_legroom
        
        # Now, appendleft the new frame (and an empty target) until we get to
        # the most recent one.
        for ii in range(offset - 1, -1, -1):
            self.frame_history.appendleft(new_history[ii])
            self.target_history.appendleft(None)
            
    def _conditional_init(self, ghid, dynamic, author):
        ''' If dynamic had not been set, set both it and the author. If
        ghid has not been set, set it.
        '''
        if self._dynamic is None:
            self._dynamic = dynamic
            self._author = author
            
        if self.ghid is None:
            self.ghid = ghid
            
            
class GAO(GAOCore):
    ''' A bare-bones GAO that performs trivial serialization (the
    serialization of the state is the state itself).
    '''
    
    def __init__(self, *args, state, **kwargs):
        self.state = state
        super().__init__(*args, **kwargs)
        
    async def pack_gao(self):
        ''' Packs self into a bytes object. May be overwritten in subs
        to pack more complex objects. Should always be a staticmethod or
        classmethod.
        
        May be used to implement, for example, packing self into a
        DispatchableState, etc etc.
        '''
        return self.state
        
    async def unpack_gao(self, packed):
        ''' Unpacks state from a bytes object and applies state to self.
        May be overwritten in subs to unpack more complex objects.
        
        May be used to implement, for example, dicts performing a
        clear() operation before an update() instead of just reassigning
        the object.
        '''
        self.state = packed
        
    
class _GAO:
    ''' Base class for Golix-Aware Objects (Golix Accountability
    Objects?). Anyways, used by core to handle plaintexts and things.
    
    TODO: thread safety? or async safety?
    TODO: support reference nesting.
    '''
    
    def __init__(self, golix_core, ghidproxy, privateer, persistence_core,
                 bookie, librarian, dynamic, _legroom=None, _bootstrap=None,
                 accountant=None, inquisitor=None, *args, **kwargs):
        ''' Creates a golix-aware object. If ghid is passed, will
        immediately pull from core to sync with existing object. If not,
        will create new object on first push. If ghid is not None, then
        dynamic will be ignored.
        '''
        # TODO: move all silencing code into the persistence core.
        # Actually, pretty sure that's already handled. But, we will need more
        # testing to check. But we should also verify that we've reorganized
        # such that anything within _history will automatically silenced.
        self.__opslock = threading.RLock()
        self.__state = None
        
        self._deleted = False
        
        # Note that, since all of these are (in production) passed through the
        # oracle, which already has weak references, these will also all be
        # weakly referenced. So we don't need to re-proxy them.
        self._golcore = golix_core
        self._ghidproxy = ghidproxy
        self._privateer = privateer
        self._percore = persistence_core
        self._bookie = bookie
        self._librarian = librarian
        # This will be added in when we start doing resource usage tracking
        # self._inquisitor = inquisitor
        
        self.dynamic = bool(dynamic)
        self.ghid = None
        self.author = None
        # self._frame_ghid = None
        
        if _legroom is None:
            _legroom = self._golcore._legroom
        # Legroom must have a minimum of 3
        _legroom = max([_legroom, 3])
        self._legroom = _legroom
        
        # Most recent FRAME GHIDS
        self._history = collections.deque(maxlen=_legroom)
        # Most recent FRAME TARGETS
        self._history_targets = collections.deque(maxlen=_legroom)
        
        # This probably only needs to be maxlen=2, but it's a pretty negligible
        # footprint to add some headspace
        self._silenced = collections.deque(maxlen=3)
        self._update_greenlight = threading.Event()
        
        def weak_touch(*args, **kwargs):
            ''' This is a smart way of avoiding issues with weakmethods
            in WeakSetMaps. It allows the GAO to be GC'd as appropriate,
            without causing problems in the Postman subscription system.
            
            Because Postman is using WeakSetMap, this also means we 
            don't need to build a __del__ system to unsubscribe, nor do
            suppression thereof at system exit. This is much, much nicer 
            than our previous strategy.
            '''
            # Note that we now have a closure around self.
            self.touch(*args, **kwargs)
        self._weak_touch = weak_touch
        
        super().__init__(*args, **kwargs)
        
        # This will only get passed if this is a NEW bootstrap object TO CREATE
        if _bootstrap is not None:
            # First, short-circuit and immediately apply a state.
            self.apply_state(_bootstrap[2])
            # Now immediately create the object, bypassing the privateer's 
            # secret lookup.
            with self.__opslock:
                self.__new(_bootstrap[1])
            # Let the accountant know that we have a new bootstrap address.
            accountant.set_bootstrap_address(_bootstrap[0], self.ghid)
            
    @classmethod
    def from_ghid(cls, ghid, golix_core, ghidproxy, privateer, 
                persistence_core, bookie, librarian, _legroom=None, 
                _bootstrap=None, accountant=None, inquisitor=None, 
                *args, **kwargs):
        ''' Loads the GAO from an existing ghid.
        
        _bootstrap allows for bypassing looking up the secret at the
        privateer.
        '''
        container_ghid = ghidproxy.resolve(ghid)
        
        # If the container ghid does not match the passed ghid, this must be a
        # dynamic object.
        dynamic = (container_ghid != ghid)
        
        packed = librarian.retrieve(container_ghid)
        secret = privateer.get(container_ghid)
        
        packed_state, author = cls._attempt_open_container(
            golix_core, privateer, secret, packed
        )
        
        self = cls(
            golix_core = golix_core, 
            ghidproxy = ghidproxy,
            privateer = privateer,
            persistence_core = persistence_core,
            bookie = bookie,
            librarian = librarian,
            dynamic = dynamic,
            _legroom = _legroom,
            _bootstrap = _bootstrap,
            accountant = accountant,
            inquisitor = inquisitor,
            *args, **kwargs
        )
        self.ghid = ghid
        self.author = author
        
        unpacked_state = self._unpack(packed_state)
        self.apply_state(unpacked_state)
        
        if dynamic:
            binding = librarian.summarize(ghid)
            self._history.extend(binding.history)
            self._history.appendleft(binding.frame_ghid)
            self._history_targets.appendleft(binding.target)
            
        # DON'T FORGET TO SET THIS!
        self._update_greenlight.set()
        
        return self
        
    def __new(self):
        ''' Creates a new Golix object for self using self._state, 
        self._dynamic, etc.
        '''
        secret = self._privateer.new_secret()
        container = self._golcore.make_container(
            self._pack(self.extract_state()), 
            secret
        )
        self._privateer.stage(container.ghid, secret)
        # Wait until successful publishing to commit the secret.
        
        try:
            if self.dynamic:
                binding = self._golcore.make_binding_dyn(target=container.ghid)
                # NOTE THAT THIS IS A GOLIX PRIMITIVE! And that therefore 
                # there's a discrepancy between ghid_dynamic and ghid.
                self.ghid = binding.ghid_dynamic
                self.author = self._golcore.whoami
                # Silence the frame address (see above) and add it to historian
                self.silence(binding.ghid)
                self._history.appendleft(binding.ghid)
                self._history_targets.appendleft(container.ghid)
                # Now assign this dynamic address as a chain owner.
                self._privateer.make_chain(self.ghid, container.ghid)
                # Finally, publish the binding and subscribe to it
                self._percore.ingest_gobd(binding)
                
            else:
                binding = self._golcore.make_binding_stat(
                    target = container.ghid
                )
                self.ghid = container.ghid
                self.author = self._golcore.whoami
                self._percore.ingest_gobs(binding)
                
            # Finally, publish the container itself.
            self._percore.ingest_geoc(container)
            
        except Exception:
            logger.error(
                'Error while creating new golix object: \n' +
                ''.join(traceback.format_exc())
            )
            # Conservatively call unstage instead of abandon
            self._privateer.unstage(container.ghid)
            raise
            
        else:
            self._privateer.commit(container.ghid)
        
        # Successful creation. Clear us for updates.
        self._update_greenlight.set()
            
    def freeze(self):
        ''' Creates a static binding for the most current state of a 
        dynamic binding. Returns the frozen ghid.
        '''
        if not self.dynamic:
            raise TypeError('Cannot freeze a static GAO.')
            
        container_ghid = self._ghidproxy.resolve(self.ghid)
        binding = self._golcore.make_binding_stat(container_ghid)
        self._percore.ingest_gobs(binding)
        
        return container_ghid
        
    def delete(self):
        ''' Attempts to permanently remove (aka debind) the object.
        ''' 
        if self.dynamic:
            debinding = self._golcore.make_debinding(self.ghid)
            self._percore.ingest_gdxx(debinding)
            
        else:
            # Get frozenset of binding ghids
            bindings = self._bookie.bind_status()
            
            for binding in bindings:
                obj = self._librarian.summarize(binding)
                if isinstance(obj, _GobsLite):
                    if obj.author == self._golcore.whoami:
                        debinding = self._golcore.make_debinding(obj.ghid)
                        self._percore.ingest_gdxx(debinding)
            
        self.apply_delete()
                
    @staticmethod
    def _attempt_open_container(golcore, privateer, secret, packed):
        try:
            # TODO: fix this leaky abstraction.
            unpacked = golcore._identity.unpack_container(packed)
            packed_state = golcore.open_container(unpacked, secret)
        
        except SecurityError:
            privateer.abandon(unpacked.ghid)
            raise
            
        else:
            privateer.commit(unpacked.ghid)
            
        return packed_state, unpacked.author
        
    def halt_updates(self):
        # TODO: this is going to create a resource leak in a race condition:
        # if we get an update while deleting, it will just sit there waiting
        # forever.
        with self.__opslock:
            self._update_greenlight.clear()
        
    def silence(self, notification):
        ''' Silence update processing for the object when the update
        notification ghid matches the frame ghid.
        
        Since this is only set up to silence one ghid at a time, this
        depends upon our local persister enforcing monotonic frame 
        progression.
        
        TODO: move all silencing into the persistence core.
        '''
        with self.__opslock:
            # Make this indempotent so we can't accidentally forget everything
            # else
            if notification not in self._silenced:
                self._silenced.appendleft(notification)
        
    def unsilence(self, notification):
        ''' Unsilence update processing for the object at the particular
        notification ghid.
        '''
        with self.__opslock:
            try:
                self._silenced.remove(notification)
            except ValueError:
                logger.debug(str(notification) + ' is missing from silenced.')
                pass
        
    @staticmethod
    def _pack(state):
        ''' Packs state into a bytes object. May be overwritten in subs
        to pack more complex objects. Should always be a staticmethod or
        classmethod.
        '''
        return state
        
    @staticmethod
    def _unpack(packed):
        ''' Unpacks state from a bytes object. May be overwritten in 
        subs to unpack more complex objects. Should always be a 
        staticmethod or classmethod.
        '''
        return packed
        
    def apply_state(self, state):
        ''' Apply the UNPACKED state to self.
        '''
        self.__state = state
        
    def extract_state(self):
        ''' Extract self into a packable state.
        '''
        return self.__state
        
    def apply_delete(self):
        ''' Executes an external delete.
        '''
        with self.__opslock:
            self._deleted = True
    
    def push(self):
        ''' Pushes updates to upstream. Must be called for every object
        mutation.
        '''
        with self.__opslock:
            if not self._deleted:
                if self.ghid is None:
                    self.__new()
                else:
                    if self.dynamic:
                        self.__update()
                    else:
                        raise TypeError('Static GAOs cannot be updated.')
            else:
                raise TypeError('Deleted GAOs cannot be pushed.')
        
    def pull(self):
        ''' Refreshes self from upstream. Should NOT be called at object 
        instantiation for any existing objects. Should instead be called
        directly, or through _weak_touch for any new status.
        '''
        with self.__opslock:
            if self._deleted:
                raise TypeError('Deleted GAOs cannot be pulled.')
                
            else:
                if self.dynamic:
                    modified = self._pull_dynamic()
                        
                else:
                    modified = self._pull_static()
        
        logger.debug('Successful pull, modified = ' + str(modified))
        return modified
        
    def _pull_dynamic(self):
        ''' Checks for the most recent update to self, regardless of 
        whatever notification was or was not received.
        '''
        # Attempt to get the notification. This SHOULD always succeed, but for
        # reasons that are increasingly difficult to diagnose, it doesn't quite
        # always go according to plan.
        try:
            # TODO: should a summary call for a dynamic ghid that has been 
            # debound return its debinding?
            summary = self._librarian.summarize(self.ghid)
        
        # Could not find the notification object. Log the error and mark it as
        # unmodified. Is this evidence of a debind coming in from upstream?
        except DoesNotExist:
            logger.error(
                'The GAO itself was unavailable while pulling an update. This '
                'is a likely indication of an upstream delete for the object, '
                'located at ' + str(self.ghid) + ', with traceback: \n' +
                ''.join(traceback.format_exc())
            )
            modified = False
        
        # We successfully retrieved the notification object, so let's handle it
        else:
            # First check to see if we're deleting the object.
            if isinstance(summary, _GdxxLite):
                modified = self._attempt_delete(summary)
                
            # This is the redundant bit. Well... maybe it isn't, if we allow 
            # for explicit pull calls, outside of just doing an update check. 
            # Anyways, now we check if it's something we already know about.
            elif summary.frame_ghid in self._history:
                modified = False
            
            # Huh, looks like it is, in fact, new.
            else:
                modified = True
                self._privateer.heal_chain(gao=self, binding=summary)
                secret = self._privateer.get(summary.target)
                packed = self._librarian.retrieve(summary.target)
                packed_state, author = self._attempt_open_container(
                    self._golcore, 
                    self._privateer, 
                    secret, 
                    packed
                )
                
                # Don't forget to extract state before applying it
                self.apply_state(self._unpack(packed_state))
                # Also don't forget to update history.
                self._advance_history(summary)
            
        return modified
        
    def _advance_history(self, new_obj):
        ''' Updates our history to match the new one.
        '''
        old_history = self._history
        # Cannot concatenate deque to list, so use extend instead
        new_history = collections.deque([new_obj.frame_ghid])
        new_history.extend(new_obj.history)
        
        right_offset = self._align_histories(old_history, new_history)
                
        # Check for a match. If right_offset == 0, there was no match, and we 
        # need to reset everything. Note: this will break any existing ratchet.
        if right_offset == 0:
            self._history.clear()
            self._history_targets.clear()
            self._history.appendleft(new_obj.frame_ghid)
            self._history_targets.appendleft(new_obj.target)
        
        # We did, in fact, find a match. Let's combine appropriately.
        else:
            # Note that deque.extendleft reverses the order of things.
            # Also note that new_history is a new, local object, so we don't
            # need to worry about accidentally affecting something else.
            new_history.reverse()
            # Note that deques don't support slicing. This is a substitute for:
            # self._history.extendleft(new_history[:right_offset])
            for __ in range(right_offset):
                new_history.popleft()
            self._history.extendleft(new_history)
            
            # Now let's create new targets. Simply populate any missing bits 
            # with None...
            new_targets = [None] * (right_offset - 1)
            # ...and then add the current target as the last item (note 
            # reversal as per above), and then extend self._history_targets.
            new_targets.append(new_obj.target)
            self._history_targets.extendleft(new_targets)
        
    @staticmethod
    def _align_histories(old_history, new_history):
        ''' Attempts to align two histories.
        '''
        jj = 0
        for ii in range(len(new_history)):
            # Check current element against offset
            if new_history[ii] == old_history[jj]:
                jj += 1
                continue
                
            # No match. Check to see if we matched the zeroth element instead.
            elif new_history[ii] == old_history[0]:
                jj = 1
                
            # No match there either. Reset.
            else:
                jj = 0
                
        return jj
            
    def _attempt_delete(self, deleter):
        ''' Attempts to apply a delete. Returns True if successful;
        False otherwise.
        '''
        if deleter.target == self.ghid:
            self.apply_delete()
            modified = True
            
        else:
            logger.warning(
                'Mismatching pull while debinding target: \n'
                '    obj.ghid:         ' + str(self.ghid) + '\n'
                '    debinding.target: ' + str(deleter.target)
            )
            modified = False
            
        return modified
        
    def _pull_static(self):
        ''' Currently, doesn't actually do anything. Just assumes that 
        our local state is correct, and returns modified=False.
        '''
        return False
        
    def touch(self, subscription, notification):
        ''' Notifies the object to check upstream for changes.
        '''
        # While we're doing this unholy abomination of half async, half
        # threaded, just spin this out into a thread to avoid async
        # deadlocks (which we'll otherwise almost certainly encounter)
        # TODO: asyncify all the things
        worker = threading.Thread(
            target = self.__touch,
            daemon = True,
            args = (subscription, notification),
            name = _generate_threadnames('gaotouch')[0],
        )
        worker.start()
            
    def __touch(self, subscription, notification):
        ''' Method to be called by self.touch from within thread.
        '''
        # First we need to wait for the update greenlight.
        self._update_greenlight.wait()
        
        # This path shouldn't happen (right?), but just in case it does...
        if notification in self._history:
            logger.debug(
                'GAO touch ignored for old frame at subscription ' + 
                str(subscription) + ' with notification ' + str(notification)
            )
            
        # Definitely-probably a new notification now
        else:
            # Attempt to get the object from the librarian.
            try:
                summary = self._librarian.summarize(notification)
            
            # Could not find the notification object. Log the error and mark it as
            # unmodified. Is this evidence of a debind coming in from upstream?
            except DoesNotExist:
                logger.error(
                    'The notification object was unavailable while pulling an '
                    'update for a dynamic gao at ' + str(self.ghid) + ' with '
                    'notification ' + str(notification) + ' and traceback:\n' +
                    ''.join(traceback.format_exc())
                )
            
            # Successfully got the object from the librarian.
            else:
                if isinstance(summary, _GdxxLite):
                    modified = self._attempt_delete(summary)
                else:
                    modified = self.pull()
                    
                logger.debug(
                    'GAO touch (modified=' + str(modified) + ') finished for '
                    'subscription ' + str(subscription) + ' at notification ' +
                    str(notification)
                )
        
    def __update(self):
        ''' Updates an existing golix object. Must already have checked
        that we 1) are dynamic, and 2) already have a ghid.
        
        If there is an error updating, this will attempt to do a pull to
        automatically roll back the current state. NOTE THAT THIS MAY
        OR MAY NOT BE THE ACTUAL CURRENT STATE!
        '''
        # Pause updates while doing this.
        self._update_greenlight.clear()
        
        # Note that, if we previously loaded this object, but didn't create it
        # through this particular contiguous hypergolix session, we will be 
        # missing a chain for it.
        
        if not self._privateer.has_chain(self.ghid):
            current_target = self._ghidproxy.resolve(self.ghid)
            self._privateer.make_chain(self.ghid, current_target)
        
        # We need a secret.
        try:
            secret = self._privateer.ratchet_chain(self.ghid)
            
        # TODO: make this a specific error.
        except Exception:
            logger.warning(
                'Failed to ratchet secret for ' + str(self.ghid) + 
                '\n' + ''.join(traceback.format_exc())
            )
            secret = self._privateer.new_secret()
            container = self._golcore.make_container(
                self._pack(self.extract_state()),
                secret
            )
            binding = self._golcore.make_binding_dyn(
                target = container.ghid,
                ghid = self.ghid,
                history = self._history
            )
            self._privateer.stage(container.ghid, secret)
            
        else:
            container = self._golcore.make_container(
                self._pack(self.extract_state()),
                secret
            )
            binding = self._golcore.make_binding_dyn(
                target = container.ghid,
                ghid = self.ghid,
                history = self._history
            )
            self._privateer.stage(container.ghid, secret)
            # And now, as everything was successful, update the ratchet
            self._privateer.update_chain(self.ghid, container.ghid)
            
        # NOTE THE DISCREPANCY between the Golix dynamic binding version
        # of ghid and ours! This is silencing the frame ghid.
        self.silence(binding.ghid)
        self._history.appendleft(binding.ghid)
        self._history_targets.appendleft(container.ghid)
                
        try:
            # Publish to persister
            self._percore.ingest_gobd(binding)
            self._percore.ingest_geoc(container)
            
        except Exception:
            # We had a problem, so we're going to forcibly restore the object
            # to the last known good state.
            logger.error(
                'Failed to update object; forcibly restoring state.\n' + 
                ''.join(traceback.format_exc())
            )
            
            # Unstage, don't abandon (just to be conservative)
            self._privateer.unstage(container.ghid)
            
            container_ghid = self._ghidproxy.resolve(self.ghid)
            secret = self._privateer.get(container_ghid)
            packed = self._librarian.retrieve(container_ghid)
            packed_state, author = self._attempt_open_container(
                self._golcore, 
                self._privateer, 
                secret, 
                packed
            )
            
            # TODO: fix these leaky abstractions.
            self.apply_state(self._unpack(packed_state))
            binding = self._librarian.summarize(self.ghid)
            # Don't forget to fix history as well
            self._advance_history(binding)
            
            # We will raise a valueerror if there's no existing chain.
            try:
                self._privateer.reset_chain(self.ghid, container_ghid)
            except ValueError:
                logger.debug('Chain missing for ' + str(self.ghid))
            
            # Re-raise the original exception that caused the update to fail
            raise
            
        else:
            self._privateer.commit(container.ghid)
            
        finally:
            # Resume accepting updates.
            self._update_greenlight.set()
            
            
class _GAOPickleBase(_GAO):
    ''' Golix-aware messagepack base object.
    '''
    def __init__(self, *args, **kwargs):
        # Include these so that we can pass *args and **kwargs to the dict
        super().__init__(*args, **kwargs)
        # Note: must be RLock, because we need to take opslock in __setitem__
        # while calling push.
        self._opslock = threading.RLock()
        
    def __eq__(self, other):
        ''' Check total equality first, and then fall back on state 
        checking.
        '''
        equal = True
        
        try:
            equal &= (self.dynamic == other.dynamic)
            equal &= (self.ghid == other.ghid)
            equal &= (self.author == other.author)
            equal &= (self._state == other._state)
            
        except AttributeError:
            equal = False
        
        return equal
        
    def pull(self, *args, **kwargs):
        with self._opslock:
            return super().pull(*args, **kwargs)
        
    def push(self, *args, **kwargs):
        with self._opslock:
            super().push(*args, **kwargs)
        
    @staticmethod
    def _pack(state):
        ''' Packs state into a bytes object. May be overwritten in subs
        to pack more complex objects. Should always be a staticmethod or
        classmethod.
        '''
        try:
            return pickle.dumps(state, protocol=4)
            
        except Exception:
            logger.error(
                'Failed to pickle the GAO w/ traceback: \n' +
                ''.join(traceback.format_exc())
            )
            raise
        
    @staticmethod
    def _unpack(packed):
        ''' Unpacks state from a bytes object. May be overwritten in 
        subs to unpack more complex objects. Should always be a 
        staticmethod or classmethod.
        '''
        try:
            return pickle.loads(packed)
            
        except Exception:
            logger.error(
                'Failed to unpickle the GAO w/ traceback: \n' +
                ''.join(traceback.format_exc())
            )
            raise
            
            
class _GAODictBase:
    ''' A golix-aware dictionary. For now at least, serializes:
            1. For every change
            2. Using pickle
    '''
    def __init__(self, *args, **kwargs):
        # Statelock needs to be an RLock, because privateer does funny stuff.
        self._statelock = threading.RLock()
        self._state = {}
        super().__init__(*args, **kwargs)
        
    def apply_state(self, state):
        ''' Apply the UNPACKED state to self.
        '''
        with self._statelock:
            self._state.clear()
            self._state.update(state)
        
    def extract_state(self):
        ''' Extract self into a packable state.
        '''
        # with self._statelock:
        # Both push and pull take the opslock, and they are the only entry 
        # points that call extract_state and apply_state, so we should be good
        # without the lock.
        return self._state
        
    def __len__(self):
        # Straight pass-through
        return len(self._state)
        
    def __iter__(self):
        for key in self._state:
            yield key
            
    def __getitem__(self, key):
        with self._statelock:
            return self._state[key]
            
    def __setitem__(self, key, value):
        with self._statelock:
            self._state[key] = value
            self.push()
            
    def __delitem__(self, key):
        with self._statelock:
            del self._state[key]
            self.push()
            
    def __contains__(self, key):
        with self._statelock:
            return key in self._state
            
    def pop(self, key, *args, **kwargs):
        with self._statelock:
            result = self._state.pop(key, *args, **kwargs)
            self.push()
            
        return result
        
    def items(self, *args, **kwargs):
        # Because the return is a view object, competing use will result in
        # python errors, so we don't really need to worry about statelock.
        return self._state.items(*args, **kwargs)
        
    def keys(self, *args, **kwargs):
        # Because the return is a view object, competing use will result in
        # python errors, so we don't really need to worry about statelock.
        return self._state.keys(*args, **kwargs)
        
    def values(self, *args, **kwargs):
        # Because the return is a view object, competing use will result in
        # python errors, so we don't really need to worry about statelock.
        return self._state_values(*args, **kwargs)
        
    def setdefault(self, key, *args, **kwargs):
        ''' Careful, need state lock.
        '''
        with self._statelock:
            if key in self._state:
                result = self._state.setdefault(key, *args, **kwargs)
            else:
                result = self._state.setdefault(key, *args, **kwargs)
                self.push()
        
        return result
        
    def get(self, *args, **kwargs):
        with self._statelock:
            return self._state.get(*args, **kwargs)
        
    def popitem(self, *args, **kwargs):
        with self._statelock:
            result = self._state.popitem(*args, **kwargs)
            self.push()
        return result
        
    def clear(self, *args, **kwargs):
        with self._statelock:
            self._state.clear(*args, **kwargs)
            self.push()
        
    def update(self, *args, **kwargs):
        with self._statelock:
            self._state.update(*args, **kwargs)
            self.push()
    
    
class _GAODict(_GAODictBase, _GAOPickleBase):
    pass
            
            
class _GAOSetBase:
    ''' A golix-aware set. For now at least, serializes:
            1. For every change
            2. Using pickle
    '''
    def __init__(self, *args, **kwargs):
        self._state = set()
        self._statelock = threading.Lock()
        super().__init__(*args, **kwargs)
        
    def apply_state(self, state):
        ''' Apply the UNPACKED state to self.
        '''
        with self._statelock:
            to_add = state - self._state
            to_remove = self._state - state
            self._state -= to_remove
            self._state |= to_add
        
    def extract_state(self):
        ''' Extract self into a packable state.
        '''
        # with self._statelock:
        # Both push and pull take the opslock, and they are the only entry 
        # points that call extract_state and apply_state, so we should be good
        # without the lock.
        return self._state
            
    def __contains__(self, key):
        with self._statelock:
            return key in self._state
        
    def __len__(self):
        # Straight pass-through
        return len(self._state)
        
    def __iter__(self):
        for key in self._state:
            yield key
            
    def add(self, elem):
        ''' Do a wee bit of checking while we're at it to avoid 
        superfluous pushing.
        '''
        with self._statelock:
            if elem not in self._state:
                self._state.add(elem)
                self.push()
                
    def remove(self, elem):
        ''' The usual. No need to check; will keyerror before pushing if
        no-op.
        '''
        with self._statelock:
            self._state.remove(elem)
            self.push()
            
    def discard(self, elem):
        ''' Do need to check for modification to prevent superfluous 
        pushing.
        '''
        with self._statelock:
            if elem in self._state:
                self._state.discard(elem)
                self.push()
            
    def pop(self):
        with self._statelock:
            result = self._state.pop()
            self.push()
            
        return result
            
    def clear(self):
        with self._statelock:
            self._state.clear()
            self.push()
            
    def isdisjoint(self, other):
        with self._statelock:
            return self._state.isdisjoint(other)
            
    def issubset(self, other):
        with self._statelock:
            return self._state.issubset(other)
            
    def issuperset(self, other):
        with self._statelock:
            return self._state.issuperset(other)
            
    def union(self, *others):
        # Note that union creates a NEW set.
        with self._statelock:
            return type(self)(
                self._golcore, 
                self._dynamic, 
                self._legroom, 
                self._state.union(*others)
            )
            
    def intersection(self, *others):
        # Note that intersection creates a NEW set.
        with self._statelock:
            return type(self)(
                self._golcore, 
                self._dynamic, 
                self._legroom, 
                self._state.intersection(*others)
            )
            
            
class _GAOSet(_GAOSetBase, _GAOPickleBase):
    pass
            
            
class _GAOSetMapBase:
    ''' A golix-aware set. For now at least, serializes:
            1. For every change
            2. Using pickle
    '''
    def __init__(self, *args, **kwargs):
        self._state = SetMap()
        self._statelock = threading.Lock()
        super().__init__(*args, **kwargs)
        
    def apply_state(self, state):
        ''' Apply the UNPACKED state to self.
        '''
        with self._statelock:
            # self._state.clear_all()
            # self._state.update()
            # Nevermind. For now, just replace the damn thing.
            self._state = state
        
    def extract_state(self):
        ''' Extract self into a packable state.
        '''
        # with self._statelock:
        # Both push and pull take the opslock, and they are the only entry 
        # points that call extract_state and apply_state, so we should be good
        # without the lock.
        return self._state
            
    def __contains__(self, key):
        with self._statelock:
            return key in self._state
        
    def __len__(self):
        # Straight pass-through
        return len(self._state)
        
    def __iter__(self):
        for key in self._state:
            yield key
    
    def __getitem__(self, key):
        ''' Pass-through to the core lookup. Will return a frozenset.
        Raises keyerror if missing.
        '''
        with self._statelock:
            return self._state[key]
        
    def get_any(self, key):
        ''' Pass-through to the core lookup. Will return a frozenset.
        Will never raise a keyerror; if key not in self, returns empty
        frozenset.
        '''
        with self._statelock:
            return self._state.get_any(key)
                
    def pop_any(self, key):
        with self._statelock:
            result = self._state.pop_any(key)
            if result:
                self.push()
            return result
        
    def contains_within(self, key, value):
        ''' Check to see if the key exists, AND the value exists at key.
        '''
        with self._statelock:
            return self._state.contains_within(key, value)
        
    def add(self, key, value):
        ''' Adds the value to the set at key. Creates a new set there if 
        none already exists.
        '''
        with self._statelock:
            # Actually do some detection to figure out if we need to push.
            if not self._state.contains_within(key, value):
                self._state.add(key, value)
                self.push()
                
    def update(self, key, value):
        ''' Updates the key with the value. Value must support being
        passed to set.update(), and the set constructor.
        '''
        # TODO: add some kind of detection of a delta to make sure this really
        # changed something
        with self._statelock:
            self._state.update(key, value)
            self.push()
        
    def remove(self, key, value):
        ''' Removes the value from the set at key. Will raise KeyError 
        if either the key is missing, or the value is not contained at
        the key.
        '''
        with self._statelock:
            # Note that this will raise a keyerror before push if nothing is 
            # going to change.
            self._state.remove(key, value)
            self.push()
        
    def discard(self, key, value):
        ''' Same as remove, but will never raise KeyError.
        '''
        with self._statelock:
            if self._state.contains_within(key, value):
                self._state.discard(key, value)
                self.push()
        
    def clear(self, key):
        ''' Clears the specified key. Raises KeyError if key is not 
        found.
        '''
        with self._statelock:
            # Note that keyerror will be raised if no delta
            self._state.clear(key)
            self.push()
            
    def clear_any(self, key):
        ''' Clears the specified key, if it exists. If not, suppresses
        KeyError.
        '''
        with self._statelock:
            if key in self._state:
                self._state.clear_any(key)
                self.push()
        
    def clear_all(self):
        ''' Clears the entire mapping.
        '''
        with self._statelock:
            self._state.clear_all()
            self.push()
            
            
class _GAOSetMap(_GAOSetMapBase, _GAOPickleBase):
    pass
