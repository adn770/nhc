# NHC — Nethack-like Crawler

Un dungeon crawler roguelike amb regles Knave i narrativa amb IA.

## Modes de Joc

### Mode Clàssic (per defecte)
Controls roguelike tradicionals. Mou-te amb les fletxes o tecles vi.
Accions amb una sola tecla. Ràpid, directe, no requereix LLM.

### Mode Escrit (--mode typed)
Escriu les teves intencions en llenguatge natural. Un Director de
Joc amb IA interpreta les teves accions, les resol amb les regles
Knave i narra el resultat. Com una sessió de TTRPG en solitari.

Prem TAB per canviar entre modes en qualsevol moment.

## Dreceres de Teclat — Mode Clàssic

### Moviment
  Fletxes        Moure's en 4 direccions
  h j k l        Tecles vi (esquerra, avall, amunt, dreta)
  y u b n        Diagonals vi (NO, NE, SO, SE)
  . o 5          Esperar un torn

### Accions
  g o ,          Agafar objecte als peus
  i              Obrir inventari
  a              Usar un objecte (mostra menú d'inventari)
  >              Descendir escales
  x              Mirar al voltant (inspeccionar casella)

### Interfície
  [ ]            Desplaçar registre de missatges
  ?              Mostrar aquesta pantalla d'ajuda
  TAB            Canviar entre mode clàssic i escrit
  S              Desar partida
  L              Carregar partida
  q              Sortir

## Dreceres de Teclat — Mode Escrit

### Entrada de Text
  Enter          Enviar intenció al Director de Joc
  ESC            Esborrar entrada actual
  Amunt/Avall    Navegar historial d'entrades
  Retrocés       Esborrar caràcter abans del cursor
  Esquerra/Dreta Moure cursor
  Inici/Fi       Saltar a inici/final de línia

### Dreceres (sense passar pel text)
  Fletxes        Moure's directament (sense interpretació del DJ)
  h j k l        Moviment vi (igual que el clàssic)
  TAB            Tornar al mode clàssic
  ?              Mostrar aquesta pantalla d'ajuda
  [ ]            Desplaçar registre narratiu
  S              Desar partida
  q              Sortir

## Exemples en Mode Escrit

  > Desenveino l'espasa i avanço cap a l'est
  > ataco l'esquelet
  > agafo la poció
  > intento escoltar a la porta
  > faig servir el pergamí de dormir contra els goblins
  > miro al voltant amb atenció

## Estadístiques del Personatge (Regles Knave)

  FOR  Força          Atac cos a cos, força bruta
  DES  Destresa       Atac a distància, esquiva, CA
  CON  Constitució    Punts de vida, espais d'inventari
  INT  Intel·ligència Coneixement arcà
  SAV  Saviesa        Percepció, voluntat
  CAR  Carisma        Social, moral

  Defensa = bonificació + 10.  Espais = defensa de CON.

## Barra d'Estat

  Línia 1: Lloc, Profunditat, Torn, Nivell/XP, Or, Barra de PV
  Línia 2: Nom (rerefons), habilitats, arma, CA
  Línia 3: Contingut de l'inventari

## Consells

  - Agafa-ho tot. La gestió d'inventari és clau a Knave.
  - Els pergamins són potents però d'un sol ús. Guarda'ls.
  - L'or no ocupa espai a l'inventari. Agafa'l tot.
  - En mode escrit, prova accions creatives — el DJ pot resoldre
    tirades d'habilitat per coses com enganyar o escorcollar.
  - Prem TAB per canviar ràpidament al mode clàssic pel moviment,
    i TAB de nou al mode escrit per accions complexes.
