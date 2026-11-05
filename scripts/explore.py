"""Ejercicios de conexión y definición de tablas en DSQL."""

import argparse
import sys
from uuid import uuid4

import psycopg
from psycopg import sql
from botocore.exceptions import BotoCoreError, ClientError

from deploy import Deployment, database


def connection_exercise(factory):
    def operation(connection):
        messages = connection.execute(
            "SELECT id, texto FROM public.mensajes ORDER BY creado_en LIMIT 10"
        ).fetchall()
        print("Mensajes existentes:")
        for message in messages:
            print(f"  {message['id']}: {message['texto']}")
        message_id = uuid4()
        connection.execute(
            "INSERT INTO public.mensajes (id, texto) VALUES (%s, %s)",
            (message_id, "Mensaje registrado desde Python"),
        )
        return message_id

    message_id = database.transaction(operation, factory)
    print(f"Escritura confirmada con COMMIT. Identificador: {message_id}")


def ddl_exercise(factory):
    # Un nombre nuevo evita modificar tablas de otro ejercicio o estudiante.
    name = sql.Identifier("prueba_ddl_" + uuid4().hex[:12])
    create = sql.SQL("CREATE TABLE {} (id UUID PRIMARY KEY, texto TEXT)").format(name)
    insert = sql.SQL("INSERT INTO {} (id, texto) VALUES (%s, %s)").format(name)

    def execute(statement, params=None):
        return database.transaction(lambda connection: connection.execute(statement, params), factory)

    try:
        print("1. Intento de CREATE TABLE e INSERT dentro de la misma transacción.")
        with factory() as connection:
            connection.execute(create)
            try:
                connection.execute(insert, (uuid4(), "Una sola transacción"))
            except psycopg.Error as error:
                connection.rollback()
                if error.sqlstate not in {"0A000", "25001"}:
                    raise
                print(f"Operación rechazada (SQLSTATE {error.sqlstate}). Se ejecutó ROLLBACK.")
            else:
                connection.rollback()
                raise RuntimeError("No se observó la restricción esperada; revisar el comportamiento del servicio.")

        print("2. CREATE TABLE y COMMIT; luego INSERT y COMMIT en otra transacción.")
        execute(create)
        execute(insert, (uuid4(), "Transacciones separadas"))

        def read(connection):
            return connection.execute(sql.SQL("SELECT texto FROM {}").format(name)).fetchone()
        print("Registro persistido:", database.transaction(read, factory)["texto"])
    finally:
        execute(sql.SQL("DROP TABLE IF EXISTS {}").format(name))
        print("Tabla auxiliar eliminada. La tabla mensajes no se modificó.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exercise", choices=["connection", "ddl"])
    args = parser.parse_args()
    try:
        deployment = Deployment()
        # Resolver el endpoint una vez; no consultar CloudFormation por operación SQL.
        endpoint = deployment.outputs()["DatabaseEndpoint"]

        def factory():
            return database.connect(endpoint, deployment.region, "admin", deployment.session)

        {"connection": connection_exercise, "ddl": ddl_exercise}[args.exercise](factory)
    except psycopg.Error as error:
        print(f"Error de DSQL: {type(error).__name__}, SQLSTATE={error.sqlstate}. Revisar tabla, endpoint y permisos.", file=sys.stderr)
        return 1
    except (ValueError, RuntimeError, OSError, BotoCoreError, ClientError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
