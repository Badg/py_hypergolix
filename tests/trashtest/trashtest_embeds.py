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

from hypergolix.persisters import MemoryPersister

from hypergolix.integrations import _EmbeddedIntegration

from hypergolix.embeds import AppObj


class TestEmbed(AgentBase, MemoryPersister, _EmbeddedIntegration):
    def __init__(self, *args, **kwargs):
        super().__init__(persister=self, integration=self, *args, **kwargs)


# ###############################################
# Testing
# ###############################################
        
        
class TestAppObj(unittest.TestCase):
    def setUp(self):
        self.agent1 = TestEmbed()
        
    def test_appobj(self):
        pt0 = b'I am a sexy stagnant beast.'
        pt1 = b'Hello, world?'
        pt2 = b'Hiyaback!'
        pt3 = b'Listening...'
        pt4 = b'All ears!'

        obj1 = AppObj(
            embed = self.agent1,
            state = pt0,
            dynamic = False
        )

        # obj1 = self.agent1.new_object(pt0, dynamic=False)
        # obj2 = self.agent1.new_object(pt1, dynamic=True)
        
        
        
        # --------------------------------------------------------------------
        # Comment this out if no interactivity desired
            
        # # Start an interactive IPython interpreter with local namespace, but
        # # suppress all IPython-related warnings.
        # with warnings.catch_warnings():
        #     warnings.simplefilter('ignore')
        #     IPython.embed()
        
    
    # def tearDown(self):
    #     self.server._halt()
        

if __name__ == "__main__":
    unittest.main()