# Prompt de implementación — Afina / Ahora

Rediseña exclusivamente la pestaña «Ahora» de Afina tomando la imagen afina-ahora.png como referencia visual. Primero revisa la arquitectura y los componentes existentes. Implementa el diseño con el sistema y las dependencias del proyecto, reutilizando la lógica de reproducción, cola, letras, canvas y Cast. Conserva todas las funciones actuales y sus estados; la imagen es una referencia de distribución, no una especificación de nuevas funciones.

Objetivo: una pantalla de reproducción más clara y cuidada, con el canvas de vídeo mucho más grande a la derecha y los controles organizados a la izquierda. Mantén el fondo oscuro con luz ambiental verde petróleo, el acento naranja, los textos blancos, los secundarios grises y las superficies translúcidas discretas.

En escritorio, distribuye aproximadamente el 60 % para la zona de información y controles y el 36–38 % para el canvas, con separación y márgenes. El canvas debe ocupar casi toda la altura disponible, con esquinas redondeadas. Conserva el vídeo real, su proporción y el comportamiento actual; evita deformarlo y reutiliza el modo de ajuste existente. Incluye acceso a pantalla completa y al menú de opciones.

Zona izquierda, de arriba abajo:
1. Cabecera compacta con Afina, «Ahora», estado del dispositivo de reproducción y perfil.
2. Portada, título, artista, favorito y menú contextual.
3. Panel con pestañas «Letra» y «Cola · N». Muestra la letra sincronizada y destaca la línea actual. En Cola conserva selección de canciones, reordenación y las demás acciones que ya existan. N debe proceder de los datos reales.
4. Barra de progreso con tiempo transcurrido y duración reales. Controles: retroceder 10 segundos, anterior, reproducir/pausar, siguiente y avanzar 10 segundos. Aleatorio y repetición según las capacidades actuales. El botón principal debe destacar en naranja.
5. Fila secundaria: volumen, dispositivo/Cast, radio si existe y acceso a cola. Conserva las diferencias entre control local y remoto y los estados conectando, conectado, pausado y error.
6. «A continuación»: vista compacta de unas cuatro canciones y «Ver cola», enlazado a la pestaña Cola; no dupliques el estado.
7. Navegación inferior: Inicio, Buscar, Biblioteca y Ahora, con Ahora activo.

Adapta la distribución a pantallas pequeñas sin ocultar funciones: reorganiza los bloques y permite desplazamiento cuando haga falta. No fijes el diseño a una sola resolución. Mantén accesibilidad, etiquetas de botones, foco visible y navegación por teclado o mando donde ya se soporte. No sustituyas componentes funcionales por una captura, ni uses datos ficticios en producción.

Valida reproducción y pausa, saltos de 10 segundos, anterior/siguiente, progreso, volumen, favoritos, letras, cola y reordenación, repetición/aleatorio, selección de dispositivo y Cast, canvas y pantalla completa. Comprueba que el cambio no rompe Inicio, Buscar ni Biblioteca. Explica los archivos cambiados y las verificaciones realizadas.

## Comportamiento de las pestañas Letra y Cola

Las pestañas son vistas excluyentes: al pulsar «Cola», desaparece la letra y en su lugar se muestra la lista de canciones. Al volver a «Letra», se restaura la letra sincronizada.

Mientras «Cola» esté activa, oculta por completo la franja inferior «A continuación», incluido su encabezado y el acceso «Ver cola», porque repetiría las mismas canciones. No reserves un hueco vacío para esa franja. Reorganiza verticalmente la zona izquierda: amplía hacia abajo el panel de la cola aprovechando el espacio liberado y desplaza los controles inferiores lo necesario, manteniéndolos accesibles y la navegación al final. La lista debe disponer de más altura útil y desplazamiento propio cuando sea necesario. Mantén el canvas derecho grande y estable.

Mientras «Letra» esté activa, muestra de nuevo la franja compacta «A continuación». Conserva una sola fuente de datos y todas las acciones existentes de la cola, incluida selección y reordenación. El cambio de pestaña no debe reiniciar ni interrumpir la reproducción.
