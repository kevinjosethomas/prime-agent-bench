"""Publishable campaign records.

The records bundle turns one campaign's results tree into the minimal,
privacy-audited, re-analyzable record committed under
``records/campaigns/<run-label>/``. Publishing is offline: the bundler
reads trial rows, settle rows, and versions evidence only — never raw
logs, screens, homes, fixtures, or vendor payloads.
"""
