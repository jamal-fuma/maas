# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Utilities for executing external commands."""

__all__ = [
    'call_and_check',
    'ExternalProcessError',
    'select_c_utf8_bytes_locale',
    'select_c_utf8_locale',
]

import os
from pipes import quote
from string import printable
from subprocess import (
    CalledProcessError,
    PIPE,
    Popen,
)

# A table suitable for use with str.translate() to replace each
# non-printable and non-ASCII character in a byte string with a question
# mark, mimicking the "replace" strategy when encoding and decoding.
non_printable_replace_table = "".join(
    chr(i) if chr(i) in printable else "?"
    for i in range(0xff + 0x01)).encode("ascii")


class ExternalProcessError(CalledProcessError):
    """Raised when there's a problem calling an external command.

    Unlike `CalledProcessError`:

    - `__str__()` returns a string containing the output of the failed
      external process, if available, and tries to keep in valid Unicode
      characters from the error message.

    """

    @classmethod
    def upgrade(cls, error):
        """Upgrade the given error to an instance of this class.

        If `error` is an instance of :py:class:`CalledProcessError`, this will
        change its class, in-place, to :py:class:`ExternalProcessError`.

        There are two ways we could have done this:

        1. Change the class of `error` in-place.

        2. Capture ``exc_info``, create a new exception based on `error`, then
           re-raise with the 3-argument version of ``raise``.

        #1 seems a lot simpler so that's what this method does. The caller
        needs then only use a naked ``raise`` to get the utility of this class
        without losing the traceback.
        """
        if type(error) is CalledProcessError:
            error.__class__ = cls

    @staticmethod
    def _to_unicode(string):
        if isinstance(string, bytes):
            return string.decode("ascii", "replace")
        else:
            return str(string)

    @staticmethod
    def _to_ascii(string, table=non_printable_replace_table):
        if isinstance(string, bytes):
            return string.translate(table)
        elif isinstance(string, str):
            return string.encode("ascii", "replace").translate(table)
        else:
            return str(string).encode("ascii", "replace").translate(table)

    def __str__(self):
        cmd = " ".join(quote(self._to_unicode(part)) for part in self.cmd)
        output = self._to_unicode(self.output)
        return "Command `%s` returned non-zero exit status %d:\n%s" % (
            cmd, self.returncode, output)

    @property
    def output_as_ascii(self):
        """The command's output as printable ASCII.

        Non-printable and non-ASCII characters are filtered out.
        """
        return self._to_ascii(self.output)

    @property
    def output_as_unicode(self):
        """The command's output as Unicode text.

        Invalid Unicode characters are filtered out.
        """
        return self._to_unicode(self.output)


def call_and_check(command, *args, **kwargs):
    """Execute a command, similar to `subprocess.check_call()`.

    :param command: Command line, as a list of strings.
    :return: The command's output from standard output.
    :raise ExternalProcessError: If the command returns nonzero.
    """
    process = Popen(command, *args, stdout=PIPE, stderr=PIPE, **kwargs)
    stdout, stderr = process.communicate()
    stderr = stderr.strip()
    if process.returncode != 0:
        raise ExternalProcessError(process.returncode, command, output=stderr)
    return stdout


def has_command_available(command):
    """Return True if `command` is available on the system."""
    try:
        call_and_check(["which", command])
    except ExternalProcessError:
        return False
    return True


def select_c_utf8_locale(environ=os.environ):
    """Return a dict containing an environment that uses the C.UTF-8 locale.

    C.UTF-8 is the new en_US.UTF-8, i.e. it's the new default locale when no
    other locale makes sense.

    This function takes a starting environment, by default that of the current
    process, strips away all locale and language settings (i.e. LC_* and LANG)
    and selects C.UTF-8 in their place.

    :param environ: A base environment to start from. By default this is
        ``os.environ``. It will not be modified.
    """
    environ = {
        name: value for name, value in environ.items()
        if not name.startswith('LC_')
    }
    environ.update({
        'LC_ALL': 'C.UTF-8',
        'LANG': 'C.UTF-8',
        'LANGUAGE': 'C.UTF-8',
    })
    return environ


def select_c_utf8_bytes_locale(environ=os.environb):
    """Return a dict containing an environment that uses the C.UTF-8 locale.

    C.UTF-8 is the new en_US.UTF-8, i.e. it's the new default locale when no
    other locale makes sense.

    This function takes a starting environment, by default that of the current
    process, strips away all locale and language settings (i.e. LC_* and LANG)
    and selects C.UTF-8 in their place.

    :param environ: A base environment to start from. By default this is
        ``os.environb``. It will not be modified.
    """
    environ = {
        name: value for name, value in environ.items()
        if not name.startswith(b'LC_')
    }
    environ.update({
        b'LC_ALL': b'C.UTF-8',
        b'LANG': b'C.UTF-8',
        b'LANGUAGE': b'C.UTF-8',
    })
    return environ
