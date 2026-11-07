# Afina: barra limpia — revisión que sustituye la propuesta recargada

El usuario rechazó la propuesta de barra con dos filas y todos los controles visibles. La prioridad es mantener la limpieza de la navegación actual. No implementar la distribución anterior.

## Distribución recomendada

Una sola barra inferior discreta, en una fila en escritorio, ampliada hacia la derecha bajo el canvas. Su altura debe parecerse a la barra de navegación actual, aproximadamente 64–76 px como orientación. Usar el tema, colores y acabados existentes.

De izquierda a derecha:
1. Inicio, Buscar, Biblioteca y Ahora, con icono y etiqueta discretos.
2. Separador sutil.
3. Portada pequeña y un solo título de canción, truncado; sin repetir artista y álbum en otras filas.
4. Anterior, play/pausa y siguiente. Solo play/pausa recibe énfasis.
5. Accesos pequeños a Letra, Cola, Dispositivos y Más.

No mostrar permanentemente volumen, aleatorio, repetición, saltos de 10 segundos, corazón, tiempos, nombre de dispositivo y tres grandes pestañas de modos. Las funciones se conservan mediante menús o popovers.

Integrar el progreso como una línea fina en el borde superior de la zona de reproducción. Permitir seek y mostrar tiempo mediante interacción accesible, sin añadir otra fila fija.

Si falta anchura, ocultar primero los metadatos secundarios o mover acciones a Más. No amontonar iconos ni reducir las áreas táctiles hasta volverlas incómodas.

## Qué se despliega

- Más: volumen, aleatorio, repetición, retroceder/avanzar 10 s, favorito y otras acciones existentes.
- Dispositivos: salidas reales disponibles y estado local/remoto/Cast. Mantener las diferencias entre conectar por Cast y controlar otro equipo si el proyecto las distingue.
- Letra: ocupa todo el panel derecho en lugar del canvas.
- Cola: ocupa todo el panel derecho en lugar del canvas.
- Cerrar Letra o Cola, o pulsar otra vez su botón activo, vuelve al canvas.
- Los popovers se cierran al pulsar fuera o Escape; el foco se devuelve al disparador.

## Canvas, letra y cola

El canvas queda limpio, dedicado a vídeo o portada. Solo puede mantener un control discreto de pantalla completa. Quitar los controles de transporte, volumen, información y la franja Siguiente | Letra de su interior.

Al abrir Letra o Cola, sustituir visualmente el panel derecho completo: nunca reducir el vídeo a la mitad y colocar el contenido debajo. La página principal permanece visible. El coste de esta opción es que el vídeo no se ve durante Letra/Cola; la reproducción no se interrumpe. Mostrar un cierre claro para volver al canvas.

Conservar letra sincronizada y estados de carga/sin letra/error. Conservar toda la cola: selección, reordenación, menús, continuación automática y su semántica actual.

La alternativa que mantendría el canvas visible usando el área principal para la letra queda pendiente de preferencia del usuario; no añadir otro sistema ni otro botón para ella en esta implementación.

## Referencias

- referencia-barra-limpia.fragment.html: maqueta conceptual interactiva con la barra simplificada. Es un fragmento de visualización que depende de iconos Lucide suministrados por su entorno. No sustituye los componentes reales de Afina ni tiene conexiones reales a reproducción o dispositivos.
- estado-actual.png: captura aportada por el usuario para conservar estructura y colores.
- PROMPT-PARA-CLAUDE.txt: instrucciones para implementar.

El canvas de la maqueta se representa como un área neutra porque se alcanzó el límite temporal de generación de imágenes. En la app real se utiliza el vídeo o la portada existentes. Las miniportadas de la maqueta son solo marcadores, no nuevos recursos del proyecto.

## Integración

Modificar solo esta distribución en Inicio, Buscar, Biblioteca y sus fichas. Conservar las listas y la estructura que el usuario ya aprobó.

Ahora está bien y se conserva. Al entrar allí, usar sus controles y su navegación actuales sin añadir un segundo transporte global. Al salir, restaurar la barra de exploración.

Reutilizar el estado y la instancia multimedia existentes. No recrear audio/vídeo, reasignar fuentes, duplicar listeners ni reiniciar canvas/Cast por navegar o cambiar de modo. Mantener todas las capacidades y estados de la reproducción local y remota.

Reservar en el layout la altura de la barra para que no tape contenido. El panel derecho termina encima de ella y mantiene altura estable. Los menús se abren hacia arriba sin quedar recortados.

En móvil, adaptar dentro del contenedor común de forma legible, conservando acceso a todo. No imponer una fila de escritorio si no cabe.

## Comprobaciones

Verificar navegación, reproducción continua, vídeo y fallback de portada, cambio Canvas/Letra/Cola y retorno, letra sincronizada, cola y reordenación, todos los controles desplazados a menús, dispositivos y Cast, entrada/salida de Ahora, títulos largos y varios tamaños.

Probar con datos y sesión reales cuando sea posible. Informar explícitamente de mocks y de las pruebas de Canvas/Cast que requieran un dispositivo real. No modificar producción ni desplegar sin la autorización correspondiente.

## Aclaración final del usuario: alcance visual estricto

El usuario aprobó la barra simplificada, pero NO aprobó cambios en el contenido de la izquierda. La maqueta interactiva simplifica esa zona únicamente para explicar la barra: no es una referencia para rediseñarla.

Mantener exactamente el diseño actual de Inicio, Buscar y Biblioteca y de sus fichas: mismas listas, tarjetas, columnas, tamaños, tipografía, separaciones, orden y funciones. No copiar la composición reducida de la izquierda que aparece en la maqueta. Usar estado-actual.png y, sobre todo, la app existente como referencia para esa zona.

Los únicos cambios autorizados por esta propuesta son:
1. Sustituir la barra de navegación por la barra simplificada aprobada, integrando los controles esenciales y los accesos desplegables.
2. Retirar del canvas los controles y la franja inferior actuales.
3. Aprovechar el espacio liberado para que el canvas se vea limpio y más alto, manteniendo su posición a la derecha y el ajuste de imagen/vídeo actual, sin deformarlo.
4. Hacer los ajustes mínimos de reserva de espacio inferior para que la barra no tape contenido. Esto no autoriza redistribuir ni rediseñar el contenido principal.
5. Aplicar el comportamiento descrito de Letra y Cola a panel completo cuando se seleccionen, conservando reproducción y acciones.

No aumentar gratuitamente el canvas a costa de estrechar o reorganizar el área izquierda. No mover la cabecera ni cambiar colores. Ahora se mantiene intacta. Si una diferencia de la maqueta contradice esta aclaración, prevalece esta aclaración.
