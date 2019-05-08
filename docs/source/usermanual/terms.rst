Terminology
===========


.. list-table:: 
   :header-rows: 1
   :widths: 20 80

   * - Term
     - Meaning
   * - Fork
     - Similar to a copy of a repository and forms a parent-child relationship between repositories.  Moving changes between forked repostitories is easy.  See `Workflow <workflow.html>`_
   * - Repository
     - An independent space to hold a set of layers and is the basic unit in GeoGig.  Similar to a database. See `Workflow <workflow.html>`_
   * - Pull Request
     - A controlled method for moving changes from one repository to another. See `Workflow <workflow.html>`_
   * - History
     - All the changes made to dataset (repository).  See `History <addexplore.html#viewing-history>`_
   * - Commit
     - A commit can refer to two related concepts - (a) a set of changes made to repository or (b) the state of a repository after changes has been applied.  See `History <addexplore.html#viewing-history>`_
   * - Revision
     - This refers to the state of a repository in the past - often denoted either by HEAD (the latest revision) or a long commit id number for a historic version of the dataset (i.e. 28aca4793a693f3ee28819adda119a9468bb1a23).  See `History <addexplore.html#viewing-history>`_
   * - Diff
     - Difference - the set of changes a commit introduces.  See `Exporting a Commit Diff <addexplore.html#exporting-a-commit-diff>`_
   * - Conflict
     - When two people both modify the same feature at the same time.  See `Conflict Resolution <../synch.html#conflict-resolution>`_
   * - Workflow
     -  Process support for moving changes between repositories. See `Workflow <workflow.html>`_ and `Synchronization <../synch.html>`_
   * - Local Changes
     - Changes made to a Live Layer or GeoPackage layer that have not been committed (moved to the repository).