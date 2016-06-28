'''
Scratchpad for test-based development.

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

import IPython
import unittest
import warnings
import collections
import threading
import time
import asyncio
import random
import traceback
import logging

from hypergolix.core import AgentBase
from hypergolix.core import Dispatcher

from hypergolix.persisters import MemoryPersister

from hypergolix.utils import Aengel
from hypergolix.comms import Autocomms
from hypergolix.comms import WSBasicServer
from hypergolix.comms import WSBasicClient
from hypergolix.ipc import IPCHost
from hypergolix.ipc import IPCEmbed

# from hypergolix.embeds import WebsocketsEmbed


# ###############################################
# Testing fixtures
# ###############################################


class MockCore(Dispatcher, AgentBase):
    def __init__(self, persister, *args, **kwargs):
        super().__init__(dispatcher=self, persister=persister, *args, **kwargs)
    
    
# class WebsocketsApp(WSReqResClient):
#     def __init__(self, name, *args, **kwargs):
#         req_handlers = {
#             # Parrot
#             b'!P': self.parrot,
#         }
        
#         self._name = name
#         self._incoming_counter = 0
        
#         super().__init__(
#             req_handlers = req_handlers, 
#             failure_code = b'-S', 
#             success_code = b'+S', 
#             *args, **kwargs)


# ###############################################
# Testing
# ###############################################


def _objhandler(obj):
    print('INCOMING UNSOLICITED OBJECT!')
    print(obj)
        
        
class WebsocketsIPCTrashTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.persister = MemoryPersister()
        cls.aengel = Aengel()
        
        cls.alice_core = MockCore(persister=cls.persister)
        cls.alice = Autocomms(
            autoresponder_class = IPCHost,
            autoresponder_kwargs = {'dispatch': cls.alice_core},
            connector_class = WSBasicServer,
            connector_kwargs = {
                'host': 'localhost',
                'port': 4628,
            },
            debug = True,
            aengel = cls.aengel,
        )
        
        time.sleep(.5)
        
        cls.bob_core = MockCore(persister=cls.persister)
        cls.bob = Autocomms(
            autoresponder_class = IPCHost,
            autoresponder_kwargs = {'dispatch': cls.bob_core},
            connector_class = WSBasicServer,
            connector_kwargs = {
                'host': 'localhost',
                'port': 4629,
            },
            debug = True,
            aengel = cls.aengel,
        )
        
        time.sleep(.5)
        
        cls.app1 = Autocomms(
            autoresponder_class = IPCEmbed,
            connector_class = WSBasicClient,
            connector_kwargs = {
                'host': 'localhost',
                'port': 4628,
            },
            debug = True,
            aengel = cls.aengel,
        )
        time.sleep(.5)
        cls.app1endpoint = cls.alice.any_session
        
        cls.app2 = Autocomms(
            autoresponder_class = IPCEmbed,
            connector_class = WSBasicClient,
            connector_kwargs = {
                'host': 'localhost',
                'port': 4628,
            },
            debug = True,
            aengel = cls.aengel,
        )
        time.sleep(.5)
        endpoints = set(cls.alice.sessions)
        cls.app2endpoint = list(endpoints - {cls.app1endpoint})[0]
        
        cls.__api_id = bytes(64) + b'1'
        
        # Should these be moved into a dedicated test? Probably.
        cls.app1.new_token_threadsafe()
        cls.app2.new_token_threadsafe()
        
    def test_client1(self):
        pt0 = b'I am a sexy stagnant beast.'
        pt1 = b'Hello, world?'
        pt2 = b'Hiyaback!'
        pt3 = b'Listening...'
        pt4 = b'All ears!'
        
        time.sleep(1)
        # Make sure we have an app token.
        print(self.app1.app_token)
        
        # Test whoami
        whoami = self.app1.whoami_threadsafe()
        print('whoami', whoami)
        
        # Test registering an api_id
        self.app1.register_api_threadsafe(self.__api_id, _objhandler)
        self.app2.register_api_threadsafe(self.__api_id, _objhandler)
        self.assertIn(self.__api_id, self.app1endpoint.apis)
        
        obj1 = self.app1.new_object(
            state = pt0,
            api_id = self.__api_id,
            dynamic = False
        )
        self.assertIn(obj1.address, self.persister._store)
        
        obj2 = self.app1.new_object(
            state = pt1,
            api_id = self.__api_id,
            dynamic = True
        )
        self.assertIn(obj2.address, self.persister._store)
        
        joint1 = self.app2.get_object(obj1.address)
        self.assertEqual(obj1, joint1)
        
        joint2 = self.app2.get_object(obj2.address)
        self.assertEqual(obj2, joint2)
        
        obj3 = self.app1.new_object(
            state = pt1,
            api_id = self.__api_id,
            dynamic = True
        )
        self.assertIn(obj3.address, self.persister._store)
        
        self.app1.update_object(obj3, pt2)
        joint3 = self.app2.get_object(obj3.address)
        self.assertEqual(obj3, joint3)
        
        # Note that this is calling bob's DISPATCH whoami, NOT an app whoami.
        self.app1.share_object(obj3, self.bob_core.whoami)
        self.assertIn(obj3.address, self.bob_core._orphan_shares_incoming)
        
        frozen3 = self.app1.freeze_object(obj3)
        self.assertEqual(frozen3.state, obj3.state)
        
        self.app2.hold_object(joint3)
        self.assertIn(obj3.address, self.alice_core._holdings)
        
        self.app2.discard_object(joint3)
        self.assertIn(self.app2endpoint.app_token, self.alice_core._discarders_by_ghid[obj3.address])
        self.assertTrue(joint3._inoperable)
        
        # self.assertIn(obj1.address, self.alice_core._state_by_ghid)
        
        self.app1.delete_object(obj1)
        self.assertNotIn(obj1.address, self.persister._store)
        self.assertTrue(obj1._inoperable)
        
        # --------------------------------------------------------------------
        # Comment this out if no interactivity desired
            
        # # Start an interactive IPython interpreter with local namespace, but
        # # suppress all IPython-related warnings.
        # with warnings.catch_warnings():
        #     warnings.simplefilter('ignore')
        #     IPython.embed()
        
    @classmethod
    def tearDownClass(cls):
        cls.aengel.stop()

if __name__ == "__main__":
    logging.basicConfig(filename='logs/ipchosts.log', level=logging.DEBUG)
    unittest.main()