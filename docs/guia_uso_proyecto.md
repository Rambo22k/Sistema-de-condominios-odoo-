# Guía paso a paso — Kabay Group

Esta guía cubre preparación local, primer acceso y recorrido funcional. Para requisitos del host, instalación y estructura del código, consulta el `README.md`.

## A. Preparar una computadora

1. Instala Docker Desktop o Docker Engine con Docker Compose v2.
2. Asegura acceso licenciado a Odoo Enterprise 19 y descarga los addons Enterprise en una carpeta local. El repositorio no distribuye esos archivos.
3. Clona el repositorio y ejecuta el script de preparación:
   - Windows: `./scripts/setup.ps1`
   - Linux/macOS: `sh scripts/setup.sh`
4. Edita `.env`: coloca contraseñas aleatorias propias, puertos disponibles y la ruta absoluta local a Enterprise.
5. Edita `config/odoo.conf`: usa el mismo usuario/contraseña de PostgreSQL que `.env` y una contraseña maestra distinta.
6. Valida y arranca:

   ```sh
   docker compose config --quiet
   docker compose up -d
   docker compose ps
   ```

7. Abre `http://localhost:18020/web/database/manager` y crea la base cuyo nombre aparece en `POSTGRES_DB`.
8. Entra en `http://localhost:18020/web/login` con la cuenta administrativa creada para esa base.
9. En **Aplicaciones**, instala los módulos Kabay en este orden si se instalan manualmente: Base, Residentes, Facturación, Financiamiento, Depósitos, Avisos, Helpdesk, Portal, Reportes y Notificaciones. Conserva instalados los módulos Odoo requeridos por cada addon.

La instalación inicial de módulos y una restauración de base son operaciones administrativas. No restaures backups dentro de una base con datos que quieras conservar.

## B. Preparar la compañía

1. Selecciona la compañía en la barra superior.
2. Completa nombre legal, dirección, país, moneda y datos fiscales solamente con información aprobada.
3. En Contabilidad, revisa diarios de venta y banco, cuentas contables, productos, impuestos y posiciones fiscales.
4. Configura secuencias de facturación y restricciones por compañía.
5. Crea o revisa el condominio, edificios y unidades. Confirma que cada unidad pertenezca a la compañía correcta.

No uses una compañía de otra jurisdicción para emitir cobros. La localización instalada no valida por sí sola el tratamiento fiscal.

## C. Residentes y Portal

1. Crea o valida el contacto del residente.
2. Registra una relación a la unidad con rol y fechas correctas.
3. Confirma la relación; las relaciones vigentes controlan las unidades y avisos que puede ver.
4. Desde el contacto/usuario, concede acceso Portal. No agregues grupos internos ni contables al residente.
5. El administrador establece la contraseña desde Odoo o usa el flujo de recuperación que esté habilitado.
6. En una ventana privada, inicia sesión y abre `/my/kabay`.
7. Recorre **Unidades**, **Facturas**, **Financiamiento**, **Depósitos**, **Avisos** y **Solicitudes**. Revisa que el residente no pueda acceder a unidades o documentos de otro contacto.

## D. Facturación y cobros

1. En Kabay Billing, revisa regla de cobro, responsable, unidad, período e importe.
2. Genera la factura usando producto, diario, cuentas e impuestos validados por Finanzas.
3. Revisa borrador, compañía, contacto, moneda, impuestos y saldo antes de publicar.
4. En Portal, el residente informa el depósito y adjunta comprobante. La declaración no es un pago.
5. Finanzas busca la línea de extracto correcta y comprueba compañía, moneda, importe, fecha y referencia.
6. Finanzas verifica la declaración y aplica el pago por la acción de Depósitos. El módulo usa el registro de pagos y la conciliación estándar de Odoo.
7. Confirma que el asiento quedó conciliado y que el estado de pago de la factura cambió.

Una factura no se considera pagada hasta que Contabilidad confirme el pago y conciliación. No uses movimientos simulados como evidencia bancaria real.

## E. Avisos, Helpdesk, reportes y comunicación

1. **Avisos:** crea el contenido, elige compañía/condominio/alcance y publica. Verifica destinatarios y lectura desde Portal.
2. **Helpdesk:** revisa equipo y categoría. Responde públicamente cuando el residente deba verla; usa nota interna para comunicación privada del personal.
3. **Reportes:** filtra por compañía y período; compara facturación, saldos, pagos conciliados, financiamiento y operación sin modificar cifras fuente.
4. **Notificaciones:** revisa preferencias, plantillas, cron, cola y servidor. Prueba SMTP solo con un buzón controlado y autorizado; distingue aceptación SMTP de recepción confirmada.

## F. Cierre diario y mantenimiento

1. Revisa `docker compose ps` y los logs con `docker compose logs -f kabay-sdc-odoo`.
2. Haz backups de base y filestore con un procedimiento aprobado, fuera de Git.
3. `docker compose down` detiene servicios y conserva datos. `docker compose down -v` elimina volúmenes y puede borrar base/filestore: no lo ejecutes como cierre rutinario.
4. Para presentar desde otro equipo, configura red autorizada, proxy inverso, HTTPS y URL base; los puertos actuales están ligados a loopback.
