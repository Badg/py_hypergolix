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

# Control * imports. Therefore controls what is available to toplevel
# package through __init__.py
__all__ = [
    'Dispatcher', 
]

# Global dependencies
import collections
import weakref
import threading
import os
import abc
# import traceback
import warnings

from golix import Ghid

# Intra-package dependencies
from .core import _GAO
from .core import _GAODict
from .core import Oracle

# Intra-package dependencies
from .utils import _JitSetDict
from .utils import _JitDictDict

from .exceptions import DispatchError
from .exceptions import DispatchWarning
from .exceptions import HandshakeWarning
# from .exceptions import HandshakeError


# ###############################################
# Logging boilerplate
# ###############################################


import logging
logger = logging.getLogger(__name__)

        
# ###############################################
# Lib
# ###############################################

        
class DispatcherBase(metaclass=abc.ABCMeta):
    ''' Base class for dispatchers. Dispatchers handle objects; they 
    translate between raw Golix payloads and application objects, as 
    well as shepherding objects appropriately to/from/between different
    applications. Dispatchers are intended to be combined with agents,
    and vice versa.
    '''
    # def __init__(self, *args, **kwargs):
    #     super().__init__(*args, **kwargs)
        
    @abc.abstractmethod
    def dispatch_handshake(self, target):
        ''' Receives the target *object* for a handshake (note: NOT the 
        handshake itself) and dispatches it to the appropriate 
        application.
        
        handshake is a StaticObject or DynamicObject.
        Raises HandshakeError if unsuccessful.
        '''
        pass
        
    @abc.abstractmethod
    def dispatch_handshake_ack(self, ack, target):
        ''' Receives a handshake acknowledgement and dispatches it to
        the appropriate application.
        
        ack is a golix.AsymAck object.
        '''
        pass
    
    @abc.abstractmethod
    def dispatch_handshake_nak(self, nak, target):
        ''' Receives a handshake nonacknowledgement and dispatches it to
        the appropriate application.
        
        ack is a golix.AsymNak object.
        '''
        pass
        
        
class _TestDispatcher(DispatcherBase):
    ''' An dispatcher that ignores all dispatching for test purposes.
    '''
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self._orphan_shares_pending = []
        self._orphan_shares_incoming = []
        self._orphan_shares_outgoing = []
        self._orphan_shares_failed = []
        
    def dispatch_handshake(self, target):
        ''' Receives the target *object* for a handshake (note: NOT the 
        handshake itself) and dispatches it to the appropriate 
        application.
        
        handshake is a StaticObject or DynamicObject.
        Raises HandshakeError if unsuccessful.
        '''
        self._orphan_shares_incoming.append(target)
        
    def dispatch_handshake_ack(self, ack, target):
        ''' Receives a handshake acknowledgement and dispatches it to
        the appropriate application.
        
        ack is a golix.AsymAck object.
        '''
        self._orphan_shares_outgoing.append(ack)
    
    def dispatch_handshake_nak(self, nak, target):
        ''' Receives a handshake nonacknowledgement and dispatches it to
        the appropriate application.
        
        ack is a golix.AsymNak object.
        '''
        self._orphan_shares_failed.append(nak)
        
    def retrieve_recent_handshake(self):
        return self._orphan_shares_incoming.pop()
        
    def retrieve_recent_ack(self):
        return self._orphan_shares_outgoing.pop()
        
    def retrieve_recent_nak(self):
        return self._orphan_shares_failed.pop()


class Dispatcher(DispatcherBase):
    ''' A standard, working dispatcher.
    
    Objects are dispatched to endpoints based on two criteria:
    
    1. API identifiers, or
    2. Application tokens.
    
    Application tokens should never be shared, as doing so may allow for
    local phishing. The token is meant to create a private and unique 
    identifier for that application; it is specific to that particular
    agent. Objects being dispatched by token will only be usable by that
    application at that agent.
    
    API identifiers (and objects dispatched by them), however, may be 
    shared as desired. They are not necessarily specific to a particular
    application; when sharing, the originating application has no 
    guarantees that the receiving application will be the same. They 
    serve only to enforce data interoperability.
    
    Ideally, the actual agent will eventually be capable of configuring
    which applications should have access to which APIs, but currently
    anything installed is considered trusted.
    '''
    def __init__(self, core, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # TODO: remove core from self (use composition instead of inheritance).
        # TODO: weakref? Need to be able to GC. Note: weakref would break 
        # _TestDispatch in trashtest_dispatching.
        self._core = core
        # Note: worthwhile to pass _oracle as arg? Dunno yet.
        # self._oracle = oracle
        
        # Lookup for app_tokens -> endpoints. Will be specific to the current
        # state of this particular client for this agent.
        self._active_tokens = weakref.WeakValueDictionary()
        # Defining b'\x00\x00\x00\x00' will prevent using it as a token.
        self._active_tokens[b'\x00\x00\x00\x00'] = self
        # Set of all known tokens. Add b'\x00\x00\x00\x00' to prevent its use.
        # Should be made persistent across all clients for any given agent.
        self._known_tokens = set()
        self._known_tokens.add(b'\x00\x00\x00\x00')
        
        # Set of private objects for a given app_token. Will be passed to the
        # app immediately after registration.
        self._private_by_ghid = _GAODict(core=core, dynamic=True)
        
        # Lookup for api_ids -> app_tokens. Contains ONLY the apps that are 
        # currently available, because it's only used for dispatching objects
        # that are being modified while the dispatcher is running.
        self._api_ids = _JitSetDict()
        
        # Lookup for handshake ghid -> handshake object
        self._outstanding_handshakes = {}
        # Lookup for handshake ghid -> app_token, recipient
        self._outstanding_shares = {}
        
        # State lookup information
        self._oracle = Oracle(
            core = self._core,
            gao_class = _Dispatchable,
        )
        
        # Lookup for ghid -> tokens that specifically requested the ghid
        self._requestors_by_ghid = _JitSetDict()
        self._discarders_by_ghid = _JitSetDict()
        
        self._orphan_shares_incoming = set()
        self._orphan_shares_outgoing_success = []
        self._orphan_shares_outgoing_failed = []
        
        # Lookup for token -> waiting ghid -> operations
        self._pending_by_token = _JitDictDict()
        
        # Very, very quick hack to ignore updates from persisters when we're 
        # the ones who initiated the update. Simple set of ghids.
        self._ignore_subs_because_updating = set()
        
    def get_object(self, asking_token, ghid):
        ''' Gets an object by ghid for a specific endpoint. Currently 
        only works for non-private objects.
        '''
        try:
            obj = self._oracle[ghid]
        except KeyError:
            obj = self._oracle.get_object(dispatch=self, ghid=ghid)
        
        if obj.app_token != bytes(4) and obj.app_token != asking_token:
            raise DispatchError(
                'Attempted to load private object from different application.'
            )
        
        self._requestors_by_ghid[ghid].add(asking_token)
        self._discarders_by_ghid[ghid].discard(asking_token)
        
        return obj
        
    def new_object(self, asking_token, *args, **kwargs):
        ''' Creates a new object with the upstream golix provider.
        asking_token is the app_token requesting the object.
        *args and **kwargs are passed to Oracle.new_object(), which are 
            in turn passed to the _GAO_Class (probably _Dispatchable)
        ''' 
        obj = self._oracle.new_object(dispatch=self, *args, **kwargs)
        
        # If this is a private object, record it as such
        if obj.app_token != bytes(4):
            self._private_by_ghid[obj.ghid] = obj.app_token
        
        # Note: should we add some kind of mechanism to defer passing to other 
        # endpoints until we update the one that actually requested the obj?
        self.distribute_to_endpoints(
            ghid = obj.ghid, 
            skip_token = asking_token
        )
        
        return obj.ghid
        
    def update_object(self, asking_token, ghid, state):
        ''' Initiates an update of an object. Must be tied to a specific
        endpoint, to prevent issuing that endpoint a notification in 
        return.
        '''
        try:
            obj = self._oracle[ghid]
        except KeyError:
            obj = self._oracle.get_object(dispatch=self, ghid=ghid)
                
        # Try updating golix before local.
        # Temporarily silence updates from persister about the ghid we're 
        # in the process of updating
        try:
            self._ignore_subs_because_updating.add(ghid)
            obj.update(state)
        except:
            # Note: because a push() failure restores previous state, we should 
            # probably distribute it INCLUDING TO THE ASKING TOKEN if there's a 
            # push failure. TODO: think about this more.
            raise
        else:
            self.distribute_to_endpoints(ghid, skip_token=asking_token)
        finally:
            self._ignore_subs_because_updating.remove(ghid)
        
    def share_object(self, asking_token, ghid, recipient):
        ''' Do the whole super thing, and then record which application
        initiated the request, and who the recipient was.
        '''
        # First make sure we actually know the object
        try:
            obj = self._oracle[ghid]
        except KeyError:
            obj = self._oracle.get_object(dispatch=self, ghid=ghid)
            
        if obj.app_token != bytes(4):
            raise DispatchError('Cannot share a private object.')
        
        try:
            self._outstanding_shares[ghid] = (
                asking_token, 
                recipient
            )
            
            # Currently, just perform a handshake. In the future, move this 
            # to a dedicated exchange system.
            self._core.hand_ghid(ghid, recipient)
            
        except:
            del self._outstanding_shares[ghid]
            raise
        
    def freeze_object(self, asking_token, ghid):
        ''' Converts a dynamic object to a static object, returning the
        static ghid.
        '''
        try:
            obj = self._oracle[ghid]
        except KeyError:
            obj = self._oracle.get_object(dispatch=self, ghid=ghid)
        
        if not obj.dynamic:
            raise DispatchError('Cannot freeze a static object.')
            
        static_address = self._core.freeze_dynamic(
            ghid_dynamic = ghid
        )
        
        # We're going to avoid a race condition by pulling the freezed object
        # post-facto, instead of using a cache.
        self._oracle.get_object(dispatch=self, ghid=static_address)
        
        return static_address
        
    def hold_object(self, asking_token, ghid):
        ''' Binds to an address, preventing its deletion. Note that this
        will publicly identify you as associated with the address and
        preventing its deletion to any connected persistence providers.
        '''
        # TODO: add some kind of proofing here? 
        self._core.hold_ghid(ghid)
        
    def delete_object(self, asking_token, ghid):
        ''' Debinds an object, attempting to delete it. This operation
        will succeed if the persistence provider accepts the deletion,
        but that doesn't necessarily mean the object was removed. A
        warning may be issued if the object was successfully debound, 
        but other bindings are preventing its removal.
        
        NOTE THAT THIS DELETES ALL COPIES OF THE OBJECT! It will become
        subsequently unavailable to other applications using it.
        '''
        # First we need to cache the object so we can call updates.
        try:
            obj = self._oracle[ghid]
        except KeyError:
            obj = self._oracle.get_object(dispatch=self, ghid=ghid)
        
        try:
            self._ignore_subs_because_updating.add(ghid)
            self._core.delete_ghid(ghid)
        except:
            # Why is it a syntax error to have else without except?
            raise
        else:
            self._oracle.forget(ghid)
            
            # If this is a private object, remove it from record
            if obj.app_token != bytes(4):
                del self._private_by_ghid[obj.ghid]
                
        finally:
            self._ignore_subs_because_updating.remove(ghid)
        
        # Todo: check to see if this actually results in deleting the object
        # upstream.
        
        # There's only a race condition here if the object wasn't actually 
        # removed upstream.
        self.distribute_to_endpoints(
            ghid, 
            skip_token = asking_token, 
            deleted = obj
        )
        
    def discard_object(self, asking_token, ghid):
        ''' Removes the object from *only the asking application*. The
        asking_token will no longer receive updates about the object.
        However, the object itself will persist, and remain available to
        other applications. This is the preferred way to remove objects.
        '''
        # This is sorta an accidental check that we're actually tracking the
        # object. Could make it explicit I suppose.
        try:
            obj = self._oracle[ghid]
        except KeyError:
            obj = self._oracle.get_object(dispatch=self, ghid=ghid)
            
        api_id = obj.api_id
        
        # Completely discard/deregister anything we don't care about anymore.
        interested_tokens = set()
        
        if obj.app_token == bytes(4):
            interested_tokens.update(self._api_ids[api_id])
        else:
            interested_tokens.add(obj.app_token)
            
        interested_tokens.update(self._requestors_by_ghid[ghid])
        interested_tokens.difference_update(self._discarders_by_ghid[ghid])
        interested_tokens.discard(asking_token)
        
        # Now perform actual updates
        if len(interested_tokens) == 0:
            # Delete? GC? Not clear what we should do here.
            # For now, just tell the oracle to ignore it.
            self._oracle.forget(ghid)
            
        else:
            self._requestors_by_ghid[ghid].discard(asking_token)
            self._discarders_by_ghid[ghid].add(asking_token)
    
    def dispatch_share(self, ghid):
        ''' Dispatches shares that were not created via handshake.
        '''
        raise NotImplementedError('Cannot yet share without handshakes.')
        
    def dispatch_handshake(self, target):
        ''' Receives the target *object* for a handshake (note: NOT the 
        handshake itself) and dispatches it to the appropriate 
        application.
        
        handshake is a StaticObject or DynamicObject.
        Raises HandshakeError if unsuccessful.
        '''        
        # Go ahead and distribute it to the appropriate endpoints.
        self.distribute_to_endpoints(target)
        
        # Note: we should add something in here to catch issues if we can't
        # distribute to endpoints or something, so that the handshake doesn't
        # get stuck in limbo.
        
        # Note that unless we raise a HandshakeError RIGHT NOW, we'll be
        # sending an ack to the handshake, just to indicate successful receipt 
        # of the share. If the originating app wants to check for availability, 
        # well, that's currently on them. In the future, add handle for that in
        # SHARE instead of HANDSHAKE? <-- probably good idea
    
    def dispatch_handshake_ack(self, ack, target):
        ''' Receives a handshake acknowledgement and dispatches it to
        the appropriate application.
        
        ack is a golix.AsymAck object.
        '''
        # This was added in our overriden share_object
        app_token, recipient = self._outstanding_shares[target]
        del self._outstanding_shares[target]
        # Now notify just the requesting app of the successful share. Note that
        # this will also handle any missing endpoints.
        self._attempt_contact_endpoint(
            app_token, 
            'notify_share_success',
            target, 
            recipient = recipient
        )
    
    def dispatch_handshake_nak(self, nak, target):
        ''' Receives a handshake nonacknowledgement and dispatches it to
        the appropriate application.
        
        ack is a golix.AsymNak object.
        '''
        app_token, ghid, recipient = self._outstanding_shares[target]
        del self._outstanding_shares[target]
        # Now notify just the requesting app of the failed share. Note that
        # this will also handle any missing endpoints.
        self._attempt_contact_endpoint(
            app_token, 
            'notify_share_failure',
            target, 
            recipient = recipient
        )
                    
    def distribute_to_endpoints(self, ghid, skip_token=None, deleted=False):
        ''' Passes the object to all endpoints supporting its api via 
        command.
        
        If tokens to skip is defined, they will be skipped.
        tokens_to_skip isinstance iter(app_tokens)
        
        Should suppressing notifications for original creator be handled
        by the endpoint instead?
        '''
        # Create a temporary set
        callsheet = set()
        
        # If deleted, we passed the object itself.
        if deleted:
            obj = deleted
        else:
            # Not deleted? Grab the object.
            try:
                obj = self._oracle[ghid]
            except KeyError:
                obj = self._oracle.get_object(dispatch=self, ghid=ghid)
            
        # The app token is defined, so contact that endpoint (and only that 
        # endpoint) directly
        # Bypass if someone is sending us an app token we don't know about
        if obj.app_token != bytes(4) and obj.app_token in self._known_tokens:
            callsheet.add(obj.app_token)
            
        # It's not defined, so get everyone that uses that api_id
        else:
            callsheet.update(self._api_ids[obj.api_id])
            
        # Now add anyone explicitly tracking that object
        callsheet.update(self._requestors_by_ghid[ghid])
        
        # And finally, remove the skip token if present, as well as any apps
        # that have discarded the object
        callsheet.discard(skip_token)
        callsheet.difference_update(self._discarders_by_ghid[ghid])
            
        if len(callsheet) == 0:
            warnings.warn(HandshakeWarning(
                'Agent lacks application to handle app id.'
            ))
            self._orphan_shares_incoming.add(ghid)
        else:
            for token in callsheet:
                if deleted:
                    # It's mildly dangerous to do this -- what if we throw an 
                    # error in _attempt_contact_endpoint?
                    self._attempt_contact_endpoint(
                        token, 
                        'send_delete', 
                        ghid
                    )
                else:
                    # It's mildly dangerous to do this -- what if we throw an 
                    # error in _attempt_contact_endpoint?
                    self._attempt_contact_endpoint(
                        token, 
                        'notify_object', 
                        ghid, 
                        state = obj.state
                )
                
    def _attempt_contact_endpoint(self, app_token, command, ghid, *args, **kwargs):
        ''' We have a token defined for the api_id, but we don't know if
        the application is locally installed and running. Try to use it,
        and if we can't, warn and stash the object.
        '''
        if app_token not in self._known_tokens:
            raise DispatchError(
                'Agent lacks application with matching token. WARNING: object '
                'may have been discarded as a result!'
            )
        
        elif app_token not in self._active_tokens:
            warnings.warn(DispatchWarning(
                'App token currently unavailable.'
            ))
            # Add it to the (potentially jit) dict record of waiting objs, so
            # we can continue later.
            # Side note: what the fuck is this trash?
            self._pending_by_token[app_token][ghid] = (
                app_token, 
                command, 
                args, 
                kwargs
            )
            
        else:
            # This is a quick way of resolving command into the endpoint 
            # operation.
            endpoint = self._active_tokens[app_token]
            
            try:
                do_dispatch = {
                    'notify_object': endpoint.notify_object_threadsafe,
                    'send_delete': endpoint.send_delete_threadsafe,
                    'notify_share_success': endpoint.notify_share_success_threadsafe,
                    'notify_share_failure': endpoint.notify_share_failure_threadsafe,
                }[command]
            except KeyError as e:
                raise ValueError('Invalid command.') from e
                
            # TODO: fix leaky abstraction that's causing us to spit out threads
            wargs = [ghid]
            wargs.extend(args)
            worker = threading.Thread(
                target = do_dispatch,
                daemon = True,
                args = wargs,
                kwargs = kwargs,
            )
            worker.start()
    
    def register_endpoint(self, endpoint):
        ''' Registers an endpoint and all of its appdefs / APIs. If the
        endpoint has already been registered, updates it.
        
        Note: this cannot be used to create new app tokens! The token 
        must already be known to the dispatcher.
        '''
        app_token = endpoint.app_token
        # This cannot be used to create new app tokens!
        if app_token not in self._known_tokens:
            raise ValueError('Endpoint app token is unknown to dispatcher.')
        
        if app_token in self._active_tokens:
            if self._active_tokens[app_token] is not endpoint:
                raise RuntimeError(
                    'Attempt to reregister a new endpoint for the same token. '
                    'Each app token must have exactly one endpoint.'
                )
        else:
            self._active_tokens[app_token] = endpoint
        
        # Do this regardless, so that the endpoint can use this to update apis.
        for api in endpoint.apis:
            self._api_ids[api].add(app_token)
        # Note: how to handle removing api_ids?
            
    def close_endpoint(self, endpoint):
        ''' Closes this client's connection to the endpoint, meaning it
        will not be able to handle any more requests. However, does not
        (and should not) clean tokens from the api_id dict.
        '''
        del self._active_tokens[endpoint.app_token]
        
    def get_tokens(self, api_id):
        ''' Gets the local app tokens registered as capable of handling
        the passed API id.
        '''
        if api_id in self._api_ids:
            return frozenset(self._api_ids[api_id])
        else:
            raise KeyError(
                'Dispatcher does not have a token for passed api_id.'
            )
        
    def new_token(self):
        # Use a dummy api_id to force the while condition to be true initially
        token = b'\x00\x00\x00\x00'
        # Birthday paradox be damned; we can actually *enforce* uniqueness
        while token in self._known_tokens:
            token = os.urandom(4)
        # Do this right away to prevent race condition (todo: also use lock?)
        # Todo: something to make sure the token is actually being used?
        self._known_tokens.add(token)
        return token
            
            
_DispatchableState = collections.namedtuple(
    typename = '_DispatchableState',
    field_names = ('api_id', 'app_token', 'state'),
)
            
            
class _Dispatchable(_GAO):
    ''' A dispatchable object.
    '''
    def __init__(self, dispatch, api_id, app_token, state, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._dispatch = dispatch
        api_id, app_token = self._normalize_api_and_token(api_id, app_token)
        self.state = state
        self.api_id = api_id
        self.app_token = app_token
        
    def pull(self, *args, **kwargs):
        ''' Refreshes self from upstream. Should NOT be called at object 
        instantiation for any existing objects. Should instead be called
        directly, or through _weak_pull for any new status.
        '''
        # Note that, when used as a subs handler, we'll be passed our own 
        # self.ghid (as the subscription ghid) as well as the ghid for the new
        # frame (as the notification ghid)
        
        if self.dynamic:
            # State will be None if no update was applied.
            packed_state = self._core.touch_dynamic(self.ghid)
            if packed_state:
                # Don't forget to extract...
                self.apply_state(
                    self._unpack(packed_state)
                )
                self._dispatch.distribute_to_endpoints(self.ghid)
        
    @classmethod
    def _init_unpack(cls, packed):
        ''' Unpacks an initial state in from_ghid into *args, **kwargs.
        Should always be staticmethod or classmethod.
        '''
        dispatchablestate = cls._unpack(packed)
        return tuple(), {
            'api_id': dispatchablestate[0],
            'app_token': dispatchablestate[1],
            'state': dispatchablestate[2],
        }
        
    @staticmethod
    def _pack(state):
        ''' Packs state into a bytes object. May be overwritten in subs
        to pack more complex objects. Should always be a staticmethod or
        classmethod.
        '''
        version = b'\x00'
        return b'hgxd' + version + state[0] + state[1] + state[2]
        
    @staticmethod
    def _unpack(packed):
        ''' Unpacks state from a bytes object. May be overwritten in 
        subs to unpack more complex objects. Should always be a 
        staticmethod or classmethod.
        '''
        magic = packed[0:4]
        version = packed[4:5]
        
        if magic != b'hgxd':
            raise DispatchError('Object does not appear to be dispatchable.')
        if version != b'\x00':
            raise DispatchError('Incompatible dispatchable version number.')
            
        api_id = packed[5:70]
        app_token = packed[70:74]
        state = packed[74:]
        
        return _DispatchableState(api_id, app_token, state)
        
    def apply_state(self, state):
        ''' Apply the UNPACKED state to self.
        '''
        self.api_id = state[0]
        self.app_token = state[1]
        self.state = state[2]
        
    def extract_state(self):
        ''' Extract self into a packable state.
        '''
        return _DispatchableState(self.api_id, self.app_token, self.state)
            
    @staticmethod
    def _normalize_api_and_token(api_id, app_token):
        ''' Converts app_token and api_id into appropriate values from 
        what may or may not be None.
        '''
        undefined = (app_token is None and api_id is None)
        
        if undefined:
            raise DispatchError(
                'Cannot leave both app_token and api_id undefined.'
            )
            
        if app_token is None:
            app_token = bytes(4)
        else:
            # Todo: "type" check app_token.
            pass
            
        if api_id is None:
            # Todo: "type" check api_id.
            api_id = bytes(65)
        else:
            pass
            
        return api_id, app_token
        
    def update(self, state):
        ''' Wrapper to apply state that reuses api_id and app_token, and
        then call push.
        '''
        if not self.dynamic:
            raise DispatchError(
                'Object is not dynamic. Cannot update.'
            )
            
        self.apply_state(
            state = (self.api_id, self.app_token, state)
        )
        self.push()