# NHC — Nethack-like Crawler

Un dungeon crawler roguelike amb regles Knave, suport multilingüe
i narrativa opcional amb IA.

## Modes de Joc

### Mode Clàssic (per defecte)
Controls roguelike tradicionals. Mou-te amb les fletxes o tecles vi.
Accions amb una sola tecla. Ràpid, directe, no requereix LLM.

### Mode Escrit (--mode typed)
Escriu ordres en llenguatge natural. Un Director de Joc amb IA
interpreta les teves accions, les resol amb les regles Knave i
narra el resultat. Com una sessió de TTRPG en solitari.

Prem TAB per canviar entre modes en qualsevol moment.

## Dreceres de Teclat — Mode Clàssic

### Moviment
  Fletxes        Moure's en 4 direccions
  h j k l        Tecles vi (esquerra, avall, amunt, dreta)
  y u b n        Diagonals vi (NO, NE, SO, SE)
  . o 5          Esperar un torn

Empènyer una criatura l'ataca.
Empènyer una porta tancada l'obre.
Empènyer un cofre l'obre i en deixa caure el contingut.

### Objectes i Equipament
  g o ,          Agafar objecte als peus
  i              Obrir inventari
  a              Usar un objecte (mostra menú d'inventari)
  q              Beure una poció
  e              Equipar arma, armadura, escut, casc o anell
  d              Deixar un objecte de l'inventari
  t              Llançar una poció a una criatura visible
  z              Disparar una vareta a una criatura visible

### Exploració
  x              Mirar a distància (mou el cursor per examinar)
  s              Cercar trampes ocultes i portes secretes
  p              Forçar un pany (requereix eines, salvació DES)
  f              Forçar una porta (salvació FOR, eines ajuden)
  >              Descendir escales
  <              Ascendir escales

### Interfície
  [ ]            Desplaçar registre de missatges
  ?              Mostrar aquesta pantalla d'ajuda
  TAB            Canviar entre mode clàssic i escrit
  Q              Sortir

## Dreceres de Teclat — Mode Escrit

### Entrada de Text
  Enter          Enviar ordre al Director de Joc
  ESC            Esborrar entrada actual
  Amunt/Avall    Navegar historial d'entrades
  Retrocés       Esborrar caràcter abans del cursor
  Esquerra/Dreta Moure cursor dins el text
  Inici/Fi       Saltar a inici/final de línia

### Dreceres (sense passar pel text)
  Fletxes        Moure's directament (sense interpretació del DJ)
  h j k l        Moviment vi (igual que el clàssic)
  TAB            Tornar al mode clàssic
  ?              Mostrar aquesta pantalla d'ajuda
  [ ]            Desplaçar registre narratiu
  Q              Sortir

## Exemples en Mode Escrit

  > ataco l'esquelet
  > agafo la poció
  > obro el cofre
  > intento escoltar a la porta
  > faig servir el pergamí de dormir contra els goblins
  > bec la poció de curació
  > llançar la poció de gel a l'ogre
  > disparo la vareta al goblin

## Estadístiques del Personatge (Regles Knave)

  FOR  Força          Atac cos a cos, força bruta, salvacions
  DES  Destresa       Atac a distància, esquiva, CA
  CON  Constitució    Punts de vida, espais d'inventari
  INT  Intel·ligència Coneixement arcà, pergamins
  SAV  Saviesa        Percepció, voluntat, trampes
  CAR  Carisma        Social, moral, encantaments

  Defensa = bonificació + 10.  Espais = defensa de CON.
  Nivell màxim: 10.  Cada pujada de nivell augmenta 3 habilitats.

## Identificació

Les pocions, pergamins, anells i varetes tenen aparences aleatòries
cada partida. Cal usar-les per identificar-les:
  - Pocions: beure per identificar
  - Pergamins: llegir/usar per identificar
  - Anells i varetes: usar Pergamí o Vareta d'Identificació

## Espais d'Equipament

  Arma        Una arma cos a cos o a distància
  Armadura    Gambeson, brigantina, mitja armadura, armadura completa
  Escut       Rodella o escut (+1 CA cadascun)
  Casc        Capell de cuir o casc (+1 CA cadascun)
  Anell (E/D) Dos espais per efectes màgics passius

L'equipament ocupat compta als espais d'inventari.

## Objectes Màgics

### Anells (passius, actius mentre equipats)
  Reparació, Velocitat, Detecció, Elements, Precisió,
  Evasió, Ombres, Protecció

### Varetes (dispara a objectius, càrregues limitades, es recarreguen)
  Bola de foc, Llamp, Teleportació, Verí, Lentitud,
  Desintegració, Míssil Màgic, Amok

## Elements de la Masmorra

  = Cofre      Empeny per obrir, deixa caure botí
  ^ Trampa     Oculta fins detectada (cerca amb 's')
  + Porta      Empeny per obrir, algunes són secretes
  > Escales    Descendir al següent nivell
  < Escales    Ascendir al nivell anterior
  % Cadàver    Restes d'una criatura morta

## Barra d'Estat

  Línia 1: Lloc, Profunditat, Torn, Nivell/XP, Or, Barra de PV
  Línia 2: Nom (classe), habilitats, arma equipada, CA
  Línia 3: Armadura/escut/casc equipats, contingut de l'inventari

## Consells

  - Agafa-ho tot. La gestió d'inventari és clau a Knave.
  - Els pergamins són potents però d'un sol ús. Guarda'ls.
  - Les varetes es recarreguen lentament — no malgastis càrregues.
  - L'or no ocupa espai a l'inventari. Agafa'l tot.
  - Cerca ('s') prop de les parets per trobar portes secretes.
  - Empeny els cofres per obrir-los i trobar botí.
  - Els anells donen bonificacions passives — equipa'n dos.
  - Més CON significa més espais d'inventari.
  - Cada 1000 XP puges de nivell, guanyant PV i +1 a 3 stats.

## Opcions de Línia d'Ordres

  --seed N        Llavor RNG per reproduïbilitat
  --lang LANG     Idioma: en, ca, es
  --god           Mode déu (invulnerable, tot identificat)
  --reset         Nova partida, ignorant l'autodesament
  -G              Generar masmorra aleatòria
  --mode MODE     classic o typed
  --no-narrative  Desactivar narrativa LLM
  -v              Registre detallat
