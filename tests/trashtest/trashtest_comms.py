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

from hypergolix.comms import Websocketeer
from hypergolix.comms import Websockee


class TestServer(Websocketeer):
    def __init__(self, *args, **kwargs):
        self._incoming_counter = 0
        super().__init__(*args, **kwargs)
        
    @asyncio.coroutine
    def init_connection(self, websocket, connid):
        ''' Does anything necessary to initialize a connection. Has 
        access to self.connections[connid], which will contain None.
        '''
        print('Connection established, whoeveryouare.')
        
    @asyncio.coroutine
    def producer(self, connid):
        ''' Produces anything needed to send to the connection indicated
        by connid. Must return bytes.
        
        NOTE: IF THIS IS ALWAYS SLOWER THAN THE CONSUMER, IT WILL NEVER
        RUN!
        '''
        burp = b'B' + (b'u' * random.randint(1, 14)) + b'rp'
        yield from asyncio.sleep(random.randint(1,4))
        return burp
        
    @asyncio.coroutine
    def consumer(self, msg, connid):
        ''' Consumes the msg produced by the websockets receiver 
        listening at connid.
        '''
        self._incoming_counter += 1
        print('Got message #', self._incoming_counter ,' from connection ', connid, ': ')
        print(msg)
    
    
class TestClient(Websockee):
    def __init__(self, name, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self._incoming_counter = 0
        self._name = name
        
        self.producer_thread = threading.Thread(
            target = self.producer,
            daemon = True,
        )
        self.producer_thread.start()
        self.consumer_thread = threading.Thread(
            target = self.consumer,
            daemon = True,
        )
        self.consumer_thread.start()
    
    @asyncio.coroutine
    def init_connection(self, websocket):
        ''' Does anything necessary to initialize a connection.
        '''
        print('Connection established, Rick.')
        
    def producer(self):
        ''' Produces anything needed to send to the connection. Must 
        return bytes.
        '''
        while True:
            time.sleep(random.randint(2,7))
            print(self._name, ' sending.')
            self.send(b'Goodbye, Moonman.')
        
    def consumer(self):
        ''' Consumes the msg produced by the websockets receiver 
        listening to the connection.
        '''
        while True:
            self._incoming_counter += 1
            msg = self.receive_blocking()
            print(self._name, ' got message #', self._incoming_counter ,' from serveRick: ', msg)
        
    @asyncio.coroutine
    def handle_producer_exc(self, exc):
        ''' Handles the exception (if any) created by the producer task.
        
        exc is either:
        1. the exception, if it was raised
        2. None, if no exception was encountered
        '''
        if exc is not None:
            print(repr(exc))
            traceback.print_tb(exc.__traceback__)
            raise exc
        
    @asyncio.coroutine
    def handle_listener_exc(self, exc):
        ''' Handles the exception (if any) created by the consumer task.
        
        exc is either:
        1. the exception, if it was raised
        2. None, if no exception was encountered
        '''
        if exc is not None:
            print(repr(exc))
            traceback.print_tb(exc.__traceback__)
            raise exc


# ###############################################
# Testing
# ###############################################
        
        
class WebsocketsTrashTest(unittest.TestCase):
    def setUp(self):
        self.server = TestServer(port=9317)
        self.server_thread = threading.Thread(
            target = self.server.run,
            daemon = True,
            name = 'server_thread'
        )
        self.server_thread.start()
        
        self.client1 = TestClient(
            host = 'ws://localhost', 
            port = 9317, 
            name = 'OneTrueMorty',
            threaded = True
        )
        self.client2 = TestClient(
            host = 'ws://localhost', 
            port = 9317, 
            name = 'HammerMorty',
            threaded = True
        )
        
    def test_comms(self):
        # pass
        # self.server._halt()
        
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