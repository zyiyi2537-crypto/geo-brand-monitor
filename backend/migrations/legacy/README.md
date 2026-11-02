# Legacy migrations (pre-alembic)

These 12 scripts predate alembic. They were each invoked manually
(`python -m migrations.001_membership_v2` etc.) on the running prod DB
to evolve the schema from v1 → current state.

**Do not run them anymore.** Prod has already applied all of them; the
current state is locked into the alembic `initial schema baseline`
revision (`backend/alembic/versions/*.py`) via `alembic stamp head` on
2026-05-14. From this point onward all schema changes go through alembic:

    cd backend
    alembic revision --autogenerate -m "describe change"
    # review the generated file under backend/alembic/versions/
    git add backend/alembic/versions/<new>.py && git commit

These files are kept here purely as historical reference — to recover the
intent / data-backfill logic of each step. They are not imported by any
runtime code.

For seed data that some of these scripts also performed (memberships,
sentiment_platforms), see `backend/seeds/`. `MembershipService.__init__`
seeds memberships automatically on first instantiation; sentiment
platforms have to be seeded explicitly:

    .venv/bin/python -m seeds.sentiment_platforms

Note: `006_contact_submissions.py` and `006_moltspay_payment.py` share
the `006` prefix — a sign that the manual numbering scheme had no
collision detection. alembic's revision IDs replace this with random
unique slugs.
