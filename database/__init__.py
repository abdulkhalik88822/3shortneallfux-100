"""Database package marker.

This file makes the local database/ directory a real Python package so
imports such as `from database.ia_filterdb import ...` are not shadowed
by the root-level database.py module.
"""
