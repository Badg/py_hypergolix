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
import argparse
import logging
import unittest
import sys

# ###############################################
# Testing
# ###############################################
                
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Hypergolix trashtest.')
    parser.add_argument(
        '--traceur', 
        action = 'store_true',
        help = 'Enable thorough analysis, including stack tracing. '
    )
    parser.add_argument(
        '--debug', 
        action = 'store_true',
        help = 'Currently unused.'
    )
    parser.add_argument(
        '--verbosity', 
        action = 'store',
        default = 'warning', 
        type = str,
        help = 'Specify the logging level. '
                '"debug" -> most verbose, '
                '"info" -> somewhat verbose, '
                '"warning" -> default python verbosity, '
                '"error" -> quiet.',
    )
    parser.add_argument('unittest_args', nargs='*')

    args = parser.parse_args()
    
    # Override the module-level logger definition to root
    # logger = logging.getLogger()
    # For now, log to console
    # log_handler = logging.StreamHandler()
    if args.debug or args.traceur:
        logging.basicConfig(filename='logs/full.log', level=logging.DEBUG)
        # log_handler.setLevel(logging.DEBUG)
    else:
        logging.basicConfig(filename='logs/full.log', level=logging.WARNING)
        # log_handler.setLevel(logging.WARNING)
    # logger.addHandler(log_handler)
    
    # Dammit unittest using argparse
    sys.argv[1:] = args.unittest_args
    from trashtest import *
    unittest.main()