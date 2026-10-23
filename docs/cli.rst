Command-line reference
======================

``educelab-globus`` ships three console scripts.

el-globus-config
----------------

Inspect and edit the endpoint configuration.

.. code-block:: shell

   el-globus-config                # print all configured endpoints
   el-globus-config --edit         # interactive add / edit / delete menu

Options
~~~~~~~

``--edit``, ``-e``
    Launch the interactive configuration editor.

``--verbose``, ``-v`` / ``--quiet``, ``-q``
    Increase or decrease log verbosity.

el-globus-login
---------------

Log into Globus and cache tokens for one or more endpoints.

.. code-block:: shell

   el-globus-login
   el-globus-login --endpoints lab-server archive
   el-globus-login --force
   el-globus-login --no-browser     # headless / SSH-friendly flow

Options
~~~~~~~

``--endpoints``, ``-e``
    Names or UUIDs of specific endpoints to authorize. Defaults to every
    endpoint in the configuration file.

``--force``, ``-f``
    Force a new login even if cached tokens look valid.

``--no-browser``
    Print the auth URL instead of opening a browser. Selected automatically
    when ``SSH_TTY`` or ``SSH_CONNECTION`` is set.

``--ignore-offline``
    Treat offline endpoints as a warning rather than a hard failure.

el-globus-cp
------------

Copy a file or directory between two configured endpoints.

.. code-block:: shell

   el-globus-cp src-endpoint:/abs/path  dst-endpoint:/abs/path
   el-globus-cp src-endpoint:rel/path   dst-endpoint:rel/path
   el-globus-cp --sync-level mtime src:data/ dst:data/
   el-globus-cp --verify src:data/ dst:data/
   el-globus-cp --background src:data/ dst:data/

Paths may be absolute or relative to the endpoint's configured ``basedir``.
Missing destination directories, including parents, are created.

Options
~~~~~~~

``--label LABEL``
    Custom transfer label shown in the Globus UI.

``--background``, ``-b``
    Submit the transfer and exit immediately. Otherwise, the command polls
    until the transfer completes and reports progress.

``--sync-level {exists,size,mtime,checksum}``
    Only transfer files whose destination does not match the source under
    the chosen comparison. By default, every file is transferred
    unconditionally.

``--verify``
    Enable checksum verification on the transfer.

``--notify-success`` / ``--no-notify-success``
    Send (or suppress) the success notification email. Default: suppress.

``--notify-failed`` / ``--no-notify-failed``
    Send (or suppress) the failure notification email. Default: send.

``--notify-inactive`` / ``--no-notify-inactive``
    Send (or suppress) the "inactive" notification email. Default: send.

``--dry-run``
    Log in, list the source as far as the filters need, and print the
    transfer plan: Globus filter rules, directories to create and transfer
    items. Nothing is created or submitted. Lists are shortened unless
    ``--verbose`` is given.

``--dry-run-files``
    Print every source file the filters include, followed by a count and
    total size, then exit. This lists the whole filtered source tree, which
    can be slow for large directories.

Filtering
~~~~~~~~~

When the source is a directory, ``el-globus-cp`` accepts `rclone's filter
flags <https://rclone.org/filtering/>`_, with the same rule syntax and
meaning:

.. code-block:: shell

   # skip a commonly named file everywhere
   el-globus-cp --exclude intermediate.tar.gz src:data/ dst:data/

   # copy two subdirectories, without any intermediate.tar.gz files
   el-globus-cp --filter '- intermediate.tar.gz' \
                --filter '+ /scan01/**' --filter '+ /scan02/**' \
                --filter '- **' src:data/ dst:data/

   # check what would be copied first
   el-globus-cp --dry-run-files --include '*.tif' src:data/ dst:data/

``--filter RULE``, ``--filter-from FILE``
    Add a ``+ glob`` (include), ``- glob`` (exclude) or ``!`` (clear) rule.

``--include GLOB``, ``--include-from FILE``
    Include matching files. Anything not included is excluded.

``--exclude GLOB``, ``--exclude-from FILE``
    Exclude matching files.

``--files-from FILE``
    Copy only the listed files (paths relative to the source). It can't be
    combined with other filter flags.

``-from`` files take one entry per line, and ``-`` reads from stdin. Blank
lines and lines starting with ``#`` or ``;`` are ignored. Each flag can be
repeated.

Patterns are matched against paths relative to the source directory, so a
leading ``/`` anchors a pattern there. Rules are checked in order and the
first match wins. As in rclone, the flags are applied in a fixed order no
matter how they appear on the command line: ``--include``, ``--exclude``,
then ``--filter`` rules. Using ``--filter`` alone is clearest. Filters
cannot be used when the source is a single file.

Basename-only rules such as ``- *.tmp`` or ``- cache/`` are passed to
Globus and need no listing. Rules that depend on the path, like
``+ /scan01/**``, make ``el-globus-cp`` list the source only as deep as
needed to resolve them. A single transfer task is submitted either way.
The log says which rules required listing; ``--dry-run`` shows the plan.

Differences from rclone:

- Every directory the filters walk into is created on the destination, even
  if none of its files are included. rclone skips empty directories.
- A negated character class such as ``[^a]`` never matches ``/``.
- ``{{regex}}`` sections use Python's regular expressions instead of Go's.
- ``--ignore-case``, ``--min-size``/``--max-size``,
  ``--min-age``/``--max-age``, ``--max-depth`` and ``--exclude-if-present``
  are not supported yet.
