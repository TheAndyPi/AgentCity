"""Dynamic scenario engine: interpret, validate, mutate, respond and analyze.

The interpreter turns free text into a plan of registry operations. The validator
checks the plan against the operation registry and the current world. The mutation
engine applies the operations to persistent world systems, and agents decide for
themselves how to respond. The analyzer reports only what was recorded.
"""
