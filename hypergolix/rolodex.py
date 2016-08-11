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
import weakref
import traceback
import threading

from golix import SecondParty
from golix import Ghid

from golix.utils import AsymHandshake
from golix.utils import AsymAck
from golix.utils import AsymNak

# Local dependencies
from .persistence import _GarqLite
from .persistence import _GdxxLite


# ###############################################
# Boilerplate
# ###############################################


import logging
logger = logging.getLogger(__name__)

# Control * imports.
__all__ = [
    'Rolodex', 
]


# ###############################################
# Library
# ###############################################
            
            
_SharePair = collections.namedtuple(
    typename = '_SharePair',
    field_names = ('ghid', 'recipient'),
)


class Rolodex:
    ''' Handles sharing, requests, etc.
    
    In the future, will maintain a contacts list to approve/reject 
    incoming requests. In the further future, will maintain sharing
    pipelines, negotiated through handshakes, to perform sharing
    symmetrically between contacts.
    '''
    def __init__(self):
        self._opslock = threading.Lock()
        
        self._golcore = None
        self._privateer = None
        self._percore = None
        self._librarian = None
        self._ghidproxy = None
        self._ipccore = None
        
        # Persistent dict-like lookup for 
        # request_ghid -> (request_target, request recipient)
        self._pending_requests = None
        # Lookup for <target_obj_ghid, recipient> -> set(<app_tokens>)
        self._outstanding_shares = None
        
    def bootstrap(self, pending_requests):
        ''' Initialize distributed state.
        '''
        # Persistent dict-like lookup for 
        # request_ghid -> (request_target, request recipient)
        self._pending_requests = pending_requests
        
        # These need to be distributed but aren't yet. TODO!
        # Lookup for <target_obj_ghid, recipient> -> set(<app_tokens>)
        self._outstanding_shares = SetMap()
        
    def assemble(self, golix_core, privateer, dispatch, 
                persistence_core, librarian, ghidproxy, ipc_core):
        # Chicken, meet egg.
        self._golcore = weakref.proxy(golix_core)
        self._privateer = weakref.proxy(privateer)
        self._dispatch = weakref.proxy(dispatch)
        self._librarian = weakref.proxy(librarian)
        self._percore = weakref.proxy(persistence_core)
        self._ghidproxy = weakref.proxy(ghidproxy)
        self._ipccore = weakref.proxy(ipc_core)
        
    def share_object(self, target, recipient, requesting_token):
        ''' Share a target ghid with the recipient.
        '''
        if not isinstance(target, Ghid):
            raise TypeError(
                'target must be Ghid or similar.'
            )
        if not isinstance(recipient, Ghid):
            raise TypeError(
                'recipient must be Ghid or similar.'
            )

        sharepair = _SharePair(target, recipient)
            
        # For now, this is just doing a handshake with some typechecking.
        self._hand_object(*sharepair)
        self._outstanding_shares.add(sharepair, requesting_token)
        
    def _hand_object(self, target, recipient):
        ''' Initiates a handshake request with the recipient.
        '''
        contact = SecondParty.from_packed(
            self._librarian.retrieve(recipient)
        )
        
        # This is guaranteed to resolve the container fully.
        container_ghid = self._ghidproxy.resolve(target)
        
        with self._opslock:
            # TODO: fix Golix library so this isn't such a shitshow re:
            # breaking abstraction barriers.
            handshake = self._golcore._identity.make_handshake(
                target = target,
                secret = self._privateer.get(container_ghid)
            )
            
            request = self._identity.make_request(
                recipient = contact,
                request = handshake
            )
        
        # Note that this must be called before publishing to the persister, or
        # there's a race condition between them.
        self._pending_requests[request.ghid] = target, recipient
        
        # Note the potential race condition here. Should catch errors with the
        # persister in case we need to resolve pending requests that didn't
        # successfully post.
        self._percore.ingest_garq(request)
        
    def request_handler(self, subscription, notification):
        ''' Callback to handle any requests.
        '''
        # Note that the notification could also be a GDXX.
        request_or_debind = self._librarian.summarize(notification)
        
        if isinstance(request_or_debind, _GarqLite):
            # We literally just did a loud summary, so no need to be loud here
            packed = self._librarian.retrieve(notification)
            payload = self._golcore.open_request(packed)
            self._handle_request(payload, notification)
            
        elif isinstance(request_or_debind, _GdxxLite):
            # This case should only be relevant if we have multiple agents 
            # logged in at separate locations at the same time, processing the
            # same GARQs.
            # For now we just need to remove any pending requests for the 
            # debinding's target.
            try:
                del self._pending_requests[request_or_debind.target]
            except KeyError:
                pass
            
        else:
            raise RuntimeError(
                'Unexpected Golix primitive while listening for requests.'
            )
        
    def _handle_request(self, payload, source_ghid):
        ''' Appropriately handles a request payload.
        '''
        if isinstance(payload, AsymHandshake):
            self._handle_handshake(payload, source_ghid)
            
        elif isinstance(payload, AsymAck):
            self._handle_ack(payload)
            
        elif isinstance(payload, AsymNak):
            self._handle_nak(payload)
            
        else:
            raise RuntimeError('Encountered an unknown request type.')
            
    def _handle_handshake(self, request, source_ghid):
        ''' Handles a handshake request after reception.
        '''
        try:
            # First, we need to figure out what the actual container object's
            # address is, and then stage the secret for it.
            container_ghid = self._ghidproxy.resolve(request.target)
            self._privateer.stage(
                ghid = container_ghid, 
                secret = request.secret
            )
            
            # Note that unless we raise a HandshakeError RIGHT NOW, we'll be
            # sending an ack to the handshake, just to indicate successful 
            # receipt of the share. If the originating app wants to check for 
            # availability, well, that's currently on them. In the future, add 
            # handle for that in SHARE instead of HANDSHAKE?
            
        except Exception as exc:
            logger.error(
                'Exception encountered while handling a handshake. Returned a '
                'NAK.\n' + ''.join(traceback.format_exc())
            )
            # Erfolglos. Send a nak to whomever sent the handshake
            response_obj = self._golcore._identity.make_nak(
                target = source_ghid
            )
            
        else:
            # Success. Send an ack to whomever sent the handshake
            response_obj = self._golcore._identity.make_ack(
                target = source_ghid
            )
        
        response = self._golcore.make_request(request.author, response_obj)
        self._percore.ingest_garq(response)
            
        self.share_handler(request.target, request.author)
            
    def _handle_ack(self, request):
        ''' Handles a handshake ack after reception.
        '''
        try:
            target, recipient = self._pending_requests.pop(request.target)
        except KeyError:
            logger.error(
                'Received an ACK for an unknown origin: ' + 
                str(bytes(request.target))
            )
        else:
            self.receipt_ack_handler(target, recipient)
            
    def _handle_nak(self, request):
        ''' Handles a handshake nak after reception.
        '''
        try:
            target, recipient = self._pending_requests.pop(request.target)
        except KeyError:
            logger.error(
                'Received a NAK for an unknown origin: ' + 
                str(bytes(request.target))
            )
        else:
            self.receipt_nak_handler(target, recipient)
    
    def share_handler(self, target, sender):
        ''' Incoming share targets (well, their ghids anyways) are 
        forwarded to the _ipccore.
        
        Only separate from _handle_handshake right now because in the
        future, object sharing will be at least partly handled within 
        its own dedicated rolodex pipeline.
        '''
        call_coroutine_threadsafe(
            coro = self._share_handler(target, sender),
            loop = self._ipccore._loop
        )
        
    async def _share_handler(self, target, sender):
        ''' Wrapper to inject our share_handler into the _ipccore's 
        event loop.
        '''
        # Build a callsheet for the target.
        callsheet = await self._ipccore.make_callsheet(target)
        # Go ahead and distribute it to the appropriate endpoints.
        await self._ipccore.distribute_to_endpoints(
            self._ipccore.send_share,
            callsheet,
            target,
            sender
        )
    
    def receipt_ack_handler(self, target, recipient):
        ''' Receives a share ack from the rolodex and passes it on to 
        the application that requested the share.
        '''
        call_coroutine_threadsafe(
            coro = self._receipt_ack_handler(target, recipient),
            loop = self._ipccore._loop
        )
            
    async def _receipt_ack_handler(self, target, recipient):
        ''' Wrapper to inject our handler into the _ipccore event loop.
        '''
        sharepair = _SharePair(target, recipient)
        callsheet = self._outstanding_shares.pop_any(sharepair)
        
        # Distribute the share success to all apps that requested its delivery
        await self._ipchost._robodialer(
            self._ipchost.notify_share_success,
            target,
            recipient
        )
    
    def receipt_nak_handler(self, target, recipient):
        ''' Receives a share nak from the rolodex and passes it on to 
        the application that requested the share.
        '''
        call_coroutine_threadsafe(
            coro = self._receipt_nak_handler(target, recipient),
            loop = self._ipccore._loop
        )
            
    async def _receipt_nak_handler(self, target, recipient):
        ''' Wrapper to inject our handler into the _ipccore event loop.
        '''
        sharepair = _SharePair(target, recipient)
        callsheet = self._outstanding_shares.pop_any(sharepair)
        
        # Distribute the share failure to all apps that requested its delivery
        await self._ipchost._robodialer(
            self._ipchost.notify_share_failure,
            target,
            recipient
        )