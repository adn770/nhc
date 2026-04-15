# NHC — Nethack-like Crawler

Un dungeon crawler roguelike amb regles Knave, suport multilingüe
i narrativa opcional amb IA. Descendeixes per nivells generats
proceduralment, lluites contra criatures, saqueges tresors,
contractes aventurers, identifiques objectes màgics i intentes
sobreviure.

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
  Fletxes           Moure's en 4 direccions
  h j k l           Tecles vi (esquerra, avall, amunt, dreta)
  y u b n           Diagonals vi (NO, NE, SO, SE)
  . o 5             Esperar un torn

Empènyer una criatura hostil l'ataca.
Empènyer una porta tancada l'obre.
Empènyer un aventurer contractat intercanvia posicions amb tu.
Empènyer un cofre, barril o caixa l'obre i en deixa caure el contingut.
Empènyer un mercader o sacerdot obre el seu menú de botiga/servei.
Empènyer un aventurer no contractat obre el menú d'encontre.

### Objectes i Equipament
  g o ,             Agafar objecte als peus
  i                 Obrir inventari
  a                 Usar un objecte (mostra menú d'inventari)
  q                 Beure una poció
  e                 Equipar arma, armadura, escut, casc o anell
  d                 Deixar un objecte de l'inventari
  t                 Llançar una poció a una criatura visible
  z                 Disparar una vareta a una criatura visible

### Exploració
  :                 Mirada llunyana — mou el cursor per examinar
                    caselles
  s                 Cercar trampes ocultes i portes secretes
  p                 Forçar un pany (requereix eines, salvació DES)
  f                 Forçar una porta (salvació FOR, les eines ajuden)
  c                 Tancar una porta oberta adjacent
  D                 Excavar paret o terra (cal una eina d'excavació)
  >                 Descendir escales
  <                 Ascendir escales

### Grup
  G                 Donar un objecte a un aventurer contractat
  P                 Acomiadar un aventurer del grup

### Interfície
  [ ]               Desplaçar registre de missatges
  ?                 Mostrar aquesta pantalla d'ajuda
  TAB               Canviar entre mode clàssic i escrit
  Q                 Sortir

## Dreceres de Teclat — Mode Escrit

### Entrada de Text
  Enter             Enviar ordre al Director de Joc
  ESC               Esborrar entrada actual
  Amunt/Avall       Navegar historial d'entrades
  Retrocés          Esborrar caràcter abans del cursor
  Esquerra/Dreta    Moure cursor dins el text
  Inici/Fi          Saltar a inici/final de línia

### Dreceres (sense passar pel text)
  Fletxes           Moure's directament (sense interpretació del DJ)
  h j k l           Moviment vi (igual que el clàssic)
  TAB               Tornar al mode clàssic
  ?                 Mostrar aquesta pantalla d'ajuda
  [ ]               Desplaçar registre narratiu
  Q                 Sortir

## Exemples en Mode Escrit

  > ataco l'esquelet
  > agafo la poció
  > obro el cofre
  > intento escoltar a la porta
  > faig servir el pergamí de dormir contra els goblins
  > bec la poció de curació
  > llanço la poció de gel a l'ogre
  > disparo la vareta al goblin
  > dono la palanca al meu aventurer

## Extres del Client Web

El client del navegador afegeix algunes funcions no disponibles
al terminal:

  Clic del ratolí   Moure's o actuar sobre la casella pitjada
  Clic dret         Menú contextual sobre un objecte (Usar, Beure,
                    Equipar, Llançar, Donar, Deixar)
  Botó Examinar     Alterna la inspecció d'una casella; clic dret
                    per mode Auto-examinar (inspecció contínua
                    mentre et mous)
  Botó Excavar      Alterna l'Auto-excavació — camina contra parets
                    per excavar-les amb l'eina equipada
  Opció TTS         Llegeix els missatges en veu alta amb Piper TTS
  Classificació     Les partides acabades surten al rànquing
                    (les de mode déu no hi compten)

## Estadístiques del Personatge (Regles Knave)

  FOR  Força          Atac cos a cos, força bruta, salvacions
  DES  Destresa       Atac a distància, esquiva, CA
  CON  Constitució    Punts de vida, espais d'inventari
  INT  Intel·ligència Coneixement arcà, pergamins
  SAV  Saviesa        Percepció, voluntat, trampes
  CAR  Carisma        Social, moral, encantaments

  Defensa = bonificació + 10.  Espais = defensa de CON.
  Nivell 1 comença amb PV màxims (8).
  Nivell màxim: 10.  Cada pujada augmenta les 3 habilitats
  més baixes en +1.
  1000 XP per nivell. Les criatures donen XP = PV màxims × 5.

## Espais d'Equipament

  Arma              Una arma cos a cos o a distància
  Armadura          Gambeson, brigandina, malla, mitja armadura,
                    armadura completa
  Escut             Rodella o escut (+1 CA cadascun)
  Casc              Capell de cuir o casc (+1 CA cadascun)
  Anell (E/D)       Dos espais per efectes màgics passius

Els objectes equipats també ocupen espais d'inventari.

## Llegenda de Símbols

### Terreny i Elements de la Masmorra

  .   Terra               ,   Herba
  #   Passadís / excavat  ~   Aigua o lava
  -   Paret (dibuix de caixa al joc)
  +   Porta tancada       '   Porta oberta
  <   Escales amunt       >   Escales avall
  ^   Trampa (un cop detectada)
  =   Cofre               0   Barril              #   Caixa
  ◎   Marca de tresor enterrat (cian, després d'excavar o detectar)

Les portes secretes semblen parets fins que les trobes amb la cerca.
Els objectes detectats i la màgia brillen un moment i s'esvaeixen.

### Objectes

  !   Poció               ?   Pergamí
  =   Anell               /   Vareta o fletxa
  )   Arma                [   Armadura
  *   Gemma o vidre sense valor
  (   Eina, menjar, clau, rossinyol, llanterna, símbol sagrat, etc.
  $   Pila d'or           %   Cadàver

Les pocions, pergamins, anells, varetes i gemmes tenen aparences
aleatòries (colors, etiquetes, tipus de gemma) fins que les identifiques;
les aparences canvien cada partida.

### Criatures

El jugador i els PNJs amistosos comparteixen el glif `@` però
es distingeixen pel color:

  @   Jugador       (contorn blau al client web)
  @   Aventurer     (cian)
  @   Mercader      (verd)
  @   Sacerdot      (blanc brillant)
  @   Bandoler      (groc, hostil)

La majoria de criatures són una sola lletra. Alguns exemples
agrupats per família (el bestiari complet és més gran):

  Humanoides / goblinoides
    g goblin, h hobgoblin, k kobold, o orc, O ogre, G gnoll,
    B osgo, f granyotic, L llangardànic, n home serp

  Bèsties i cànids
    b ratpenat, r rata, w llop, d llop terrible,
    c os negre / os bru, U uarg, W licàntrop llop,
    W llop d'hivern, O os oliba

  Rèptils i serps
    l llangardaix gegant, S serp gegant, D llangardaix drac,
    F granota gegant, c cocatriu, B basilisc (mirada)

  Morts vivents
    s esquelet, Z zombie, M mòmia, W entitat, W aparegut,
    S espectre, g gul

  Plagues, insectes i aràcnids
    s aranya, i eixam d'insectes, a escarabat de foc,
    L llagosta de cova, S escorpí gegant, c centpeus gegant,
    S taràntula gegant, B abella gegant

  Llims i plantes
    P púding negre, j gelatina ocre, o llot gris, s llim verd,
    m fong groc, f flor carnívora, f bolet violeta

  Exòtiques i caos
    T trol (regenera), $ mímic (disfressat de cofre/or),
    ! cridaner (alerta les criatures), C centaure, H hàrpia,
    V víbria, I assetjador invisible, A armadura animada,
    G gàrgola

Regla general: minúscula = més petit, majúscula = més gran o fort.
Els trols regeneren 3 PV per torn; els mímics i cridaners es
disfressen d'objectes — les sorpreses són part del joc.

## Objectes Màgics

### Pocions (14)
  Curació, Força, Velocitat, Gel, Invisibilitat, Levitació,
  Flama Líquida, Visió Mental, Gas Paralitzant, Purificació,
  Confusió, Ceguera, Àcid, Malaltia.

Algunes pocions fan més mal llançades que begudes.
Beure qualsevol poció recupera una mica de nutrició.

### Pergamins
Detecció (brillantor que s'esvaeix, revelen coses durant una estona):
  Detectar Màgia, Detectar Mal, Detectar Or, Detectar Menjar,
  Detectar Gemmes, Detectar Invisibilitat, Trobar Trampes,
  Revelar Mapa.
Ofensius / estat:
  Llamp, Bola de Foc, Míssil Màgic, Dormir, Subjectar Persona,
  Teranyina, Encantar Persona, Força Fantasmal, Dissipar Màgia.
Defensius / millora:
  Benedicció, Escut, Velocitat, Curar Ferides, Imatge Mirall,
  Invisibilitat, Protecció contra el Mal, Protecció contra
  Projectils, Resistència al Foc, Resistència al Fred,
  Silenci, Levitació, Vol.
Utilitat:
  Identificar, Recarregar, Teletransport, Encantar Arma,
  Encantar Armadura, Clarividència, Infravisió, Respirar
  sota l'Aigua, Encantar Serps.

### Anells (passius, actius mentre equipats)
  Reparació, Velocitat, Detecció, Elements, Precisió,
  Evasió, Ombres, Protecció.

### Varetes (dispara a objectius, càrregues limitades, es recarreguen)
  Bola de foc, Llamp, Fred, Míssil Màgic, Desintegració,
  Teleportació, Verí, Lentitud, Amok, Obertura, Bloqueig,
  Excavació, Cancel·lació, Mort.

### Gemmes i Vidre
Les gemmes reals (robí, safir, maragda, diamant, ametista,
topazi, òpal, granat) es venen per or. El vidre sense valor
es veu igual fins a identificar — un Pergamí d'Identificació
o l'ull expert d'un mercader els distingeix.

## Identificació

Les pocions, pergamins, anells, varetes i gemmes tenen aparences
aleatòries cada partida. Per identificar-les:
  - Pocions: beure per identificar (o llançar-ne una coneguda)
  - Pergamins: llegir/usar per identificar
  - Anells i varetes: equipar/disparar, o usar Pergamí/Vareta
    d'Identificació
  - Gemmes: usar Pergamí d'Identificació, o vendre-les a un mercader

## Elements de la Masmorra i Sales Especials

  Temple (2+)       Garantit a profunditat 2. Un sacerdot ofereix
                    curació, eliminar maledicció i benedicció, a més
                    de béns sagrats. Els preus pugen amb la
                    profunditat.
  Botigues          Un mercader ven objectes i compra botí al 50%
                    del valor. Empeny per comerciar.
  Caus (3+)         1–3 sales connectades amb humanoides de la
                    mateixa espècie. Les caselles del voltant
                    amaguen trampes reactivables.
  Zoos (5+)         Sales mitjanes plenes de criatures.
  Nius de plagues   Sales plenes de rates, ratpenats o insectes.
  Tresoreries       Cambres ocultes amb piles d'or.
  Coves             Disposicions orgàniques sense portes però amb
                    més pous i trapes.

## Trampes

Les trampes estan ocultes fins que les detectes. Usa `s` (cerca)
adjacent a una casella sospitosa, equipa l'Anell de Detecció o
llança Trobar Trampes. Tipus: pou, trapa, fletxa, dard, pedra,
foc, verí, paràlisi, alarma, teletransport, invocació, aferrar,
espores. Algunes trampes al voltant dels caus es reactiven
passats 40 torns.

## Portes

  Tancada           Empeny per obrir (només els humanoides
                    ho poden fer).
  Bloquejada        Usa `p` per forçar el pany (salvació DES, pot
                    trencar un rossinyol) o `f` per forçar la porta
                    (salvació FOR, pot ferir-te).
  Eines de força    Una palanca absorbeix el rebot i baixa la DC;
                    una arma baixa una mica la DC però pot
                    fer-se malbé.
  Secreta           Semblen parets. Troba-les amb `s`.
  Coves             Sense portes — només passadissos oberts.

## Excavació i Tresor Enterrat

Una eina d'excavació (pala, picassa, càvec o pic) et deixa
excavar. Se'n garanteix una a les profunditats 1–5.

  Parets            Qualsevol eina. Salvació FOR DC 12 menys la
                    bonificació de l'eina.
  Terra             Només la pala. Pot revelar objectes enterrats
                    (◎). Possibilitat 1 entre 20 (+1 per bonificació
                    FOR) de caure al pis següent rebent 2d6 de dany.
                    Excavar la mateixa casella dues vegades garanteix
                    la caiguda.
  Pics              Colpejar el terra amb un pic, picassa o càvec pot
                    rebotar per 1d2 de dany en un 1 natural.

Al client web, clic dret al botó Excavar activa l'Auto-excavació
i pots excavar només movent-te contra parets.

## Aventurers / Grup

  Reclutar          Empeny un aventurer no contractat per obrir el
                    menú d'encontre. Contractar costa 100 monedes
                    d'or × el seu nivell.
  Mida              Fins a dos aventurers a la vegada.
  Comportament      Lluiten, es curen amb pocions, agafen botí,
                    eviten trampes visibles i et segueixen entre
                    sales i baixant escales.
  Donar             Prem `G` (o el menú contextual) per passar
                    objectes. La seva IA tria quin equip és millor
                    portar.
  Intercanvi        Empeny un aventurer per canviar-vos de lloc.
  Acomiadar         Prem `P` per alliberar-lo.
  Mort              Es notifica al registre. Els aventurers reben
                    la meitat d'XP.

## Fam i Menjar

Un rellotge de fam avança mentre explores. Menja (`a` i tria
racions, pa, formatge, poma, bolet, carn seca…) abans que et moris
de gana.
Els bolets poden curar, enverinar o confondre. Beure una poció
dóna una mica de nutrició, però mai prou per viure-hi.

## Conceptes de Combat

  Cos a cos         d20 + bonificació FOR + màgia d'arma vs CA de
                    l'objectiu. 20 natural = dany màxim. 1 natural
                    = fallada. Dany = dau d'arma + bonificació FOR
                    + màgia (mínim 1).
  Distància         Llançar (`t`), disparar (`z`), o disparar amb
                    l'arc equipat.
  Defensa           CA = 10 + bonificació DES + armadura/escut/
                    casc/anell.
  Moral             Els enemics fan salvació de moral en veure't
                    per primera vegada i en arribar a la meitat
                    de PV; els covards fugen.
  Aventurers        Sumen les seves armes i encanteris al teu dany.

## Barra d'Estat

  Línia 1           Lloc, Profunditat, Torn, Nivell/XP, Or, Barra de PV
  Línia 2           Nom (classe), habilitats, arma equipada, CA
  Línia 3           Armadura/escut/casc equipats, contingut de
                    l'inventari

## Com Jugar — Guia Breu

1. **Explora amb cautela.** Entra una vegada a cada sala nova,
   mira què hi ha i retrocedeix si les probabilitats no et
   afavoreixen.
2. **Agafa gairebé tot.** L'or no ocupa espai; la resta sí, però
   la majoria d'objectes val la pena.
3. **Identifica amb seguretat.** Beu pocions desconegudes amb PV
   plens. Llegeix pergamins desconeguts en sales buides — alguns
   invoquen o teletransporten. No identifiquis mai en un cau.
4. **Gasta els consumibles.** Pergamins i càrregues no et
   acompanyen si mors. Usa'ls en els combats durs, no en els fàcils.
5. **Cerca sovint.** Portes secretes i tresors enterrats s'amaguen
   a parets i terres. Pitjar `s` uns quants cops costa poc.
6. **Llegeix la sala.** Una sala plena de gent sol ser un zoo; una
   sala gran amb criatures de la mateixa espècie, un cau; una
   graella perfecta amb un mercader, una botiga; les decoracions
   marquen els temples.
7. **Puja de nivell amb cap.** Cada nivell augmenta les tres
   habilitats més baixes en +1. No ho aboquis tot a FOR — CON
   dóna espais, DES dóna CA, SAV resisteix la màgia.
8. **Controla la fam.** No perdis torns en passadissos. Porta
   almenys dues racions quan baixis.

## Consells Tàctics

- **Els passadissos canalitzen enemics** — lluita contra grups
  a passos d'una sola casella perquè només et pugui atacar un.
- **Tanca les portes darrere teu** amb `c` per bloquejar els
  perseguidors i guanyar un cop gratis quan les obrin.
- **Llança pocions als enemics** — Gel, Flama Líquida, Gas
  Paralitzant, Àcid, Confusió i Ceguera fan debuff a l'impacte.
- **Les varetes brillen contra enemics durs** — guarda Míssil
  Màgic per objectius difícils d'encertar; mai falla.
- **Anells de Reparació + Detecció** aguanten moltes partides.
  Equipa els dos anells sempre que puguis.
- **Les palanques fan que forçar portes sigui segur** —
  absorbeixen el rebot i baixen la DC.
- **Els trols regeneren** — crema'ls (Flama Líquida, Vareta de
  Bola de Foc, Pergamí de Bola de Foc) per aturar la regeneració.
- **Els mímics es fan passar per cofres** i **els cridaners
  semblen pocions** — examina (`:`) el que et sembli fora de lloc.
- **Els temples són un botó de reset** — la curació i eliminar
  maledicció del sacerdot poden salvar una partida per un
  grapat d'or.
- **Contracta aviat.** Un aventurer de profunditat 1 és barat,
  aguanta cops i es cura sol. Dóna-li la palanca sobrant.
- **Excava amb mesura.** Excavar el terra estalvia temps però
  pot deixar-te en un combat amb PV baixos — cura't abans.
- **No pugis per gust.** Pujar escales desbarata el ritme d'XP
  i només hi ha escales amunt a profunditat 1.

## Desament

El joc guarda automàticament cada torn — no hi ha tecla de
desament manual. Els desaments se signen amb HMAC per detectar
manipulació. Usa `--reset` per començar de nou ignorant
l'autodesament.

## Opcions de Línia d'Ordres

  --seed N          Llavor RNG per reproduïbilitat
  --lang LANG       Idioma: en, ca, es
  --god             Mode déu (invulnerable, tot identificat)
  --reset           Nova partida, ignorant l'autodesament
  -G                Generar masmorra aleatòria
  --mode MODE       classic o typed
  --no-narrative    Desactivar narrativa LLM
  -v                Registre detallat
