from alembic import context
from backend.app.db import Base, make_engine
from backend.app import models  # noqa: F401

config = context.config
with make_engine().connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
