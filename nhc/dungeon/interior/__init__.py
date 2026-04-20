"""Building interior partitioners.

See ``design/building_interiors.md`` for the contract. Each
partitioner consumes a :class:`PartitionerConfig` and returns a
:class:`LayoutPlan`; the site assembler stamps the plan onto the
floor's :class:`~nhc.dungeon.model.Level`.
"""
