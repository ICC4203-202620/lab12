# Laboratorio 12: Aurora DSQL y despliegue automatizado

Este laboratorio tiene como propósito desplegar una aplicación serverless con persistencia relacional en Amazon Aurora DSQL. Para ello se utilizará una plantilla de AWS CloudFormation y herramientas Python que permitirán crear, actualizar y eliminar la infraestructura desde el computador personal.

La aplicación consiste en un registro de mensajes: una página permite escribir un mensaje y consultar los que ya están guardados. El sitio, el backend, las instrucciones SQL y las herramientas de despliegue se entregan preparados. El trabajo consiste en utilizar estas herramientas, interactuar directamente con la base de datos y comprobar el funcionamiento de los servicios integrados.

La actividad es autocontenida: se crearán todos los recursos necesarios y no se requiere conservar los utilizados en laboratorios anteriores. No se utilizarán React, autenticación de usuarios de la aplicación, notificaciones ni dominios propios.

Las habilidades que se espera ejercitar en esta actividad son:

1. Configurar el acceso a AWS desde el computador personal
2. Desplegar infraestructura mediante CloudFormation e identificar sus recursos y resultados
3. Conectarse a Aurora DSQL desde la consola y desde Python
4. Crear una tabla, insertar registros y consultar información mediante SQL
5. Reconocer diferencias con PostgreSQL en la autenticación y la preparación del esquema
6. Comprobar la integración de una función Lambda con Aurora DSQL
7. Actualizar la aplicación sin perder los datos y eliminar los recursos al finalizar

## Entorno de trabajo

Para desarrollar este laboratorio se requiere:

- Una cuenta AWS activa, con acceso mediante un usuario IAM administrador protegido con MFA
- Un computador con navegador, Python 3.14 y un editor de texto
- Una copia del repositorio del laboratorio en el computador

Se utilizará la consola de AWS en inglés y la región **South America (São Paulo), `sa-east-1`**, para los servicios regionales. CloudFront es un servicio global.

A diferencia del laboratorio anterior, los comandos se ejecutan en un terminal del computador personal. No se utilizarán CloudShell, AWS CLI ni Docker. El acceso a los servicios desde Python se realizará mediante **Boto3**, la biblioteca oficial de AWS para ese lenguaje.

Los servicios pueden generar cargos. No se debe asumir que los créditos o beneficios de la cuenta cubren todo el consumo. Cerrar la consola o el terminal no elimina los recursos; la limpieza final forma parte del laboratorio.

## Preparación

El repositorio contiene:

```text
lab12/
├── README.md
├── config.example.json
├── requirements.txt
├── template.yaml
├── scripts/
│   ├── deploy.py
│   └── explore.py
├── database/
│   └── schema.sql
├── backend/
│   ├── lambda_function.py
│   ├── database.py
│   └── requirements.txt
└── website/
    ├── index.html
    └── app.js
```

- **`config.example.json`**: configuración de ejemplo para seleccionar el nombre del despliegue y la región
- **`requirements.txt`**: dependencias de las herramientas Python
- **`template.yaml`**: definición de los recursos AWS y sus permisos
- **`scripts/deploy.py`**: herramienta para comprobar el acceso, desplegar, preparar la base de datos, consultar el estado y eliminar los recursos
- **`scripts/explore.py`**: ejercicios guiados de conexión y transacciones en DSQL
- **`database/schema.sql`**: definición de la tabla de mensajes
- **`backend/lambda_function.py`**: función que recibe solicitudes para registrar y consultar mensajes
- **`backend/database.py`**: conexión y acceso a la base de datos
- **`backend/requirements.txt`**: dependencias que se incorporan al paquete de Lambda; Boto3 está disponible en su entorno de ejecución
- **`website/`**: archivos estáticos de la página

El sitio utiliza dos operaciones: `GET /api/mensajes` para consultar los mensajes y `POST /api/mensajes` para registrar uno nuevo.

La API permite consultar y registrar mensajes sin autenticación.

## Procedimiento

### 1. Preparar el acceso desde el computador

El inicio de sesión en la consola web no autentica automáticamente los programas del computador. Para ejecutar el despliegue, Boto3 debe disponer de credenciales que identifiquen al usuario IAM y permitan realizar las operaciones correspondientes.

#### 1.1 Preparar el ambiente Python

1. Descargar el repositorio y descomprimirlo, o clonarlo mediante Git
2. Abrir un terminal en la carpeta que contiene este README
3. Crear y activar un ambiente virtual mediante los comandos correspondientes al sistema operativo

**Windows, con PowerShell:**

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Si PowerShell impide ejecutar el archivo de activación por su política de ejecución, se puede habilitar para la sesión actual y repetir la activación:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
```

**Linux o macOS:**

```bash
python3.14 -m venv .venv
source .venv/bin/activate
```

Con el ambiente activo, instalar las dependencias:

```text
python -m pip install -r requirements.txt
```

Los demás comandos se ejecutan desde esta misma carpeta y con el ambiente activo. Si se abre otro terminal, se debe activar nuevamente el ambiente; no es necesario volver a crearlo.

#### 1.2 Configurar las credenciales de AWS

1. Iniciar sesión en la consola de AWS con el usuario IAM, no con la cuenta root
2. Buscar **IAM**, abrir **Users** y seleccionar el usuario utilizado para el laboratorio
3. Abrir **Security credentials** y localizar **Access keys**
4. Si no se dispone de una clave de acceso para el computador, seleccionar **Create access key**, escoger **Local code** y completar el asistente
5. Guardar el **Access key ID** y la **Secret access key** en el archivo local indicado a continuación; la clave secreta solo se muestra al crearla

El archivo se llama `credentials`, sin extensión, y se ubica dentro de la carpeta `.aws` del usuario del sistema operativo:

- **Windows:** `C:\Users\NOMBRE_USUARIO\.aws\credentials`
- **Linux:** `/home/NOMBRE_USUARIO/.aws/credentials`
- **macOS:** `/Users/NOMBRE_USUARIO/.aws/credentials`

Si la carpeta o el archivo no existen, se deben crear. El contenido para un usuario IAM con clave de acceso es:

```ini
[default]
aws_access_key_id = REEMPLAZAR_POR_ACCESS_KEY_ID
aws_secret_access_key = REEMPLAZAR_POR_SECRET_ACCESS_KEY
```

Si el archivo ya contiene credenciales, se debe revisar antes de modificarlo y conservar las configuraciones ajenas a esta actividad. Se utilizará la configuración `default` de la cuenta destinada al laboratorio.

Las credenciales no deben quedar dentro del repositorio ni incorporarse al código de Lambda. La clave de acceso permite operar con los permisos del usuario IAM y no solicita el MFA utilizado al ingresar a la consola. No se debe compartir ni incluir en capturas de pantalla.

#### 1.3 Comprobar la cuenta y la región

1. Copiar `config.example.json` como `config.local.json` en la misma carpeta, sin modificar sus valores
2. Reconocer los campos `deployment_name`, con valor `icc4203-lab12`, y `region`, con valor `sa-east-1`
3. Ejecutar la comprobación de acceso

```text
python scripts/deploy.py check
```

El resultado debe identificar la cuenta AWS, la identidad utilizada y la región de destino. Se debe comparar el número de cuenta con el que aparece en el menú de la cuenta, en la esquina superior derecha de la consola. Si no coincide, se debe corregir la configuración antes de continuar.

El archivo contiene la configuración local del despliegue, no las credenciales, y está excluido de Git. El nombre del despliegue debe conservarse al actualizar la aplicación.

### 2. Desplegar la infraestructura

**AWS CloudFormation** permite describir infraestructura en una plantilla y administrar conjuntamente los recursos definidos en ella. Un **stack** es el conjunto de recursos que CloudFormation crea y mantiene a partir de esa plantilla.

La plantilla describe los recursos y sus relaciones. El script Python prepara el código de Lambda, carga los archivos necesarios y solicita a CloudFormation la creación o actualización del stack. No se requiere crear manualmente cada servicio.

Para cargar el paquete de Lambda, el script crea previamente un bucket S3 auxiliar y privado. Su nombre aparece al consultar el estado del despliegue. Ese bucket no forma parte del stack, pero la herramienta también lo elimina durante la limpieza final.

#### 2.1 Revisar y ejecutar el despliegue

1. Abrir `template.yaml` en el editor de texto
2. Localizar `Resources` e identificar el bucket del sitio, la distribución CloudFront, la API, la función Lambda, el clúster DSQL y el rol de ejecución de Lambda
3. Localizar `Outputs`, donde se declaran los valores que se podrán consultar al terminar el despliegue
4. Ejecutar el despliegue

```text
python scripts/deploy.py deploy
```

La creación de los recursos puede tardar varios minutos. El comando debe permanecer en ejecución hasta informar su resultado. En esta etapa se crea la infraestructura y se publica el código; todavía no se ha preparado la tabla que utilizará la aplicación.

El paquete de Lambda se prepara para Linux y arquitectura x86_64, aunque el comando se ejecute desde Windows o macOS. Los archivos generados quedan en `.build/` y no se deben incorporar al repositorio. La función utiliza Python 3.14.

#### 2.2 Observar el stack en la consola

1. Abrir la consola de AWS y seleccionar **South America (São Paulo)** en el selector de región
2. Buscar **CloudFormation**, abrir **Stacks** y seleccionar `icc4203-lab12`
3. En **Events**, observar las operaciones de creación y actualizar la vista cuando sea necesario
4. En **Resources**, reconocer los recursos definidos en la plantilla y los identificadores asignados por AWS
5. Esperar que el stack alcance el estado **CREATE_COMPLETE**
6. Abrir **Outputs** e identificar la URL del sitio y el endpoint de DSQL

También se pueden consultar los resultados desde el terminal:

```text
python scripts/deploy.py status
```

Si el despliegue falla, se debe revisar en **Events** el motivo asociado al recurso que presenta el error. La existencia de algunos recursos no significa que el despliegue haya terminado correctamente.

### 3. Conectarse e interactuar con Aurora DSQL

**Amazon Aurora DSQL** es una base de datos relacional distribuida y serverless. Permite ejecutar SQL y utilizar clientes compatibles con PostgreSQL, sin seleccionar ni administrar un servidor de base de datos. Un **clúster** identifica la base de datos administrada por el servicio y dispone de un endpoint para establecer conexiones.

La compatibilidad con PostgreSQL permite reutilizar herramientas y parte del código, pero no implica que todas las funcionalidades y procedimientos se comporten de la misma manera. Se observarán diferencias en la autenticación y la preparación de tablas.

#### 3.1 Abrir una conexión desde la consola

1. Buscar **Aurora DSQL** en la consola de AWS y abrir el servicio
2. En **Clusters**, seleccionar el clúster cuyo endpoint coincide con el informado por el despliegue
3. Revisar que su estado sea **Active** e identificar su endpoint
4. Seleccionar **Connect with Query editor**
5. Establecer la conexión con ese clúster utilizando el rol de base de datos `admin`; si se solicita el nombre de la base de datos, utilizar `postgres`
6. Comprobar el clúster activo antes de ejecutar una consulta
7. Ejecutar la siguiente instrucción y observar el resultado

```sql
SELECT current_database(), current_user;
```

El nombre `postgres` corresponde a la base de datos a la que se establece la conexión. `admin` es el rol de administración dentro de DSQL; no es el nombre del usuario IAM que inició sesión en AWS. El [editor de consultas](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/getting-started-query-editor.html) permite ejecutar estas operaciones sin instalar un cliente SQL adicional.

#### 3.2 Crear una tabla y guardar un mensaje

1. Abrir `database/schema.sql` y revisar la definición de la tabla `mensajes`
2. Copiar la instrucción de creación en el editor SQL de DSQL y ejecutarla
3. Comprobar que la tabla aparezca en el explorador de objetos; actualizar la vista si es necesario

La tabla tiene tres columnas:

- **`id`**: identificador UUID del mensaje y clave primaria
- **`texto`**: contenido del mensaje
- **`creado_en`**: fecha y hora de creación

El UUID permite asignar un identificador desde la aplicación, sin depender de un contador de registros. En la siguiente inserción se utiliza un valor fijo para facilitar su identificación.

Ejecutar por separado la inserción:

```sql
INSERT INTO mensajes (id, texto, creado_en)
VALUES (
    '11111111-1111-4111-8111-111111111111',
    'Mensaje registrado desde la consola',
    CURRENT_TIMESTAMP
);
```

Luego consultar los registros:

```sql
SELECT id, texto, creado_en
FROM mensajes
ORDER BY creado_en;
```

La inserción se debe ejecutar una sola vez: repetirla con el mismo identificador produciría un conflicto de clave primaria. La consulta se puede repetir sin modificar los datos.

#### 3.3 Conectarse desde Python

En una instalación habitual de PostgreSQL se puede autenticar la conexión con un usuario y una contraseña de la base de datos. DSQL utiliza un token generado con una identidad IAM autorizada. Ese token se entrega al cliente SQL en el lugar de la contraseña; no corresponde a la contraseña de ingreso a la consola AWS.

1. Abrir el código de conexión en `backend/database.py`
2. Identificar dónde se obtiene el endpoint y dónde se genera el token mediante Boto3
3. Identificar la conexión del cliente PostgreSQL, el nombre de la base de datos, el usuario y la verificación TLS del servidor
4. Ejecutar el ejercicio de conexión

```text
python scripts/explore.py connection
```

El ejercicio consulta los mensajes existentes, inserta uno nuevo, confirma la escritura y cierra la conexión. Después, se debe repetir la consulta SQL desde la consola para comprobar que el nuevo mensaje quedó guardado. La confirmación mediante `commit` se encuentra en la función `transaction` de `backend/database.py`.

El token tiene una vigencia limitada para establecer conexiones. Si vence, se debe generar otro antes de abrir una nueva conexión; su vencimiento no interrumpe por sí mismo una conexión ya establecida. No debe guardarse como contraseña permanente ni mostrarse en los registros. La [autenticación de DSQL](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/authentication-authorization.html) combina los permisos IAM para conectarse con los permisos de la base de datos para operar sobre sus objetos.

#### 3.4 Separar la creación de tablas de la escritura de registros

Una transacción agrupa operaciones que se confirman con `COMMIT` o se descartan con `ROLLBACK`. En PostgreSQL es posible crear una tabla e insertar sus primeros registros dentro de una misma transacción. En DSQL, cada transacción admite una sola instrucción de definición de estructura y no permite combinarla con instrucciones que consultan o modifican los datos.

Para observar esta diferencia, ejecutar:

```text
python scripts/explore.py ddl
```

El programa utiliza una tabla auxiliar, independiente de `mensajes`, y realiza dos intentos:

1. Crear la tabla e insertar un registro dentro de una misma transacción: se debe observar el rechazo y el descarte de la transacción
2. Crear la tabla y confirmar esa operación antes de insertar el registro en otra transacción: se debe comprobar que ambas operaciones finalicen correctamente

Al terminar, el programa elimina únicamente su tabla auxiliar. Se debe revisar la función `ddl_exercise` en `scripts/explore.py` e identificar los límites de ambas transacciones. El error del primer intento es un resultado esperado del ejercicio, no un fallo del despliegue.

Esta diferencia afecta los scripts de preparación y las migraciones de esquema. No basta con que cada instrucción SQL sea válida por separado: también importa cómo se agrupan y confirman. La restricción está descrita en las [operaciones DDL de Aurora DSQL](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/working-with-ddl.html).

### 4. Integrar la aplicación con la base de datos

Hasta este punto, las operaciones se han ejecutado directamente desde la consola y desde el computador. Ahora se utilizará la misma tabla desde Lambda.

#### 4.1 Completar la preparación automatizada

Ejecutar:

```text
python scripts/deploy.py database
```

Este procedimiento comprueba la existencia de la tabla y la crea si falta, sin eliminar los mensajes existentes. También prepara el rol de base de datos `lab_app` y los permisos necesarios para consultar e insertar mensajes. Se puede repetir sin volver a cargar los registros.

La creación del clúster por CloudFormation y la preparación de sus tablas son operaciones distintas. Crear un rol IAM tampoco equivale a otorgarle permisos SQL: la preparación debe asociar el rol de ejecución de Lambda con un rol de base de datos autorizado.

La administración local utiliza `admin`, mientras que Lambda utiliza un rol de base de datos con permisos acotados a sus operaciones. La función obtiene las credenciales temporales de su rol de ejecución; no debe contener la clave de acceso configurada en el computador.

#### 4.2 Comprobar el recorrido completo

1. Ejecutar `python scripts/deploy.py status` y copiar la URL HTTPS del sitio
2. Abrirla en el navegador y comprobar que aparezcan los mensajes registrados durante los ejercicios anteriores
3. Escribir un mensaje nuevo desde el formulario y enviarlo
4. Recargar la página y comprobar que el mensaje permanezca disponible
5. Volver al editor SQL y ejecutar la consulta de la tabla `mensajes`
6. Comprobar que el registro creado desde el navegador también aparezca en la consulta

La página no se conecta directamente a DSQL. Envía una solicitud HTTP a la API y Lambda ejecuta la operación sobre la base de datos.

#### 4.3 Revisar el código y los registros de ejecución

1. Abrir `backend/lambda_function.py` e identificar el tratamiento de las solicitudes de lectura y escritura
2. Seguir la llamada al módulo de acceso a la base de datos e identificar la consulta SQL, sus parámetros y la confirmación de la escritura
3. En la consola, abrir **CloudFormation → Stacks → icc4203-lab12 → Resources** y localizar la función Lambda
4. Abrir la función, seleccionar **Monitor** y luego **View CloudWatch logs**
5. Abrir el flujo de registros reciente y localizar las ejecuciones correspondientes a las solicitudes realizadas

Los registros deben permitir reconocer las operaciones y los errores sin mostrar credenciales ni tokens de conexión. No se requiere modificar el handler ni implementar nuevas rutas.

### 5. Actualizar el despliegue conservando los datos

1. Registrar la URL del sitio y consultar los mensajes existentes
2. Abrir `website/index.html` y modificar el título visible de la página
3. Ejecutar nuevamente el despliegue

```text
python scripts/deploy.py deploy
```

4. Observar el resultado desde el terminal y revisar el stack en CloudFormation; si la plantilla no requiere cambios, CloudFormation puede informar que no hay actualizaciones de infraestructura
5. Esperar que el comando termine, abrir la misma URL y recargar la página para comprobar el cambio de título
6. Comprobar que los mensajes anteriores continúen disponibles

El despliegue publica los archivos modificados y espera la actualización de la caché de CloudFront. No se debe cambiar el nombre del stack ni eliminarlo para realizar esta actualización: eso correspondería a otro despliegue. Tampoco se deben repetir los ejercicios SQL ni la carga de mensajes.

### 6. Eliminar los recursos

La eliminación del despliegue borra la base de datos y sus mensajes, además de los archivos y servicios creados para la actividad. Antes de continuar, se debe comprobar que el nombre del stack y la cuenta correspondan al laboratorio.

1. Ejecutar la eliminación y revisar los recursos que informa el programa antes de confirmar

```text
python scripts/deploy.py delete
```

2. Esperar que el procedimiento termine; cerrar el terminal no sustituye esta comprobación
3. Abrir CloudFormation y comprobar que el stack haya sido eliminado; si se consulta entre los stacks eliminados, debe figurar como **DELETE_COMPLETE**
4. Verificar en Aurora DSQL que el clúster ya no exista y comprobar que no queden buckets ni otros recursos auxiliares creados por las herramientas del laboratorio
5. Una vez eliminados los recursos, buscar **IAM** en la consola de AWS, abrir **Users** y seleccionar el usuario utilizado en el laboratorio
6. Abrir **Security credentials** y localizar **Access keys**. Identificar la clave creada para esta actividad comparando su **Access key ID** con el valor `aws_access_key_id` del archivo local `credentials`
7. En esa clave, seleccionar **Actions → Deactivate**, confirmar la operación y comprobar que su estado sea **Inactive**
8. Seleccionar **Actions → Delete** en la misma clave y completar la confirmación solicitada por la consola
9. Comprobar que la clave ya no aparezca en **Access keys**
10. Retirar del archivo local `credentials` los valores `aws_access_key_id` y `aws_secret_access_key` correspondientes a esa clave. Si se descargó un archivo CSV al crearla, eliminar también esa copia, sin alterar otras credenciales del computador

**La limpieza incluye desactivar y eliminar en AWS la clave de acceso creada para el laboratorio.** Eliminar el stack no elimina esa clave, y borrar sus valores del computador no la desactiva en AWS. Esta operación se realiza al final, porque los comandos de eliminación de infraestructura todavía requieren acceso a la cuenta.

Si se utilizó una clave preexistente que también se ocupa en otras actividades, no se debe eliminar como parte de este laboratorio.

No se debe eliminar el usuario IAM ni su dispositivo MFA. Ambos podrán utilizarse en actividades posteriores.
