# Kabay Group — Odoo 19

Sistema modular para administración de condominios sobre Odoo 19 Enterprise, PostgreSQL y Docker Compose. Los addons propios están en `addons/extra/`. El repositorio no contiene los addons propietarios de Odoo Enterprise, secretos ni una base de datos.

## Requisitos

- Docker Desktop con Docker Compose v2, o Docker Engine/Compose v2 en Linux.
- Acceso licenciado a los addons de Odoo Enterprise 19; deben estar instalados localmente y no se incluyen aquí.
- Una máquina compatible con la imagen `linux/amd64` usada por Odoo.

## Inicio rápido

1. Clona el repositorio.
2. Prepara los archivos locales sin sobrescribir los existentes:
   - Windows PowerShell: `./scripts/setup.ps1`
   - Linux/macOS: `sh scripts/setup.sh`
3. Edita `.env` y `config/odoo.conf`: define una contraseña PostgreSQL larga, copia ese mismo valor en `db_password`, cambia `admin_passwd` por otra clave y configura `ODOO_ENTERPRISE_ADDONS_PATH` con la ruta local licenciada.
4. Valida y levanta el stack:

   ```sh
   docker compose config --quiet
   docker compose up -d
   docker compose ps
   ```

5. Abre `http://localhost:18020/web/database/manager`, crea la base indicada por `POSTGRES_DB` y después entra a `/web/login`.
6. En **Aplicaciones**, instala los addons Kabay. Odoo instalará automáticamente sus dependencias disponibles.

Los puertos publicados por defecto son Odoo `18020`, eventos Odoo `16020` y PostgreSQL `15220`, enlazados solo a `127.0.0.1`. Puedes cambiarlos en `.env`. No publiques PostgreSQL en una red externa.

## Recorrido funcional

1. Configura la compañía y sus datos contables aprobados.
2. Crea condominios, edificios y apartamentos.
3. Registra y confirma las relaciones vigentes de residentes.
4. Usa Facturación para generar cargos y facturas según las reglas del condominio.
5. Usa Depósitos para que residentes declaren comprobantes; Finanzas coteja el movimiento bancario y aplica pagos mediante Contabilidad estándar de Odoo.
6. Publica Avisos y atiende solicitudes desde Helpdesk.
7. Consulta los indicadores de Finanzas y Gerencia en Reportes.
8. Revisa Comunicaciones/Notificaciones y la cola de correo. Configura SMTP solo con datos autorizados y prueba primero en un buzón controlado.

El Portal requiere un usuario Portal ligado a un contacto y a una relación residencial vigente. Para cobros dominicanos, valida con Finanzas el producto, impuestos, cuentas y configuración fiscal antes de publicar facturas. El repositorio no incluye datos semilla: identifica como QA los registros y movimientos bancarios simulados que cargues; no representan operaciones reales.

## Operación frecuente

```sh
docker compose ps
docker compose logs -f kabay-sdc-odoo
docker compose logs -f kabay-sdc-db
docker compose restart kabay-sdc-odoo
docker compose down
```

`docker compose down` conserva los volúmenes. **No uses `docker compose down -v`** si quieres mantener la base y el filestore. Para una copia de seguridad, utiliza los procedimientos de Odoo/PostgreSQL y guarda los archivos fuera del repositorio.

## Estructura

- `addons/extra/`: módulos Kabay.
- `compose.yaml`: servicios Odoo/PostgreSQL, puertos, volúmenes y red local.
- `config/odoo.conf.example`: plantilla de configuración Odoo.
- `.env.example`: plantilla de variables locales.
- `postgres-config/`: configuración PostgreSQL usada por el stack.
- `scripts/`: preparación inicial no destructiva para Windows y POSIX.
- `docs/`: arquitectura, guía paso a paso y pendientes de demo compartibles.

## Seguridad y límites de distribución

No subas `.env`, `config/odoo.conf`, backups, logs, filestore, datos personales, contraseñas ni los addons Enterprise. Las plantillas de configuración sí se versionan; los archivos locales reales están ignorados por Git. El README y los documentos compartibles no sustituyen revisión legal, fiscal o de seguridad antes de producción.
