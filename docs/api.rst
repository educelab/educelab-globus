Python API
==========

The ``educelab.globus`` package exposes a small Python API for use from
scripts and pipelines.

.. code-block:: python

   from educelab.globus import login, endpoints, get_endpoint

   # Inspect the configuration
   for name, ep in endpoints().items():
       print(name, ep['uuid'])

   # Log in and get an authorized TransferClient
   ep = get_endpoint('lab-server')
   tc = login([ep['uuid']])
   for item in tc.operation_ls(ep['uuid']):
       print(item['name'])

educelab.globus
---------------

.. automodule:: educelab.globus
   :members:
   :show-inheritance:

educelab.globus.config
----------------------

.. automodule:: educelab.globus.config
   :members:
   :show-inheritance:

educelab.globus.login
---------------------

.. automodule:: educelab.globus.login
   :members:
   :show-inheritance:

educelab.globus.cp.main
-----------------------

.. automodule:: educelab.globus.cp.main
   :members:
   :show-inheritance:
