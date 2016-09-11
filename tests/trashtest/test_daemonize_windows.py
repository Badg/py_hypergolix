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
import logging
import tempfile
import sys
import os
import time
import shutil
import pickle
import subprocess

from hypergolix._daemonize_windows import _SUPPORTED_PLATFORM

from hypergolix._daemonize_windows import Daemonizer
from hypergolix._daemonize_windows import daemonize1
from hypergolix._daemonize_windows import daemonize2
from hypergolix._daemonize_windows import _capability_check
from hypergolix._daemonize_windows import _acquire_pidfile
from hypergolix._daemonize_windows import _filial_usurpation
from hypergolix._daemonize_windows import _clean_file
from hypergolix._daemonize_windows import _NamespacePasser
from hypergolix._daemonize_windows import _fork_worker


# ###############################################
# "Paragon of adequacy" test fixtures
# ###############################################


# ###############################################
# Testing
# ###############################################
        
        
class Deamonizing_test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ''' Prep for abortability.
        '''
        cls.skip_remaining = False
    
    def setUp(self):
        ''' Add a check that a test has not called for an exit, keeping
        forks from doing a bunch of nonsense.
        '''
        if self.skip_remaining:
            raise unittest.SkipTest('Internal call to skip remaining.')
    
    @unittest.skipIf(not _SUPPORTED_PLATFORM, 'Unsupported platform.')
    def test_acquire_file(self):
        ''' Test that "locking" the pidfile worked. Platform-specific.
        '''
        with tempfile.TemporaryDirectory() as dirname:
            fpath = dirname + '/testpid.txt'
                
            self.assertFalse(os.path.exists(fpath))
            try:
                pidfile = _acquire_pidfile(fpath)
                self.assertTrue(os.path.exists(fpath))
                with self.assertRaises(SystemExit):
                    pidfile = _acquire_pidfile(fpath)
            finally:
                pidfile.close()
        
    @unittest.skipIf(not _SUPPORTED_PLATFORM, 'Unsupported platform.')
    def test_filial_usurp(self):
        ''' Test decoupling child from parent environment. Platform-
        specific.
        '''
        cwd = os.getcwd()
        
        with tempfile.TemporaryDirectory() as dirname:
            chdir = os.path.abspath(dirname)
            
            _filial_usurpation(dirname)
            self.assertEqual(os.getcwd(), dirname)
            
            os.chdir(cwd)
        
    @unittest.skipIf(not _SUPPORTED_PLATFORM, 'Unsupported platform.')
    def test_clean_file(self):
        ''' Test closing files. Platform-specific.
        '''
        # Ensure this does not raise
        _clean_file('/this/path/does/not/exist')
        with tempfile.TemporaryDirectory() as dirname:
            path = dirname + '/test.txt'
            with open(path, 'w') as f:
                pass
            self.assertTrue(os.path.exists(path))
            _clean_file(path)
            self.assertFalse(os.path.exists(path))
        
    @unittest.skipIf(not _SUPPORTED_PLATFORM, 'Unsupported platform.')
    def test_namespace_passer(self):
        ''' Test the namespace passing thingajobber.
        '''
        with _NamespacePasser() as temppath:
            self.assertTrue(os.path.exists(temppath))
            
            # Make sure we can also open and write
            with open(temppath, 'w') as f:
                f.write('hello world')
                
            tempdir = os.path.dirname(temppath)
            
        # Ensure everything was cleaned up
        self.assertFalse(os.path.exists(temppath))
        self.assertFalse(os.path.exists(tempdir))
        
    @unittest.skipIf(not _SUPPORTED_PLATFORM, 'Unsupported platform.')
    def test_fork_worker(self):
        ''' Test the worker meant to start the new process. Platform-
        specific.
        '''
        with tempfile.TemporaryDirectory() as dirname:
            ns_path = dirname + '/test'
            child_env = os.environ
            pid_file = dirname + '/pid.pid'
            invocation = '"' + sys.executable + '" -c return'
            chdir = '/'
            stdin_goto = None
            stdout_goto = None
            stderr_goto = None
            args = ('hello world', 'I am tired', 'hello Tired, I am Dad.')
            
            _fork_worker(
                ns_path, 
                child_env, 
                pid_file, 
                invocation, 
                chdir,
                stdin_goto,
                stdout_goto,
                stderr_goto,
                args
            )
            
            with open(ns_path, 'rb') as f:
                payload = pickle.load(f)
                
            self.assertEqual(payload[0], os.getpid())
            self.assertEqual(payload[1], pid_file)
            self.assertEqual(payload[2], chdir)
            self.assertEqual(payload[3], stdin_goto)
            self.assertEqual(payload[4], stdout_goto)
            self.assertEqual(payload[5], stderr_goto)
            self.assertEqual(payload[6:], args)
        
    @unittest.skipIf(not _SUPPORTED_PLATFORM, 'Unsupported platform.')
    def test_daemonize2(self):
        ''' Test respawning. Platform-specific.
        '''
        # Cache all of the stds
        stdin_fd = os.dup(0)
        stdout_fd = os.dup(1)
        stderr_fd = os.dup(2)
        
        cwd = os.getcwd()
        
        invocation = '"' + sys.executable + \
                     '" -c "import time; time.sleep(60)"'
        worker = None
        
        try:
            with _NamespacePasser() as ns_path:
                dirname = os.path.dirname(ns_path)
        
                worker = subprocess.Popen(invocation)
        
                parent = worker.pid
                pid_file = dirname + '/pid.pid'
                chdir = '/'
                stdin_goto = None
                stdout_goto = None
                stderr_goto = None
                args = ('hello world', 'I am tired', 'hello Tired, I am Dad.')
                
                pkg = (parent, pid_file, chdir, stdin_goto, stdout_goto, 
                       stderr_goto) + args
                
                with open(ns_path, 'wb') as f:
                    pickle.dump(pkg, f, protocol=-1)
                    
                os.environ['__INVOKE_DAEMON__'] = ns_path
                
                result = daemonize2()
                
                self.assertEqual(list(result), list(args))
                
        # Restore our original stdin, stdout, stderr. Do this before dir
        # cleanup or we'll get cleanup errors.
        finally:
            os.dup2(stdin_fd, 0)
            os.dup2(stdout_fd, 1)
            os.dup2(stderr_fd, 2)
            os.chdir(cwd)
            
            if worker is not None and worker.returncode is None:
                worker.terminate()
        

if __name__ == "__main__":
    from hypergolix import logutils
    logutils.autoconfig()
    
    # from hypergolix.utils import TraceLogger
    # with TraceLogger(interval=10):
    #     unittest.main()
    unittest.main()