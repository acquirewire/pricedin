"""Signal library.

Everything here is point-in-time by construction: a feature for an event on
date D may only use data observable at the close of the last trading session
before the announcement. That constraint is enforced in events.py rather than
trusted to each feature.
"""
