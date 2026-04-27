from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import types
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import psycopg  # noqa: F401
except ModuleNotFoundError:
    psycopg = types.ModuleType("psycopg")

    class _PsycopgError(Exception):
        pass

    psycopg.Error = _PsycopgError
    psycopg.connect = lambda *args, **kwargs: None
    psycopg_rows = types.ModuleType("psycopg.rows")
    psycopg_rows.dict_row = object()
    sys.modules["psycopg"] = psycopg
    sys.modules["psycopg.rows"] = psycopg_rows

try:
    import dotenv  # noqa: F401
except ModuleNotFoundError:
    dotenv = types.ModuleType("dotenv")

    def _dotenv_values(env_path):
        values = {}
        for line in Path(env_path).read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
        return values

    dotenv.dotenv_values = _dotenv_values
    sys.modules["dotenv"] = dotenv

from tools.common.statuses import StepStatus
from tools.db.loaders import DbEnvLoader
from tools.db.models import DbEnvConfig, QueryStep
from tools.db.services import DatabaseQueryRunner


class DbActorProfilesTests(unittest.TestCase):
    def test_actor_scoped_env_profile_overrides_base_db_settings(self) -> None:
        with TemporaryDirectory() as tmp:
            env_path = Path(tmp) / "demo.env"
            env_path.write_text(
                "\n".join(
                    [
                        "DATABASE_URL=postgresql://localhost:5432/public_db",
                        "DATABASE_USER=public_user",
                        "DATABASE_PASSWORD=public_password",
                        "DATABASE_URL__API_CLIENT=postgresql://localhost:5432/partner_db",
                        "DATABASE_USER__API_CLIENT=partner_user",
                        "DATABASE_PASSWORD__API_CLIENT=partner_password",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            env = DbEnvLoader().load(env_path, actor="api-client")

        self.assertEqual(env.actor, "api-client")
        self.assertEqual(env.database_url, "postgresql://localhost:5432/partner_db")
        self.assertEqual(env.database_user, "partner_user")
        self.assertEqual(env.database_password, "partner_password")
        self.assertEqual(env.database_url_key, "DATABASE_URL__API_CLIENT")

    def test_database_query_runner_uses_step_actor_for_env_resolution(self) -> None:
        env_loader = _RecordingDbEnvLoader(
            DbEnvConfig.from_mapping(
                {"DATABASE_URL": "postgresql://localhost:5432/app_db", "DATABASE_USER": "user", "DATABASE_PASSWORD": "password"},
                actor="admin",
            )
        )
        result = DatabaseQueryRunner(
            env_loader=env_loader,
            step_loader=_StaticQueryStepLoader(QueryStep(sql="select 1", actor="admin")),
            sql_validator=_PassingSqlValidator(),
            query_service=_PassingQueryService(),
        ).run(Path("env"), Path("step"))

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertEqual(env_loader.last_actor, "admin")
        self.assertEqual(result.details["actor"], "admin")
        self.assertEqual(result.details["database_url_key"], "DATABASE_URL")


class _RecordingDbEnvLoader:
    def __init__(self, env: DbEnvConfig) -> None:
        self._env = env
        self.last_actor: str | None = None

    def load(self, env_path: Path, actor: str | None = None) -> DbEnvConfig:
        self.last_actor = actor
        return self._env


class _StaticQueryStepLoader:
    def __init__(self, step: QueryStep) -> None:
        self._step = step

    def load(self, step_path: Path) -> QueryStep:
        return self._step


class _PassingSqlValidator:
    @staticmethod
    def validate(sql: str) -> None:
        return None


class _PassingQueryService:
    @staticmethod
    def execute(env: DbEnvConfig, step: QueryStep):
        from tools.common import ExecutionResult

        return ExecutionResult(
            status=StepStatus.PASS,
            message="ok",
            details={
                "sql": step.sql,
                "actor": env.actor,
                "database_url_key": env.database_url_key,
            },
        )


if __name__ == "__main__":
    unittest.main()
