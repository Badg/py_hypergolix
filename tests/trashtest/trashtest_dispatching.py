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

from golix import Guid

from hypergolix import AgentBase

# from hypergolix.persisters import LocalhostClient
# from hypergolix.persisters import LocalhostServer
from hypergolix.persisters import MemoryPersister

from hypergolix.core import Dispatcher

from hypergolix.utils import AppObj
# from hypergolix.utils import RawObj

from hypergolix.embeds import _TestEmbed

from hypergolix.ipc_hosts import _TestEndpoint

# from hypergolix.ipc_hosts import _EmbeddedIPC


class _TestDispatch(AgentBase, Dispatcher, _TestEmbed):
    def __init__(self, *args, **kwargs):
        super().__init__(dispatcher=self, *args, **kwargs)


# ###############################################
# Testing
# ###############################################
        
        
class TestAppObj(unittest.TestCase):
    def setUp(self):
        self.persister = MemoryPersister()
        
        self.agent1 = _TestDispatch(persister=self.persister)
        self.endpoint1 = _TestEndpoint(
            dispatch = self.agent1,
            apis = [bytes(65)]
        )
        self.agent1.register_endpoint(self.endpoint1)
        # This is fucking gross.
        self.agent1.app_token = self.endpoint1.app_token
        
        self.agent2 = _TestDispatch(persister=self.persister)
        self.endpoint2 = _TestEndpoint(
            dispatch = self.agent2,
            apis = [bytes(65)]
        )
        self.agent2.register_endpoint(self.endpoint2)
        # This is fucking gross.
        self.agent2.app_token = self.endpoint2.app_token
        
    def test_appobj(self):
        pt0 = b'I am a sexy stagnant beast.'
        pt1 = b'Hello, world?'
        pt2 = b'Hiyaback!'
        pt3 = b'Listening...'
        pt4 = b'All ears!'

        obj1 = AppObj(
            embed = self.agent1,
            state = pt0,
            api_id = bytes(65),
            private = False,
            dynamic = False
        )

        obj2 = AppObj(
            embed = self.agent1,
            state = pt1,
            api_id = bytes(65),
            private = False,
            dynamic = True
        )
        
        obj2.share(self.agent2.whoami)
        obj2.update(pt2)

        # obj1 = self.agent1.new_object(pt0, dynamic=False)
        # obj2 = self.agent1.new_object(pt1, dynamic=True)
        
        
        
        # --------------------------------------------------------------------
        # Comment this out if no interactivity desired
            
        # Start an interactive IPython interpreter with local namespace, but
        # suppress all IPython-related warnings.
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            IPython.embed()
        
    
    # def tearDown(self):
    #     self.server._halt()
        

if __name__ == "__main__":
    unittest.main()