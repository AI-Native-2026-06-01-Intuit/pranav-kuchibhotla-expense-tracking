"""Great Expectations validation over the seeded pgvector doc_chunks table.

The suite runs against a Testcontainers Postgres+pgvector instance seeded
with real corpus data (via the shared corpus loader + fake deterministic
embedder). Doing so is deliberate: it exercises the same path the CI job
uses, not a hand-crafted DataFrame, so drift in the schema or loader will
break the suite.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import great_expectations as gx
import numpy as np
import pandas as pd
import psycopg
import pytest
from _pg_wait import wait_for_postgres
from great_expectations import expectations as gxe
from numpy.typing import NDArray
from testcontainers.postgres import PostgresContainer

from expense_ai.corpus import EMBEDDING_DIM, embed_dataframe, load_corpus
from expense_ai.pgvector_loader import load_rows

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "sql" / "V001__doc_chunks.sql"
_SEED_PATH = Path(__file__).resolve().parent / "fixtures" / "corpus_seed.jsonl"

pytestmark = pytest.mark.docker


class _FakeEncoder:
    def encode(
        self,
        sentences: list[str],
        batch_size: int = 64,
        normalize_embeddings: bool = True,
        convert_to_numpy: bool = True,
    ) -> NDArray[np.float32]:
        rng = np.random.default_rng(seed=1234)
        mat = rng.standard_normal((len(sentences), EMBEDDING_DIM)).astype(np.float32)
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        return (mat / norms).astype(np.float32)


@pytest.fixture(scope="module")
def seeded_dsn() -> Iterator[str]:
    with PostgresContainer(
        "pgvector/pgvector:pg16",
        username="expense",
        password="expense",
        dbname="expense",
        driver=None,
    ) as pg:
        host = pg.get_container_host_ip()
        port = pg.get_exposed_port(5432)
        dsn = f"postgresql://expense:expense@{host}:{port}/expense"
        wait_for_postgres(dsn)
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(_SCHEMA_PATH.read_text())
            conn.commit()

        df = load_corpus(_SEED_PATH)
        rows = embed_dataframe(df, model=_FakeEncoder())
        load_rows(dsn, rows)
        yield dsn


_FETCH_SQL = (
    "SELECT doc_id, chunk_idx, chunk_text, model_version, tenant_id, "
    "length(chunk_text) AS chunk_len, embedding IS NOT NULL AS has_embedding "
    "FROM doc_chunks"
)
_FETCH_COLUMNS = (
    "doc_id",
    "chunk_idx",
    "chunk_text",
    "model_version",
    "tenant_id",
    "chunk_len",
    "has_embedding",
)


def _fetch_doc_chunks_df(dsn: str) -> pd.DataFrame:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(_FETCH_SQL)
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=list(_FETCH_COLUMNS))


def test_doc_chunks_gx_suite_passes(seeded_dsn: str) -> None:
    df = _fetch_doc_chunks_df(seeded_dsn)
    assert len(df) >= 100

    ctx = gx.get_context(mode="ephemeral")
    data_source = ctx.data_sources.add_pandas("expense_ai_pd")
    asset = data_source.add_dataframe_asset("doc_chunks")
    batch_def = asset.add_batch_definition_whole_dataframe("whole")

    suite = ctx.suites.add(gx.ExpectationSuite(name="doc_chunks_v1"))
    suite.add_expectation(gxe.ExpectColumnValuesToNotBeNull(column="doc_id"))
    suite.add_expectation(gxe.ExpectColumnValuesToNotBeNull(column="chunk_text"))
    suite.add_expectation(gxe.ExpectColumnValuesToNotBeNull(column="model_version"))
    suite.add_expectation(gxe.ExpectColumnValuesToBeInSet(column="has_embedding", value_set=[True]))
    suite.add_expectation(gxe.ExpectTableRowCountToBeBetween(min_value=100, max_value=10_000_000))
    suite.add_expectation(
        gxe.ExpectColumnValueLengthsToBeBetween(column="chunk_text", min_value=1, max_value=8000)
    )
    suite.add_expectation(
        gxe.ExpectColumnValuesToBeInSet(
            column="tenant_id", value_set=["tenant-a", "tenant-b", "tenant-c"]
        )
    )

    vd = ctx.validation_definitions.add(
        gx.ValidationDefinition(name="doc_chunks_vd", data=batch_def, suite=suite)
    )
    result = vd.run(batch_parameters={"dataframe": df})
    assert result.success, result.describe()
