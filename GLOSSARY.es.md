# Glosario de Weeb Alexandria

Este glosario explica de forma sencilla qué información contiene Weeb Alexandria y para qué sirve cada herramienta del MCP.

## Información de la base

### Tags

Las tags son palabras usadas para describir una imagen, personaje, estilo, acción, objeto o concepto. Ejemplos:

```text
blue_hair
school_uniform
smile
holding_sword
```

Son los bloques principales para buscar información o construir prompts.

### Categorías

Las categorías indican qué tipo de tag es algo. Puede ser un concepto general, un personaje, una serie, un artista u otro tipo de información.

### Definiciones

Las definiciones explican qué significa una tag y cómo suele utilizarse.

Cuando es posible, provienen de las fuentes indexadas. Las definiciones generadas con modelos de lenguaje están marcadas claramente como sintéticas.

### Aliases

Los aliases son nombres alternativos para el mismo concepto. Ayudan a conectar nombres utilizados por distintos sitios o comunidades.

Ejemplo:

```text
stuck_in_wall → through_wall
```

Esto significa que `stuck_in_wall` se trata como un nombre alternativo de `through_wall`.

### Implicaciones

Las implicaciones describen relaciones donde una tag normalmente incluye otra idea.

Ejemplo:

```text
holding_tripod → holding
holding_tripod → tripod
```

Esto significa que alguien que sostiene un trípode también está sosteniendo algo y está relacionado con un trípode.

### Popularidad y cantidad de posts

La cantidad de posts indica cuántas publicaciones están asociadas con una tag en un sitio de origen. Sirve como una referencia aproximada de qué tan común o establecida está.

Una cantidad mayor no significa automáticamente que una tag sea mejor; solo que aparece con más frecuencia en esa fuente.

### Fuentes

Una fuente es el sitio o dataset de donde proviene la información, como Danbooru, e621, Gelbooru o AnimaDex.

Conservar la fuente ayuda a entender de dónde salió una definición o relación.

### Personajes

Las tags relacionadas con personajes pueden representar personajes de ficción aunque no tengan una ficha estructurada. La tabla general de tags contiene muchas más tags de personajes que la tabla seleccionada de personajes.

La tabla de personajes es una colección estructurada y seleccionada de los datos integrados de AnimaDex. **No representa la cantidad total de personajes de toda la base**. Muchos nombres de personajes pueden existir como tags normales con wiki, aliases, popularidad o información de fuentes sin tener una ficha estructurada de personaje.

Un personaje puede incluir:

- Nombre.
- Serie o franquicia.
- Trigger o tag identificadora.
- Core tags útiles para describirlo.
- Popularidad o cantidad de posts.
- Traits visuales.

### Franquicias y series

Una franquicia identifica la obra o universo al que pertenece un personaje, como un videojuego, anime, manga o serie de ficción.

En sistemas de tags booru también puede aparecer como `copyright`, que es el término habitual de esas plataformas.

### Triggers

Un trigger es la tag o frase principal utilizada para identificar a un personaje en un prompt o búsqueda.

Normalmente es la forma más directa de referirse a ese personaje.

### Core tags

Las core tags son las tags visuales más útiles asociadas con un personaje. Pueden describir cabello, ropa, accesorios, colores u otros rasgos reconocibles.

Son un punto de partida y no una descripción completa de todas sus apariencias.

### Traits

Los traits describen características específicas agrupadas en áreas como:

- Color del cabello.
- Largo del cabello.
- Color de ojos.
- Género.
- Ropa u otros detalles visuales.

Ayudan a buscar personajes con características parecidas.

### Artistas

Las tags relacionadas con artistas pueden representar artistas aunque no tengan una ficha estructurada. La tabla general de tags contiene muchas más tags de artistas que la tabla seleccionada de artistas.

Los registros de artistas contienen información sobre artistas y sus tags, triggers, popularidad y puntuaciones cuando están disponibles. La tabla estructurada de artistas proviene de los datos integrados de AnimaDex y no debe interpretarse como la cantidad total de artistas representados por tags.

Pueden ayudar a identificar un artista o preparar un prompt relacionado con su estilo.

### LoRAs

Las LoRAs son complementos opcionales para modelos de generación de imágenes. Weeb Alexandria tiene un espacio para información de LoRAs, pero el snapshot actual no contiene registros publicados de LoRAs.

### NSFW y SFW

NSFW significa contenido que puede no ser apropiado para el trabajo o para todo público. SFW significa contenido considerado seguro para el trabajo.

Estas etiquetas ayudan a entender la categoría general del contenido. No sustituyen las reglas de la aplicación o plataforma donde se utilicen los datos.

## Herramientas del MCP

### `search_knowledge`

Es la herramienta de búsqueda general.

Busca entre:

- Tags.
- Personajes.
- Artistas.
- Franquicias o series.

Es útil cuando la consulta es amplia o no estás seguro del nombre exacto.

Ejemplos:

```text
Busca información sobre Miku
Encuentra personajes de Genshin Impact
Busca tags relacionadas con sostener una espada
```

Los resultados priorizan coincidencias exactas, después coincidencias por prefijo y finalmente coincidencias parciales.

### `get_tag_knowledge`

Úsala cuando ya conoces la tag exacta que quieres revisar.

Devuelve:

- Definiciones.
- Fuente.
- Categoría.
- Popularidad.
- Aliases.
- Implicaciones.
- Estado NSFW.

Ejemplo:

```text
Obtén toda la información de stuck_in_wall
```

Es una herramienta precisa y funciona mejor con la escritura canónica de la tag, normalmente en minúsculas y con guiones bajos.

### `search_characters`

Úsala para buscar personajes, especialmente cuando quieres aplicar filtros.

Permite buscar o filtrar por:

- Nombre.
- Franquicia.
- Color del cabello.
- Largo del cabello.
- Color de ojos.
- Género.
- Popularidad o nombre.

Ejemplo:

```text
Busca personajes femeninos de Genshin Impact con cabello azul
```

### `get_character`

Úsala cuando conoces el slug exacto del personaje y quieres su registro completo.

Puede devolver:

- Nombre.
- Franquicia.
- Trigger.
- Core tags.
- Traits.
- Popularidad.
- LoRAs relacionadas, si existen.

Ejemplo:

```text
Obtén el registro completo de hatsune_miku
```

### `get_sources_status`

Sirve para comprobar si las fuentes locales y la base están disponibles.

Es útil para diagnosticar problemas o confirmar qué partes de la base están instaladas.

## Qué herramienta elegir

```text
No sé exactamente qué necesito       → search_knowledge
Conozco la tag exacta                → get_tag_knowledge
Quiero buscar personajes             → search_characters
Conozco el slug exacto del personaje → get_character
Quiero revisar la instalación       → get_sources_status
```

## Limitaciones importantes

- Los resultados dependen del snapshot local instalado.
- Que no aparezca un resultado no significa necesariamente que el concepto no exista.
- Las cantidades de posts provienen de los sitios de origen y pueden no representar la popularidad actual en todas partes.
- Las definiciones y relaciones pueden variar entre fuentes.
- Las definiciones sintéticas están marcadas por separado y deben tratarse como sugerencias, no como texto oficial de una fuente.
