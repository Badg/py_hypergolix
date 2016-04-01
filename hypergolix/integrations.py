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

# Control * imports.
__all__ = [
    'EmbeddedIntegration', 
    'LocalhostIntegration'
]

# External dependencies
import abc
import msgpack
import os
import warnings

# Intrapackage dependencies
from .exceptions import HandshakeError
from .exceptions import HandshakeWarning
from .utils import AppDef


class _EndpointBase(metaclass=abc.ABCMeta):
    ''' Base class for an endpoint. Defines everything needed by the 
    Integration to communicate with an individual application.
    '''
    pass


class _IntegrationBase(metaclass=abc.ABCMeta):
    ''' Base class for a integration. Note that an integration cannot 
    exist without also being an agent. They are separated to allow 
    mixing-and-matching agent/persister/integration configurations.
    
    Could subclass _EndpointBase to ensure that we can use self as an 
    endpoint for incoming messages. To prevent spoofing risks, anything
    we'd accept this way MUST be append-only with a very limited scope.
    Or, we could just handle all of our operations directly with the 
    agent bootstrap object. Yeah, let's do that instead.
    '''
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Lookup for app_tokens -> endpoints
        self._app_tokens = {
            b'\x00\x00\x00\x00': False,
        }
        
        # Lookup for app_ids -> AppDef.
        self._app_ids = {}
        
        self._orphan_handshakes_incoming = []
        self._orphan_handshakes_outgoing = []
        
    def initiate_handshake(self, appdef, recipient):
        ''' Creates a handshake for the passed appdef with recipient.
        
        appdef isinstance AppDef
        recipient isinstance Guid
        '''
        try:
            pass 
        except (
            msgpack.exceptions.BufferFull,
            msgpack.exceptions.ExtraData,
            msgpack.exceptions.OutOfData,
            msgpack.exceptions.PackException,
            msgpack.exceptions.PackValueError
        ):
            raise
        
    def app_id_lookup(self, app_id):
        pass
        
    def dispatch_handshake(self, handshake):
        ''' Receives the target *object* for a handshake (note: NOT the 
        handshake itself) and dispatches it to the appropriate 
        application.
        
        handshake is a StaticObject or DynamicObject.
        Raises HandshakeError if unsuccessful.
        '''
        try:
            raise RuntimeError()
            
        except KeyError:
            warnings.warn(HandshakeWarning(
                'Agent lacks application to handle app id.'
            ))
            
        except (
            msgpack.exceptions.BufferFull,
            msgpack.exceptions.ExtraData,
            msgpack.exceptions.OutOfData,
            msgpack.exceptions.UnpackException,
            msgpack.exceptions.UnpackValueError
        ) as e:
            raise HandshakeError(
                'Handshake does not appear to conform to the hypergolix '
                'integration handshake procedure.'
            ) from e
            
        try:
            self._orphan_handshakes_incoming.append(handshake)
        except:
            raise
        
    def dispatch_handshake_ack(self, ack):
        ''' Receives a handshake acknowledgement and dispatches it to
        the appropriate application.
        
        ack is a golix.AsymAck object.
        '''
        self._orphan_handshakes_outgoing.append(ack)
    
    def dispatch_handshake_nak(self, nak):
        ''' Receives a handshake nonacknowledgement and dispatches it to
        the appropriate application.
        
        ack is a golix.AsymNak object.
        '''
        pass
    
    def register_application(self, app_id=None, appdef=None):
        ''' Registers an application with the integration. If appdef is
        None, will create an AppDef for the app. Must define app_id XOR
        appdef.
        
        Returns an AppDef object.
        '''
        if appdef is None and app_id is not None:
            app_token = self.new_token()
            endpoint = self.new_endpoint()
            appdef = AppDef(app_id, app_token, endpoint)
            
        elif appdef is not None and app_id is None:
            pass
            
        else:
            raise ValueError('Must specify appdef XOR app_id.')
            
        self._app_tokens[appdef.app_token] = appdef.endpoint
        self._app_ids[appdef.app_id] = appdef
        
        return appdef
        
    def new_token(self):
        # Use a dummy app_id to force the while condition to be true initially
        token = b'\x00\x00\x00\x00'
        # Birthday paradox be damned; we can actually *enforce* uniqueness
        while token in self._app_tokens:
            token = os.urandom(4)
        return token
        
    @abc.abstractmethod
    def new_endpoint(self):
        ''' Creates a new endpoint for the integration. Endpoints must
        be unique. Uniqueness must be enforced by subclasses of the
        _IntegrationBase class.
        
        Returns an Endpoint object.
        '''
        pass
    
    @property
    @abc.abstractmethod
    def address(self):
        ''' Inherited from Agent.
        '''
        pass
        
    @abc.abstractmethod
    def new_static(self, data=None, link=None):
        ''' Inherited from Agent.
        '''
        pass
        
    @abc.abstractmethod
    def new_dynamic(self, data):
        ''' Inherited from Agent.
        '''
        pass
        
    @abc.abstractmethod
    def update_dynamic(self, obj, data=None, link=None):
        ''' Inherited from Agent.
        '''
        pass
        
    @abc.abstractmethod
    def refresh_dynamic(self, obj):
        ''' Inherited from Agent.
        '''
        pass
        
    @abc.abstractmethod
    def freeze_dynamic(self, obj):
        ''' Inherited from Agent.
        '''
        pass
        
    @abc.abstractmethod
    def hold_object(self, obj):
        ''' Inherited from Agent.
        '''
        pass
        
    @abc.abstractmethod
    def delete_object(self, obj):
        ''' Inherited from Agent.
        '''
        pass
        
    @abc.abstractmethod
    def hand_object(self, obj, recipient_guid):
        ''' Inherited from Agent.
        '''
        pass
        
    @abc.abstractmethod
    def get_object(self, secret, guid):
        ''' Inherited from Agent.
        '''
        pass
        
        
class EmbeddedEndpoint(_EndpointBase):
    ''' An embedded application endpoint.
    '''
    pass
    
    
class EmbeddedIntegration(_IntegrationBase):
    def new_endpoint(self):
        ''' Creates a new endpoint for the integration. Endpoints must
        be unique. Uniqueness must be enforced by subclasses of the
        _IntegrationBase class.
        '''
        return EmbeddedEndpoint()
    
    
class LocalhostIntegration(_IntegrationBase):
    pass
    
    
class PipeIntegration(_IntegrationBase):
    pass
    
    
class FileIntegration(_IntegrationBase):
    pass