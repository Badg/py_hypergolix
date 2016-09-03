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

This was written with heavy consultation of the following resources:
    Chad J. Schroeder, Creating a daemon the Python way (Python recipe) 
        http://code.activestate.com/recipes/
        278731-creating-a-daemon-the-python-way/
    Ilya Otyutskiy, Daemonize
        https://github.com/thesharp/daemonize
    David Mytton, unknown, et al: A simple daemon in Python
        http://www.jejik.com/articles/2007/02/
        a_simple_unix_linux_daemon_in_python/www.boxedice.com
    
'''

# Global dependencies
import os
import sys
import signal
import logging
import atexit
import traceback
import shutil

# Intra-package dependencies
from .utils import platform_specificker

_SUPPORTED_PLATFORM = platform_specificker(
    linux_choice = True,
    win_choice = False,
    cygwin_choice = False,
    osx_choice = True,
    # Dunno if this is a good idea but might as well try
    other_choice = True
)

if _SUPPORTED_PLATFORM:
    import fcntl
    import pwd
    import grp
    import resource


# ###############################################
# Boilerplate
# ###############################################


import logging
logger = logging.getLogger(__name__)

# Control * imports.
__all__ = [
    # 'Inquisitor', 
]


# ###############################################
# Library
# ###############################################


class Daemonizer:
    ''' Gets ready to create a daemon, and then exposes utilities to 
    actually start one.
    '''
    def __init__(self, pid_file, fd_check_limit=1024):
        self.pid_file = pid_file
        
        # Get /dev/null if overridden
        if hasattr(os, "devnull"):
            # Python may set a different devnull than /dev/null; prefer it to 
            # /dev/null.
            devnull = os.devnull
        else:
            devnull = "/dev/null"
        
        # Redirect stdin, stdout, stderr to here. None -> dev/null.
        self._stdin_goto = _default_to(None, devnull)
        self._stdout_goto = _default_to(None, devnull)
        self._stderr_goto = _default_to(None, devnull)
        
        self._fdchecklimit = fd_check_limit
        self._forknum = 1
        self._use_dir = '.'
            
        # This will allow owner to set any permissions.
        # This will prevent group from setting write permission
        # This will prevent other from setting any permission
        # See https://en.wikipedia.org/wiki/Umask
        self._umask = 0o027
        
        # These file descriptors will be shielded from autoclosure
        self._shielded = {}
        
    def daemonize(self):
        ''' Unix double-fork to prevent zombie daemon. Because the immediate 
        parent is already dead, the unix init then takes over responsibility
        for killing the resulting daemon.
        '''
        # Get a lock on the PIDfile before forking anything.
        self._lock_pidfile()
        # Register this as soon as possible in case something goes wrong.
        atexit.register(self._cleanup)
        # Note that because fratricidal fork is calling os._exit(), our parents
        # will never call cleanup.
        
        # Now fork the toplevel parent, killing it.
        self._fratricidal_fork()
        
        # We're now running from within the child. We need to detach ourself 
        # from the parent environment.
        self._filial_usurpation()
        
        # Okay, re-fork (no zombies!) and continue business as usual
        self._fratricidal_fork()
            
        # What's on the label
        self._write_pid()
        self._autoclose_files()
        self._std_redirect()
        
        # Should this be advanced to just after forking?
        signal.signal(signal.SIGTERM, self._handle_sigterm)
        
    def _write_pid(self):
        ''' If our PID file doesn't contain a value, write our PID 
        there.
        '''
        self._locked_pid.seek(0)
        self._locked_pid.truncate(0)
        pid = str(os.getpid())
        self._locked_pid.write(pid + '\n')
        self._locked_pid.flush()
        
    def _autoclose_files(self):
        ''' Automatically close any open file descriptors.
        '''
        # Figure out the maximum number of files to try to close.
        # This returns a tuple of softlimit, hardlimit; the hardlimit is always
        # greater.
        softlimit, hardlimit = resource.getrlimit(resource.RLIMIT_NOFILE)
        
        # If the hard limit is infinity, we can't iterate to it.
        if hardlimit == resource.RLIM_INFINITY:
            # Check the soft limit. If it's also infinity, fallback to guess.
            if softlimit == resource.RLIM_INFINITY:
                fdlimit = self._fdchecklimit
                
            # The soft limit is finite, so fallback to that.
            else:
                fdlimit = softlimit
                
        # The hard limit is not infinity, so prefer it.
        else:
            fdlimit = hardlimit
        
        # Skip fd 0, 1, 2, which are used by stdin, stdout, and stderr 
        # (respectively)
        # NOTE BUG! This ignores shielded fds!
        # How nice of os to include this for us!
        os.closerange(3, fdlimit)
                    
    def _lock_pidfile(self):
        ''' Gets a lock for the PIDfile. This ensures that only one 
        instance of this particular daemon is running at any given time.
        '''
        # We're going to switch modes depending on if the file exists or not.
        # Normally I'd open it as append, BUT saw this note in the python docs:
        # "which on some Unix systems, means that all writes append to the end 
        # of the file regardless of the current seek position"
        try:
            if os.path.isfile(self.pid_file):
                logger.warning(
                    'PID file already exists. It will be overwritten with the '
                    'new PID upon successful daemonization.'
                )
                self._locked_pid = open(self.pid_file, 'r+')
            else:
                self._locked_pid = open(self.pid_file, 'w+')
                
        except (IOError, OSError):
            logger.critical(
                'Unable to create/open the PID file w/ traceback: \n' + 
                ''.join(traceback.format_exc())
            )
            sys.exit(1)
            
        # Acquire an exclusive lock. Do not block to acquire it. Failure will 
        # raise an OSError (older versions raised IOError?).
        try:
            # Note that the flock(2) manpage states the lock will be released
            # when all open file descriptors of it are closed.
            fcntl.flock(self._locked_pid, fcntl.LOCK_EX | fcntl.LOCK_NB)
            
        except (IOError, OSError):
            logger.critical(
                'Unable to lock the PID file w/ traceback: \n' + 
                ''.join(traceback.format_exc())
            )
            sys.exit(1)
            
        # If we've been successful, protect the self._locked_pid from closure.
        # Note that forking inherits file descriptors, so this can safely be
        # called before forking.
        self._shielded.add(self._locked_pid.fileno())
        
    def _stds_flush(self):
        ''' Flush stdout and stderr.
        '''
        try:
            sys.stdout.flush()
        except BlockingIOError:
            logger.error(
                'Failed to flush stdout w/ traceback: \n' + 
                ''.join(traceback.format_exc())
            )
            # Honestly not sure if we should exit here.
        
        try:
            sys.stderr.flush()
        except BlockingIOError:
            logger.error(
                'Failed to flush stderr w/ traceback: \n' + 
                ''.join(traceback.format_exc())
            )
            # Honestly not sure if we should exit here.
                    
    def _std_redirect(self):
        ''' Set stdin, stdout, sterr
        '''
        # The general strategy here is to:
        # 1. figure out which unique paths we need to open for the redirects
        # 2. figure out the minimum access we need to open them with
        # 3. open the files to get them a file descriptor
        # 4. copy those file descriptors into the FD's used for stdio, etc
        # 5. close the original file descriptors
        
        # Remove repeated values through a set.
        streams = set([self._stdin_goto, self._stdout_goto, self._stderr_goto])
        # Transform that into a dictionary of {location: 0, location: 0...}
        # Basically, start from zero permissions
        streams = {stream: 0 for stream in streams}
        # And now create a bitmask for each of reading and writing
        read_mask = 0b01
        write_mask = 0b10
        rw_mask = 0b11
        # Update the streams dict depending on what access each stream requires
        streams[self._stdin_goto] |= read_mask
        streams[self._stdout_goto] |= write_mask
        streams[self._stderr_goto] |= write_mask
        # Now create a lookup to transform our masks into file access levels
        access_lookup = {
            read_mask: os.O_RDONLY,
            write_mask: os.O_WRONLY,
            rw_mask: os.O_RDWR
        }
        
        # Now, use our mask lookup to translate into actual file descriptors
        for stream in streams:
            # Transform the mask into the actual access level.
            access = access_lookup[streams[stream]]
            # Open the file with that level of access.
            stream_fd = os.open(stream, access)
            # And update streams to be that, instead of the access mask.
            streams[stream] = stream_fd
            # We cannot immediately close the stream, because we'll get an 
            # error about a bad file descriptor.
        
        # Okay, duplicate our streams into the FDs for stdin, stdout, stderr.
        stdin_fd = streams[self._stdin_goto]
        stdout_fd = streams[self._stdout_goto]
        stderr_fd = streams[self._stderr_goto]
        # Flush before transitioning
        self._stds_flush()
        # Do iiiitttttt
        os.dup2(stdin_fd, 0)
        os.dup2(stdout_fd, 1)
        os.dup2(stderr_fd, 2)
        
        # Finally, close the extra fds.
        for duped_fd in streams.values():
            os.close(duped_fd)
        
    def _filial_usurpation(self):
        ''' Decouple the child process from the parent environment.
        '''
        # This prevents "directory busy" errors when attempting to remove 
        # subdirectories.
        os.chdir(self._use_dir)
        
        # Get new PID.
        # Stop listening to parent signals.
        # Put process in new parent group
        # Detatch controlling terminal.
        new_sid = os.setsid()
        if new_sid == -1:
            # A new pid of -1 is bad news bears
            logger.critical('Failed setsid call.')
            sys.exit(1)
            
        # Set the permissions mask
        os.umask(self._umask)
            
    def _fratricidal_fork(self):
        ''' Fork the current process, and immediately exit the parent.
        
        OKAY TECHNICALLY THIS WOULD BE PARRICIDE but it just doesn't 
        have the same ring to it.
        '''
        try:
            # This will create a clone of our process. The clone will get zero
            # for the PID, and the parent will get an actual PID.
            pid = os.fork()
                
        except OSError as exc:
            logger.critical(
                'Fork ' + str(self._forknum) + ' failed with traceback: \n' + 
                ''.join(traceback.format_exc())
            )
            sys.exit(1)
        
        # If PID != 0, this is the parent process, and we should IMMEDIATELY 
        # die.
        if pid != 0:
            # Exit first parent without cleanup.
            os._exit(0)
        else:
            self._forknum += 1
            
    def _cleanup(self):
        ''' Remove PIDfile and clean up anything else that needs it.
        '''
        os.remove(self.pid_file)
        
    def _handle_sigterm(self, signum, frame):
        ''' Call sys.exit when a sigterm is received. Or don't! Who 
        knows!
        '''
        logger.warning('Caught signal. Exiting.')
        sys.exit()
        
        
        
    
# Etc

def _default_to(check, default):
    ''' If check is None, apply default; else, return check.
    '''
    if check is None:
        return default
    else:
        return check
        
        
# Daemonization and helpers
                    
def _lock_pidfile(pid_file):
    ''' Gets a lock for the PIDfile. This ensures that only one 
    instance of this particular daemon is running at any given time.
    '''
    # We're going to switch modes depending on if the file exists or not.
    # Normally I'd open it as append, BUT saw this note in the python docs:
    # "which on some Unix systems, means that all writes append to the end 
    # of the file regardless of the current seek position"
    try:
        if os.path.isfile(pid_file):
            logger.warning(
                'PID file already exists. It will be overwritten with the '
                'new PID upon successful daemonization.'
            )
            locked_pid = open(pid_file, 'r+')
        else:
            locked_pid = open(pid_file, 'w+')
            
    except (IOError, OSError):
        logger.critical(
            'Unable to create/open the PID file w/ traceback: \n' + 
            ''.join(traceback.format_exc())
        )
        sys.exit(1)
        
    # Acquire an exclusive lock. Do not block to acquire it. Failure will 
    # raise an OSError (older versions raised IOError?).
    try:
        # Note that the flock(2) manpage states the lock will be released
        # when all open file descriptors of it are closed.
        fcntl.flock(locked_pid, fcntl.LOCK_EX | fcntl.LOCK_NB)
        
    except (IOError, OSError):
        logger.critical(
            'Unable to lock the PID file w/ traceback: \n' + 
            ''.join(traceback.format_exc())
        )
        sys.exit(1)
        
    return locked_pid
        
def _write_pid(locked_pidfile):
    ''' Write our PID to the (already locked (by us)) PIDfile.
    '''
    locked_pidfile.seek(0)
    locked_pidfile.truncate(0)
    pid = str(os.getpid())
    locked_pidfile.write(pid + '\n')
    locked_pidfile.flush()
            
def _fratricidal_fork():
    ''' Fork the current process, and immediately exit the parent.
    
    OKAY TECHNICALLY THIS WOULD BE PARRICIDE but it just doesn't 
    have the same ring to it.
    '''
    try:
        # This will create a clone of our process. The clone will get zero
        # for the PID, and the parent will get an actual PID.
        pid = os.fork()
            
    except OSError as exc:
        logger.critical(
            'Fork failed with traceback: \n' + 
            ''.join(traceback.format_exc())
        )
        sys.exit(1)
    
    # If PID != 0, this is the parent process, and we should IMMEDIATELY 
    # die.
    if pid != 0:
        # Exit first parent without cleanup.
        os._exit(0)
    else:
        logger.info('Fork successful.')
        
def _filial_usurpation(chdir, umask):
    ''' Decouple the child process from the parent environment.
    '''
    # This prevents "directory busy" errors when attempting to remove 
    # subdirectories.
    os.chdir(chdir)
    
    # Get new PID.
    # Stop listening to parent signals.
    # Put process in new parent group
    # Detatch controlling terminal.
    new_sid = os.setsid()
    if new_sid == -1:
        # A new pid of -1 is bad news bears
        logger.critical('Failed setsid call.')
        sys.exit(1)
        
    # Set the permissions mask
    os.umask(umask)
    
def _make_range_tuples(start, stop, exclude):
    ''' Creates a list of tuples for all ranges needed to close all 
    files between start and stop, except exclude. Ex:
    start=3, stop=7, exclude={4,}:
        (3, 4),
        (5, 7)
    '''
    # Make a list copy of exclude, discarding anything less than stop
    exclude = [ii for ii in exclude if ii >= start]
    # Sort ascending
    exclude.sort()
    
    ranges = []
    seeker = start
    for ii in exclude:
        # Only add actual slices (it wouldn't matter if we added empty ones, 
        # but there's also no reason to).
        if seeker != ii:
            this_range = (seeker, ii)
            ranges.append(this_range)
            
        # But always do this.
        seeker = ii + 1
        
    # Don't forget to add the final range!
    if seeker < stop:
        final_range = (seeker, stop)
        ranges.append(final_range)
        
    return ranges
        
def _autoclose_files(shielded, fallback_limit=1024):
    ''' Automatically close any open file descriptors.
    '''
    # Figure out the maximum number of files to try to close.
    # This returns a tuple of softlimit, hardlimit; the hardlimit is always
    # greater.
    softlimit, hardlimit = resource.getrlimit(resource.RLIMIT_NOFILE)
    
    # If the hard limit is infinity, we can't iterate to it.
    if hardlimit == resource.RLIM_INFINITY:
        # Check the soft limit. If it's also infinity, fallback to guess.
        if softlimit == resource.RLIM_INFINITY:
            fdlimit = fallback_limit
            
        # The soft limit is finite, so fallback to that.
        else:
            fdlimit = softlimit
            
    # The hard limit is not infinity, so prefer it.
    else:
        fdlimit = hardlimit
    
    # Skip fd 0, 1, 2, which are used by stdin, stdout, and stderr 
    # (respectively)
    ranges_to_close = _make_range_tuples(
        start = 3,
        stop = fdlimit,
        exclude = shielded
    )
    for start, stop in ranges_to_close:
        # How nice of os to include this for us!
        os.closerange(start, stop)
        
def _flush_stds():
    ''' Flush stdout and stderr.
    '''
    try:
        sys.stdout.flush()
    except BlockingIOError:
        logger.error(
            'Failed to flush stdout w/ traceback: \n' + 
            ''.join(traceback.format_exc())
        )
        # Honestly not sure if we should exit here.
    
    try:
        sys.stderr.flush()
    except BlockingIOError:
        logger.error(
            'Failed to flush stderr w/ traceback: \n' + 
            ''.join(traceback.format_exc())
        )
        # Honestly not sure if we should exit here.
        
def _redirect_stds(stdin_goto, stdout_goto, stderr_goto):
    ''' Set stdin, stdout, sterr. If any of the paths don't exist, 
    create them first.
    '''
    # The general strategy here is to:
    # 1. figure out which unique paths we need to open for the redirects
    # 2. figure out the minimum access we need to open them with
    # 3. open the files to get them a file descriptor
    # 4. copy those file descriptors into the FD's used for stdio, etc
    # 5. close the original file descriptors
    
    # Remove repeated values through a set.
    streams = {stdin_goto, stdout_goto, stderr_goto}
    # Transform that into a dictionary of {location: 0, location: 0...}
    # Basically, start from zero permissions
    streams = {stream: 0 for stream in streams}
    # And now create a bitmask for each of reading and writing
    read_mask = 0b01
    write_mask = 0b10
    rw_mask = 0b11
    # Update the streams dict depending on what access each stream requires
    streams[stdin_goto] |= read_mask
    streams[stdout_goto] |= write_mask
    streams[stderr_goto] |= write_mask
    # Now create a lookup to transform our masks into file access levels
    access_lookup = {
        read_mask: os.O_RDONLY,
        write_mask: os.O_WRONLY,
        rw_mask: os.O_RDWR
    }
    
    # Now, use our mask lookup to translate into actual file descriptors
    for stream in streams:
        # First create the file if its missing.
        if not os.path.exists(stream):
            with open(stream, 'w'):
                pass
        
        # Transform the mask into the actual access level.
        access = access_lookup[streams[stream]]
        # Open the file with that level of access.
        stream_fd = os.open(stream, access)
        # And update streams to be that, instead of the access mask.
        streams[stream] = stream_fd
        # We cannot immediately close the stream, because we'll get an 
        # error about a bad file descriptor.
    
    # Okay, duplicate our streams into the FDs for stdin, stdout, stderr.
    stdin_fd = streams[stdin_goto]
    stdout_fd = streams[stdout_goto]
    stderr_fd = streams[stderr_goto]
    # Flush before transitioning
    _flush_stds()
    # Do iiiitttttt
    os.dup2(stdin_fd, 0)
    os.dup2(stdout_fd, 1)
    os.dup2(stderr_fd, 2)
    
    # Finally, close the extra fds.
    for duped_fd in streams.values():
        os.close(duped_fd)
        
def daemonize(pid_file, chdir=None, stdin_goto=None, stdout_goto=None, 
              stderr_goto=None, umask=0o027, shielded_fds=None, 
              fd_fallback_limit=1024):
    ''' Performs a classic unix double-fork daemonization. Registers all
    appropriate cleanup functions.
    
    fd_check_limit is a fallback value for file descriptor searching 
    while closing descriptors.
    
    umask is the eponymous unix umask. The default value:
        1. will allow owner to have any permissions.
        2. will prevent group from having write permission
        3. will prevent other from having any permission
    See https://en.wikipedia.org/wiki/Umask
    '''
    if not _SUPPORTED_PLATFORM:
        raise OSError('Daemonization is unsupported on your platform.')
    
    ####################################################################
    # Prep the arguments
    ####################################################################
    
    # Convert the pid_file to an abs path
    pid_file = os.path.abspath(pid_file)
    
    # Get the noop stream, in case Python is using something other than 
    # /dev/null
    if hasattr(os, "devnull"):
        devnull = os.devnull
    else:
        devnull = "/dev/null"
        
    # Convert any unset std streams to go to dev null
    stdin_goto = _default_to(stdin_goto, devnull)
    stdout_goto = _default_to(stdout_goto, devnull)
    stderr_goto = _default_to(stderr_goto, devnull)
    
    # Convert chdir to go to current dir, and also to an abs path.
    chdir = _default_to(chdir, '.')
    chdir = os.path.abspath(chdir)
    
    # And convert shield_fds to a set
    shielded_fds = _default_to(shielded_fds, set())
    shielded_fds = set(shielded_fds)
    
    ####################################################################
    # Begin actual daemonization
    ####################################################################
    
    # Get a lock on the PIDfile before forking anything.
    locked_pidfile = _lock_pidfile(pid_file)
    # Make sure we don't accidentally autoclose it though.
    shielded_fds.add(locked_pidfile.fileno())
    
    # Define a memoized cleanup function.
    def cleanup(pid_path=pid_file, pid_lock=locked_pidfile):
        pid_lock.close()
        os.remove(pid_path)
    
    # Register this as soon as possible in case something goes wrong.
    atexit.register(cleanup)
    # Note that because fratricidal fork is calling os._exit(), our parents
    # will never call cleanup.
    
    # Now fork the toplevel parent, killing it.
    _fratricidal_fork()
    # We're now running from within the child. We need to detach ourself 
    # from the parent environment.
    _filial_usurpation(chdir, umask)
    # Okay, re-fork (no zombies!) and continue business as usual
    _fratricidal_fork()
    
    # Do some important housekeeping
    _write_pid(locked_pidfile)
    _autoclose_files(shielded_fds, fd_fallback_limit)
    _redirect_stds(stdin_goto, stdout_goto, stderr_goto)
    
    def handle_sigterm(signum, frame):
        ''' Call sys.exit when a sigterm is received. Or don't! Who 
        knows!
        '''
        logger.warning('Caught signal. Exiting.')
        sys.exit()
        
    # Should this be advanced to just after forking?
    signal.signal(signal.SIGTERM, self._handle_sigterm)
       
       
# Daemotion and helpers
        
def _setuser(user):
    ''' Normalizes user to a uid and sets the current uid, or does 
    nothing if user is None.
    '''
    if user is None:
        return
        
    # Normalize group to gid
    elif isinstance(user, str):
        uid = pwd.getpwnam(user).pw_uid
    # The group is already a gid.
    else:
        uid = user
        
    try:
        os.setuid(uid)
    except OSError:
        self.logger.error('Unable to change user.')
        sys.exit(1)
    
def _setgroup(group):
    ''' Normalizes group to a gid and sets the current gid, or does 
    nothing if group is None.
    '''
    if group is None:
        return
        
    # Normalize group to gid
    elif isinstance(group, str):
        gid = grp.getgrnam(group).gr_gid
    # The group is already a gid.
    else:
        gid = group
        
    try:
        os.setgid(gid)
    except OSError:
        self.logger.error('Unable to change group.')
        sys.exit(1)
            
def daemote(pid_file, user, group):
    ''' Change gid and uid, dropping privileges.
    
    Either user or group may explicitly pass None to keep it the same.
    
    The pid_file will be chown'ed so it can still be cleaned up.
    '''
    if not _SUPPORTED_PLATFORM:
        raise OSError('Daemotion is unsupported on your platform.')
    
    # No need to do anything special, just chown the pidfile
    # This will also catch any bad group, user names
    shutil.chown(pid_file, user, group)
    
    # Now update group and then user
    _setgroup(group)
    _setuser(user)