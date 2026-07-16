from logging.config import fileConfig

from alembic import context

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from config import settings
from database.models import Base


# ----------------------------------------------------------
# Конфигурация Alembic
# ----------------------------------------------------------

config = context.config


# Используем URL подключения из .env через config.py
#
# Благодаря этому строка подключения хранится
# только в одном месте.
#
config.set_main_option(
    "sqlalchemy.url",
    settings.database_url,
)


# ----------------------------------------------------------
# Логирование
# ----------------------------------------------------------

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


# ----------------------------------------------------------
# Все модели проекта
# ----------------------------------------------------------
print(Base.metadata.tables.keys())
target_metadata = Base.metadata

# ----------------------------------------------------------
# Исключение таблиц другого бота
# ----------------------------------------------------------

def include_object(
    object,
    name,
    type_,
    reflected,
    compare_to
):
    """
    Контроль того, какие объекты Alembic отслеживает.

    Старые таблицы HR-проекта игнорируем.
    """

    ignored_tables = {
        "candidates",
        "vacancies",
        "applications",
        "interviews",
        "hr_messages",
        "hr_admins",
        "auto_reject_rules",
    }


    if type_ == "table" and name in ignored_tables:
        return False


    return True

# ----------------------------------------------------------
# Offline migration
# ----------------------------------------------------------

def run_migrations_offline() -> None:
    """
    Генерация SQL без подключения к БД.
    """

    url = config.get_main_option("sqlalchemy.url")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
        dialect_opts={
            "paramstyle": "named",
        },

        # Следить за изменением типов
        compare_type=True,

        # Следить за DEFAULT
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ----------------------------------------------------------
# Online migration
# ----------------------------------------------------------

def run_migrations_online() -> None:

    connectable = engine_from_config(
        config.get_section(
            config.config_ini_section,
            {}
        ),

        prefix="sqlalchemy.",

        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


# ----------------------------------------------------------
# Точка входа
# ----------------------------------------------------------

if context.is_offline_mode():

    run_migrations_offline()

else:

    run_migrations_online()