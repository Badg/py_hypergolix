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

Some notes:

'''

# Control * imports. Therefore controls what is available to toplevel
# package through __init__.py
__all__ = [
    'Privateer', 
]

# External dependencies
import threading
import collections


# ###############################################
# Logging boilerplate
# ###############################################


import logging
logger = logging.getLogger(__name__)

        
# ###############################################
# Lib
# ###############################################


class Privateer:
    ''' Lookup system to get secret from ghid. Threadsafe?
    '''
    def __init__(self):
        self._modlock = threading.Lock()
        self._secrets_persistent = {}
        self._secrets_staging = {}
        self._secrets = collections.ChainMap(
            self._secrets_persistent, 
            self._secrets_staging,
        )
        
    def get(self, ghid):
        ''' Get a secret for a ghid, regardless of status.
        
        Raises KeyError if secret is not present.
        '''
        try:
            with self._modlock:
                return self._secrets[ghid]
        except KeyError as exc:
            raise KeyError('Secret not found for GHID ' + str(ghid)) from exc
        
    def stage(self, ghid, secret):
        ''' Preliminarily set a secret for a ghid.
        
        If a secret is already staged for that ghid and the ghids are 
        not equal, raises ValueError.
        '''
        with self._modlock:
            if ghid in self._secrets_staging:
                if self._secrets_staging[ghid] != secret:
                    raise ValueError(
                        'Non-matching secret already staged for GHID ' + 
                        str(ghid)
                    )
            else:
                self._secrets_staging[ghid] = secret
            
    def unstage(self, ghid):
        ''' Remove a staged secret, probably due to a SecurityError.
        Returns the secret.
        '''
        with self._modlock:
            try:
                secret = self._secrets_staging.pop(ghid)
            except KeyError as exc:
                raise KeyError(
                    'No currently staged secret for GHID ' + str(ghid)
                ) from exc
        return secret
        
    def commit(self, ghid):
        ''' Store a secret "permanently". The secret must already be
        staged.
        
        Raises KeyError if ghid is not currently in staging
        
        This is indempotent; if a ghid is currently in staging AND 
        already committed, will compare the two and raise ValueError if
        they don't match.
        
        This is transactional and atomic; any errors (ex: ValueError 
        above) will return its state to the previous.
        '''
        with self._modlock:
            if ghid in self._secrets_persistent:
                self._compare_staged_to_persistent(ghid)
            else:
                try:
                    secret = self._secrets_staging.pop(ghid)
                except KeyError as exc:
                    raise KeyError(
                        'Secret not currently staged for GHID ' + str(ghid)
                    ) from exc
                else:
                    # It doesn't exist, so commit it directly.
                    self._secrets_persistent[ghid] = secret
            
    def _compare_staged_to_persistent(self, ghid):
        try:
            staged = self._secrets_staging.pop(ghid)
        except KeyError:
            # Nothing is staged. Short-circuit.
            pass
        else:
            if staged != self._secrets_persistent[ghid]:
                # Re-stage, just in case.
                self._secrets_staging[ghid] = secret
                raise ValueError(
                    'Non-matching secret already committed for GHID ' +
                    str(ghid)
                )
        
    def abandon(self, ghid, quiet=True):
        ''' Remove a secret. If quiet=True, silence any KeyErrors.
        '''
        # Short circuit any tests if quiet is enabled
        fail_test = not quiet
        
        with self._modlock:
            try:
                del self._secrets_staging[ghid]
            except KeyError as exc:
                fail_test &= True
                logger.debug('Secret not staged for GHID ' + str(ghid))
            else:
                fail_test = False
                
            try:
                del self._secrets_persistend[ghid]
            except KeyError as exc:
                fail_test &= True
                logger.debug('Secret not stored for GHID ' + str(ghid))
            else:
                fail_test = False
                
        if fail_test:
            raise KeyError('Secret not found for GHID ' + str(ghid))