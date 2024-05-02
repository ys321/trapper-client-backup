==============
 Installation
==============

Installing with pip & virtualenv on Linux
++++++++++++++++++++++++++++++++++++++++++

1) First, clone the source code to your local repository:
   
   .. code-block:: console
                   
      $ git clone https://gitlab.com/oscf/trapper-client.git

2) Change directory to ``trapper-client``:
   
   .. code-block:: console
                   
      $ cd trapper-client
      
3) To get the most up-to-date version switch to a branch ``develop``:

   .. code-block:: console

      $ git checkout -b develop

4) Pull the source code of selected branch: 

   .. code-block:: console

      $ git pull origin develop

5) Create the virtual environment:

   .. code-block:: console
      
      $ virtualenv -p python3 ./env

6) Activate the virtual environment:
   
   .. code-block:: console
      
      $ source ./env/bin/activate
      
7) Install the requirements:

   .. code-block:: console
      
      $ pip install -r reqs.txt
      $ garden install filebrowser --kivy

8) Finally you can run **trapper-client**:
   
   .. code-block:: console
      
      $ python ./main.py

            
Installing with Anaconda on Windows (not tested)
++++++++++++++++++++++++++++++++++++++++++++++++

.. note::
   This is a recommended way of installing **trapper-client** on Windows machines.
   However, you can always use pip & virtualenv as described above for Linux.

1) To install Anaconda follow the official documentation:

   https://docs.anaconda.com/anaconda/install/

   .. note::
      Be sure to download Python **3.X** version of Anaconda.


2) It is much more convenient to use **Git for Windows** for cloning git repositories instead
   of using a standard Windows command line. Download and install Git (& Bash) for Windows:

   https://git-scm.com/download/win

3) Follow the steps 1-4 from **Installing with pip & virtualenv on Linux**. 

4) Install the requirements:

   .. code-block:: console
                
      conda install --file reqs.txt

5) Finally you can run **trapper-client**:
   
   .. code-block:: console
      
      python ./main.py

.. note::
   If you want to run **trapper-client** with Anaconda in a virtual environment follow the steps
   described `here <https://uoa-eresearch.github.io/eresearch-cookbook/recipe/2014/11/20/conda/>`_
   before installing the requirements (step 4)
      



