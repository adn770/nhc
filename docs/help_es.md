# NHC — Nethack-like Crawler

Un dungeon crawler roguelike con reglas Knave, soporte multilingüe
y narrativa opcional con IA. Desciendes por niveles generados
procedimentalmente, luchas contra criaturas, saqueas tesoros,
contratas aventureros, identificas objetos mágicos e intentas
sobrevivir.

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
  Flechas           Moverse en 4 direcciones
  h j k l           Teclas vi (izquierda, abajo, arriba, derecha)
  y u b n           Diagonales vi (NO, NE, SO, SE)
  . o 5             Esperar un turno

Empujar a una criatura hostil la ataca.
Empujar una puerta cerrada la abre.
Empujar a un aventurero contratado intercambia posiciones contigo.
Empujar un cofre, barril o caja lo abre y suelta su contenido.
Empujar a un mercader o sacerdote abre su menú de tienda/servicio.
Empujar a un aventurero no contratado abre el menú de encuentro.

### Objetos y Equipamiento
  g o ,             Recoger objeto a los pies
  i                 Abrir inventario
  a                 Usar un objeto (muestra menú de inventario)
  q                 Beber una poción
  e                 Equipar arma, armadura, escudo, casco o anillo
  d                 Soltar un objeto del inventario
  t                 Lanzar una poción a una criatura visible
  z                 Disparar una varita a una criatura visible

### Exploración
  :                 Mirada lejana — mueve el cursor para examinar
                    casillas
  s                 Buscar trampas ocultas y puertas secretas
  p                 Forzar una cerradura (requiere ganzúas,
                    salvación DES)
  f                 Forzar una puerta (salvación FUE, las
                    herramientas ayudan)
  c                 Cerrar una puerta abierta adyacente
  D                 Excavar muro o suelo (requiere herramienta)
  >                 Descender escaleras
  <                 Ascender escaleras

### Grupo
  G                 Dar un objeto a un aventurero contratado
  P                 Despedir a un aventurero del grupo

### Interfaz
  [ ]               Desplazar registro de mensajes
  ?                 Mostrar esta pantalla de ayuda
  TAB               Cambiar entre modo clásico y escrito
  Q                 Salir

## Atajos de Teclado — Modo Escrito

### Entrada de Texto
  Enter             Enviar comando al Director de Juego
  ESC               Borrar entrada actual
  Arriba/Abajo      Navegar historial de entradas
  Retroceso         Borrar carácter antes del cursor
  Izq./Derecha      Mover cursor dentro del texto
  Inicio/Fin        Saltar al inicio/final de línea

### Atajos (sin pasar por el texto)
  Flechas           Moverse directamente (sin interpretación del DJ)
  h j k l           Movimiento vi (igual que el clásico)
  TAB               Volver al modo clásico
  ?                 Mostrar esta pantalla de ayuda
  [ ]               Desplazar registro narrativo
  Q                 Salir

## Ejemplos en Modo Escrito

  > ataco al esqueleto
  > cojo la poción
  > abro el cofre
  > intento escuchar en la puerta
  > uso el pergamino de dormir contra los goblins
  > bebo la poción de curación
  > lanzo la poción de escarcha al ogro
  > disparo la varita al goblin
  > doy la palanca a mi aventurero

## Extras del Cliente Web

El cliente del navegador añade algunas funciones no disponibles
en el terminal:

  Clic del ratón    Moverse o actuar sobre la casilla seleccionada
  Clic derecho      Menú contextual sobre un objeto del inventario
                    (Usar, Beber, Equipar, Lanzar, Dar, Soltar)
  Botón Examinar    Alterna la inspección de una casilla; clic
                    derecho para Auto-examinar (inspección
                    continua al moverse)
  Botón Excavar     Alterna la Auto-excavación — camina contra
                    muros para excavarlos con la herramienta
                    equipada
  Opción TTS        Lee los mensajes en voz alta con Piper TTS
  Clasificación     Las partidas terminadas entran en el ranking
                    (las de modo dios no cuentan)

## Estadísticas del Personaje (Reglas Knave)

  FUE  Fuerza         Ataque cuerpo a cuerpo, fuerza, salvaciones
  DES  Destreza       Ataque a distancia, esquiva, CA
  CON  Constitución   Puntos de vida, espacios de inventario
  INT  Inteligencia   Conocimiento arcano, pergaminos
  SAB  Sabiduría      Percepción, voluntad, trampas
  CAR  Carisma        Social, moral, encantamientos

  Defensa = bonificación + 10.  Espacios = defensa de CON.
  El nivel 1 empieza con PV máximos (8).
  Nivel máximo: 10.  Cada subida aumenta las 3 habilidades más
  bajas en +1.
  1000 XP por nivel. Las criaturas dan XP = PV máximos × 5.

## Espacios de Equipamiento

  Arma              Un arma cuerpo a cuerpo o a distancia
  Armadura          Gambesón, brigantina, cota de malla, media
                    armadura, armadura completa
  Escudo            Rodela o escudo (+1 CA cada uno)
  Casco             Gorro de cuero o casco (+1 CA cada uno)
  Anillo (I/D)      Dos espacios para efectos mágicos pasivos

Los objetos equipados también ocupan espacios de inventario.

## Leyenda de Símbolos

### Terreno y Elementos de la Mazmorra

  .   Suelo               ,   Hierba
  #   Corredor / excavado ~   Agua o lava
  -   Muro (caracteres de caja en el juego)
  +   Puerta cerrada      '   Puerta abierta
  <   Escaleras arriba    >   Escaleras abajo
  ^   Trampa (una vez detectada)
  =   Cofre               0   Barril              #   Caja
  ◎   Marca de tesoro enterrado (cian, tras excavar o detectar)

Las puertas secretas parecen muros hasta que las encuentras al buscar.
Los objetos detectados y la magia brillan un momento y se desvanecen.

### Objetos

  !   Poción              ?   Pergamino
  =   Anillo              /   Varita o flecha
  )   Arma                [   Armadura
  *   Gema o vidrio sin valor
  (   Herramienta, comida, llave, ganzúa, linterna, símbolo sagrado…
  $   Pila de oro         %   Cadáver

Las pociones, pergaminos, anillos, varitas y gemas tienen
apariencias aleatorias (colores, etiquetas, tipo de gema) hasta
identificarlas; las apariencias se barajan de nuevo cada partida.

### Criaturas

El jugador y los PNJs amistosos comparten el glifo `@` pero se
distinguen por color:

  @   Jugador       (contorno azul en el cliente web)
  @   Aventurero    (cian)
  @   Mercader      (verde)
  @   Sacerdote     (blanco brillante)
  @   Bandido       (amarillo, hostil)

La mayoría de criaturas son una sola letra. Algunos ejemplos
agrupados por familia (el bestiario completo es más grande):

  Humanoides / goblinoides
    g goblin   h hobgoblin   k kobold   o orco    O ogro
    G gnoll    f hombre-rana             L hombre-lagarto
    n hombre-serpiente
  Bestias y cánidos
    b murciélago  r rata     w lobo     d lobo huargo
    c oso      U warg        W hombre-lobo / lobo de invierno
  Reptiles y serpientes
    l lagarto  S serpiente   D lagarto-dragón     F rana gigante
  No-muertos
    s esqueleto Z zombi      M momia    W espectro / alma en pena
    g ghoul
  Alimañas, insectos y arácnidos
    s araña    i enjambre de insectos   a escarabajo de fuego
    L langosta de cueva       S escorpión gigante  c ciempiés gigante
  Limos y plantas
    P pudding negro  j gelatina ocre    o limo gris
    f hongo / flor carnívora            m moho amarillo
  Exóticas y caos
    T trol (regenera)         $ mímico (disfrazado de cofre/oro)
    ! chillón (alerta a las criaturas)
    C centauro  H harpía       V wyvern  I acechador invisible
    A armadura animada         G gárgola  B basilisco (mirada)

Regla general: minúscula = más pequeño, mayúscula = más grande
o duro. Los troles regeneran 3 PV por turno; mímicos y chillones
se disfrazan de objetos — las sorpresas son parte del juego.

## Objetos Mágicos

### Pociones (14)
  Curación, Fuerza, Velocidad, Escarcha, Invisibilidad, Levitación,
  Llama Líquida, Visión Mental, Gas Paralizante, Purificación,
  Confusión, Ceguera, Ácido, Enfermedad.

Algunas pociones hacen más daño lanzadas que bebidas.
Beber cualquier poción recupera algo de nutrición.

### Pergaminos
Detección (brillo que se desvanece, revelan cosas durante un tiempo):
  Detectar Magia, Detectar Mal, Detectar Oro, Detectar Comida,
  Detectar Gemas, Detectar Invisibilidad, Encontrar Trampas,
  Revelar Mapa.
Ofensivos / estado:
  Relámpago, Bola de Fuego, Misil Mágico, Dormir, Sujetar Persona,
  Telaraña, Encantar Persona, Fuerza Fantasmal, Disipar Magia.
Defensivos / mejora:
  Bendición, Escudo, Velocidad, Curar Heridas, Imagen Espejo,
  Invisibilidad, Protección contra el Mal, Protección contra
  Proyectiles, Resistencia al Fuego, Resistencia al Frío,
  Silencio, Levitación, Vuelo.
Utilidad:
  Identificar, Recargar, Teletransporte, Encantar Arma,
  Encantar Armadura, Clarividencia, Infravisión, Respirar
  bajo el Agua, Encantar Serpientes.

### Anillos (pasivos, activos mientras equipados)
  Reparación, Velocidad, Detección, Elementos, Precisión,
  Evasión, Sombras, Protección.

### Varitas (dispara a objetivos, cargas limitadas, se recargan)
  Bola de fuego, Rayo, Frío, Misil Mágico, Desintegración,
  Teletransporte, Veneno, Lentitud, Amok, Apertura, Bloqueo,
  Excavación, Cancelación, Muerte.

### Gemas y Vidrio
Las gemas reales (rubí, zafiro, esmeralda, diamante, amatista,
topacio, ópalo, granate) se venden por oro. El vidrio sin valor
parece igual hasta identificarlo — un Pergamino de Identificar
o el ojo experto de un mercader los distingue.

## Identificación

Las pociones, pergaminos, anillos, varitas y gemas tienen
apariencias aleatorias cada partida. Para identificarlas:
  - Pociones: beber para identificar (o lanzar una conocida)
  - Pergaminos: leer/usar para identificar
  - Anillos y varitas: equipar/disparar, o usar Pergamino/Varita
    de Identificar
  - Gemas: usar Pergamino de Identificar, o venderlas a un mercader

## Elementos de la Mazmorra y Salas Especiales

  Templo (2+)       Garantizado en profundidad 2. Un sacerdote
                    ofrece curación, quitar maldición y bendición,
                    además de bienes sagrados. Los precios suben
                    con la profundidad.
  Tiendas           Un mercader vende objetos y compra botín al
                    50% de su valor. Empuja para comerciar.
  Guaridas (3+)     1–3 salas conectadas con humanoides de la
                    misma especie. Las casillas alrededor ocultan
                    trampas reactivables.
  Zoos (5+)         Salas medianas llenas de criaturas.
  Nidos             Salas llenas de ratas, murciélagos o insectos.
  Tesorerías        Cámaras ocultas con pilas de oro.
  Cuevas            Disposiciones orgánicas sin puertas pero con
                    más pozos y trampas.

## Trampas

Las trampas están ocultas hasta detectarse. Usa `s` (buscar)
adyacente a una casilla sospechosa, equipa el Anillo de Detección
o lanza Encontrar Trampas. Tipos: pozo, trampilla, flecha, dardo,
piedra, fuego, veneno, parálisis, alarma, teletransporte,
invocación, agarre, esporas. Algunas trampas alrededor de las
guaridas se reactivan a los 40 turnos.

## Puertas

  Cerrada           Empuja para abrir (solo los humanoides pueden
                    abrirlas).
  Bloqueada         Usa `p` para forzar la cerradura (salvación
                    DES, puede romper una ganzúa) o `f` para
                    forzar la puerta (salvación FUE, puede herirte).
  Herramientas      Una palanca absorbe el rebote y baja la DC;
                    un arma baja un poco la DC y puede mellarse.
  Secreta           Parecen muros. Encuéntralas con `s`.
  Cuevas            Sin puertas — solo pasadizos abiertos.

## Excavación y Tesoros Enterrados

Una herramienta de excavación (pala, piqueta, zapapico o pico) te
permite cavar. Una está garantizada en profundidades 1–5.

  Muros             Cualquier herramienta. Salvación FUE DC 12
                    menos la bonificación de la herramienta.
  Suelo             Solo la pala. Puede revelar objetos enterrados
                    (◎). Probabilidad 1 entre 20 (+1 por bonificación
                    de FUE) de caer al piso siguiente recibiendo 2d6
                    de daño. Excavar la misma casilla dos veces
                    garantiza la caída.
  Piquetas          Golpear el suelo con una piqueta, zapapico o
                    pico puede rebotar por 1d2 de daño con un 1
                    natural.

En el cliente web, clic derecho al botón Excavar activa la
Auto-excavación y puedes excavar solo moviéndote contra muros.

## Aventureros / Grupo

  Reclutar          Empuja a un aventurero no contratado para
                    abrir el menú de encuentro. Contratar cuesta
                    100 monedas de oro × su nivel.
  Tamaño            Hasta dos aventureros a la vez.
  Comportamiento    Luchan, se curan con pociones, recogen botín,
                    evitan trampas visibles y te siguen entre
                    salas y bajando escaleras.
  Dar               Pulsa `G` (o el menú contextual) para pasarles
                    objetos. Su IA elige el mejor equipamiento.
  Intercambio       Empuja a un aventurero para intercambiar
                    posiciones.
  Despedir          Pulsa `P` para liberarlo.
  Muerte            Se notifica en el registro. Los aventureros
                    reciben la mitad de XP.

## Hambre y Comida

Un reloj de hambre avanza mientras exploras. Come (`a` y elige
raciones, pan, queso, manzana, hongo, carne seca…) antes de morir
de hambre. Los hongos pueden curar, envenenar o confundir. Beber
una poción da algo de nutrición, pero nunca suficiente para vivir.

## Conceptos de Combate

  Cuerpo a cuerpo   d20 + bonificación FUE + magia de arma vs CA
                    del objetivo. 20 natural = daño máximo. 1
                    natural = fallo automático. Daño = dado de
                    arma + bonificación FUE + magia (mínimo 1).
  Distancia         Lanzar (`t`), disparar (`z`) o disparar con
                    arco.
  Defensa           CA = 10 + bonificación DES + armadura/escudo/
                    casco/anillo.
  Moral             Los enemigos hacen salvación de moral al verte
                    por primera vez y al bajar a la mitad de PV;
                    los cobardes huyen.
  Aventureros       Suman sus armas y hechizos a tu daño.

## Barra de Estado

  Línea 1           Lugar, Profundidad, Turno, Nivel/XP, Oro, Barra de PV
  Línea 2           Nombre (clase), habilidades, arma equipada, CA
  Línea 3           Armadura/escudo/casco equipados, contenido del
                    inventario

## Cómo Jugar — Guía Breve

1. **Explora con cautela.** Entra una vez a cada sala nueva, mira
   qué hay y retrocede si las probabilidades no te favorecen.
2. **Recoge casi todo.** El oro no ocupa espacio; el resto sí,
   pero la mayoría vale la pena.
3. **Identifica con seguridad.** Bebe pociones desconocidas con PV
   llenos. Lee pergaminos desconocidos en salas vacías — algunos
   invocan o teletransportan. Nunca identifiques en una guarida.
4. **Gasta los consumibles.** Pergaminos y cargas no te acompañan
   si mueres. Úsalos en combates duros, no en fáciles.
5. **Busca a menudo.** Puertas secretas y tesoros enterrados se
   esconden en muros y suelos. Pulsar `s` unas cuantas veces
   cuesta poco.
6. **Lee la sala.** Una sala abarrotada suele ser un zoo; una
   sala grande con criaturas de la misma especie, una guarida;
   una cuadrícula perfecta con un mercader, una tienda; las
   decoraciones marcan los templos.
7. **Sube de nivel con cabeza.** Cada nivel sube las tres
   habilidades más bajas en +1. No lo vuelques todo en FUE —
   CON da espacios, DES da CA, SAB resiste la magia.
8. **Controla el hambre.** No pierdas turnos en corredores. Lleva
   al menos dos raciones al bajar.

## Consejos Tácticos

- **Los corredores canalizan enemigos** — lucha contra grupos
  en pasos de una sola casilla para que solo uno te alcance.
- **Cierra las puertas tras de ti** con `c` para bloquear
  perseguidores y ganar un golpe gratis cuando las reabran.
- **Lanza pociones a los enemigos** — Escarcha, Llama Líquida,
  Gas Paralizante, Ácido, Confusión y Ceguera hacen debuff
  al impactar.
- **Las varitas brillan contra enemigos duros** — guarda Misil
  Mágico para objetivos difíciles; nunca falla.
- **Anillos de Reparación + Detección** aguantan muchas
  partidas. Equipa los dos anillos siempre que puedas.
- **Las palancas hacen que forzar puertas sea seguro** —
  absorben el rebote y bajan la DC.
- **Los troles regeneran** — quémalos (Llama Líquida, Varita de
  Bola de Fuego, Pergamino de Bola de Fuego) para detener la
  regeneración.
- **Los mímicos se hacen pasar por cofres** y **los chillones
  parecen pociones** — examina (`:`) lo que parezca fuera de lugar.
- **Los templos son un botón de reset** — la curación y quitar
  maldición del sacerdote pueden salvar una partida por un
  puñado de oro.
- **Contrata pronto.** Un aventurero de profundidad 1 es barato,
  aguanta golpes y se cura solo. Dale la palanca sobrante.
- **Cava con mesura.** Excavar el suelo ahorra tiempo pero puede
  dejarte en un combate con PV bajos — cúrate antes.
- **No subas por gusto.** Subir escaleras desbarata el ritmo de
  XP y solo hay escaleras arriba en profundidad 1.

## Guardado

El juego guarda automáticamente cada turno — no hay tecla de
guardado manual. Los guardados se firman con HMAC para detectar
manipulación. Usa `--reset` para empezar de nuevo ignorando el
autoguardado.

## Opciones de Línea de Comandos

  --seed N          Semilla RNG para reproducibilidad
  --lang LANG       Idioma: en, ca, es
  --god             Modo dios (invulnerable, todo identificado)
  --reset           Nueva partida, ignorando el autoguardado
  -G                Generar mazmorra aleatoria
  --mode MODE       classic o typed
  --no-narrative    Desactivar narrativa LLM
  -v                Registro detallado
