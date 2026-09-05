"""Preprocessing tools that generate sbeam decks.

Deliberately **outside** the ``sbeam/`` solver package: tools here may know
about physical units, standard atmospheres and regulatory constants, none of
which are permitted inside the solver (conventions charter §7 — sbeam never
converts units and its card fields are unit-neutral).  Anything in this package
must produce ordinary BDF that the solver reads without special knowledge.
"""
