# Descripción de la página — Afina / Ahora

Propuesta visual de la pestaña Ahora: una vista centrada en escuchar música, con el canvas de vídeo como protagonista a la derecha y una zona de control ordenada a la izquierda.

El canvas ocupa aproximadamente un tercio largo de la anchura y casi toda la altura útil. La composición mantiene el ambiente oscuro verde petróleo de Afina, el naranja para las acciones principales y el vídeo violeta de referencia. La imagen es un mockup estático, no una implementación.

La zona izquierda presenta primero la canción y el artista, después un panel alternable de letra y cola, y a continuación los controles de reproducción. La letra destaca el verso actual. La cola completa se consulta en su pestaña para evitar una lista lateral permanente y conserva sus acciones, incluida la reordenación.

Los controles principales se separan de los secundarios: progreso y transporte en el centro; volumen, dispositivo de salida y accesos adicionales debajo. Una franja A continuación permite anticipar las próximas canciones sin mostrar toda la lista. La navegación inferior conserva Inicio, Buscar, Biblioteca y Ahora.

Los nombres de canciones, tiempos, dispositivo y cantidad de canciones de la imagen son ejemplos de la referencia; la implementación debe usar el estado real de la aplicación.

Archivos:
- afina-ahora.png: imagen de referencia generada con la herramienta integrada de imágenes.
- prompt-implementacion.md: prompt para implementar esta distribución en la aplicación existente.
- descripcion.md: esta descripción.

## Alternancia entre letra y cola

Al seleccionar «Cola», la lista de canciones sustituye a la letra. En esta vista desaparece la franja «A continuación» de abajo, ya que duplicaría el contenido de la cola. El espacio se aprovecha para ampliar hacia abajo la lista: los controles inferiores se desplazan según haga falta y la navegación permanece al final. La cola tiene más altura para mostrar canciones y permite desplazamiento y reordenación. El canvas conserva su tamaño y posición.

Al regresar a «Letra», vuelven la letra sincronizada y la franja compacta «A continuación». Cambiar de vista no altera la reproducción.
