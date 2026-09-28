"""Verify the extracted handoff before installation; Python standard library only."""

import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / 'handoff/manifest.json').read_text(encoding='utf-8'))
failures = []
for entry in manifest['files']:
    path = (root / entry['path']).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        failures.append(entry['path'])
        continue
    with path.open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if actual != entry['sha256'] or path.stat().st_size != entry['bytes']:
        failures.append(entry['path'])
if failures:
    raise SystemExit('Missing or modified package files: ' + ', '.join(failures))
print(f"Verified {len(manifest['files']):,} handoff files and their SHA-256 checksums.")
