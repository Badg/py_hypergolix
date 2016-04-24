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

from hypergolix.core import AgentBase
from hypergolix.core import Dispatcher

from hypergolix.persisters import MemoryPersister

from hypergolix.ipc_hosts import WebsocketsIPC

from hypergolix.embeds import WebsocketsEmbed


class WebsocketsHost(WebsocketsIPC, AgentBase, MemoryPersister, Dispatcher):
    def __init__(self, *args, **kwargs):
        super().__init__(dispatcher=self, dispatch=self, persister=self, *args, **kwargs)
    
    
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
        
        
class WebsocketsIPCTrashTest(unittest.TestCase):
    def setUp(self):
        self.host = WebsocketsHost(
            host = 'localhost',
            port = 4628,
            threaded = True,
            # debug = True
        )
        
        self.app1 = WebsocketsEmbed(
            host = 'ws://localhost', 
            port = 4628, 
            threaded = True,
            # debug = True
        )
        
        self.app1endpoint = list(self.host.connections.values())[0]
        
    def test_client1(self):
        time.sleep(1)
        # Make sure we have an app token.
        print(self.app1.app_token)
        
        # Test whoami
        whoami = self.app1.whoami
        print('whoami', whoami)
        
        # Test registering an api_id
        api_id = bytes(65)
        self.app1.register_api(api_id)
        self.assertIn(api_id, self.app1endpoint.apis)
        
        
        
        # --------------------------------------------------------------------
        # Comment this out if no interactivity desired
            
        # # Start an interactive IPython interpreter with local namespace, but
        # # suppress all IPython-related warnings.
        # with warnings.catch_warnings():
        #     warnings.simplefilter('ignore')
        #     IPython.embed()
        
    
    def tearDown(self):
        self.app1.halt()
        self.host.halt()
        time.sleep(1)

if __name__ == "__main__":
    unittest.main()