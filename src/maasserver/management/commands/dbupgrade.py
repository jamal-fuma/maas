# Copyright 2015-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""
Django command: Upgrade MAAS regiond database using both south and django
>1.7 migration system.
"""

__all__ = []

import argparse
from importlib import import_module
import json
import os
import shutil
import subprocess
import sys
import tempfile
from textwrap import dedent

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import (
    connections,
    DEFAULT_DB_ALIAS,
)

# Modules that required a south migration.
SOUTH_MODULES = [
    "maasserver",
    "metadataserver",
]

# Script that performs the south migrations for MAAS under django 1.6 and
# python2.7.
MAAS_UPGRADE_SCRIPT = """\
# Copyright 2015-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type
__all__ = []

import os
import sys

import django.conf


class LazySettings(django.conf.LazySettings):
    '''Prevent Django from mangling warnings settings.

    At present, Django adds a single filter that surfaces all deprecation
    warnings, but MAAS handles them differently. Django doesn't appear to give
    a way to prevent it from doing its thing, so we must undo its changes.

    Deprecation warnings in production environments are not desirable as they
    are a developer tool, and not something an end user can reasonably do
    something about. This brings control of warnings back into MAAS's control.
    '''

    def _configure_logging(self):
        # This is a copy of *half* of Django's `_configure_logging`, omitting
        # the problematic bits.
        if self.LOGGING_CONFIG:
            from django.utils.log import DEFAULT_LOGGING
            from django.utils.module_loading import import_by_path
            # First find the logging configuration function ...
            logging_config_func = import_by_path(self.LOGGING_CONFIG)
            logging_config_func(DEFAULT_LOGGING)
            # ... then invoke it with the logging settings
            if self.LOGGING:
                logging_config_func(self.LOGGING)


# Install our `LazySettings` as the Django-global settings class. First,
# ensure that Django hasn't yet loaded its settings.
assert not django.conf.settings.configured
# This is needed because Django's `LazySettings` overrides `__setattr__`.
object.__setattr__(django.conf.settings, "__class__", LazySettings)

# Force Django configuration.
os.environ["DJANGO_SETTINGS_MODULE"] = "maas19settings"

# Inject the sys.path from the parent process so that the python path is
# is similar, except that the directory that this script is running from is
# already the first path in sys.path.
for path in os.environ["MAAS_SYSPATH_COPY"].split(":"):
    if path not in sys.path:
        sys.path.append(path)

# Import django and ensure that it is actually 1.6.6 that is provided by
# the tarball.
import django
assert django.get_version() == "1.6.6"

# Install piston and south.
from django.conf import settings
settings.INSTALLED_APPS += (
    'piston',
    'south',
)

# Remove the following applications as they should not exist when running
# under python2.7 and performing the south migrations.
REMOVE_APPS = [
    "piston3",
    "django_nose",
    "maastesting",
]
settings.INSTALLED_APPS = [
    app
    for app in settings.INSTALLED_APPS
    if app not in REMOVE_APPS
]

# Perform the migrations.
from django.core.management import call_command
call_command(
    "syncdb", database=sys.argv[1], interactive=False)
call_command(
    "migrate", "maasserver", database=sys.argv[1], interactive=False)
call_command(
    "migrate", "metadataserver", database=sys.argv[1],
    interactive=False)
"""


class Command(BaseCommand):
    help = "Upgrades database schema for MAAS regiond."

    def add_arguments(self, parser):
        super(Command, self).add_arguments(parser)

        parser.add_argument(
            '--database', action='store', dest='database',
            default=DEFAULT_DB_ALIAS,
            help=(
                'Nominates a database to synchronize. Defaults to the '
                '"default" database.'))
        parser.add_argument(
            '--always-south', action='store_true', help=(
                'Always run the south migrations even if not required.'))
        # Hidden argument that is not shown to the user. This argument is used
        # internally to call itself again to run the django builtin migrations
        # in a subprocess.
        parser.add_argument(
            '--django', action='store_true', help=argparse.SUPPRESS)

    @classmethod
    def _path_to_django16_south_maas19(cls):
        """Return path to the in-tree django16, south, and
        MAAS 1.9 source code."""
        from maasserver.migrations import south
        path_to_south_dir = os.path.dirname(south.__file__)
        return os.path.join(
            path_to_south_dir, "django16_south_maas19.tar.gz")

    @classmethod
    def _extract_django16_south_maas19(cls):
        """Extract the django16, south, and MAAS 1.9 source code in to a temp
        path."""
        path_to_tarball = cls._path_to_django16_south_maas19()
        tempdir = tempfile.mkdtemp(prefix='maas-upgrade-')
        subprocess.check_call([
            "tar", "zxf", path_to_tarball, "-C", tempdir])

        settings_json = os.path.join(tempdir, "maas19settings.json")
        with open(settings_json, "w", encoding="utf-8") as fd:
            fd.write(json.dumps({"DATABASES": settings.DATABASES}))

        script_path = os.path.join(tempdir, "migrate.py")
        with open(script_path, "wb") as fp:
            fp.write(MAAS_UPGRADE_SCRIPT.encode("utf-8"))
        return tempdir, script_path

    @classmethod
    def _south_was_performed(cls, database):
        """Return True if the database had south migrations performed."""
        with connections[database].cursor() as cursor:
            cursor.execute(dedent("""\
                SELECT c.relname
                FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                AND c.relname = 'south_migrationhistory'
                AND c.relkind = 'r'
                """))
            output = cursor.fetchone()
            if output is None:
                return False
            else:
                return output[0] == 'south_migrationhistory'

    @classmethod
    def _get_last_db_south_migration(cls, database, app):
        """Return the name of the last south migration in the database for
        the application."""
        with connections[database].cursor() as cursor:
            cursor.execute(
                "SELECT migration FROM south_migrationhistory "
                "WHERE app_name = %s ORDER BY id DESC LIMIT 1", [app])
            output = cursor.fetchone()
            return output[0]

    @classmethod
    def _get_all_app_south_migrations(cls, app):
        """Return list of all migrations for the given application."""
        migration_module_name = settings.SOUTH_MIGRATION_MODULES[app]
        migration_module = import_module(migration_module_name)
        migration_path = os.path.dirname(migration_module.__file__)
        return sorted([
            os.path.splitext(filename)[0]
            for filename in os.listdir(migration_path)
            if filename != "__init__.py" and filename.endswith(".py")
            ])

    @classmethod
    def _get_last_app_south_migration(cls, app):
        """Return the name of the last migration for the application."""
        return cls._get_all_app_south_migrations(app)[-1]

    @classmethod
    def _south_migrations_are_complete(cls, database):
        """Return True if all of the south migrations have been performed."""
        for module in SOUTH_MODULES:
            should_have_ran = cls._get_last_app_south_migration(module)
            last_ran = cls._get_last_db_south_migration(database, module)
            if should_have_ran != last_ran:
                return False
        return True

    @classmethod
    def _south_needs_to_be_performed(cls, database):
        """Return True if south needs to run on the database."""
        return (
            cls._south_was_performed(database) and
            not cls._south_migrations_are_complete(database))

    @classmethod
    def _find_tables(cls, database, startwith):
        """Return list of tables that start with `startwith`."""
        with connections[database].cursor() as cursor:
            cursor.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name LIKE %s",
                [startwith + "%"])
            return [
                row[0]
                for row in cursor.fetchall()
            ]

    @classmethod
    def _rename_piston_to_piston3(cls, database, tables):
        """Rename piston to piston3."""
        with connections[database].cursor() as cursor:
            for table in tables:
                cursor.execute(
                    "ALTER TABLE piston_%s RENAME TO piston3_%s" % (
                        table, table))

    @classmethod
    def _perform_south_migrations(cls, script_path, database):
        """Perform the south migrations.

        This forces the south migrations to run under python2.7. python2.7 is
        required to run the south migrations.
        """
        # Send a copy of the current sys.path of this process into the child
        # process. Except anything that references /usr/lib/python3 which will
        # be excluded since the child process will run under python2.7.
        paths = [
            path
            for path in sys.path
            if not path.startswith('/usr/lib/python3')
        ]
        env = os.environ.copy()
        env['MAAS_SYSPATH_COPY'] = ":".join(paths)
        process = subprocess.Popen(
            ["python2.7", script_path, database], env=env)
        return process.wait()

    @classmethod
    def _perform_django_migrations(cls, database):
        """Perform the django migrations."""
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
        cmd = [
            sys.executable, "-m", "maasserver", "dbupgrade",
            "--database", database, "--django",
        ]
        process = subprocess.Popen(cmd, env=env)
        return process.wait()

    @classmethod
    def _perform_trigger_installation(cls, database):
        """Register all PL/pgSQL functions and triggers.

        :attention: `database` argument is not used!
        """
        from maasserver import triggers
        triggers.register_all_triggers()

    @classmethod
    def _get_all_triggers(cls, database):
        """Return list of all triggers in the database."""
        with connections[database].cursor() as cursor:
            cursor.execute(dedent("""\
                SELECT tgname::text, pg_class.relname
                FROM pg_trigger, pg_class
                WHERE pg_trigger.tgrelid = pg_class.oid AND (
                    pg_class.relname LIKE 'maasserver_%' OR
                    pg_class.relname LIKE 'metadataserver_%' OR
                    pg_class.relname LIKE 'auth_%') AND
                    NOT pg_trigger.tgisinternal
                ORDER BY tgname::text;
                """))
            return [
                (row[0], row[1])
                for row in cursor.fetchall()
            ]

    @classmethod
    def _drop_all_triggers(cls, database):
        """Remove all of the triggers that MAAS has created previously."""
        triggers = cls._get_all_triggers(database)
        with connections[database].cursor() as cursor:
            for trigger_name, table in triggers:
                cursor.execute(
                    "DROP TRIGGER IF EXISTS %s ON %s;" % (trigger_name, table))

    @classmethod
    def _drop_all_views(cls, database):
        """Register all PL/pgSQL views.

        :attention: `database` argument is not used!
        """
        from maasserver import dbviews
        dbviews.drop_all_views()

    @classmethod
    def _perform_view_installation(cls, database):
        """Register all PL/pgSQL views.

        :attention: `database` argument is not used!
        """
        from maasserver import dbviews
        dbviews.register_all_views()

    def handle(self, *args, **options):
        database = options.get('database')
        always_south = options.get('always_south', False)
        run_django = options.get('django', False)
        if not run_django:
            # Neither south or django provided as an option then this is the
            # main process that will do the initial sync and spawn the
            # subprocesses.

            # First, drop any views that may already exist. We don't want views
            # that that depend on a particular schema to prevent schema
            # changes due to the dependency. The views will be recreated at the
            # end of this process.
            self._drop_all_views(database)

            # Remove all of the trigger that MAAS uses before performing the
            # migrations. This ensures that no triggers are ran during the
            # migrations and that only the updated triggers are installed in
            # the database.
            self._drop_all_triggers(database)

            # Run south migrations only if forced or needed.
            if always_south or self._south_needs_to_be_performed(database):
                # Extract django16 and south for the subprocess.
                tempdir, script_path = self._extract_django16_south_maas19()

                # Perform south migrations.
                try:
                    rc = self._perform_south_migrations(script_path, database)
                finally:
                    # Placed in try-finally just to make sure that even if
                    # an exception is raised that the temp directory is
                    # cleaned up.
                    shutil.rmtree(tempdir)
                if rc != 0:
                    sys.exit(rc)

            # Run the django builtin migrations.
            rc = self._perform_django_migrations(database)
            if rc != 0:
                sys.exit(rc)

            # Make sure we're going to see the same database as the migrations
            # have left behind.
            if connections[database].in_atomic_block:
                raise AssertionError(
                    "An ongoing transaction may hide changes made "
                    "by external processes.")

            # Install all database functions, triggers, and views. This is
            # idempotent, so we run it at the end of every database upgrade.
            self._perform_trigger_installation(database)
            self._perform_view_installation(database)
        else:
            # Piston has been renamed from piston to piston3.
            piston_tables = self._find_tables(database, "piston")
            piston_tables = [
                table[7:]
                for table in piston_tables
                if not table.startswith("piston3")
            ]
            if len(piston_tables):
                self._rename_piston_to_piston3(database, piston_tables)

            # Perform the builtin migration faking the initial migrations
            # if south was ever performed.
            call_command(
                "migrate",
                interactive=False,
                fake_initial=self._south_was_performed(database))
