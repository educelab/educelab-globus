Configuration
=============

``educelab-globus`` stores named Globus endpoints in a TOML config file at
``~/.globuscp/config.toml``.

Example
-------

.. code-block:: toml

   [lab-server]
   uuid = "16fd2706-8baf-433b-82eb-8c7fada847da"
   basedir = "/mnt/scratch/"   # optional

   [archive]
   uuid = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
   basedir = "/cold/"

Each table key is the endpoint *name* that you use on the command line.

Fields
------

``uuid``
    Required. The Globus collection / endpoint UUID.

``basedir``
    Optional. A directory that is prepended to any relative path supplied
    on the command line. When omitted, only absolute paths are accepted.

Interactive editor
------------------

You can add, edit, rename, and delete endpoints with the built-in interactive
menu:

.. code-block:: shell

   el-globus-config --edit

Token storage
-------------

OAuth tokens acquired by ``el-globus-login`` are cached at
``~/.globuscp/tokenstore.json`` so subsequent commands do not have to log
in again until consents or scopes change.
