# Dispatch · proyecto de ejemplo de Code Checker

Ejemplo Python pequeño y ejecutable de preparación de pedidos. Sus métricas se calculan desde estos archivos; no hay evaluaciones ni informes de tests precargados.

## Recorrido

API → servicio de pedidos → reglas de precios + repositorio → notificación.

## Contratos

- Los importes se expresan en céntimos, siempre enteros no negativos.
- Una línea debe tener cantidad positiva. Un pedido necesita al menos una línea.
- La clave de idempotencia identifica una única operación de creación de pedido.
- Repetir la clave debe devolver el pedido original, sin duplicar la notificación.
- La notificación se produce después de guardar el pedido.

El servicio legacy conserva una implementación con responsabilidades mezcladas para contrastar resultados. No se debe asumir que cumple todos los contratos. Los tests incluidos cubren solo algunas reglas; no hay garantía de cobertura completa.

Ejecutar desde esta carpeta: `python -m unittest discover -s tests`.
