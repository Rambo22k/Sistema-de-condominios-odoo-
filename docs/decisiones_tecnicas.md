# Decisiones técnicas

## Fundación

- La solución vive en módulos instalables de Odoo; no se crea una API, aplicación separada ni almacenamiento paralelo.
- `kabay_base` depende de `base` y reutiliza `res.company` para la compañía administradora/facturadora.
- Los modelos son `kabay.condominium`, `kabay.building`, `kabay.apartment` y `kabay.apartment.photo`.
- La compañía se propaga desde condominio a edificio, apartamento y fotografía mediante campos relacionados almacenados.
- Se usan restricciones SQL para códigos únicos dentro del ámbito de cada padre y validaciones ORM para evitar relaciones cruzadas.
- Los registros tienen `active` para archivar y conservar historial.
- Las fotos se guardan como binarios de adjunto privado; el límite de diez se valida en servidor al crear y mover fotos. Se bloquea la fila del apartamento durante el conteo para evitar superar el límite con solicitudes simultáneas.
- Los grupos Kabay tienen ACL diferenciadas y reglas de compañía. Administrador incluye los cuatro roles funcionales, para dar acceso consistente a menús y operaciones administrativas de los módulos; los usuarios con roles funcionales independientes conservan solo los permisos de su rol. Las reglas multiempresa limitan todos los registros a las compañías permitidas. Solo Administración escribe estructura y relaciones; ningún rol tiene permiso de eliminación de estructura.
- Las vistas se expresan como vistas list/form/search estándar, con menús y acciones desde XML.

## Relaciones de residentes

- `kabay_residents` reutiliza `res.partner` y crea `kabay.apartment.relation`; no extiende ni modifica facturas y no depende de `account`.
- La relación conserva persona, unidad, rol, fechas, participación, estado y compañía. Confirmadas y finalizadas congelan los datos de identidad/fechas/participación; la finalización fija la fecha final y conserva el registro.
- Se rechazan períodos inclusivos solapados para el mismo contacto, unidad y rol. Una restricción SQL rechaza duplicados exactos y el bloqueo de la unidad serializa escrituras concurrentes antes de validar solapamientos.
- Coexisten roles distintos, incluso para la misma persona, porque la especificación permite convivencia entre roles y no define pares incompatibles. Esta regla se debe confirmar con el negocio.
- Las participaciones son opcionales. Si se registra alguna participación para propietarios que comparten un período, todas las relaciones de propietario activas en cada tramo deben indicar porcentaje y sumar 100 % antes de confirmar.
- `company_id` de la relación se hereda desde la unidad; un contacto global es válido y un contacto ligado a otra compañía se rechaza.
- Las fichas de apartamento y contacto muestran la misma relación desde lados opuestos. La aplicación no crea usuarios portal ni comparte facturas o adjuntos.

## Compatibilidad y evidencia

La instalación verificada informa Odoo `19.0-20261112` y PostgreSQL `17.12`. `kabay_base` y `kabay_residents` quedaron instalados en `kabay_dev`; la última ejecución hizo 21 pruebas, con 0 fallos y 0 errores. El respaldo previo a cambios está en `backups/kabay_dev_pre_residents.dump`.
