"""Despliegue del laboratorio mediante CloudFormation y Boto3."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import zipfile

import boto3
from botocore.exceptions import BotoCoreError, ClientError
import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import database  # noqa: E402


def configuration():
    path = ROOT / "config.local.json"
    if not path.exists():
        raise ValueError("Copiar config.example.json como config.local.json antes de continuar.")
    config = json.loads(path.read_text(encoding="utf-8"))
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,22}[a-z0-9]", config.get("deployment_name", "")):
        raise ValueError("deployment_name debe tener de 3 a 24 letras minúsculas, números o guiones; comenzar con una letra y terminar con letra o número.")
    if config.get("region") != "sa-east-1":
        raise ValueError("Este laboratorio utiliza la región sa-east-1.")
    return config


def package():
    if sys.version_info[:2] != (3, 14):
        raise ValueError("El empaquetado requiere Python 3.14.")
    build = ROOT / ".build"
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lambda-", dir=build) as directory:
        target = Path(directory)
        subprocess.run([
            sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-compile",
            "--only-binary=:all:", "--platform", "manylinux2014_x86_64",
            "--implementation", "cp", "--python-version", "3.14", "--abi", "cp314",
            "--target", str(target), "-r", str(ROOT / "backend/requirements.txt"),
        ], check=True)
        archive = build / "lambda.zip"
        files = [(p, p.relative_to(target).as_posix()) for p in sorted(target.rglob("*"))
                 if p.is_file() and "__pycache__" not in p.parts]
        files += [(p, p.name) for p in sorted((ROOT / "backend").glob("*.py"))]
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
            for source, name in files:
                info = zipfile.ZipInfo(name)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                output.writestr(info, source.read_bytes())
        return archive


class Deployment:
    def __init__(self):
        config = configuration()
        self.name, self.region = config["deployment_name"], config["region"]
        self.session = boto3.Session(region_name=self.region)
        identity = self.session.client("sts").get_caller_identity()
        self.account = identity["Account"]
        print(f"Cuenta: {self.account}\nIdentidad: {identity['Arn']}\nRegión: {self.region}\nStack: {self.name}")
        self.cf = self.session.client("cloudformation")
        self.s3 = self.session.client("s3")
        suffix = hashlib.sha256(f"{self.account}:{self.region}:{self.name}".encode()).hexdigest()[:12]
        self.artifacts = f"icc4203-lab12-artifacts-{self.account}-{suffix}"
        self.tags = {"CourseLab": "icc4203-lab12", "Deployment": self.name}

    def stack(self):
        try:
            stack = self.cf.describe_stacks(StackName=self.name)["Stacks"][0]
        except ClientError as error:
            details = error.response["Error"]
            if details["Code"] == "ValidationError" and "does not exist" in details["Message"]:
                return None
            raise
        tags = {item["Key"]: item["Value"] for item in stack.get("Tags", [])}
        if any(tags.get(key) != value for key, value in self.tags.items()):
            raise ValueError("El stack existente no pertenece a este laboratorio. No se modificará.")
        return stack

    def outputs(self):
        stack = self.stack()
        if not stack or stack["StackStatus"] not in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}:
            raise ValueError("Se requiere un despliegue terminado correctamente. Revisar CloudFormation.")
        return {item["OutputKey"]: item["OutputValue"] for item in stack.get("Outputs", [])}

    def status(self):
        stack = self.stack()
        print(f"Estado: {stack['StackStatus']}" if stack else "El stack no existe.")
        for item in (stack or {}).get("Outputs", []):
            print(f"{item['OutputKey']}: {item['OutputValue']}")
        print(f"Bucket auxiliar: {self.artifacts}")

    def bucket_exists(self, bucket):
        try:
            self.s3.head_bucket(Bucket=bucket, ExpectedBucketOwner=self.account)
            return True
        except ClientError as error:
            if error.response["Error"]["Code"] in {"404", "NoSuchBucket", "NotFound"}:
                return False
            raise

    def verify_bucket(self, bucket, stack_id=None):
        if not self.bucket_exists(bucket):
            return False
        tags = {item["Key"]: item["Value"] for item in self.s3.get_bucket_tagging(
            Bucket=bucket, ExpectedBucketOwner=self.account
        )["TagSet"]}
        expected = {"aws:cloudformation:stack-id": stack_id} if stack_id else self.tags
        if any(tags.get(key) != value for key, value in expected.items()):
            raise ValueError(f"El bucket {bucket} no tiene las etiquetas de propiedad esperadas.")
        return True

    def ensure_artifacts(self):
        if not self.bucket_exists(self.artifacts):
            self.s3.create_bucket(Bucket=self.artifacts, CreateBucketConfiguration={"LocationConstraint": self.region})
            self.s3.put_bucket_tagging(Bucket=self.artifacts, Tagging={"TagSet": [
                {"Key": key, "Value": value} for key, value in self.tags.items()
            ]}, ExpectedBucketOwner=self.account)
        self.verify_bucket(self.artifacts)
        self.s3.put_public_access_block(Bucket=self.artifacts, ExpectedBucketOwner=self.account,
            PublicAccessBlockConfiguration={key: True for key in (
                "BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"
            )})

    def wait_stack(self, action):
        print("Esperando CloudFormation; se puede seguir el avance en Events...", flush=True)
        self.cf.get_waiter(f"stack_{action}_complete").wait(
            StackName=self.name, WaiterConfig={"Delay": 15, "MaxAttempts": 240}
        )

    def deploy(self):
        existing = self.stack()
        if existing and existing["StackStatus"] not in {"CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"}:
            raise ValueError("El stack está ocupado o falló. Revisar Events; no se eliminará automáticamente.")
        archive = package()
        self.ensure_artifacts()
        key = f"lambda/{hashlib.sha256(archive.read_bytes()).hexdigest()}.zip"
        with archive.open("rb") as source:
            self.s3.put_object(Bucket=self.artifacts, Key=key, Body=source,
                               ExpectedBucketOwner=self.account, ServerSideEncryption="AES256")
        arguments = {
            "StackName": self.name,
            "TemplateBody": (ROOT / "template.yaml").read_text(encoding="utf-8"),
            "Parameters": [
                {"ParameterKey": "ArtifactBucket", "ParameterValue": self.artifacts},
                {"ParameterKey": "ArtifactKey", "ParameterValue": key},
            ],
            "Capabilities": ["CAPABILITY_IAM"],
            "Tags": [{"Key": key, "Value": value} for key, value in self.tags.items()],
        }
        if existing:
            try:
                self.cf.update_stack(**arguments)
            except ClientError as error:
                if "No updates are to be performed" not in error.response["Error"]["Message"]:
                    raise
                print("No hay cambios en la infraestructura.")
            else:
                self.wait_stack("update")
        else:
            self.cf.create_stack(**arguments)
            self.wait_stack("create")
        outputs = self.outputs()
        self.verify_bucket(outputs["WebsiteBucket"], self.stack()["StackId"])
        for source in sorted((ROOT / "website").iterdir()):
            if source.is_file():
                content_type = {".js": "application/javascript", ".html": "text/html"}[source.suffix]
                self.s3.put_object(Bucket=outputs["WebsiteBucket"], Key=source.name,
                    Body=source.read_bytes(), ContentType=content_type, CacheControl="max-age=60",
                    ExpectedBucketOwner=self.account)
        cloudfront = self.session.client("cloudfront")
        result = cloudfront.create_invalidation(DistributionId=outputs["DistributionId"], InvalidationBatch={
            "Paths": {"Quantity": 1, "Items": ["/*"]}, "CallerReference": str(time.time_ns())
        })
        print("Esperando la actualización de la caché de CloudFront...", flush=True)
        cloudfront.get_waiter("invalidation_completed").wait(
            DistributionId=outputs["DistributionId"], Id=result["Invalidation"]["Id"],
            WaiterConfig={"Delay": 15, "MaxAttempts": 120},
        )
        self.status()
        print("Archivos publicados. En un despliegue nuevo, continuar con la preparación de DSQL.")

    def prepare_database(self):
        outputs = self.outputs()

        def factory():
            return database.connect(outputs["DatabaseEndpoint"], self.region, "admin", self.session)

        def execute(statement):
            def operation(connection):
                cursor = connection.execute(statement)
                return cursor.fetchall() if cursor.description else None
            return database.transaction(operation, factory)

        # Cada llamada confirma una sola instrucción; no se mezcla DDL con DML.
        execute((ROOT / "database/schema.sql").read_text(encoding="utf-8"))
        if not execute("SELECT rolname FROM pg_roles WHERE rolname = 'lab_app'"):
            execute("CREATE ROLE lab_app WITH LOGIN")
        execute("GRANT SELECT, INSERT ON TABLE public.mensajes TO lab_app")
        # public ya otorga USAGE; no se modifica un esquema del sistema.
        usage = execute("SELECT has_schema_privilege('lab_app', 'public', 'USAGE') AS permitted")
        if not usage[0]["permitted"]:
            raise ValueError("El rol lab_app no tiene acceso al esquema public.")
        grant = sql.SQL("AWS IAM GRANT lab_app TO {}").format(sql.Literal(outputs["LambdaRoleArn"]))
        execute(grant)
        print("Tabla y permisos preparados. Los mensajes existentes se conservaron.")

    def empty_bucket(self, bucket):
        for page in self.s3.get_paginator("list_object_versions").paginate(
            Bucket=bucket, ExpectedBucketOwner=self.account
        ):
            objects = [{"Key": item["Key"], "VersionId": item["VersionId"]}
                       for item in page.get("Versions", []) + page.get("DeleteMarkers", [])]
            if objects:
                result = self.s3.delete_objects(Bucket=bucket, Delete={"Objects": objects},
                                                ExpectedBucketOwner=self.account)
                if result.get("Errors"):
                    raise ValueError(f"No se pudieron eliminar todos los objetos de {bucket}.")

    def delete(self):
        stack = self.stack()
        if stack and stack["StackStatus"].endswith("IN_PROGRESS"):
            raise ValueError("Esperar que termine la operación actual antes de eliminar el stack.")
        buckets = []
        if stack:
            for page in self.cf.get_paginator("list_stack_resources").paginate(StackName=self.name):
                for resource in page["StackResourceSummaries"]:
                    if resource["ResourceType"] == "AWS::S3::Bucket" and resource.get("PhysicalResourceId"):
                        bucket = resource["PhysicalResourceId"]
                        if self.verify_bucket(bucket, stack["StackId"]):
                            buckets.append(bucket)
        auxiliary_exists = self.verify_bucket(self.artifacts)
        if not stack and not auxiliary_exists:
            print("No quedan recursos del despliegue.")
            return
        print("Se eliminarán el stack, los mensajes de DSQL y estos buckets:")
        for bucket in buckets + ([self.artifacts] if auxiliary_exists else []):
            print(f"  {bucket}")
        if input(f"Para confirmar, escribir {self.name}: ").strip() != self.name:
            print("Eliminación cancelada.")
            return
        # Verificar todos los propietarios antes de borrar el primer objeto.
        for bucket in buckets:
            self.empty_bucket(bucket)
        if stack:
            self.cf.delete_stack(StackName=self.name)
            self.wait_stack("delete")
        if auxiliary_exists:
            self.empty_bucket(self.artifacts)
            self.s3.delete_bucket(Bucket=self.artifacts, ExpectedBucketOwner=self.account)
        print("Recursos eliminados.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "deploy", "status", "database", "delete"])
    args = parser.parse_args()
    try:
        deployment = Deployment()
        if args.command == "check":
            print("Acceso a AWS comprobado. Este comando no crea recursos.")
        elif args.command == "database":
            deployment.prepare_database()
        else:
            getattr(deployment, args.command)()
    except psycopg.Error as error:
        print(f"Error de DSQL: {type(error).__name__}, SQLSTATE={error.sqlstate}. Revisar endpoint y permisos.", file=sys.stderr)
        return 1
    except (ValueError, OSError, BotoCoreError, ClientError, subprocess.CalledProcessError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
