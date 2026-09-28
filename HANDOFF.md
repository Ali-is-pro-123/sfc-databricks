# DineIQ - teammate development handoff

This is a private working project transfer, including synthetic data and a database
backup with existing application accounts. It is not the final public submission.

## Files to send together

- `dineiq-project.zip`: source, SRS, documentation, full-run datasets, saved models,
  verified analytical outputs, setup/check scripts and a PostgreSQL custom-format backup.
- `dineiq-docker-images.tar.gz`: the exact PostgreSQL, Redis and custom Spark images.
- `SHA256SUMS.txt`: checksums of both archives.
- `START-HERE.md`: this guide, also present as `HANDOFF.md` inside the project.

The database backup preserves existing users/roles/location grants and password
hashes. Active browser sessions, the sender's `.env`, virtual environment, caches,
Git internals and small/medium data rehearsals are excluded. Full-run variants are
retained because saved lineage and development investigations can refer to them.
No original Docker volume directories need to be copied.

## Student setup (Windows)

Prerequisites: Docker Desktop running **Linux containers on an x64 machine**, uv,
and Internet access for uv/Python dependencies and the Tailwind CDN. Docker images
are included, so Spark does not need rebuilding. Docker Desktop itself is not
included; the image archive is Linux/amd64, not an installer or a full offline kit.

1. Put the four transfer files in one folder, for example `D:\DineIQ-Transfer`.
2. Verify archive checksums against `SHA256SUMS.txt`:

   ```powershell
   Get-FileHash .\dineiq-project.zip -Algorithm SHA256
   Get-FileHash .\dineiq-docker-images.tar.gz -Algorithm SHA256
   ```

3. Extract `dineiq-project.zip` into that folder. It contains a `dineiq` folder.
4. Open PowerShell in the extracted `dineiq` folder and run:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_teammate.ps1 -ImagesArchive ..\dineiq-docker-images.tar.gz
   ```

The execution-policy option applies only to this PowerShell process. The setup
installs the locked uv environment, verifies package hashes, loads images, creates
fresh local secrets, starts a separate `dineiq-student` Compose project, restores
the database only if empty, and checks domain counts and 23 application/report
requests. It does not delete an existing database. A nonempty incompatible database
causes validation to fail; investigate rather than clearing the volume.

5. Start Django:

   ```powershell
   uv run python dine_iq/manage.py runserver 127.0.0.1:8000
   ```

6. Open `http://127.0.0.1:8000/accounts/login/`.

The transferred local development login is **admin / admin**, preserved at the
sender's request. Use it only for this private localhost handoff. To choose your
own password afterwards: `uv run python dine_iq/manage.py changepassword admin`.
Never publish this backup or these credentials as a production deployment.

## If Docker ports are already occupied

On the first setup, before `.env` exists, supply unused ports:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_teammate.ps1 -ImagesArchive ..\dineiq-docker-images.tar.gz -PostgresPort 55432 -RedisPort 56379 -SparkPort 17777 -MasterUiPort 18090 -WorkerUiPort 18091
```

An existing `.env` is preserved; port arguments do not silently rewrite it. If
the web port is occupied, use `runserver 127.0.0.1:8001` and add the corresponding
origin to `DJANGO_CSRF_TRUSTED_ORIGINS` in the local `.env` when needed.

## Everyday work

```powershell
docker compose -p dineiq-student up -d --no-build
uv run python dine_iq/manage.py runserver 127.0.0.1:8000
```

Stop Django with Ctrl+C. Stop containers while retaining all data with:

```powershell
docker compose -p dineiq-student stop
```

Do not use `down -v` for routine shutdown: it removes the project's database
volume. Redis starts fresh because there is no verified application queue/cache
state that needs transfer. Keep the original archives as recovery copies.

## Continue development

- Start at `documentation/submission/README.md` and its requirements matrix.
- Priority gaps include application audit trail, job-status monitoring, uniform
  model version identifiers, hidden-data acceptance and release packaging.
- Django source: `dine_iq/`; UI: `templates/` and `static/`; Spark: `spark_jobs/`
  and `spark_sql/`; independent analytics: `python_pipeline/`.
- Use `uv run` and the existing lockfile. Write code/comments in English.
- Preserve passed report hashes and source artifacts. Saved JSON can contain
  historical absolute paths; the current web readers use the new project root.
  Do not rewrite all report paths because doing so invalidates lineage hashes.
- For new processing runs, use fresh output directories and explicitly update
  dependencies/configuration. Database edits do not refresh saved analytics.
- Review `AI_USAGE.md` and record actual human review/contributions. No historical
  Git commits are invented or included in this source archive.

Tests:

```powershell
uv run python dine_iq/manage.py test apps --noinput
uv run python -m unittest discover -s python_pipeline -p 'test_*.py'
uv run python -m unittest tests.test_generator
```

If image transfer is inconvenient, the project ZIP works with the same setup
command **without** `-ImagesArchive`; Docker then downloads/builds the defined
images. Full data is already included and need not be generated again.

## Recreate the transfer after new development

From the source project, with its PostgreSQL Compose service running:

```powershell
uv run python scripts/build_handoff.py --output handoff_exports/new-transfer --include-images
```

The output directory must not exist. Keep exports out of Git. This creates a
transactionally consistent database backup and checksums, but avoid editing
analytical files during packaging. Verify a newly extracted copy before sharing.
