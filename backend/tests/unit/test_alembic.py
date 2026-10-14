from io import StringIO
import ast
from pathlib import Path
import py_compile
import shutil

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import MetaData, Table
from sqlalchemy.dialects.mysql import dialect
from sqlalchemy.schema import AddConstraint, CreateColumn

from app.core.config import DatabaseNotConfiguredError, PROJECT_ROOT
from app.db.base import Base
import app.models


def test_repository_has_initial_schema_and_interest_seed_migrations():
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["012_plan_item_user_note"]
    assert scripts.get_revision("001_initial_schema").down_revision is None
    assert scripts.get_revision("002_seed_interest_codes").down_revision == "001_initial_schema"
    assert scripts.get_revision("003_setup_preferences").down_revision == "002_seed_interest_codes"
    assert scripts.get_revision("004_local_auth_and_oauth_state").down_revision == "003_setup_preferences"
    assert scripts.get_revision("005_trip_selected_places").down_revision == "004_local_auth_and_oauth_state"
    assert scripts.get_revision("006_trip_preference_travel_style").down_revision == "005_trip_selected_places"
    assert scripts.get_revision("007_youtube_saved_discoveries").down_revision == "006_trip_preference_travel_style"
    assert scripts.get_revision("008_youtube_destination_fields").down_revision == "007_youtube_saved_discoveries"
    assert scripts.get_revision("009_merge_legacy_road_addr").down_revision == "008_youtube_destination_fields"
    assert scripts.get_revision("009_trip_share_links").down_revision == "009_merge_legacy_road_addr"
    assert scripts.get_revision("010_plan_regeneration_previews").down_revision == "009_trip_share_links"
    assert scripts.get_revision("011_trip_transport_mode_walk").down_revision == "010_plan_regeneration_previews"
    assert scripts.get_revision("012_plan_item_user_note").down_revision == "011_trip_transport_mode_walk"


def test_alembic_template_and_offline_sql_without_database(tmp_path):
    # Generate only in an isolated copy, never in the project's versions directory.
    script_path = tmp_path / "alembic"
    shutil.copytree(PROJECT_ROOT / "alembic", script_path, ignore=shutil.ignore_patterns("__pycache__"))
    output = StringIO()
    config = Config(str(PROJECT_ROOT / "alembic.ini"), stdout=StringIO(), output_buffer=output)
    config.set_main_option("script_location", str(script_path))
    revision = command.revision(config, message="isolated template smoke test")
    py_compile.compile(str(Path(revision.path)), doraise=True)
    command.upgrade(config, "head", sql=True)
    assert revision.revision in output.getvalue()
    assert "CREATE DATABASE" not in output.getvalue().upper()
    assert "DROP DATABASE" not in output.getvalue().upper()


def test_online_alembic_rejects_missing_credentials_before_engine(monkeypatch):
    def forbid_engine(*args, **kwargs):
        pytest.fail("Alembic must validate credentials before creating an engine")

    monkeypatch.setattr("sqlalchemy.create_engine", forbid_engine)
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    with pytest.raises(DatabaseNotConfiguredError):
        command.current(config)


def test_initial_migration_matches_every_model_and_has_no_destructive_operations(monkeypatch):
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("001_initial_schema")
    source = Path(revision.path).read_text(encoding="utf-8")
    operations = [node.func.attr for node in ast.walk(ast.parse(source))
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and isinstance(node.func.value, ast.Name) and node.func.value.id == "op"]
    assert operations == ["create_table"] * 22
    captured = MetaData()

    def capture_table(name, *items, **kwargs):
        return Table(name, captured, *items, **kwargs)

    monkeypatch.setattr(revision.module.op, "create_table", capture_table)
    revision.module.upgrade()
    assert set(captured.tables) == set(Base.metadata.tables) - {
        "oauth_login_states", "trip_selected_places", "youtube_saved_discoveries",
        "trip_share_links", "plan_regeneration_previews",
    }
    for name, table in captured.tables.items():
        model = Base.metadata.tables[name]
        # Setup preferences and local/OAuth auth fields were introduced later.
        model_columns = [
            column for column in model.c
            if (name, column.name) not in {
                ("user_preferences", "travel_style"),
                ("user_preferences", "senior_mode"),
                ("trip_preferences", "travel_style"),
                ("users", "password_hash"),
                ("trip_companions", "member_user_id"),
                ("plan_items", "user_note"),
            }
        ]
        if name != "user_auths":
            expected_columns = [
                str(CreateColumn(c).compile(dialect=dialect())) for c in model_columns
            ]
            # WALK is intentionally introduced by revision 011, not rewritten
            # into the historical initial schema.
            if name == "trips":
                expected_columns = [
                    value.replace("'WALK',", "")
                    for value in expected_columns
                ]
            assert [str(CreateColumn(c).compile(dialect=dialect())) for c in table.c] == expected_columns
        # user_auths gains LOCAL in a later migration.
        if name != "user_auths":
            assert {str(AddConstraint(c).compile(dialect=dialect())) for c in table.constraints} == {
                str(AddConstraint(c).compile(dialect=dialect())) for c in model.constraints
                if c.name not in {"fk_trip_companions_member_user", "uq_trip_companions_trip_member"}}
        assert dict(table.dialect_options["mysql"]) == dict(model.dialect_options["mysql"])
    with pytest.raises(RuntimeError, match="downgrade is disabled"):
        revision.module.downgrade()


def test_initial_upgrade_sql_contains_only_expected_schema_changes():
    import re

    output = StringIO()
    config = Config(str(PROJECT_ROOT / "alembic.ini"), output_buffer=output)
    command.upgrade(config, "001_initial_schema", sql=True)
    sql = output.getvalue()
    created = re.findall(r"CREATE TABLE (\w+)", sql)
    assert set(created) == (set(Base.metadata.tables) - {
        "oauth_login_states", "trip_selected_places", "youtube_saved_discoveries",
        "trip_share_links", "plan_regeneration_previews",
    }) | {"alembic_version"}
    assert len(created) == 23
    assert not re.search(r"\b(DROP|TRUNCATE|GRANT)\b|DELETE\s+FROM|CREATE\s+(DATABASE|USER)", sql, re.I)
    inserted = re.findall(r"INSERT INTO (\w+)", sql)
    assert inserted == ["alembic_version"]  # No service data or interest-code seed.


def test_plan_regeneration_preview_migration_matches_model_and_indexes(monkeypatch):
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("010_plan_regeneration_previews")
    captured = MetaData()
    created_indexes = []

    def capture_table(name, *items, **kwargs):
        return Table(name, captured, *items, **kwargs)

    def capture_index(name, table_name, columns, **kwargs):
        created_indexes.append((name, table_name, tuple(columns)))

    monkeypatch.setattr(revision.module.op, "create_table", capture_table)
    monkeypatch.setattr(revision.module.op, "create_index", capture_index)
    revision.module.upgrade()

    table = captured.tables["plan_regeneration_previews"]
    model = Base.metadata.tables["plan_regeneration_previews"]
    assert [str(CreateColumn(column).compile(dialect=dialect())) for column in table.c] == [
        str(CreateColumn(column).compile(dialect=dialect())) for column in model.c
    ]
    def constraint_signature(constraint):
        return (
            type(constraint).__name__, constraint.name, tuple(constraint.columns.keys()),
            tuple((element.target_fullname, element.ondelete) for element in getattr(constraint, "elements", ())),
        )

    assert {constraint_signature(constraint) for constraint in table.constraints} == {
        constraint_signature(constraint) for constraint in model.constraints
    }
    assert dict(table.dialect_options["mysql"]) == dict(model.dialect_options["mysql"])
    assert set(created_indexes) == {
        ("ix_plan_regeneration_previews_plan_status", "plan_regeneration_previews", ("plan_id", "status")),
        ("ix_plan_regeneration_previews_expires_at", "plan_regeneration_previews", ("expires_at",)),
    }
    assert {(index.name, tuple(index.columns.keys())) for index in model.indexes} == {
        ("ix_plan_regeneration_previews_plan_status", ("plan_id", "status")),
        ("ix_plan_regeneration_previews_expires_at", ("expires_at",)),
    }


def test_trip_walk_migration_expands_only_the_current_trip_enum(monkeypatch):
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("011_trip_transport_mode_walk")
    captured = []

    monkeypatch.setattr(revision.module.op, "alter_column", lambda *args, **kwargs: captured.append((args, kwargs)))
    revision.module.upgrade()

    assert len(captured) == 1
    args, kwargs = captured[0]
    assert args == ("trips", "transport_mode")
    assert kwargs["existing_nullable"] is True
    assert kwargs["existing_type"].enums == ["PUBLIC_TRANSIT", "CAR", "MIXED", "OTHER"]
    assert kwargs["type_"].enums == ["PUBLIC_TRANSIT", "CAR", "WALK", "MIXED", "OTHER"]
