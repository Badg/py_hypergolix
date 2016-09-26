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
import argparse
import sys
import getpass
import socket
import multiprocessing
import time
import traceback
import collections
import logging
import logging.handlers

import daemoniker
from daemoniker import Daemonizer
from daemoniker import SignalHandler1
from daemoniker import SIGTERM

# Intra-package dependencies (that require explicit imports, courtesy of
# daemonization)
from hypergolix.config import Config

from hypergolix.app import app_core


# ###############################################
# Boilerplate
# ###############################################


logger = logging.getLogger(__name__)

# Control * imports.
__all__ = [
    'start',
]


# ###############################################
# Bootstrap logging comms
# ###############################################


class _BootstrapFilter(logging.Filter):
    ''' Use multiple logging levels based on the logger, all with the
    same handler.
    '''
    
    def filter(self, record):
        # Emit anything at WARNING or higher from all loggers
        if record.levelno >= logging.WARNING:
            return True
            
        # Emit everything from bootstrapping
        elif record.name == 'hypergolix.bootstrapping':
            return True
            
        # Emit nothing else
        else:
            return False
            
            
def _await_server(port, cycle_time, timeout):
    ''' Busy wait for a logserver to be available. Raises
    socket.timeout if unavailable.
    '''
    conn_timeout = cycle_time / 2
    sleep_for = conn_timeout
    cycles = int(timeout / cycle_time)
    
    log_server = ('127.0.0.1', port)
    
    # Attempt to connect until approximately hitting the timeout
    for __ in range(cycles):
        
        try:
            socket.create_connection(log_server, conn_timeout)
            
        except socket.timeout:
            # Busy wait and try again
            time.sleep(sleep_for)
            
        else:
            break
            

def _close_server(port):
    ''' Saturates the logging server's max number of connections,
    ensuring it departs its .accept() loop.
    '''
    conn_timeout = .1
    log_server = ('127.0.0.1', port)
    
    # Attempt to connect repeatedly until we error
    while True:
        try:
            socket.create_connection(log_server, conn_timeout)
            
        except OSError:
            # OSError includes socket.timeout. This implies that the parent
            # is not receiving connections and has successfully closed.
            break
        

class _StartupReporter:
    ''' Context manager for temporary reporting of startup logging.
    '''
    
    def __init__(self, port, cycle_time=.1, timeout=30):
        ''' port determines what localhost port to contact
        '''
        self.port = port
        self.handler = None
        
        self._cycle_time = cycle_time
        self._timeout = timeout
        
    def __enter__(self):
        ''' Sets up the logging reporter.
        '''
        # Wait for the server to exist first.
        logging_port = self.port
        
        try:
            _await_server(logging_port, self._cycle_time, self._timeout)

        # No connection happened, so we should revert to a stream handler
        except socket.timeout:
            logger.warning(
                'Timeout while attempting to connect to the bootstrap ' +
                'logging server.'
            )
            logging_port = None
            
        # If we have an available server to log to, use it
        if logging_port is not None:
            self.handler = logging.handlers.SocketHandler(
                host = '127.0.0.1',
                port = logging_port
            )
            
        # Otherwise, default to sys.stdout
        else:
            self.handler = logging.StreamHandler(sys.stdout)
            self.handler.setFormatter(
                logging.Formatter(
                    'Hypergolix startup: %(message)s'
                )
            )
            
        self.handler.handleError = print
            
        # Assign a filter to chill the noise
        self.handler.addFilter(_BootstrapFilter())
        
        # Enable the handler for hypergolix.bootstrapping
        bootstrap_logger = logging.getLogger('hypergolix.bootstrapping')
        self._bootstrap_revert_level = bootstrap_logger.level
        self._bootstrap_revert_propagation = bootstrap_logger.propagate
        bootstrap_logger.setLevel(logging.INFO)
        bootstrap_logger.addHandler(self.handler)
        # If we don't do this we get two messages for everything
        bootstrap_logger.propagate = False
        
        # Enable the handler for root
        root_logger = logging.getLogger('')
        # Ensure a minimum level of WARNING
        if root_logger.level < logging.WARNING:
            self._root_revert_level = root_logger.level
            root_logger.setLevel(logging.WARNING)
        else:
            self._root_revert_level = None
        # And finally, add the handler
        root_logger.addHandler(self.handler)
        
        # Return the bootstrap_logger so it can be used.
        return bootstrap_logger
        
    def __exit__(self, exc_type, exc_value, exc_tb):
        ''' Restores the bootstrap process logging to its previous
        verbosity and removes the handler.
        '''
        try:
            root_logger = logging.getLogger('')
            bootstrap_logger = logging.getLogger('hypergolix.bootstrapping')
            
            # Well first, if we aren't cleanly exiting, report the error.
            if exc_type is not None:
                root_logger.error(
                    'Exception during startup: ' + str(exc_type) + '(' +
                    str(exc_value) + ') + \n' +
                    ''.join(traceback.format_tb(exc_tb))
                )
            
            bootstrap_logger.propagate = self._bootstrap_revert_propagation
            bootstrap_logger.setLevel(self._bootstrap_revert_level)
            if self._root_revert_level is not None:
                root_logger.setLevel(self._root_revert_level)
                
            bootstrap_logger.removeHandler(self.handler)
            root_logger.removeHandler(self.handler)
        
        finally:
            # Close the handler and, if necessary, the server
            self.handler.close()
            if isinstance(self.handler, logging.handlers.SocketHandler):
                _close_server(self.port)
        
        
def _handle_startup_connection(conn, timeout):
        try:
            # Loop forever until the connection is closed.
            while not conn.closed:
                if conn.poll(timeout):
                    try:
                        request = conn.recv()
                        print('Hypergolix startup: ' + request['msg'])
                    
                    except EOFError:
                        # Connections that ping without a body and immediately
                        # disconnect, or the end of the connection, will EOF
                        return
                        
                else:
                    # We want to break out of the parent _serve for loop.
                    raise socket.timeout(
                        'Timeout while listening to daemon startup.'
                    )
            
        finally:
            conn.close()
        
        
def _startup_listener(port, timeout):
    server_address = ('127.0.0.1', port)
    
    with multiprocessing.connection.Listener(server_address) as server:
        # Do this twice: once for the client asking "are you there?" and a
        # second time for the actual logs.
        for __ in range(2):
            with server.accept() as conn:
                _handle_startup_connection(conn, timeout)


# ###############################################
# Password stuff
# ###############################################
    
    
def _create_password():
    ''' The typical double-prompt for password creation.
    '''
    password1 = False
    password2 = True
    first_prompt = ('Please create a password for your Hypergolix account. ' +
                    'It won\'t be shown while you type. Hit enter when done:')
    second_prompt = 'And once more to check it:'
    
    while password1 != password2:
        password1 = getpass.getpass(prompt=first_prompt)
        password2 = getpass.getpass(prompt=second_prompt)
        
        first_prompt = 'Passwords do not match! Try again please:'
        
    return password1.encode('utf-8')
    
    
def _enter_password():
    ''' Single-prompt for logging in via an existing password.
    '''
    prompt = ('Please enter your Hypergolix password. It will not be shown '
              'while you type. Hit enter when done:')
    password = getpass.getpass(prompt=prompt)
    return password.encode('utf-8')
    
    
def _request_password(user_id):
    ''' Checks the user_id. If None, creates a password (with the
    infamous double-prompt). If defined, just gets it normally.
    '''
    # Create an account
    if user_id is None:
        password = _create_password()
        
    # Log in to existing account
    else:
        password = _enter_password()
        
    return password


# ###############################################
# Actionable intelligence
# ###############################################

    
def start(namespace=None):
    ''' Starts a Hypergolix daemon.
    '''
    with Daemonizer() as (is_setup, daemonizer):
        # Need these so that the second time around doesn't NameError
        user_id = None
        password = None
        pid_file = None
        parent_port = 7771
        
        if is_setup:
            with Config() as config:
                user_id = config.user_id
                password = config.password
                # Convert the path to a str
                pid_file = str(config.pid_file)
                
            if password is None:
                password = _request_password(user_id)
            
        # Daemonize. Don't strip cmd-line arguments, or we won't know to
        # continue with startup
        is_parent, user_id, password = daemonizer(pid_file, user_id, password)
         
        if is_parent:
            # Set up a logging server that we can print() to the terminal
            _startup_listener(
                port = parent_port,
                timeout = 60
            )
            #####################
            # PARENT EXITS HERE #
            #####################
                
    # Daemonized child only from here on out.
    with _StartupReporter(parent_port) as startup_logger:
        # We need to set up a signal handler ASAP
        with Config() as config:
            pid_file = str(config.pid_file)
        sighandler = SignalHandler1(pid_file)
        sighandler.start()
        
        core = app_core(user_id, password, startup_logger)

    # Wait indefinitely until signal caught.
    # TODO: literally anything smarter than this.
    try:
        while True:
            time.sleep(.5)
    except SIGTERM:
        logger.info('Caught SIGTERM. Exiting.')
    
    del core
    
    
def stop(namespace=None):
    ''' Stops the Hypergolix daemon.
    '''
    with Config() as config:
        pid_file = str(config.pid_file)
        
    daemoniker.send(pid_file, SIGTERM)


# ###############################################
# Command line stuff
# ###############################################


COMMANDS = collections.OrderedDict((
    ('start', start),
    ('stop', stop)
))


def _ingest_args(argv=None):
    ''' Parse and handle any command-line args.
    '''
    parser = argparse.ArgumentParser(
        description = 'Control the Hypergolix service.'
    )
    parser.add_argument(
        'cmd',
        action = 'store',
        type = str,
        choices = COMMANDS,
        help = 'What should we do to the daemon? Note that stop and ' +
               'restart will only work if the daemon is already running.'
    )

    args = parser.parse_args()
    return args
        

if __name__ == '__main__':
    namespace = _ingest_args()
    # Invoke the command
    COMMANDS[namespace.cmd.lower()](namespace)
