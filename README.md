# Code Checker

Herramienta local para explorar proyectos Python y evaluar cómo pueden evolucionar mediante agentes. Integra mapa de dependencias, código, métricas, documentación, evaluación del modelo y registros de ensayos.

## Abrir en Windows

Clona este repositorio y abre PowerShell en su carpeta:

```powershell
.\start.ps1
```

Dirección predeterminada: <http://127.0.0.1:8873>. El servidor escucha exclusivamente en loopback. El script crea un entorno virtual e instala las dependencias si todavía no existe. Usa `-Port 8874` si el puerto está ocupado, o `-NoBrowser` para no abrir un navegador. Ctrl+C detiene una sesión iniciada en primer plano.

Instalación manual reproducible:

```powershell
# Desde la carpeta del repositorio clonado
python -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install -r requirements-lock.txt
& '.\.venv\Scripts\python.exe' -m uvicorn code_checker.app:app --host 127.0.0.1 --port 8873
```

Requiere Python 3.11 o posterior. Esta entrega se comprueba con Python 3.13 en Windows.

## Linux y macOS

Desde la carpeta del repositorio:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn code_checker.app:app --host 127.0.0.1 --port 8873
```

Abre `http://127.0.0.1:8873/`. La validación principal de esta versión se ha realizado en Windows.

## Privacidad

Este repositorio contiene la herramienta, sus tests y un ejemplo sintético. No incluye análisis de proyectos reales, accesos a servidores, credenciales ni material de referencia privado. Cada usuario configura su propio SSH, GitHub CLI y proveedor de modelos. Consulta [SECURITY.md](SECURITY.md) antes de analizar código sensible; la evaluación lazy puede enviar contexto al modelo cuando está activada.

## Recorrido de uso

1. Pulsa **Abrir proyecto** e introduce la ruta absoluta de una carpeta Python, o abre **Explorar ejemplo Python** en la pantalla inicial.
2. Selecciona un módulo en el mapa. Usa el explorador lateral para abrir clases y funciones. Puedes buscar, mover el mapa, ampliar, mostrar tests y dependencias externas.
3. Examina **Código** y **Métricas**. El análisis no importa ni ejecuta módulos del proyecto seleccionado.
4. En **Evaluación**, inspecciona el paquete de contexto y pulsa **Evaluar componente**. Aparecen el color, las cinco dimensiones, hallazgos con referencias, límites y próximas comprobaciones.
5. En **Consultar**, pregunta sobre el componente o pide una propuesta de ensayo. Son consultas de lectura; no aplican cambios al repositorio. Cada pregunta es independiente, acompañada del paquete de evidencia.
6. En **Evidencias**, importa un JSON de coverage.py o registra una tarea con criterios de aceptación y resultados. Los registros mantienen su procedencia declarada.
7. La interfaz comprueba cambios en archivos cada 20 segundos y actualiza el mapa cuando no hay evaluaciones en curso. También puedes volver a analizar con ↻. Las evaluaciones afectadas quedan marcadas como desactualizadas. La invalidación es conservadora a nivel de proyecto.
8. **Exportar** descarga el análisis con fuentes, métricas, evaluaciones y registros como JSON. Los proyectos y evaluaciones permanecen disponibles tras reiniciar.

**Evaluar mapa** procesa hasta 12 módulos visibles por acción y reutiliza resultados válidos del mismo perfil y contexto cuando se ha especificado un modelo. Si se utiliza el predeterminado del CLI se vuelve a evaluar, porque su identidad puede cambiar entre versiones. Usa la búsqueda para acotar el siguiente grupo en proyectos grandes. La evaluación de cada componente también está disponible individualmente.


## Proyectos remotos por SSH y navegación lazy

En la barra superior escribe el alias SSH (por ejemplo `my-server`) y la ruta absoluta (`/srv/projects/my-python-app`), y pulsa **Conectar y analizar**. Se reutiliza OpenSSH con autenticación ya configurada; la aplicación no pide ni guarda contraseñas.

El análisis AST se ejecuta en memoria en el servidor mediante `python3 -I -`. Radon y el analizador viajan por stdin; no se instalan dependencias, no se crean archivos de trabajo en el servidor y no se importa ni ejecuta código del proyecto. Las consultas Git usan `--no-optional-locks`. Se leen fuentes y metadatos; no se ejecutan tests, scripts administrativos ni despliegues.

El índice local conserva estructura, métricas, hashes y evaluaciones, **sin cuerpos de fuentes ni documentos** del proyecto SSH. Los fragmentos necesarios para el inspector o el modelo llegan bajo demanda y no se persisten como fuentes. Los textos de evaluación sí se conservan y pueden describir o citar fragmentos. Los fragmentos enviados a Codex CLI siguen el mismo tratamiento del proveedor que cualquier evaluación de código; SSH no convierte al modelo en un modelo local.

La raíz muestra paquetes. **Un clic** selecciona una caja; **doble clic** abre su siguiente nivel: paquetes, módulos, clases y funciones. **Subir nivel** vuelve al padre. Cada página contiene como máximo 12 cajas; la paginación conserva el resto del nivel sin iniciar evaluaciones de páginas no visibles.

Con **Evaluación lazy** activada, el modelo evalúa secuencialmente solo las cajas de la página visible. Al cambiar de nivel deja de iniciar trabajo del anterior; una petición ya enviada puede terminar y quedar en caché. Se puede pausar la evaluación automática. Los colores de paquetes son juicios sobre su estructura y contratos visibles, no una media de los colores de sus hijos ni una auditoría de sus cuerpos. Un gris justificado por contexto insuficiente también es un resultado válido.

Los resultados válidos del mismo modelo, política y versión se reutilizan. El refresco comprueba el servidor remoto cada 20 segundos cuando no hay análisis/evaluación en curso. Si cambia una fuente o documento del ámbito, se vuelve a indexar y se invalidan las evaluaciones anteriores.

Ámbito remoto actual: Python de la raíz y de `src`, `scripts`, `tests`, `test`, `tools`, `deploy`; documentos de esas carpetas y de `docs/03_current_architecture`, `docs/06_reference`, `docs/11_testing_and_qa`. Se excluyen entornos virtuales, enlaces simbólicos, logs, datos y auditorías históricas. El recorrido directo incluye archivos ignorados por Git dentro de ese ámbito. Es un ámbito de trabajo explícito, no una lectura de todos los archivos del servidor.

Se requiere Python 3.10 o posterior en el servidor. Si el servidor está inaccesible o un archivo cambia antes de leerse, se muestra un error y no se inventa un resultado.

## Modelos

### Codex CLI

Se utiliza una instalación existente de Codex CLI y su sesión autenticada. No se copian credenciales a la aplicación. Verificación manual:

```powershell
codex login status
```

El perfil inicial utiliza **gpt-6-luna**. Puedes cambiarlo en **Configurar modelo**; los resultados conservan el identificador utilizado. Si dejas el modelo vacío, se usa el predeterminado del CLI en las peticiones manuales.

Al evaluar o consultar se envía al proveedor el paquete mostrado: código del componente, métricas, fragmentos de documentación y contexto relacionado. Se ejecuta `codex exec` con salida JSON estructurada, configuración de usuario omitida, carpeta temporal y sandbox de solo lectura. El prompt solicita exclusivamente interpretación, sin herramientas ni ediciones. Además se desactivan shell/unified_exec, conectores, plugins, hooks, navegador, computer use, subagentes y otras herramientas del evaluador. El modelo interpreta el paquete; el transporte SSH pertenece a la aplicación. La cuenta SSH existente no se modifica ni se convierte en una cuenta con permisos distintos.

Cada petición tiene un límite de cinco minutos. Solo se ejecuta una evaluación a la vez; hasta cinco trabajos pueden estar pendientes. Errores de autenticación, límites del proveedor o JSON inválido se muestran sin inventar resultados de reemplazo.

Referencia: [modo no interactivo de Codex](https://developers.openai.com/codex/noninteractive/).

### Ollama

Selecciona Ollama e indica un modelo instalado en un servicio HTTP de loopback, normalmente `http://127.0.0.1:11434`. El modelo debe admitir el esquema de salida solicitado. El adaptador envía una petición `/api/chat` y valida el resultado con el mismo esquema y catálogo de evidencias.

No se instala ni descarga ningún modelo local automáticamente. Los errores del servicio se muestran como fallos de evaluación. La comprobación de entrega puede utilizar Codex sin que ello pruebe la disponibilidad de Ollama en esta máquina.

## Qué significa el color

El modelo evalúa **contratos, contexto, verificabilidad, observabilidad y localidad del cambio**. Ciclomática o tamaño elevados no determinan el color.

| Estado | Interpretación |
| --- | --- |
| Verde | Condiciones favorables justificadas dentro del contexto revisado |
| Amarillo | Fricción localizada |
| Naranja | Obstáculos importantes |
| Rojo | Obstáculos graves concretos |
| Gris | No hay evaluación válida o suficiente; también se usa para resultados desactualizados |

Todas las evaluaciones LLM de esta versión son **predictivas**. Los ensayos registrados son evidencia declarada por el usuario; el sistema no afirma haber ejecutado, observado o verificado independientemente esas tareas.

El esquema de salida limita `evidence_refs` a los identificadores del paquete actual, tanto en hallazgos como en dimensiones. Por ejemplo, un paquete puede citar `package.children`, pero no `component.source` si esa evidencia no está incluida. También se valida la respuesta recibida: cinco dimensiones, colores válidos y referencias existentes. Esta validación no demuestra que todas las interpretaciones del modelo sean correctas. Los hallazgos siempre se pueden contrastar con el contexto.

La rúbrica distingue las condiciones de trabajo de agentes de la dificultad cognitiva para una persona: necesita contratos explícitos, contexto acotado y señales verificables.

## Métricas y alcance

- AST de Python y Radon 6.0.1 para complejidad ciclomática por función, clases, parámetros, anotaciones, anidamiento y declaraciones globales.
- Grafo de **imports**, no de llamadas. Imports de tipado y condicionales se distinguen. Los externos permanecen separados; “externo” significa no resuelto dentro de la carpeta seleccionada, no necesariamente una librería de terceros.
- Ciclos de imports normales mediante componentes fuertemente conexos. No se incluyen aristas exclusivas de tipado o condicionales en ese cálculo.
- Los posibles efectos se detectan por nombres de llamadas; se etiquetan como candidatos heurísticos.
- Los docstrings son contexto, no pruebas de cumplimiento de contratos. Las anotaciones no garantizan tipos en ejecución.
- El anidamiento se calcula sobre AST; `elif` puede incrementar profundidad. No se presenta como Cognitive Complexity de Sonar.
- Los ámbitos anidados conservan componentes propios. No se suman sus medidas sin explicar el alcance.
- Máximo 1.500 archivos Python, 500 KB por archivo y un presupuesto de 20 MB de fuentes. Omisiones y errores aparecen en el análisis.
- Hasta 100 documentos Markdown, 12.000 caracteres por documento. El contexto del modelo incluye hasta ocho documentos, 4.000 caracteres por documento, y hasta 28.000 caracteres del componente, con truncamientos explícitos.
- En mapas grandes se muestran hasta 120 módulos simultáneos y 30 dependencias externas; la búsqueda permite acotar. El informe conserva el análisis completo dentro de los límites de extracción.
- Se excluyen entornos virtuales, dependencias, repositorios Git, archivos generados habituales y enlaces simbólicos.

## Cobertura y ensayos

Para producir un informe con herramientas instaladas en el entorno del proyecto que se desea comprobar, un ejemplo es:

```text
python -m coverage run --branch -m pytest
python -m coverage json -o coverage.json
```

La aplicación no ejecuta estos comandos automáticamente. Importa un informe JSON con rutas relativas a la raíz seleccionada, o rutas absolutas de esa raíz. La cobertura de funciones se atribuye por rango de líneas y puede incluir cuerpos anidados. No tener informe significa desconocido, no cero. Se muestran numeradores, denominadores y ramas no medidas.

El formato coverage.json no prueba por sí solo la revisión exacta del código: la aplicación declara esa limitación y asocia la importación al análisis elegido por el usuario. Al cambiar el proyecto se retira la asociación vigente.

Los ensayos incluyen tarea, perfil, aceptación, evidencia, intentos, regresiones, intervenciones y tokens/tiempo opcionales. No se mezclan esos registros con resultados de benchmarks propios ni se deducen probabilidades de éxito universales.

Mutation testing, ejecución automática de tareas en copias aisladas, edición de código desde el mapa y comparación estadística entre perfiles son extensiones posteriores. Esta versión permite preparar esas tareas y conservar sus evidencias; no simula su ejecución.

## Datos locales

Los análisis se guardan en `.codechecker/`, dentro de la carpeta de esta herramienta. Puede cambiarse con la variable `CODE_CHECKER_DATA` antes de arrancar. El almacenamiento contiene fragmentos de código y documentos, por lo que debe tratarse como parte de tus datos de proyecto.

El perfil elegido se guarda en el navegador sin claves. Los jobs son transitorios: si se interrumpe el servidor, se puede volver a solicitar la evaluación. Las evaluaciones completadas se guardan atómicamente en JSON.

## Comprobaciones del proyecto

Las métricas se calculan al analizar, sin Codex CLI ni otro modelo, también por SSH. La pestaña **Métricas** está disponible aunque la evaluación lazy esté pausada. Incluye tamaño, funciones/clases, sentencias y llamadas AST, complejidad ciclomática (Radon), anidamiento, proporciones de parámetros/retornos anotados y funciones documentadas, dependencias de entrada/salida, imports no resueltos, módulos en ciclos, imports desde módulos de test, `assert`, `raise`, manejadores `except`, candidatos a logging y declaraciones `global`/`nonlocal`.

Los agregados recorren ámbitos AST sin contar dos veces los cuerpos anidados. Las dependencias de paquetes cuentan módulos únicos fuera de la frontera, no la suma de dependencias de los hijos. Las dependencias de un módulo no se atribuyen automáticamente a funciones. Las líneas físicas incluyen comentarios y blancos. Tests se identifican por rutas `test`/`tests` o nombres `test_*.py`/`*_test.py`; logging es una heurística por nombre. Presencia de tipos o docstrings no mide su calidad. Los denominadores vacíos son no aplicables, no cero.

El modelo recibe estas medidas ya calculadas y solo interpreta su significado en la rúbrica. La cobertura requiere un informe importado; latencia real, rendimiento, éxito de agentes y calidad de contratos no se infieren de estos contadores. No se ejecutan tests ni código del proyecto inspeccionado. Al cambiar la versión del analizador se solicita un nuevo análisis y se invalidan evaluaciones basadas en evidencia anterior.

```powershell
# Desde la carpeta del repositorio clonado
& '.\.venv\Scripts\python.exe' -m pytest -q
node --check web/app.js
node --test tests/test_graph_routing.cjs
node --test tests/test_python_highlight.cjs
node --test tests/test_inspector.cjs
```

Los tests verifican resolución de imports relativos, ciclos y tipado, ámbitos anidados, no ejecución de fuentes, cobertura ausente frente a cero, invalidación por documentación, acotación del contexto y el flujo HTTP de análisis/persistencia/exportación.

El ejemplo `examples\dispatch` incluye tests propios que se ejecutan desde esa carpeta con `python -m unittest discover -s tests`.

La prueba reproducible `python verification/probe_legacy_contract.py` termina deliberadamente con código 1 porque confirma un incumplimiento de idempotencia en el ejemplo `legacy`; es independiente de la suite de la herramienta.

Los tests usan proyectos temporales y un transporte SSH simulado; no necesitan acceso a un servidor privado.

El mapa muestra por defecto las flechas de la caja seleccionada: azul para sus dependencias y violeta para quienes la usan. El selector **Flechas** permite ver todas las conexiones o esconderlas. Los recorridos van por los huecos entre cajas, con fondos opacos para mantener legible el contenido. Los contadores se limitan a las cajas visibles en la página actual; no representan todas las dependencias del proyecto. Un clic selecciona y el doble clic sigue abriendo el siguiente nivel por SSH.

La pestaña **Código** resalta la sintaxis Python y conserva los números de línea del archivo. **Ampliar código** abre un visor de casi toda la ventana, con tamaño de letra ajustable y ajuste opcional de líneas largas. Se cierra con **Esc** o la cruz. El visor es de solo lectura; el resaltado se hace en el navegador, sin modelo, librerías externas ni peticiones adicionales de código al ampliar. Las f-strings se colorean como cadenas completas.

Dentro de un script, el mapa muestra un marco con la ruta del archivo y sus componentes dentro. Un clic en el marco abre las métricas del módulo completo; un clic en una caja interior abre las métricas de ese componente. Las flechas representan llamadas a nombres locales resueltos estáticamente, con líneas de origen en el tooltip; los imports siguen siendo el grafo de los niveles superiores. Se muestran las conexiones de la página actual y el contador de conexiones con cajas fuera de ella. Seleccionar el marco muestra todas las flechas visibles (salvo en modo Ocultas). La recursión se representa con un bucle.

El grafo de llamadas es parcial: respeta ámbitos léxicos, separa cuerpos anidados y descarta parámetros, imports o asignaciones que ocultan un nombre. No resuelve atributos (`self.metodo()` incluido), alias, despacho dinámico, lambda, decoradores ni argumentos por defecto. Una flecha indica una referencia de llamada estática, no ejecución observada. El índice se calcula por SSH en memoria y no requiere CLI ni cambios en el repositorio analizado.

## Enlaces directos

Un enlace puede abrir un proyecto local y su comparación sin clics:

```text
http://127.0.0.1:8873/?project=/srv/projects/my-python-app&pr=465&diff=1&impact=1
http://127.0.0.1:8873/?project=/srv/projects/my-python-app&base=main&rev=feature-x&diff=1
```

- `project`: ruta absoluta de una carpeta existente dentro de un repositorio Git. Solo se aceptan carpetas bajo las raíces de `CODE_CHECKER_DEEP_LINK_ROOTS` (rutas absolutas separadas por `:` en Linux/macOS o `;` en Windows). Sin esa variable los enlaces directos están desactivados.
- `pr`: número entero positivo de un PR de GitHub (mismo flujo que el selector, vía `gh`). Alternativa: `base` y `rev` para **Comparar ramas**; nombres de rama, etiqueta o commit, sin opciones ni sintaxis de revisión.
- `diff` (`0`/`1`, por defecto `1` si hay comparación) activa **Ver solo el diff**; `impact` (`0`/`1`, por defecto `0`) activa **Incluir impacto potencial**.

El servidor valida cada parámetro y rechaza parámetros desconocidos o repetidos. Si el proyecto ya tiene índice local se reutiliza; si no, se analiza de forma estática como al abrirlo. No se ejecuta código del proyecto.

`CODE_CHECKER_MODELS=off` desactiva en el servidor cualquier llamada a modelos (evaluar, consultar y evaluación lazy); el análisis estático y el diff siguen disponibles.

## Filtro Git: ver solo el diff

Activa **Ver solo el diff** para conservar únicamente los componentes cambiados y los paquetes, scripts y clases necesarios para llegar hasta ellos. Funciona en todos los niveles, incluido el marco del script. Las etiquetas Añadido, Modificado, Eliminado y Contiene cambios son estados de Git/análisis, separados de la evaluación del modelo. Un desplazamiento de líneas no marca funciones intactas; los cambios en decoradores sí cuentan. Los eliminados permiten consultar el código y las métricas anteriores. Los archivos no Python, fuera de alcance o no analizables permanecen en el inventario desplegable; los errores de parseo no se presentan como eliminaciones confirmadas.

- **Mis cambios sin commit:** por defecto compara HEAD con archivos actuales, incluyendo cambios preparados, no preparados y archivos nuevos no ignorados. Puedes cambiar la referencia base.
- **Un PR de GitHub:** el desplegable consulta los PR reales del repositorio y muestra número, título y ramas. Puedes filtrar abiertos, cerrados/integrados o todos, refrescar la lista e introducir un número para un PR antiguo. Al calcular se vuelven a consultar sus commits en GitHub; no se confía en nombres de rama ni en los SHA antiguos del listado.
- **Comparar ramas (ancestro común):** introduce la rama destino en Base y la rama del PR en Revisión. Compara el ancestro común con la revisión del PR, sin incluir el trabajo sin commit ni cambios exclusivos de la rama destino posteriores a la bifurcación.
- **Dos revisiones:** compara directamente los dos commits/referencias seleccionados.

**Cargar ramas** ofrece las referencias ya disponibles en ese repositorio. **Actualizar diff** aplica las referencias y opciones elegidas. Se consultan metadatos de PR, pero no se descargan ramas ni objetos Git ausentes: no se hace fetch, checkout, reset ni escritura en Git. También se puede leer una rama distinta de la activa directamente desde objetos Git, en memoria, sin copiar el repositorio aquí.

**Incluir impacto potencial** añade consumidores transitivos según los imports y llamadas locales de ambas revisiones. Son relaciones estáticas, no fallos demostrados; los métodos dinámicos sin resolver y cambios no Python limitan la cobertura. Las funciones de un módulo consumidor se muestran como Contexto del consumidor cuando no hay atribución individual. Un renombrado aparece en el inventario como tal y en la jerarquía como símbolos eliminados/añadidos.

El selector de GitHub requiere `gh` autenticado con acceso al repositorio en la máquina donde se encuentra el código (en el servidor SSH para proyectos remotos). Usa solo peticiones GET, sin cambiar cuentas ni configuración. Soporta `github.com` a través de `remote.origin.url`; otros proveedores conservan la comparación manual. La lista está limitada a los 500 PR más recientemente actualizados y avisa si alcanza ese límite. Si faltan los commits del PR, muestra un error sin hacer fetch.

La comparación es una vista estática independiente del índice habitual: no ejecuta el modelo ni arrastra colores de otra revisión. Puedes consultar métricas y código; evaluaciones, importación de cobertura y exportación habitual quedan deshabilitadas en esta vista. Al quitar el tick recuperas el proyecto y su evaluación lazy. Si el repositorio cambia mientras calculas un diff del trabajo actual, se rechaza el resultado y puedes actualizarlo. Los objetos de código solo se mantienen en memoria; el índice de la comparación no contiene fuentes.
