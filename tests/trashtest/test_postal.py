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

import unittest
import collections
import queue
import random
import inspect
import asyncio

from loopa import NoopLoop
from loopa.utils import await_coroutine_threadsafe

from golix._getlow import GIDC

from hypergolix.librarian import LibrarianCore
from hypergolix.postal import PostalCore

from hypergolix.persistence import _GidcLite
from hypergolix.persistence import _GeocLite
from hypergolix.persistence import _GobsLite
from hypergolix.persistence import _GobdLite
from hypergolix.persistence import _GdxxLite
from hypergolix.persistence import _GarqLite

from hypergolix.exceptions import InvalidIdentity
from hypergolix.exceptions import InconsistentAuthor


# ###############################################
# Testing fixtures
# ###############################################


from _fixtures.ghidutils import make_random_ghid
from _fixtures.identities import TEST_AGENT1
from _fixtures.identities import TEST_AGENT2
from _fixtures.identities import TEST_READER1
from _fixtures.identities import TEST_READER2

# Identities
from _fixtures.remote_exchanges import gidc1
from _fixtures.remote_exchanges import gidc2
# Containers
from _fixtures.remote_exchanges import cont1_1  # Known author
from _fixtures.remote_exchanges import cont3_1  # Unknown author
# Static bindings
from _fixtures.remote_exchanges import bind1_1  # Known author
from _fixtures.remote_exchanges import bind3_1  # Unknown author
# Dynamic bindings
from _fixtures.remote_exchanges import dyn1_1a  # Known author frame 1
from _fixtures.remote_exchanges import dyn1_1b  # Known author frame 2
from _fixtures.remote_exchanges import dyn3_1a  # Unknown author frame 1
from _fixtures.remote_exchanges import dyn3_1b  # Unknown author frame 2
from _fixtures.remote_exchanges import dynF_a   # Inconsistent author frame 1
from _fixtures.remote_exchanges import dynF_b   # Inconsistent author frame 2
from _fixtures.remote_exchanges import dynF_c   # Inconsistent, unk author frm2
# Debindings
from _fixtures.remote_exchanges import debind1_1        # Consistent author
from _fixtures.remote_exchanges import debind1_F        # Inconsistent author
from _fixtures.remote_exchanges import debind3_1        # Unknown author
from _fixtures.remote_exchanges import debindR_1
from _fixtures.remote_exchanges import debindR_F
from _fixtures.remote_exchanges import debind3_TF
from _fixtures.remote_exchanges import dyndebind1_1
from _fixtures.remote_exchanges import dedebind1_1
# Requests
from _fixtures.remote_exchanges import handshake1_1     # Known recipient
from _fixtures.remote_exchanges import handshake3_1     # Unknown recipient


# Identities
gidclite1 = _GidcLite.from_golix(GIDC.unpack(gidc1))
gidclite2 = _GidcLite.from_golix(GIDC.unpack(gidc2))

# Containers
obj1 = _GeocLite.from_golix(cont1_1)
obj3 = _GeocLite.from_golix(cont3_1)

# Static bindings
sbind1 = _GobsLite.from_golix(bind1_1)
sbind3 = _GobsLite.from_golix(bind3_1)

# Dynamic bindings
dbind1a = _GobdLite.from_golix(dyn1_1a)
dbind1b = _GobdLite.from_golix(dyn1_1b)

dbind3a = _GobdLite.from_golix(dyn3_1a)
dbind3b = _GobdLite.from_golix(dyn3_1b)

dbindFa = _GobdLite.from_golix(dynF_a)
dbindFb = _GobdLite.from_golix(dynF_b)
dbindFc = _GobdLite.from_golix(dynF_c)

# Debindings
xbind1 = _GdxxLite.from_golix(debind1_1)
xbind3 = _GdxxLite.from_golix(debind3_1)
xbind1R = _GdxxLite.from_golix(debindR_1)
xbindF1 = _GdxxLite.from_golix(debind1_F)
xbindFR = _GdxxLite.from_golix(debindR_F)
xbind3TF = _GdxxLite.from_golix(debind3_TF)

xbind1d = _GdxxLite.from_golix(dyndebind1_1)
xbind1x = _GdxxLite.from_golix(dedebind1_1)

# Requests
req1 = _GarqLite.from_golix(handshake1_1)
req3 = _GarqLite.from_golix(handshake3_1)


class PostalCoreTester(PostalCore):
    ''' Add a delivery mechanism that can be checked in tests.
    '''
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._delivery_buffer = collections.deque()
        
    async def _deliver(self, subscription, notification):
        ''' Just put it into the delivery buffer.
        '''
        self._delivery_buffer.append((subscription, notification))
        
    async def get_scheduled(self):
        ''' Empty the scheduling queue.
        '''
        result = []
        while self._scheduled.qsize() > 0:
            result.append(await self._scheduled.get())
        return result


# ###############################################
# Testing
# ###############################################


@unittest.skip('DNE')
class PostalLoopingTest(unittest.TestCase):
    ''' Test the actual, real, live undertaker loop, but inject stuff
    directly into self._triage instead of using _check calls.
    '''
    
    @classmethod
    def setUpClass(cls):
        ''' Do a per-test fresh init of the undertaker, as well as the
        fixtures for both librarian and postman.
        '''
        # First prep fixtures
        cls.librarian = LibrarianCore.__fixture__()
        
        cls.undertaker = PostalCoreTester(
            reusable_loop = False,
            threaded = True,
            debug = True,
            thread_kwargs = {'name': 'postal'}
        )
        cls.postman.assemble(cls.librarian)
        
        # Start it!
        cls.postman.start()
        # And wait for init to complete to indicate loop fully started
        await_coroutine_threadsafe(
            coro = cls.postman.await_init(),
            loop = cls.postman._loop
        )
            
    @classmethod
    def tearDownClass(cls):
        # Kill the running loop.
        cls.postman.stop_threadsafe_nowait()
        
    def test_gidc(self):
        ''' Test gidc operations.
        '''
        self.librarian.RESET()
        await_coroutine_threadsafe(
            coro = self.librarian.store(gidclite1, gidc1),
            loop = self.postman._loop
        )
        
        # Gidc should never be GC'd
        await_coroutine_threadsafe(
            coro = self.undertaker._triage.put(gidclite1.ghid),
            loop = self.postman._loop
        )
        await_coroutine_threadsafe(
            coro = self.undertaker.await_idle(),
            loop = self.postman._loop
        )
        self.assertTrue(
            await_coroutine_threadsafe(
                coro = self.librarian.contains(gidclite1.ghid),
                loop = self.postman._loop
            )
        )
        
    def test_geoc(self):
        ''' Test geoc operations.
        '''
        self.librarian.RESET()
        await_coroutine_threadsafe(
            coro = self.librarian.store(obj1, cont1_1),
            loop = self.postman._loop
        )
        
        # Geoc should be GC'd if unbound.
        await_coroutine_threadsafe(
            coro = self.undertaker._triage.put(obj1.ghid),
            loop = self.postman._loop
        )
        await_coroutine_threadsafe(
            coro = self.undertaker.await_idle(),
            loop = self.postman._loop
        )
        self.assertFalse(
            await_coroutine_threadsafe(
                coro = self.librarian.contains(obj1.ghid),
                loop = self.postman._loop
            )
        )
        
        # But kept if bound.
        await_coroutine_threadsafe(
            coro = self.librarian.store(sbind1, bind1_1),
            loop = self.postman._loop
        )
        await_coroutine_threadsafe(
            coro = self.librarian.store(obj1, cont1_1),
            loop = self.postman._loop
        )
        await_coroutine_threadsafe(
            coro = self.undertaker._triage.put(obj1.ghid),
            loop = self.postman._loop
        )
        await_coroutine_threadsafe(
            coro = self.undertaker.await_idle(),
            loop = self.postman._loop
        )
        self.assertTrue(
            await_coroutine_threadsafe(
                coro = self.librarian.contains(obj1.ghid),
                loop = self.postman._loop
            )
        )
        
    def test_gobs(self):
        ''' Test gobs operations.
        '''
        self.librarian.RESET()
        self.postman.RESET()
        await_coroutine_threadsafe(
            coro = self.librarian.store(sbind1, bind1_1),
            loop = self.postman._loop
        )
        await_coroutine_threadsafe(
            coro = self.librarian.store(obj1, cont1_1),
            loop = self.postman._loop
        )
        
        # Gobs should be kept if not DEbound.
        await_coroutine_threadsafe(
            coro = self.undertaker._triage.put(sbind1.ghid),
            loop = self.postman._loop
        )
        await_coroutine_threadsafe(
            coro = self.undertaker.await_idle(),
            loop = self.postman._loop
        )
        self.assertTrue(
            await_coroutine_threadsafe(
                coro = self.librarian.contains(sbind1.ghid),
                loop = self.postman._loop
            )
        )
        # As should their targets.
        self.assertTrue(
            await_coroutine_threadsafe(
                coro = self.librarian.contains(obj1.ghid),
                loop = self.postman._loop
            )
        )
        
        # But removed otherwise.
        await_coroutine_threadsafe(
            coro = self.librarian.store(xbind1, debind1_1),
            loop = self.postman._loop
        )
        await_coroutine_threadsafe(
            coro = self.undertaker._triage.put(sbind1.ghid),
            loop = self.postman._loop
        )
        await_coroutine_threadsafe(
            coro = self.undertaker.await_idle(),
            loop = self.postman._loop
        )
        self.assertFalse(
            await_coroutine_threadsafe(
                coro = self.librarian.contains(sbind1.ghid),
                loop = self.postman._loop
            )
        )
        # As should their targets.
        self.assertFalse(
            await_coroutine_threadsafe(
                coro = self.librarian.contains(obj1.ghid),
                loop = self.postman._loop
            )
        )
        
    def test_gobd(self):
        ''' Test gobd operations.
        '''
        self.librarian.RESET()
        self.postman.RESET()
        await_coroutine_threadsafe(
            coro = self.librarian.store(dbind1a, dyn1_1a),
            loop = self.postman._loop
        )
        await_coroutine_threadsafe(
            coro = self.librarian.store(obj1, cont1_1),
            loop = self.postman._loop
        )
        
        # Gobd should be kept unless explicitly DEbound (or if also explicitly
        # bound; TODO.)
        await_coroutine_threadsafe(
            coro = self.undertaker._triage.put(dbind1a.ghid),
            loop = self.postman._loop
        )
        await_coroutine_threadsafe(
            coro = self.undertaker.await_idle(),
            loop = self.postman._loop
        )
        self.assertTrue(
            await_coroutine_threadsafe(
                coro = self.librarian.contains(dbind1a.frame_ghid),
                loop = self.postman._loop
            )
        )
        # As should their targets.
        self.assertTrue(
            await_coroutine_threadsafe(
                coro = self.librarian.contains(obj1.ghid),
                loop = self.postman._loop
            )
        )
        
        # But removed otherwise.
        await_coroutine_threadsafe(
            coro = self.librarian.store(xbind1d, dyndebind1_1),
            loop = self.postman._loop
        )
        await_coroutine_threadsafe(
            coro = self.undertaker._triage.put(dbind1a.ghid),
            loop = self.postman._loop
        )
        await_coroutine_threadsafe(
            coro = self.undertaker.await_idle(),
            loop = self.postman._loop
        )
        self.assertFalse(
            await_coroutine_threadsafe(
                coro = self.librarian.contains(dbind1a.frame_ghid),
                loop = self.postman._loop
            )
        )
        # As should their targets.
        self.assertFalse(
            await_coroutine_threadsafe(
                coro = self.librarian.contains(obj1.ghid),
                loop = self.postman._loop
            )
        )
        
    def test_gdxx(self):
        ''' Test gdxx operations.
        '''
        self.librarian.RESET()
        self.postman.RESET()
        await_coroutine_threadsafe(
            coro = self.librarian.store(xbind1, debind1_1),
            loop = self.postman._loop
        )
        
        # Gdxx should be kept if not DEbound.
        await_coroutine_threadsafe(
            coro = self.undertaker._triage.put(xbind1.ghid),
            loop = self.postman._loop
        )
        await_coroutine_threadsafe(
            coro = self.undertaker.await_idle(),
            loop = self.postman._loop
        )
        self.assertTrue(
            await_coroutine_threadsafe(
                coro = self.librarian.contains(xbind1.ghid),
                loop = self.postman._loop
            )
        )
        
        # But removed otherwise.
        await_coroutine_threadsafe(
            coro = self.librarian.store(xbind1x, dedebind1_1),
            loop = self.postman._loop
        )
        await_coroutine_threadsafe(
            coro = self.undertaker._triage.put(xbind1.ghid),
            loop = self.postman._loop
        )
        await_coroutine_threadsafe(
            coro = self.undertaker.await_idle(),
            loop = self.postman._loop
        )
        self.assertFalse(
            await_coroutine_threadsafe(
                coro = self.librarian.contains(xbind1.ghid),
                loop = self.postman._loop
            )
        )
        
    def test_garq(self):
        ''' Test garq operations.
        '''
        self.librarian.RESET()
        self.postman.RESET()
        await_coroutine_threadsafe(
            coro = self.librarian.store(req1, handshake1_1),
            loop = self.postman._loop
        )
        
        # Garq should be kept if not DEbound.
        await_coroutine_threadsafe(
            coro = self.undertaker._triage.put(req1.ghid),
            loop = self.postman._loop
        )
        await_coroutine_threadsafe(
            coro = self.undertaker.await_idle(),
            loop = self.postman._loop
        )
        self.assertTrue(
            await_coroutine_threadsafe(
                coro = self.librarian.contains(req1.ghid),
                loop = self.postman._loop
            )
        )
        
        # But removed otherwise.
        await_coroutine_threadsafe(
            coro = self.librarian.store(xbind1R, debindR_1),
            loop = self.postman._loop
        )
        await_coroutine_threadsafe(
            coro = self.undertaker._triage.put(req1.ghid),
            loop = self.postman._loop
        )
        await_coroutine_threadsafe(
            coro = self.undertaker.await_idle(),
            loop = self.postman._loop
        )
        self.assertFalse(
            await_coroutine_threadsafe(
                coro = self.librarian.contains(req1.ghid),
                loop = self.postman._loop
            )
        )


class PostalSchedulingTest(unittest.TestCase):
    ''' Test the standard UndertakerCore internal interface (_checking
    and garbage collecting).
    '''
    
    @classmethod
    def setUpClass(cls):
        cls.nooploop = NoopLoop(
            debug = True,
            threaded = True
        )
        cls.nooploop.start()
        
    @classmethod
    def tearDownClass(cls):
        # Kill the running loop.
        cls.nooploop.stop_threadsafe_nowait()
    
    def setUp(self):
        ''' Do a per-test fresh init of the undertaker, as well as the
        fixtures for both librarian and postman.
        '''
        # First prep fixtures
        self.librarian = LibrarianCore.__fixture__()
        
        self.postman = PostalCoreTester()
        self.postman.assemble(self.librarian)
        
        # Manually call loop init to create _scheduled
        await_coroutine_threadsafe(
            coro = self.postman.loop_init(),
            loop = self.nooploop._loop
        )
        
    def test_gidc(self):
        ''' Test gidc operations.
        '''
        await_coroutine_threadsafe(
            coro = self.librarian.store(gidclite1, gidc1),
            loop = self.nooploop._loop
        )
        
        # Gidc should never notify
        await_coroutine_threadsafe(
            coro = self.postman.schedule(gidclite1),
            loop = self.nooploop._loop
        )
        
        scheduled = await_coroutine_threadsafe(
            coro = self.postman.get_scheduled(),
            loop = self.nooploop._loop
        )
        self.assertTrue(len(scheduled) == 0)
        
    def test_geoc(self):
        ''' Test geoc operations.
        '''
        await_coroutine_threadsafe(
            coro = self.librarian.store(obj1, cont1_1),
            loop = self.nooploop._loop
        )
        
        # On its own, geoc should never notify
        await_coroutine_threadsafe(
            coro = self.postman.schedule(obj1),
            loop = self.nooploop._loop
        )
        
        scheduled = await_coroutine_threadsafe(
            coro = self.postman.get_scheduled(),
            loop = self.nooploop._loop
        )
        self.assertTrue(len(scheduled) == 0)
        
        # But with a deferred update...
        deferred = (dbind1a.ghid, dbind1a.frame_ghid)
        self.postman._deferred.add(obj1.ghid, deferred)
        await_coroutine_threadsafe(
            coro = self.postman.schedule(obj1),
            loop = self.nooploop._loop
        )
        
        scheduled = await_coroutine_threadsafe(
            coro = self.postman.get_scheduled(),
            loop = self.nooploop._loop
        )
        self.assertTrue(len(scheduled) == 1)
        deferred2 = scheduled.pop()
        self.assertEqual(deferred, deferred2)
        
    def test_gobs(self):
        ''' Test gobs operations.
        '''
        await_coroutine_threadsafe(
            coro = self.librarian.store(sbind1, bind1_1),
            loop = self.nooploop._loop
        )
        
        # Gobs should never notify
        await_coroutine_threadsafe(
            coro = self.postman.schedule(sbind1),
            loop = self.nooploop._loop
        )
        
        scheduled = await_coroutine_threadsafe(
            coro = self.postman.get_scheduled(),
            loop = self.nooploop._loop
        )
        self.assertTrue(len(scheduled) == 0)
        
    def test_gobd(self):
        ''' Test gobd operations.
        '''
        # Prep with dynamic binding and debinding
        await_coroutine_threadsafe(
            coro = self.librarian.store(dbind1a, dyn1_1a),
            loop = self.nooploop._loop
        )
        await_coroutine_threadsafe(
            coro = self.librarian.store(xbind1d, dyndebind1_1),
            loop = self.nooploop._loop
        )
        
        # Removal should generate a notification
        await_coroutine_threadsafe(
            coro = self.postman.schedule(dbind1a, removed=True),
            loop = self.nooploop._loop
        )
        scheduled = await_coroutine_threadsafe(
            coro = self.postman.get_scheduled(),
            loop = self.nooploop._loop
        )
        self.assertTrue(len(scheduled) == 1)
        removal = scheduled.pop()
        self.assertEqual(removal, (dbind1a.ghid, xbind1d.ghid))
        
        # Test with normal (non-delete), but missing object (should defer)
        await_coroutine_threadsafe(
            coro = self.postman.schedule(dbind1a),
            loop = self.nooploop._loop
        )
        scheduled = await_coroutine_threadsafe(
            coro = self.postman.get_scheduled(),
            loop = self.nooploop._loop
        )
        self.assertTrue(len(scheduled) == 0)
        # Note that this also resets deferred to pristine state!
        deferred = self.postman._deferred.pop_any(obj1.ghid)
        self.assertIn((dbind1a.ghid, dbind1a.frame_ghid), deferred)
        
        # Finally, test with normal (non-delete), and existant object
        await_coroutine_threadsafe(
            coro = self.librarian.store(obj1, cont1_1),
            loop = self.nooploop._loop
        )
        await_coroutine_threadsafe(
            coro = self.postman.schedule(dbind1a),
            loop = self.nooploop._loop
        )
        scheduled = await_coroutine_threadsafe(
            coro = self.postman.get_scheduled(),
            loop = self.nooploop._loop
        )
        self.assertTrue(len(scheduled) == 1)
        self.assertEqual(scheduled.pop(), (dbind1a.ghid, dbind1a.frame_ghid))
        
    def test_gdxx(self):
        ''' Test gdxx operations.
        '''
        await_coroutine_threadsafe(
            coro = self.librarian.store(xbind1, debind1_1),
            loop = self.nooploop._loop
        )
        
        # Gidc should never notify
        await_coroutine_threadsafe(
            coro = self.postman.schedule(xbind1),
            loop = self.nooploop._loop
        )
        
        scheduled = await_coroutine_threadsafe(
            coro = self.postman.get_scheduled(),
            loop = self.nooploop._loop
        )
        self.assertTrue(len(scheduled) == 0)
        
    def test_garq(self):
        ''' Test garq operations.
        '''
        # Prep with dynamic binding and debinding
        await_coroutine_threadsafe(
            coro = self.librarian.store(req1, handshake1_1),
            loop = self.nooploop._loop
        )
        await_coroutine_threadsafe(
            coro = self.librarian.store(xbind1R, debindR_1),
            loop = self.nooploop._loop
        )
        
        # Removal should generate a notification
        await_coroutine_threadsafe(
            coro = self.postman.schedule(req1, removed=True),
            loop = self.nooploop._loop
        )
        scheduled = await_coroutine_threadsafe(
            coro = self.postman.get_scheduled(),
            loop = self.nooploop._loop
        )
        self.assertTrue(len(scheduled) == 1)
        removal = scheduled.pop()
        self.assertEqual(removal, (req1.recipient, xbind1R.ghid))
        
        # As should non-removal
        await_coroutine_threadsafe(
            coro = self.postman.schedule(req1),
            loop = self.nooploop._loop
        )
        scheduled = await_coroutine_threadsafe(
            coro = self.postman.get_scheduled(),
            loop = self.nooploop._loop
        )
        self.assertTrue(len(scheduled) == 1)
        notification = scheduled.pop()
        self.assertEqual(notification, (req1.recipient, req1.ghid))


if __name__ == "__main__":
    from hypergolix import logutils
    logutils.autoconfig(loglevel='debug')
    
    # from hypergolix.utils import TraceLogger
    # with TraceLogger(interval=10):
    #     unittest.main()
    unittest.main()
