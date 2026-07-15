# Database migrations

SecMind business tables are managed by Alembic. Run migrations from
`secmind/backend` before starting a PostgreSQL deployment:

```powershell
python -m alembic -c alembic/alembic.ini upgrade head
```

Set `SECMIND_DATABASE_URL` to select the target database. Existing databases that
were created by the old `create_all()` startup path must be inspected and then
baselined with `alembic stamp 20260715_0001` before normal upgrades.

LangGraph checkpoint tables are not part of this migration tree. They are owned by
the installed LangGraph checkpointer package and initialized by its idempotent
`setup()` method.
