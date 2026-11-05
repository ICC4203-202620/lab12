"""Conexión compartida por Lambda y los ejercicios locales."""

import os
import time
from uuid import uuid4

import boto3
import certifi
import psycopg
from psycopg.rows import dict_row


def connect(endpoint=None, region=None, user=None, session=None):
    endpoint = endpoint or os.environ["DSQL_ENDPOINT"]
    region = region or os.environ["AWS_REGION"]
    user = user or os.environ.get("DSQL_USER", "lab_app")
    session = session or boto3.Session(region_name=region)
    dsql = session.client("dsql", region_name=region)

    # El token se genera para cada conexión; no se guarda como contraseña fija.
    if user == "admin":
        token = dsql.generate_db_connect_admin_auth_token(Hostname=endpoint)
    else:
        token = dsql.generate_db_connect_auth_token(Hostname=endpoint)

    return psycopg.connect(
        host=endpoint,
        port=5432,
        dbname="postgres",
        user=user,
        password=token,
        sslmode="verify-full",
        sslrootcert=certifi.where(),
        connect_timeout=10,
        row_factory=dict_row,
    )


def transaction(operation, connection_factory=connect):
    """Reintenta solo conflictos de serialización, con una transacción nueva."""
    for attempt in range(3):
        try:
            with connection_factory() as connection:
                result = operation(connection)
                connection.commit()
                return result
        except psycopg.errors.SerializationFailure:
            if attempt == 2:
                raise
            time.sleep(0.1 * (2 ** attempt))


def list_messages():
    return transaction(lambda connection: connection.execute(
        "SELECT id, texto, creado_en FROM public.mensajes "
        "ORDER BY creado_en DESC, id LIMIT 100"
    ).fetchall())


def create_message(text):
    message_id = uuid4()

    def insert(connection):
        return connection.execute(
            "INSERT INTO public.mensajes (id, texto) VALUES (%s, %s) "
            "RETURNING id, texto, creado_en",
            (message_id, text),
        ).fetchone()

    return transaction(insert)
