# Čo otestovať v programe

Zoznam toho, čo treba po každej etape prejsť ručne. Odškrtni, čo sedí, a napíš mi, čo nie.

## Etapa 5 — klientske PDF (verzia 0.7.1)

Stiahni si build z [desktop-latest](https://github.com/metjus/Calculator/releases/tag/desktop-latest),
rozbaľ do nového priečinka a prekopíruj k nemu svoj starý priečinok `data`.

### Nastavenia

- [ ] **Logo** — nahraj PNG, JPEG, SVG alebo WebP do 1 MB. Má sa ukázať náhľad a tlačidlá *Replace* a *Remove*.
- [ ] Súbor väčší než 1 MB alebo iný typ (napr. `.txt`) má byť odmietnutý zrozumiteľnou hláškou.
- [ ] **Tvoje údaje** — meno, IČO, telefón, e-mail. Idú do pätičky obálky aj do QR vizitky.

### Obrazovka Client PDF

- [ ] V audite klikni na web so skóre → **Create PDF**. Pri weboch bez skóre tlačidlo nie je.
- [ ] Prepni jazyk **SK / ČS / EN** — texty problémov aj nadpisy sa musia zmeniť všetky.
- [ ] Nechaj **názov firmy** prázdny → na obálke má byť doména. Vypíš ho → má byť v hlavičke.
- [ ] Prepíš **úvodný odstavec** a sleduj, či sa do pol sekundy objaví v náhľade vpravo.
- [ ] Odškrtni pár problémov → počet aj náhľad sa musia zmeniť (aj počet strán hore vpravo).
- [ ] Presuň problém **šípkami ↑ ↓** → v náhľade sa má presunúť aj poradie čísel.
- [ ] Vypíš **tri ceny**, vyber rádiovkou, ktorá možnosť je „Odporúčam".
- [ ] **Show at full size** → náhľad sa zväčší na skutočnú šírku strany a dá sa v ňom skrolovať;
      druhý klik ho vráti do stĺpca. Nesmie vyskočiť žiadne okno Windowsu („Get an app…").
- [ ] **Export PDF** → súbor sa stiahne a pomenuje podľa domény.

### Samotné PDF

- [ ] Obálka: logo, názov firmy, dátum po slovensky, veľké skóre s pásikom a verdikt s bodkou.
- [ ] Problémy: pri každom *Čo je zle / Čo to spôsobuje / Riešenie*, vykanie, žiadne vymyslené čísla.
- [ ] Screenshoty počítača aj telefónu.
- [ ] Porovnanie s konkurenciou, ak si ju pri audite zadal.
- [ ] Posledná strana: tri možnosti so správnymi cenami, zvýraznená tá odporúčaná, veta
      „Ak chcete riešiť len niektoré veci…" a **nikde žiadny rozpis po položkách**.
- [ ] **Naskenuj QR kód telefónom — z exportovaného PDF, nie z náhľadu.** Má ponúknuť uloženie kontaktu
      s tvojím menom, telefónom a e-mailom. V PDF má 36 mm; v náhľade je celá strana zmenšená do stĺpca,
      takže kód tam má asi 75 px a neprečíta ho žiadny telefón.
- [ ] **Nastavenia → Your contact code** ukazujú ten istý kód dosť veľký na to, aby sa dal naskenovať
      priamo z obrazovky. Tam si ho overuj, netreba kvôli tomu robiť PDF.
- [ ] Otvor PDF **bez internetu** — musí sa zobraziť celé vrátane písma a obrázkov.

### Po exporte

- [ ] Spusti druhý export → **ceny majú byť predvyplnené** tie, čo si zadal naposledy.

## Etapa 7 — CRM (verzia 0.7.0)

### Zoznam zákazníkov

- [ ] **Customers** — hore počty (spolu / otvorených / čaká na teba), lievik, konverzia a donut podľa stavu.
- [ ] **Follow up** — v zozname majú byť tí, čo čakajú na odpoveď dlhšie než 7 dní, a tí s dátumom
      ďalšieho kroku na dnes alebo skôr. Klik na meno otvorí kartu.
- [ ] Filtre **stav / projekt / má web** a vyhľadávanie sa dajú kombinovať.
- [ ] Klik na stĺpec v lieviku prefiltruje tabuľku; druhý klik filter zruší.
- [ ] **Add customer** — pridaj firmu **bez webu**. Má dostať stav „Lead (no website)" a objaviť sa
      vo filtri „No website (lead)".

### Karta zákazníka

- [ ] Klikni na stav v riadku → uloží sa a objaví sa v časovej osi s dátumom.
- [ ] Pri stave **Deal** sa zobrazí pole na dohodnutú cenu; po uložení sa pripočíta do „Agreed".
- [ ] **Log a contact** — vyber spôsob (osobne / telefón / e-mail / správa) a napíš poznámku.
      Pri prvom kontakte sa stav sám prepne na „Contacted".
- [ ] Časová os ukazuje aj **audity** — klik na *Open* otvorí detail webu.
- [ ] Koš pri zázname ho vymaže (audit sa vymazať nedá).
- [ ] **Next step** + dátum → zákazník sa v deň splatnosti objaví v zozname Follow up.
- [ ] **Design demo** — vlož odkaz. Po 30 dňoch má karta hore upozorniť, že ukážku treba stiahnuť.
- [ ] Leadovi bez webu dopíš **Website** → stav sa zmení na „Audited" a dá sa auditovať.
- [ ] **Delete notes** zmaže poznámky, ale nechá firmu, web, dátumy a výsledky auditov.
- [ ] **Delete, keep the address** nechá adresu označenú „do not contact".

## Etapa 8 — archív, duplicity, osloviť znova (verzia 0.8.0)

### Nastavenia → Reminders and the archive

- [ ] Päť čísel: follow up (dni), stiahnuť ukážku (dni), archív (mesiace), osloviť znova (mesiace),
      zmazať poznámky (roky v archíve). **Save rules** → hláška „Rules saved".
- [ ] Skús uložiť 0 → má to odmietnuť.
- [ ] Zníž „Move to the archive after" na 1 mesiac → zákazníci so stavom Deal / Nemá záujem /
      Neozval sa starší než mesiac sa pri najbližšom otvorení Customers presunú do archívu.

### Archív

- [ ] Tlačidlo **Archive (počet)** hore vpravo na obrazovke Customers. Prepne na archív.
- [ ] V archíve sa dá hľadať aj filtrovať rovnako ako v zozname. Stĺpec vpravo ukazuje dátum archivácie.
- [ ] Archivovaný zákazník **nie je** v lieviku, v grafoch ani vo Follow up.
- [ ] Otvor kartu → modrý pruh „In the archive since…", tlačidlo **Bring back** ho vráti späť
      a do časovej osi pribudne „Brought back from the archive".
- [ ] Vrátený zákazník sa **nesmie** sám znova zarchivovať, kým nezmeníš jeho stav.
- [ ] Na karte je aj tlačidlo **Archive** — odloží zákazníka ručne, bez čakania na pravidlo.

### Osloviť znova

- [ ] Karta **Worth another try** na obrazovke Customers: tí, čo odmietli alebo sa neozvali
      pred viac než 12 mesiacmi. Zákazka tam nepatrí, „do not contact" tiež nie.

### Poznámky po čase

- [ ] Ak je niekto v archíve dlhšie než 2 roky a má poznámky, hore sa objaví oranžový pruh.
      **Nič sa nezmazalo** — je to len upozornenie.
- [ ] **Clear them now** → potvrdenie → poznámky zmiznú, ale firma, web, dátumy aj výsledky
      auditov zostanú a v časovej osi pribudne „Notes cleared".

### Duplicity a „do not contact"

- [ ] **Add customer** s menom alebo webom, ktorý už máš → žltý pruh „You have approached this
      business already" s odkazom na existujúceho zákazníka. Druhý klik na **Add anyway** ho pridá.
- [ ] Ak je ten existujúci označený „do not contact", pruh je červený.
- [ ] Na karte zákazníka, ktorý má dvojníka, je rovnaké upozornenie.
- [ ] **Nový audit** s webom firmy označenej „do not contact" → web sa **neauditoval**, hore je
      pruh s jej menom a tlačidlom **Audit it anyway**. Ostatné weby z toho istého zoznamu
      sa normálne auditujú.
- [ ] Ak je medzi webmi niekto, koho si už oslovil, dole vyskočí hláška „… you have already approached".

## Verzia 0.8.2 — drobnosti po etape 8

- [ ] **Dve nové kontroly.** Preskenuj web a v detaile hľadaj *Canonical* a *Tenký obsah*.
      Staré audity majú pôvodné skóre, nové kontroly sa prejavia až pri novom skene.
- [ ] **Odporúčaná možnosť v ponuke.** Pri webe so skóre pod 40 (alebo so zlým AI posudkom dizajnu)
      má byť zvýraznená tretia možnosť „Nový web", nie prostredná. Pri lepšom webe prostredná.
- [ ] **Vyhľadávanie firiem** — pri firme, ktorú už máš v zákazníkoch, má byť vidieť jej **stav**
      (napr. „Waiting for an answer") a pod ním dátum posledného kontaktu, nie len „In your list".
- [ ] **Nastavenia → Files** (len v programe, nie v prehliadači): tlačidlo **Open data folder**
      otvorí priečinok v Prieskumníkovi.
- [ ] Do poľa pod tým zadaj inú cestu (napr. `D:\WebAudit\data`) a ulož → objaví sa upozornenie,
      že program ju použije po reštarte. **Dáta sa nepresunú** — ak chceš staré audity, prekopíruj
      priečinok ručne. Tlačidlom *Back to the default* sa vrátiš späť.
- [ ] Zadaj nezmyselnú cestu (relatívnu alebo priečinok bez práv) → má to odmietnuť zrozumiteľne.
- [ ] **Customers → filter „Any time"** — prepni na *Active in the last 30 days*; zákazníci, s ktorými
      sa dlho nič nedialo, zo zoznamu zmiznú. Kombinuje sa s ostatnými filtrami.

## Verzia 0.8.3 — AI posudok dizajnu v appke Claude

Nepotrebuje API kľúč ani kredity; stačí predplatné claude.ai.

- [ ] **Nový audit → Upload CSV** — súbor sa dá **pretiahnuť myšou** do rámčeka, nielen vybrať cez
      dialóg. Po pustení ukáže názov súboru a počet riadkov.
- [ ] **Detail webu → Design review (AI) → Copy prompt for the Claude app** → hláška „Prompt copied".
- [ ] Vedľa sú tlačidlá na stiahnutie **desktop** a **mobile** screenshotu.
- [ ] V Claude appke založ nový chat, vlož prompt, pripni oba screenshoty a odošli. Claude má
      odpovedať **iba CSV** s jedným riadkom.
- [ ] Odpoveď ulož ako `.csv` a **pretiahni ju do rámčeka** na detaile webu → hláška „Review added",
      objaví sa skóre, verdikt, silné stránky aj slabiny a **skóre webu sa prepočíta**
      (oblasť „Design (AI review)" prestane byť prázdna).
- [ ] Hore v karte má byť napísané **by claude.ai (pasted by hand)** a **žiadna cena** — nič sa
      nefakturovalo.
- [ ] Pretiahni tam nesprávny súbor (napr. obyčajný text) → má to odmietnuť zrozumiteľnou vetou.
- [ ] Ak Claude obalí CSV do bloku s ```, má to fungovať tiež.

## Verzia 0.8.4 — koľko toho PDF prezradí

- [ ] **Client PDF → How much to show** s tromi možnosťami. Predvolená je **Without the fix**.
- [ ] *With the fix* — pri každom probléme sú tri časti vrátane „Riešenie".
- [ ] *Without the fix* — „Riešenie" zmizne, „Čo je zle" aj „Čo to spôsobuje" zostanú.
      Problémy sú stále všetky, nič sa nezatají.
- [ ] *Top 3 only* — prvé tri problémy s popisom, zvyšok len vymenovaný v dvoch stĺpcoch
      pod čiarou, plus veta „Týchto N vecí sme pri kontrole tiež našli…". PDF je kratšie.
- [ ] Náhľad sa pri prepnutí prekreslí do pol sekundy a mení sa aj počet strán.
- [ ] Po exporte sa voľba zapamätá — pri ďalšom PDF je predvolená tá, ktorú si použil naposledy.

## Verzia 0.8.5 — posudok dizajnu ešte pred auditom

- [ ] **Nový audit** → vlož adresy (alebo vyber CSV) → v časti *Or do the design review yourself*
      klikni **Copy prompt for the Claude app** → hláška „Prompt for N websites copied".
- [ ] V Claude appke vlož prompt. Claude má weby **sám otvoriť**, poscrollovať ich, otvoriť menu
      a všímať si aj animácie a správanie stránky — nie len statický obrázok.
- [ ] Odpoveď (jeden riadok na web) ulož ako `.csv` a **pretiahni ju** do rámčeka pod tlačidlom.
      Ukáže sa názov súboru a počet posudkov.
- [ ] Spusti audit. Po dobehnutí má mať každý web v detaile **Design review (AI)** s textom
      od Clauda, „by claude.ai (pasted by hand)", bez ceny, a **skóre už obsahuje oblasť dizajnu**.
- [ ] Ak je v CSV web, ktorý v tomto audite nie je, program to po spustení napíše
      („… matched no website here") a zvyšok použije.
- [ ] Pretiahni tam nesprávny súbor → odmietne to s číslom riadku a dôvodom.

### Čo zatiaľ nie je

- PDF „Čo by vám web priniesol" pre firmy bez webu — potrebuje vlastný návrh a texty.
