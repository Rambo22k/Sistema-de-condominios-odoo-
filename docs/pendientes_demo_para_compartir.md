# Pendientes para una demo comercial de Kabay Group

Estado resumido para coordinación de la presentación. La instancia local tiene los diez módulos Kabay instalados y sus flujos cubiertos por pruebas. La base `kabay_dev` actualmente no contiene condominios, residentes, facturas ni movimientos bancarios de QA; el repositorio no incluye datos semilla. Antes de una demostración hay que cargar fixtures QA aprobados. La demostración de cobros también depende de validaciones contables y fiscales.

## Antes de presentar

1. **Preparar los datos de demo:** cargar registros QA claramente ficticios de compañía, condominio, edificio, unidades y residentes; luego establecer la contraseña del usuario Portal y comprobar una sesión autenticada.
2. **Validar facturación con Finanzas/contador:** confirmar compañía, cuentas, producto, impuestos y requisitos de documento fiscal. No publicar cargos hasta tener esa decisión.
3. **Cerrar el recorrido de pagos QA:** usar una factura demo publicada y aprobada, declarar un depósito, verificar una línea bancaria QA cargada expresamente para la prueba, aplicar el pago estándar y revisar la conciliación/estado. Todo movimiento simulado debe identificarse como ficticio; no representa dinero real.
4. **Revisar acceso del equipo financiero:** confirmar los permisos mínimos para revisar/aplicar depósitos y responder tickets desde el perfil de Finanzas.
5. **Terminar pruebas de aceptación:** ejecutar las pruebas HttpCase y una regresión dirigida en un entorno de prueba aislado; revisar acceso permitido/denegado, recibos, pagos, reportes y protecciones contables.
6. **Probar la entrega de correo:** elegir un buzón controlado, comprobar SMTP, cola, plantillas, cron y recepción real. La configuración activa por sí sola no demuestra entrega.
7. **Validar dashboard visualmente:** revisar escritorio y móvil con sesiones separadas de Residente, Finanzas y Gerencia.
8. **Definir financiamiento de muestra:** aprobar precio, inicial, periodicidad, intereses y plan de cuotas antes de crear un contrato QA.
9. **Preparar acceso de presentación:** hoy el servicio es local. Si se comparte desde otra computadora, definir red, dominio, HTTPS, proxy confiable y política de acceso.
10. **Dejar reversión documentada:** acordar cómo revertir el asiento bancario simulado y cualquier pago QA sin borrar movimientos contables.

## Criterios de cierre

- Residente inicia sesión y solo ve sus unidades y documentos.
- Factura de demo publicada bajo configuración contable/fiscal aprobada.
- Depósito QA validado y aplicado por el procedimiento estándar; conciliación y reportes coherentes.
- Avisos, ticket, respuesta pública y privacidad de notas comprobados desde Portal y backend.
- Correo confirmado en buzón controlado, o limitación presentada con claridad.
- Registros QA inventariados y la información real de otros residentes protegida.

No presentar la operación bancaria simulada como dinero recibido ni llamar pagada a una factura hasta que el asiento esté aplicado y conciliado en Odoo.
