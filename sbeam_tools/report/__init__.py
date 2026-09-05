"""Cross-run reduction and the critical-case report — issue #5.

Placeholder. This is the half of the loads process the solver must not do: it
reduces **across** runs, joining the case index written by
:mod:`sbeam_tools.cases` to the per-run CSVs the solver exports, and produces
the loads envelope and the critical-case report a stress office consumes.

The solver's own enveloping stays where it is: within one run, over per-sample
data that is never exported in full.
"""
