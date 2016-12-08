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

# External deps
import logging
import os

# This is only used for padding **within** encrypted containers
import random
# import weakref
# import traceback
# import threading

# from golix import SecondParty
from hashlib import sha512
from golix import Ghid
from golix import Secret
from golix import FirstParty

# Internal deps
from .hypothetical import API
from .hypothetical import public_api
from .hypothetical import fixture_noop
from .hypothetical import fixture_api

from .utils import immortal_property
from .utils import weak_property
from .utils import SetMap

from .gao import GAO
from .gao import GAOSet
from .gao import GAODict
from .gao import GAOSetMap

# from golix.utils import AsymHandshake
# from golix.utils import AsymAck
# from golix.utils import AsymNak

# Local dependencies
# from .persistence import _GarqLite
# from .persistence import _GdxxLite


# ###############################################
# Boilerplate
# ###############################################


logger = logging.getLogger(__name__)

# Control * imports.
__all__ = [
    # 'Inquisitor',
]


# ###############################################
# Library
# ###############################################


class Account(metaclass=API):
    ''' Accounts settle all sorts of stuff.
    
    TODO: move GolixCore into account. That way, everything to do with
    the private keys stays within the account, and is never directly
    accessed outside of it.
    '''
    _identity = immortal_property('__identity')
    _user_id = immortal_property('__user_id')
    
    golcore = weak_property('_golcore')
    privateer = weak_property('_privateer')
    oracle = weak_property('_oracle')
    rolodex = weak_property('_rolodex')
    dispatch = weak_property('_dispatch')
    percore = weak_property('_percore')
    librarian = weak_property('_librarian')
    salmonator = weak_property('_salmonator')
    
    @public_api
    def __init__(self, user_id, root_secret, *args, golcore, privateer, oracle,
                 rolodex, dispatch, percore, librarian, salmonator, **kwargs):
        ''' Gets everything ready for account bootstrapping.
        
        +   user_id explicitly passed with None means create a new
            Account.
        +   identity explicitly passed with None means load an existing
            account.
        +   user_id XOR identity must be passed.
        '''
        super().__init__(*args, **kwargs)
        
        if user_id is None:
            logger.info(
                'Generating a new set of private keys. Please be patient.'
            )
            self._identity = FirstParty()
            self._user_id = None
            logger.info('Private keys generated.')
        
        else:
            self._identity = None
            self._user_id = user_id
            
        self.golcore = golcore
        self.privateer = privateer
        self.oracle = oracle
        self.rolodex = rolodex
        self.dispatch = dispatch
        self.percore = percore
        self.librarian = librarian
        self.salmonator = salmonator
        
        self._root_secret = root_secret
        
    @__init__.fixture
    def __init__(self, identity, *args, **kwargs):
        ''' Lulz just ignore errytang and skip calling super!
        '''
        self._identity = identity
        
        self.privateer_persistent = {}
        self.privateer_quarantine = {}
        
        self.rolodex_pending = {}
        self.rolodex_outstanding = SetMap()
        
        self.dispatch_tokens = set()
        self.dispatch_startup = {}
        self.dispatch_private = {}
        self.dispatch_incoming = set()
        self.dispatch_orphan_acks = SetMap()
        self.dispatch_orphan_naks = SetMap()
        
    async def _inject_gao(self, gao):
        ''' Bypass the normal oracle get_object, new_object process and
        create the object directly.
        '''
        await self.salmonator.register(gao)
        await self.salmonator.attempt_pull(gao.ghid, quiet=True)
        self.oracle._lookup[gao.ghid] = gao
            
    async def bootstrap_account(self):
        ''' Used for account creation, to initialize the root node with
        its resource directory.
        '''
        if self._user_id is not None:
            logger.info('Loading the root node.')
            root_node = GAO(
                ghid = self._user_id,
                dynamic = True,
                author = None,
                legroom = 7,
                golcore = self._golcore,
                privateer = self._privateer,
                percore = self._percore,
                librarian = self._librarian,
                master_secret = self._root_secret
            )
            # And now, remove the root secret from the parent namespace. This
            # will make the root_node GAO the only live reference to the root
            # secret from within the Account.
            del self._root_secret
            await root_node._pull()
                
            # TODO: convert all of this into a smartyparser (after rewriting
            # smartyparse, that is)
            password_validator = \
                root_node[0: 64]
            password_comparator = \
                root_node[64: 128]
            
            # This comparison is timing-insensitive; improper generation will
            # be simply comparing noise to noise.
            if sha512(password_validator).digest() != password_comparator:
                logger.critical('Incorrect password.')
                raise ValueError('Incorrect password.')
            
            identity_ghid = Ghid.from_bytes(
                root_node[128: 193])
            identity_master = Secret.from_bytes(
                root_node[193: 246])
            
            privateer_persistent_ghid = Ghid.from_bytes(
                root_node[246: 311])
            privateer_persistent_master = Secret.from_bytes(
                root_node[311: 364])
            
            privateer_quarantine_ghid = Ghid.from_bytes(
                root_node[364: 429])
            privateer_quarantine_master = Secret.from_bytes(
                root_node[429: 482])
            
            secondary_manifest_ghid = Ghid.from_bytes(
                root_node[482: 547])
            secondary_manifest_master = Secret.from_bytes(
                root_node[547: 600])
                
        else:
            root_node = GAO(
                ghid = None,
                dynamic = True,
                author = None,
                legroom = 7,
                state = b'you pass butter',
                golcore = self._golcore,
                privateer = self._privateer,
                percore = self._percore,
                librarian = self._librarian,
                master_secret = self._root_secret
            )
            # And now, remove the root secret from the parent namespace. This
            # will make the root_node GAO the only live reference to the root
            # secret from within the Account.
            del self._root_secret
            # Initializing is needed to prevent losing the first frame while
            # the secret ratchet initializes
            logger.info('Allocating the root node.')
            await root_node._push()
            
            identity_ghid = None
            identity_master = self._identity.new_secret()
            
            privateer_persistent_ghid = None
            privateer_persistent_master = self._identity.new_secret()
            
            privateer_quarantine_ghid = None
            privateer_quarantine_master = self._identity.new_secret()
            
            secondary_manifest_ghid = None
            secondary_manifest_master = self._identity.new_secret()
        
        # Allocate the identity container
        #######################################################################
        # This stores the private keys
        identity_container = GAODict(
            ghid = identity_ghid,
            dynamic = True,
            author = None,
            legroom = 7,
            golcore = self._golcore,
            privateer = self._privateer,
            percore = self._percore,
            librarian = self._librarian,
            master_secret = identity_master
        )
        
        # Allocate the persistent secret store
        #######################################################################
        # This stores persistent secrets
        self.privateer_persistent = GAODict(
            ghid = privateer_persistent_ghid,
            dynamic = True,
            author = None,
            legroom = 7,
            golcore = self._golcore,
            privateer = self._privateer,
            percore = self._percore,
            librarian = self._librarian,
            master_secret = privateer_persistent_master
        )
        
        # Allocate the quarantined secret store
        #######################################################################
        # This stores quarantined secrets
        self.privateer_quarantine = GAODict(
            ghid = privateer_quarantine_ghid,
            dynamic = True,
            author = None,
            legroom = 7,
            golcore = self._golcore,
            privateer = self._privateer,
            percore = self._percore,
            librarian = self._librarian,
            master_secret = privateer_quarantine_master
        )
        
        # Allocate the secondary manifest
        #######################################################################
        # This contains references to all of the remaining account GAO objects.
        # Their secrets are stored within the persistent lookup.
        secondary_manifest = GAODict(
            ghid = secondary_manifest_ghid,
            dynamic = True,
            author = None,
            legroom = 7,
            golcore = self._golcore,
            privateer = self._privateer,
            percore = self._percore,
            librarian = self._librarian,
            master_secret = secondary_manifest_master
        )
        
        # Save/load the identity container and bootstrap golcore, privateer
        #######################################################################
        
        # Privateer can be bootstrapped with or without pulling, but it won't
        # work until after pulling. So bootstrap first, pull later.
        logger.info('Bootstrapping privateer.')
        self.privateer.bootstrap(self)
        
        # Load existing account
        if self._user_id is not None:
            logger.info('Loading identity.')
            await identity_container._pull()
            self._identity = FirstParty._from_serialized(
                identity_container.state
            )
            logger.info('Bootstrapping golcore.')
            self.golcore.bootstrap(self)
            
            logger.info('Loading persistent keystore.')
            await self.privateer_persistent._pull()

            logger.info('Loading quarantined keystore.')
            await self.privateer_quarantine._pull()
            
            logger.info('Loading secondary manifest.')
            await secondary_manifest._pull()
            
            # Rolodex
            rolodex_pending = secondary_manifest['rolodex.pending']
            rolodex_outstanding = secondary_manifest['rolodex.outstanding']
            # Dispatch
            dispatch_tokens = secondary_manifest['dispatch.tokens']
            dispatch_startup = secondary_manifest['dispatch.startup']
            dispatch_private = secondary_manifest['dispatch.private']
            dispatch_incoming = secondary_manifest['dispatch.incoming']
            dispatch_orphan_acks = secondary_manifest['dispatch.orphan_acks']
            dispatch_orphan_naks = secondary_manifest['dispatch.orphan_naks']
            
        # Save new account
        else:
            # We need an identity at to golcore before we can do anything
            logger.info('Bootstrapping golcore.')
            self.golcore.bootstrap(self)
            logger.info('Saving identity.')
            identity_container.update(self._identity._serialize())
            await identity_container.push()
            
            # Because these use a master secret, they need to be initialized,
            # or the first frame will be unrecoverable.
            logger.info('Allocating persistent keystore.')
            await self.privateer_persistent._push()
            
            logger.info('Allocating quarantined keystore.')
            await self.privateer_quarantine._push()
            
            logger.info('Allocating secondary manifest.')
            await secondary_manifest._push()
        
            logger.info('Building root node...')
            # Generate secure-random-length, pseudorandom-content padding
            logger.info('    Generating noisy padding.')
            # Note that we don't actually need CSRNG for the padding, just the
            # padding length, since the whole thing is encrypted. We could just
            # as easily fill it with zeros, but by filling it with pseudorandom
            # noise, we can remove a recognizable pattern and therefore slighly
            # hinder brute force attacks against the password.
            # While we COULD use CSRNG despite all that, entropy is a limited
            # resource, and I'd rather conserve it as much as possible.
            padding_seed = int.from_bytes(os.urandom(2), byteorder='big')
            padding_min_size = 1024
            padding_clip_mask = 0b0001111111111111
            # Clip the seed to an upper range of 13 bits, of 8191, for a
            # maximum padding length of 8191 + 1024 = 9215 bytes
            padding_len = padding_min_size + (padding_seed & padding_clip_mask)
            padding_int = random.getrandbits(padding_len * 8)
            padding = padding_int.to_bytes(length=padding_len, byteorder='big')
            
            logger.info('   Generating validator and comparator.')
            # We'll use this upon future logins to verify password correctness
            password_validator = os.urandom(64)
            password_comparator = sha512(password_validator).digest()
            
            logger.info('    Serializing primary manifest.')
            root_node.state = (password_validator +
                               password_comparator +
                               bytes(identity_container.ghid) +
                               bytes(identity_master) +
                               bytes(self.privateer_persistent.ghid) +
                               bytes(privateer_persistent_master) +
                               bytes(self.privateer_quarantine.ghid) +
                               bytes(privateer_quarantine_master) +
                               bytes(secondary_manifest.ghid) +
                               bytes(secondary_manifest_master) +
                               padding)
            
            logger.info('Saving root node.')
            await root_node.push()
            
            # Rolodex
            rolodex_pending = None
            rolodex_outstanding = None
            # Dispatch
            dispatch_tokens = None
            dispatch_startup = None
            dispatch_private = None
            dispatch_incoming = None
            dispatch_orphan_acks = None
            dispatch_orphan_naks = None
            
        # Establish the rest of the above at the various tracking agencies
        logger.info('Reticulating keystores.')
        await self._inject_gao(self.privateer_persistent)
        await self._inject_gao(self.privateer_quarantine)
        # We don't need to do this with the secondary manifest (unless we're
        # planning on adding things to it while already running, which would
        # imply an ad-hoc, on-the-fly upgrade process)
        
        #######################################################################
        #######################################################################
        # ROOT NODE CREATION (PRIMARY BOOTSTRAP) COMPLETE!
        #######################################################################
        #######################################################################
        
        # Rolodex gaos:
        self.rolodex_pending = GAODict(
            ghid = rolodex_pending,
            dynamic = True,
            author = None,
            legroom = 7,
            golcore = self._golcore,
            privateer = self._privateer,
            percore = self._percore,
            librarian = self._librarian
        )
        self.rolodex_outstanding = GAOSetMap(
            ghid = rolodex_outstanding,
            dynamic = True,
            author = None,
            legroom = 7,
            golcore = self._golcore,
            privateer = self._privateer,
            percore = self._percore,
            librarian = self._librarian
        )
        
        # Dispatch gaos:
        self.dispatch_tokens = GAOSet(
            ghid = dispatch_tokens,
            dynamic = True,
            author = None,
            legroom = 7,
            golcore = self._golcore,
            privateer = self._privateer,
            percore = self._percore,
            librarian = self._librarian
        )
        self.dispatch_startup = GAODict(
            ghid = dispatch_startup,
            dynamic = True,
            author = None,
            legroom = 7,
            golcore = self._golcore,
            privateer = self._privateer,
            percore = self._percore,
            librarian = self._librarian
        )
        self.dispatch_private = GAODict(
            ghid = dispatch_private,
            dynamic = True,
            author = None,
            legroom = 7,
            golcore = self._golcore,
            privateer = self._privateer,
            percore = self._percore,
            librarian = self._librarian
        )
        self.dispatch_incoming = GAOSet(
            ghid = dispatch_incoming,
            dynamic = True,
            author = None,
            legroom = 7,
            golcore = self._golcore,
            privateer = self._privateer,
            percore = self._percore,
            librarian = self._librarian
        )
        self.dispatch_orphan_acks = GAOSetMap(
            ghid = dispatch_orphan_acks,
            dynamic = True,
            author = None,
            legroom = 7,
            golcore = self._golcore,
            privateer = self._privateer,
            percore = self._percore,
            librarian = self._librarian
        )
        self.dispatch_orphan_naks = GAOSetMap(
            ghid = dispatch_orphan_naks,
            dynamic = True,
            author = None,
            legroom = 7,
            golcore = self._golcore,
            privateer = self._privateer,
            percore = self._percore,
            librarian = self._librarian
        )
        
        # These need not have the actual objects pulled yet
        self.rolodex.bootstrap(self)
        self.dispatch.bootstrap(self)
        
        if self._user_id is not None:
            logger.info('Restoring sharing subsystem.')
            await self.rolodex_pending._pull()
            await self.rolodex_outstanding._pull()
            
            logger.info('Restoring object dispatch.')
            await self.dispatch_tokens._pull()
            await self.dispatch_startup._pull()
            await self.dispatch_private._pull()
            await self.dispatch_incoming._pull()
            await self.dispatch_orphan_acks._pull()
            await self.dispatch_orphan_naks._pull()
        
        else:
            logger.info('Building sharing subsystem.')
            await self.rolodex_pending._push()
            await self.rolodex_outstanding._push()
            
            logger.info('Building object dispatch.')
            await self.dispatch_tokens._push()
            await self.dispatch_startup._push()
            await self.dispatch_private._push()
            await self.dispatch_incoming._push()
            await self.dispatch_orphan_acks._push()
            await self.dispatch_orphan_naks._push()
        
            logger.info('Building secondary manifest.')
            secondary_manifest['rolodex.pending'] = \
                self.rolodex_pending.ghid
            secondary_manifest['rolodex.outstanding'] = \
                self.rolodex_outstanding.ghid
            secondary_manifest['dispatch.tokens'] = \
                self.dispatch_tokens.ghid
            secondary_manifest['dispatch.startup'] = \
                self.dispatch_startup.ghid
            secondary_manifest['dispatch.private'] = \
                self.dispatch_private.ghid
            secondary_manifest['dispatch.incoming'] = \
                self.dispatch_incoming.ghid
            secondary_manifest['dispatch.orphan_acks'] = \
                self.dispatch_orphan_acks.ghid
            secondary_manifest['dispatch.orphan_naks'] = \
                self.dispatch_orphan_naks.ghid
            
            await secondary_manifest.push()
            self._user_id = root_node.ghid
        
        logger.info('Reticulating sharing subsystem.')
        await self._inject_gao(self.rolodex_pending)
        await self._inject_gao(self.rolodex_outstanding)
        
        logger.info('Reticulating object dispatch.')
        await self._inject_gao(self.dispatch_tokens)
        await self._inject_gao(self.dispatch_startup)
        await self._inject_gao(self.dispatch_private)
        await self._inject_gao(self.dispatch_incoming)
        await self._inject_gao(self.dispatch_orphan_acks)
        await self._inject_gao(self.dispatch_orphan_naks)
        
        logger.info('Account login successful.')
        
    async def flush(self):
        ''' Push changes to any modified account components.
        '''


class Accountant:
    ''' The accountant handles account meta-operations. For example,
    tracks device IDs associated with the account, for the purposes of
    making a distributed GAO locks, etc etc etc. Other uses are, for
    example, tracking which devices have handled a given incoming share,
    etc etc etc.
    '''
    pass
