# NHC — Nethack-like Crawler

Un dungeon crawler roguelike con reglas Knave y narrativa con IA.

## Modos de Juego

### Modo Clásico (por defecto)
Controles roguelike tradicionales. Muévete con las flechas o teclas
vi. Acciones con una sola tecla. Rápido, directo, no requiere LLM.

### Modo Escrito (--mode typed)
Escribe tus intenciones en lenguaje natural. Un Director de Juego
con IA interpreta tus acciones, las resuelve con las reglas Knave
y narra el resultado. Como una sesión de TTRPG en solitario.

Pulsa TAB para cambiar entre modos en cualquier momento.

## Atajos de Teclado — Modo Clásico

### Movimiento
  Flechas        Moverse en 4 direcciones
  h j k l        Teclas vi (izquierda, abajo, arriba, derecha)
  y u b n        Diagonales vi (NO, NE, SO, SE)
  . o 5          Esperar un turno

### Acciones
  g o ,          Recoger objeto a los pies
  i              Abrir inventario
  a              Usar un objeto (muestra menú de inventario)
  >              Descender escaleras
  x              Mirar alrededor (inspeccionar casilla)

### Interfaz
  [ ]            Desplazar registro de mensajes
  ?              Mostrar esta pantalla de ayuda
  TAB            Cambiar entre modo clásico y escrito
  S              Guardar partida
  L              Cargar partida
  q              Salir

## Atajos de Teclado — Modo Escrito

### Entrada de Texto
  Enter          Enviar intención al Director de Juego
  ESC            Borrar entrada actual
  Arriba/Abajo   Navegar historial de entradas
  Retroceso      Borrar carácter antes del cursor
  Izq./Derecha   Mover cursor
  Inicio/Fin     Saltar al inicio/final de línea

### Atajos (sin pasar por el texto)
  Flechas        Moverse directamente (sin interpretación del DJ)
  h j k l        Movimiento vi (igual que el clásico)
  TAB            Volver al modo clásico
  ?              Mostrar esta pantalla de ayuda
  [ ]            Desplazar registro narrativo
  S              Guardar partida
  q              Salir

## Ejemplos en Modo Escrito

  > Desenvaino la espada y avanzo hacia el este
  > ataco al esqueleto
  > cojo la poción
  > intento escuchar en la puerta
  > uso el pergamino de dormir contra los goblins
  > miro alrededor con atención

## Estadísticas del Personaje (Reglas Knave)

  FUE  Fuerza         Ataque cuerpo a cuerpo, fuerza bruta
  DES  Destreza       Ataque a distancia, esquiva, CA
  CON  Constitución   Puntos de vida, espacios de inventario
  INT  Inteligencia   Conocimiento arcano
  SAB  Sabiduría      Percepción, voluntad
  CAR  Carisma        Social, moral

  Defensa = bonificación + 10.  Espacios = defensa de CON.

## Barra de Estado

  Línea 1: Lugar, Profundidad, Turno, Nivel/XP, Oro, Barra de PV
  Línea 2: Nombre (trasfondo), habilidades, arma, CA
  Línea 3: Contenido del inventario

## Consejos

  - Recógelo todo. La gestión de inventario es clave en Knave.
  - Los pergaminos son potentes pero de un solo uso. Guárdalos.
  - El oro no ocupa espacio en el inventario. Recógelo todo.
  - En modo escrito, prueba acciones creativas — el DJ puede
    resolver tiradas de habilidad para cosas como engañar o
    registrar.
  - Pulsa TAB para cambiar rápidamente al modo clásico para
    movimiento, y TAB de nuevo al modo escrito para acciones
    complejas.
