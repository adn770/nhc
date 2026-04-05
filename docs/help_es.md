# NHC — Nethack-like Crawler

Un dungeon crawler roguelike con reglas Knave, soporte multilingüe
y narrativa opcional con IA.

## Modos de Juego

### Modo Clásico (por defecto)
Controles roguelike tradicionales. Muévete con las flechas o teclas
vi. Acciones con una sola tecla. Rápido, directo, no requiere LLM.

### Modo Escrito (--mode typed)
Escribe comandos en lenguaje natural. Un Director de Juego con IA
interpreta tus acciones, las resuelve con las reglas Knave y narra
el resultado. Como una sesión de TTRPG en solitario.

Pulsa TAB para cambiar entre modos en cualquier momento.

## Atajos de Teclado — Modo Clásico

### Movimiento
  Flechas        Moverse en 4 direcciones
  h j k l        Teclas vi (izquierda, abajo, arriba, derecha)
  y u b n        Diagonales vi (NO, NE, SO, SE)
  . o 5          Esperar un turno

Empujar a una criatura la ataca.
Empujar una puerta cerrada la abre.
Empujar un cofre lo abre y suelta su contenido.

### Objetos y Equipamiento
  g o ,          Recoger objeto a los pies
  i              Abrir inventario
  a              Usar un objeto (muestra menú de inventario)
  q              Beber una poción
  e              Equipar arma, armadura, escudo, casco o anillo
  d              Soltar un objeto del inventario
  t              Lanzar una poción a una criatura visible
  z              Disparar una varita a una criatura visible

### Exploración
  x              Mirar a distancia (mover cursor para examinar)
  s              Buscar trampas ocultas y puertas secretas
  p              Forzar una cerradura (requiere ganzúas, salvación DES)
  f              Forzar una puerta (salvación FUE, herramientas ayudan)
  c              Cerrar una puerta abierta adyacente
  >              Descender escaleras
  <              Ascender escaleras

### Interfaz
  [ ]            Desplazar registro de mensajes
  ?              Mostrar esta pantalla de ayuda
  TAB            Cambiar entre modo clásico y escrito
  Q              Salir

## Atajos de Teclado — Modo Escrito

### Entrada de Texto
  Enter          Enviar comando al Director de Juego
  ESC            Borrar entrada actual
  Arriba/Abajo   Navegar historial de entradas
  Retroceso      Borrar carácter antes del cursor
  Izq./Derecha   Mover cursor dentro del texto
  Inicio/Fin     Saltar al inicio/final de línea

### Atajos (sin pasar por el texto)
  Flechas        Moverse directamente (sin interpretación del DJ)
  h j k l        Movimiento vi (igual que el clásico)
  TAB            Volver al modo clásico
  ?              Mostrar esta pantalla de ayuda
  [ ]            Desplazar registro narrativo
  Q              Salir

## Ejemplos en Modo Escrito

  > ataco al esqueleto
  > cojo la poción
  > abro el cofre
  > intento escuchar en la puerta
  > uso el pergamino de dormir contra los goblins
  > bebo la poción de curación
  > lanzo la poción de escarcha al ogro
  > disparo la varita al goblin

## Estadísticas del Personaje (Reglas Knave)

  FUE  Fuerza         Ataque cuerpo a cuerpo, fuerza, salvaciones
  DES  Destreza       Ataque a distancia, esquiva, CA
  CON  Constitución   Puntos de vida, espacios de inventario
  INT  Inteligencia   Conocimiento arcano, pergaminos
  SAB  Sabiduría      Percepción, voluntad, trampas
  CAR  Carisma        Social, moral, encantamientos

  Defensa = bonificación + 10.  Espacios = defensa de CON.
  Nivel máximo: 10.  Cada subida de nivel aumenta 3 habilidades.

## Identificación

Las pociones, pergaminos, anillos y varitas tienen apariencias
aleatorias en cada partida. Hay que usarlos para identificarlos:
  - Pociones: beber para identificar
  - Pergaminos: leer/usar para identificar
  - Anillos y varitas: usar Pergamino o Varita de Identificación

## Espacios de Equipamiento

  Arma        Un arma cuerpo a cuerpo o a distancia
  Armadura    Gambeson, brigantina, media armadura, armadura completa
  Escudo      Rodela o escudo (+1 CA cada uno)
  Casco       Gorro de cuero o casco (+1 CA cada uno)
  Anillo (I/D) Dos espacios para efectos mágicos pasivos

El equipamiento equipado cuenta para los espacios de inventario.

## Objetos Mágicos

### Anillos (pasivos, activos mientras equipados)
  Reparación, Velocidad, Detección, Elementos, Precisión,
  Evasión, Sombras, Protección

### Varitas (dispara a objetivos, cargas limitadas, se recargan)
  Bola de fuego, Rayo, Teletransporte, Veneno, Lentitud,
  Desintegración, Misil Mágico, Amok

## Elementos de la Mazmorra

  = Cofre      Empuja para abrir, suelta botín
  ^ Trampa     Oculta hasta ser detectada (buscar con 's')
  + Puerta     Empuja para abrir, algunas son secretas
  > Escaleras  Descender al siguiente nivel
  < Escaleras  Ascender al nivel anterior
  % Cadáver    Restos de una criatura muerta

## Barra de Estado

  Línea 1: Lugar, Profundidad, Turno, Nivel/XP, Oro, Barra de PV
  Línea 2: Nombre (clase), habilidades, arma equipada, CA
  Línea 3: Armadura/escudo/casco equipados, contenido del inventario

## Consejos

  - Recógelo todo. La gestión de inventario es clave en Knave.
  - Los pergaminos son potentes pero de un solo uso. Guárdalos.
  - Las varitas se recargan lentamente — no desperdicies cargas.
  - El oro no ocupa espacio en el inventario. Recógelo todo.
  - Busca ('s') cerca de las paredes para encontrar puertas secretas.
  - Empuja los cofres para abrirlos y encontrar botín.
  - Los anillos dan bonificaciones pasivas — equipa dos.
  - Más CON significa más espacios de inventario.
  - Cada 1000 XP subes de nivel, ganando PV y +1 a 3 stats.

## Opciones de Línea de Comandos

  --seed N        Semilla RNG para reproducibilidad
  --lang LANG     Idioma: en, ca, es
  --god           Modo dios (invulnerable, todo identificado)
  --reset         Nueva partida, ignorando el autoguardado
  -G              Generar mazmorra aleatoria
  --mode MODE     classic o typed
  --no-narrative  Desactivar narrativa LLM
  -v              Registro detallado
