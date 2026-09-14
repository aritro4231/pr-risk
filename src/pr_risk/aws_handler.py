import json
import os

import psycopg2


def get_database_connection():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ["DB_PORT"],
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        connect_timeout=5,
    )


def ensure_tables_exist(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS repositories (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS pr_analyses (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                repository_id BIGINT NOT NULL
                    REFERENCES repositories(id),
                pull_request_number INTEGER NOT NULL,
                risk_score DOUBLE PRECISION NOT NULL,
                risk_level TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS file_analyses (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                pr_analysis_id BIGINT NOT NULL
                    REFERENCES pr_analyses(id)
                    ON DELETE CASCADE,
                path TEXT NOT NULL,
                additions INTEGER NOT NULL,
                deletions INTEGER NOT NULL,
                historical_commit_count INTEGER NOT NULL,
                historical_bugfix_count INTEGER NOT NULL,
                churn_percentile DOUBLE PRECISION NOT NULL,
                bugfix_ratio DOUBLE PRECISION NOT NULL,
                risk_score DOUBLE PRECISION NOT NULL,
                risk_level TEXT NOT NULL
            );
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_pr_analyses_repository
            ON pr_analyses(repository_id);
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_file_analyses_pr_analysis
            ON file_analyses(pr_analysis_id);
            """
        )


def store_analysis(connection, payload: dict) -> int:
    repository_name = payload["repository"]
    pull_request_number = payload["pull_request_number"]

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO repositories (name)
            VALUES (%s)
            ON CONFLICT (name)
            DO UPDATE SET name = EXCLUDED.name
            RETURNING id;
            """,
            (repository_name,),
        )

        repository_id = cursor.fetchone()[0]

        cursor.execute(
            """
            INSERT INTO pr_analyses (
                repository_id,
                pull_request_number,
                risk_score,
                risk_level
            )
            VALUES (%s, %s, %s, %s)
            RETURNING id;
            """,
            (
                repository_id,
                pull_request_number,
                payload["risk_score"],
                payload["risk_level"],
            ),
        )

        analysis_id = cursor.fetchone()[0]

        for file_data in payload.get("files", []):
            cursor.execute(
                """
                INSERT INTO file_analyses (
                    pr_analysis_id,
                    path,
                    additions,
                    deletions,
                    historical_commit_count,
                    historical_bugfix_count,
                    churn_percentile,
                    bugfix_ratio,
                    risk_score,
                    risk_level
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s
                );
                """,
                (
                    analysis_id,
                    file_data["path"],
                    file_data["additions"],
                    file_data["deletions"],
                    file_data["historical_commit_count"],
                    file_data["historical_bugfix_count"],
                    file_data["churn_percentile"],
                    file_data["bugfix_ratio"],
                    file_data["risk_score"],
                    file_data["risk_level"],
                ),
            )

    return analysis_id


def lambda_handler(event, context):
    try:
        body = event.get("body", {})

        if isinstance(body, str):
            body = json.loads(body)

        connection = get_database_connection()

        try:
            with connection:
                ensure_tables_exist(connection)
                analysis_id = store_analysis(connection, body)
        finally:
            connection.close()

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps(
                {
                    "message": "PR risk analysis stored",
                    "analysis_id": analysis_id,
                    "risk_score": body["risk_score"],
                    "risk_level": body["risk_level"],
                }
            ),
        }

    except Exception as error:
        print("PR Risk Lambda error:", repr(error))

        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps(
                {
                    "error": "Failed to store PR analysis"
                }
            ),
        }