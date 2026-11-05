"""Handler HTTP API: consultar y registrar mensajes."""

import base64
import binascii
import json
import logging
from datetime import datetime

import psycopg
from botocore.exceptions import BotoCoreError, ClientError

import database

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def response(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"},
        "body": json.dumps(body, ensure_ascii=False,
                           default=lambda value: value.isoformat() if isinstance(value, datetime) else str(value)),
    }


def lambda_handler(event, context):
    http = event.get("requestContext", {}).get("http", {})
    method = http.get("method")
    if event.get("rawPath") != "/api/mensajes":
        return response(404, {"error": "Ruta no encontrada"})

    logger.info("Solicitud %s /api/mensajes", method)
    try:
        if method == "GET":
            return response(200, {"mensajes": database.list_messages()})
        if method != "POST":
            return response(405, {"error": "Método no permitido"})

        body = event.get("body") or ""
        if len(body) > 10000:
            return response(413, {"error": "Solicitud demasiado grande"})
        try:
            if event.get("isBase64Encoded"):
                body = base64.b64decode(body, validate=True).decode("utf-8")
            data = json.loads(body)
        except (ValueError, UnicodeError, binascii.Error):
            return response(400, {"error": "Se requiere un cuerpo JSON válido"})
        text = data.get("texto") if isinstance(data, dict) else None
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 500 or "\x00" in text:
            return response(400, {"error": "El mensaje debe contener entre 1 y 500 caracteres"})
        return response(201, database.create_message(text.strip()))
    except psycopg.Error as error:
        # No se imprime el error completo: podría contener SQL o datos privados.
        logger.error("Error de base de datos: %s, SQLSTATE=%s", type(error).__name__, error.sqlstate)
        return response(503, {"error": "No fue posible acceder a la base de datos"})
    except (BotoCoreError, ClientError) as error:
        logger.error("Error de acceso a AWS: %s", type(error).__name__)
        return response(503, {"error": "No fue posible acceder a la base de datos"})
