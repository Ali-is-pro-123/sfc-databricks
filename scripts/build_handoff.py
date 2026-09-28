"""Create a portable private development handoff without local secrets/caches."""

import argparse
import gzip
import hashlib
import json
import shutil
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGES = ['postgres:17.11-alpine', 'redis:7.4-alpine', 'dineiq-spark-ml:3.5.9']
SOURCE_DIRS = {'config', 'data_generator', 'database', 'dine_iq', 'documentation',
               'notebooks', 'python_pipeline', 'reports', 'sample_data', 'screenshots',
               'spark_jobs', 'spark_sql', 'src', 'static', 'templates', 'tests', 'scripts'}
SKIP_PARTS = {'__pycache__', '.git', '.venv', '.pytest_cache', '.ruff_cache', 'node_modules'}
ROOT_FILES = {'.dockerignore', '.env.example', '.gitignore', '.python-version',
              'README.md', 'AI_USAGE.md', 'compose.yaml', 'pyproject.toml', 'uv.lock',
              'HANDOFF.md', 'DineIQ Analytics-Data Science Intelligence Arena_SRS.pdf'}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def selected_files():
    for folder in sorted(SOURCE_DIRS | {'raw_data', 'processed_data', 'parquet_data', 'models'}):
        base = ROOT / folder
        if not base.exists():
            continue
        for path in sorted(base.rglob('*')):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(ROOT)
            if any(part in SKIP_PARTS for part in relative.parts):
                continue
            if path.suffix in {'.pyc', '.pyo', '.sqlite3'} or path.name.startswith('.env'):
                continue
            if folder in {'raw_data', 'processed_data', 'parquet_data', 'models'}:
                # Full-run variants retain existing provenance chains; omit rehearsals.
                if len(relative.parts) > 2 and 'full' not in relative.parts[1]:
                    continue
                if len(relative.parts) == 2 and path.name != 'README.md':
                    if folder != 'processed_data' or 'full' not in path.name:
                        continue
            yield path
    for name in sorted(ROOT_FILES):
        path = ROOT / name
        if path.is_file():
            yield path


def build(output, include_images):
    output.mkdir(parents=True, exist_ok=False)
    backup = output / 'database.dump'
    print('Taking a consistent PostgreSQL backup (active sessions excluded)...', flush=True)
    with backup.open('wb') as stream:
        subprocess.run(['docker', 'compose', 'exec', '-T', 'postgres', 'sh', '-c',
                        'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc '
                        '--no-owner --no-acl --exclude-table-data=django_session'],
                       cwd=ROOT, stdout=stream, check=True)

    archive = output / 'dineiq-project.zip'
    manifest = {'created_utc': datetime.now(timezone.utc).isoformat(),
                'platform': 'Windows host; linux/amd64 Docker images',
                'includes': 'Source, full-run artifacts, models, database with accounts but no sessions',
                'excludes': '.env, virtual environments, caches, Git internals, small/medium runs',
                'files': []}
    print('Compressing source, full datasets, models and database...', flush=True)
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in selected_files():
            relative = path.relative_to(ROOT).as_posix()
            manifest['files'].append({'path': relative, 'bytes': path.stat().st_size, 'sha256': digest(path)})
            bundle.write(path, 'dineiq/' + relative)
        manifest['files'].append({'path': 'handoff/database.dump', 'bytes': backup.stat().st_size,
                                  'sha256': digest(backup)})
        bundle.write(backup, 'dineiq/handoff/database.dump')
        bundle.writestr('dineiq/handoff/manifest.json', json.dumps(manifest, indent=2) + '\n')
    with zipfile.ZipFile(archive) as bundle:
        bad = bundle.testzip()
        if bad:
            raise RuntimeError(f'Archive CRC check failed: {bad}')
    # This is only the build's temporary backup; its verified copy is in the ZIP.
    backup.unlink()
    artifacts = [archive]

    if include_images:
        target = output / 'dineiq-docker-images.tar.gz'
        print('Exporting the three project Docker images...', flush=True)
        process = subprocess.Popen(['docker', 'image', 'save', *IMAGES], stdout=subprocess.PIPE)
        try:
            with gzip.open(target, 'wb', compresslevel=1) as destination:
                shutil.copyfileobj(process.stdout, destination, length=1024 * 1024)
        finally:
            process.stdout.close()
        if process.wait() != 0:
            raise RuntimeError('Docker image export failed; do not distribute this incomplete folder.')
        artifacts.append(target)

    checksums = ''.join(f'{digest(path)}  {path.name}\n' for path in artifacts)
    (output / 'SHA256SUMS.txt').write_text(checksums, encoding='utf-8')
    shutil.copy2(ROOT / 'HANDOFF.md', output / 'START-HERE.md')
    print(json.dumps({'output': str(output), 'files': len(manifest['files']),
                      'archives': [{'name': p.name, 'bytes': p.stat().st_size} for p in artifacts]}, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='A new, unused directory')
    parser.add_argument('--include-images', action='store_true')
    args = parser.parse_args()
    build(args.output.resolve(), args.include_images)
