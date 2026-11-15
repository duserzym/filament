# Shared mask ownership and history

`Analysis` owns its resolved `ElementMapping`. A new standalone analysis starts
with `propose_mapping`; the workspace supplies remembered mappings and user edits
through `Analysis.set_mapping`. Pb and U analyses never share flags.

`group_keys` contains the mapped function keys, plus the actual oxide input keys
and derived oxide functions for U. Cycle operations expand addressed group keys
before recording their targets and changed cells. Block flags already apply to
the entire run. Free functions retain their own flags. Validity is combined across
the group when computing its effective mask, without recording a user rejection.

A mapping change records the old and new mapping and each adopted flag in one
history operation. Newly mapped functions adopt the previous group's selection;
leaving functions keep their flags. Undo and redo restore both mapping and flags.
The workspace follows the analysis's mapping after undo/redo.

Replay uses recorded targets, without expansion under today's mapping. This is
necessary both for exact history reconstruction and for loading old sessions:
a saved per-ratio selection must not be changed by opening it. Saved mappings
are bound through `restore_mapping`, which does not adopt or record flags.
`group_consistent()` checks selection flags; inconsistent restored selections
remain legacy until the user explicitly accepts the union of rejections.
