"""sbeam_tools — pre- and post-processing tooling around the sbeam solver.

The architecture boundary (``docs/10_standard/00_program_overview.md``):

    The solver reads a deck and writes results for the cases it is given.
    It never decides which cases exist, and it never reduces across runs.

Everything on the other side of that line lives here: case construction
(:mod:`sbeam_tools.cases`), cross-run reduction and reporting
(:mod:`sbeam_tools.report`), and the GUI (``sbeam_tools.viewer``, relocated at
v0.4.0).  Unlike ``sbeam`` itself, modules here **may** know about physical
units, standard atmospheres and regulatory constants — that is the whole point
of the split, since the solver's card fields are unit-neutral by charter §7.

The dependency direction is one-way and CI-enforced
(``tests/tools/test_import_boundary.py``): ``sbeam_tools`` may import ``sbeam``;
``sbeam`` may never import ``sbeam_tools``.
"""
