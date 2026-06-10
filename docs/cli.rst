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
